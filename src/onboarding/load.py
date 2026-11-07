"""Write a whole school inside one transaction.

The caller owns the transaction: it commits, or rolls back for a dry run. The connection is the
database owner's (ADMIN_DATABASE_URL), as `useradd` uses. Nothing is written unless the file
validates and the database has no school yet; any failure part-way leaves the transaction for the
caller to roll back, so there is never a half-installed school.
"""

from dataclasses import dataclass, field
from datetime import date, time, timedelta
from typing import Any, override
from uuid import UUID

from sqlalchemy import (
    Connection,
    Date,
    DateTime,
    Executable,
    Text,
    cast,
    extract,
    func,
    insert,
    literal,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.exc import DBAPIError

import auth as authpkg
from curriculum import DEFAULT_MODALITY, Catalog, capability_code
from mawta_schema.tables import (
    AcademicYear,
    Capability,
    Class,
    ClassSchedule,
    ClassSession,
    ClassTeacher,
    Competency,
    Course,
    EvaluationCriterion,
    GradeLevel,
    GradeLevelPerformance,
    GradeScale,
    GradeScaleLevel,
    LearningStandard,
    Membership,
    NonTeachingDay,
    School,
    Section,
    SectionMembership,
    StandardLevelMapping,
    Student,
    Subject,
    Teacher,
    Term,
    User,
)
from onboarding import derive_id as ID
from onboarding.spec import Clase, CriterioLegacy, Estudiante, Franja, Periodo, Spec
from onboarding.validate import ValidationErrors, parse_clock, parse_weekday, validate

SCALE_MINEDU = "minedu_ad_a_b_c"

# The RVM 094-2020 achievement levels: (code, label, ordinal, min_norm, max_norm, color_key). The
# normalised bands are presentation only: the teacher asserts the level, and nothing derives it
# from a mark.
MINEDU_LEVELS = [
    ("C", "En inicio", 1, 0.00, 0.55, "rojo"),
    ("B", "En proceso", 2, 0.55, 0.70, "ambar"),
    ("A", "Logro esperado", 3, 0.70, 0.85, "verde"),
    ("AD", "Logro destacado", 4, 0.85, 1.00, "azul"),
]


@dataclass
class Summary:
    """What a load created, for the operator to check and hand over. Never carries a password."""

    colegio: str = ""
    school_id: UUID | None = None
    usuarios: list[str] = field(default_factory=list)
    periodos: int = 0
    dias_no_lectivos: int = 0
    docentes: int = 0
    areas: int = 0
    competencias: int = 0
    capacidades: int = 0
    criterios: int = 0
    estandares: int = 0
    desempenos: int = 0
    aulas: int = 0
    estudiantes: int = 0
    clases: int = 0
    franjas: int = 0
    sesiones: int = 0
    sesiones_con_tema: int = 0

    @override
    def __str__(self) -> str:
        return (
            f"Colegio:        {self.colegio} ({self.school_id})\n"
            f"Periodos:       {self.periodos}, con {self.dias_no_lectivos} días no lectivos\n"
            f"Docentes:       {self.docentes} ({', '.join(self.usuarios)})\n"
            f"Áreas:          {self.areas}, con {self.competencias} competencias, "
            f"{self.capacidades} capacidades y {self.criterios} criterios\n"
            f"Currículo:      {self.estandares} estándares y {self.desempenos} desempeños de grado\n"
            f"Aulas:          {self.aulas}, con {self.estudiantes} estudiantes\n"
            f"Clases:         {self.clases}, con {self.franjas} franjas de horario\n"
            f"Sesiones:       {self.sesiones} generadas, {self.sesiones_con_tema} con tema\n"
        )


def _nz(value: str) -> str | None:
    """An empty optional value becomes SQL NULL."""
    return None if not value.strip() else value


def _clock(value: str) -> str:
    """ "8:00" -> "08:00", stable inside a derived id."""
    minutes = parse_clock(value)
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _weekday(value: str) -> int:
    """ "lunes" -> 1. validate() has already rejected any other text."""
    day = parse_weekday(value)
    if day is None:
        raise RuntimeError(f"unvalidated weekday {value!r}")
    return day


def _room_for(c: Clase, f: Franja) -> str:
    return f.salon if f.salon.strip() else c.salon


def _date(value: str) -> date | None:
    """An ISO date from the file; validate() already rejected anything else. Empty is NULL."""
    return date.fromisoformat(value) if value.strip() else None


def _time(value: str) -> time:
    minutes = parse_clock(value)
    return time(minutes // 60, minutes % 60)


def _error_text(exc: DBAPIError) -> str:
    orig: Any = exc.orig
    diag = getattr(orig, "diag", None)
    return (diag.message_primary if diag is not None else None) or str(orig)


def load(conn: Connection, spec: Spec, cat: Catalog, bcrypt_cost: int) -> Summary:
    validate(spec, cat)
    loader = _Loader(conn, spec, cat)
    loader.precheck()
    steps = [
        ("colegio y año escolar", loader.colegio),
        ("docentes", lambda: loader.docentes(bcrypt_cost)),
        ("áreas, competencias y capacidades", loader.areas),
        ("aulas y estudiantes", loader.aulas),
        # After aulas: performances reference the grade_levels rows that aulas creates.
        ("desempeños, estándares y niveles esperados", loader.curriculum_data),
        ("clases y horario", loader.clases),
        ("sesiones", loader.sesiones),
    ]
    for name, step in steps:
        try:
            step()
        except DBAPIError as exc:
            raise RuntimeError(f"{name}: {_error_text(exc)}") from exc
    return loader.sum


def _days(from_: date, to: date) -> Any:
    """Every date in [from_, to], as a set-returning column d."""
    return func.generate_series(
        literal(from_, Date), literal(to, Date), timedelta(days=1)
    ).column_valued("d")


class _Loader:
    conn: Connection
    s: Spec
    cat: Catalog
    mod: str
    anio: str
    school: UUID
    year: UUID
    sum: Summary
    first_day: date

    def __init__(self, conn: Connection, spec: Spec, cat: Catalog) -> None:
        self.conn = conn
        self.s = spec
        self.cat = cat
        self.mod = spec.colegio.codigo_modular
        self.anio = str(spec.anio_escolar.anio)
        self.school = ID("school", self.mod, "")
        self.year = ID("year", self.mod, self.anio)
        self.sum = Summary(colegio=spec.colegio.nombre, school_id=self.school)
        # earliest periodo start: when titulars and horarios begin (ISO dates sort as strings)
        self.first_day = date.fromisoformat(min(p.inicio for p in spec.anio_escolar.periodos))

    def exec(self, stmt: Executable) -> None:
        self.conn.execute(stmt)

    def count(self, stmt: Any) -> int:
        """Rows written by an INSERT ... SELECT, counted through RETURNING."""
        return len(self.conn.execute(stmt).all())

    def precheck(self) -> None:
        """Refuse when the database already has its school, or an account already exists, before
        writing anything, with a message about the file rather than a constraint."""
        existing = self.conn.execute(select(School.name, School.modular_code)).first()
        if existing is not None:
            raise ValidationErrors(
                [
                    f"colegio.codigo_modular: esta base ya tiene su colegio ({existing.name}, "
                    f"{existing.modular_code}). Cada colegio usa su propia base de datos; este "
                    "cargador no modificó nada."
                ]
            )
        usuarios = [d.usuario.lower() for d in self.s.docentes]
        emails = [d.email.strip().lower() for d in self.s.docentes]
        rows = self.conn.execute(
            select(
                func.coalesce(func.lower(User.username), "").label("u"),
                func.lower(User.email).label("e"),
            ).where(
                User.deleted_at.is_(None),
                func.lower(User.username).in_(usuarios) | func.lower(User.email).in_(emails),
            )
        ).all()
        errs: list[str] = []
        for r in rows:
            for i, (u, e) in enumerate(zip(usuarios, emails, strict=True)):
                path = f"docentes[{i}]"
                if r.u and r.u == u:
                    errs.append(f'{path}.usuario: "{u}" ya existe en Mawta; elige otro')
                if r.e == e:
                    errs.append(
                        f'{path}.email: "{e}" ya está registrado en Mawta; una persona solo puede '
                        "pertenecer a un colegio"
                    )
        if errs:
            raise ValidationErrors(sorted(errs))

    # ------------------------------------------------------------ colegio, año --

    def term_id(self, p: Periodo) -> UUID:
        return ID("term", self.mod, f"{self.anio}:{p.numero}")

    def colegio(self) -> None:
        c = self.s.colegio
        self.exec(
            insert(School).values(
                id=self.school,
                name=c.nombre,
                legal_name=_nz(c.razon_social),
                modular_code=c.codigo_modular,
                kind=c.tipo,
                city=_nz(c.ciudad),
                region=_nz(c.region),
                timezone=c.zona_horaria or "America/Lima",
                status="active",
            )
        )
        a = self.s.anio_escolar
        self.exec(
            insert(AcademicYear).values(
                id=self.year,
                year=a.anio,
                name=a.nombre,
                starts_on=_date(a.inicio),
                ends_on=_date(a.fin),
                term_structure=a.estructura,
                status="active",
            )
        )
        # Only the first periodo of the year goes in 'active' (terms_one_active_key allows one
        # per nivel); the rest are 'planned'. 'planned' still accepts scores, only 'closed' and
        # 'archived' are rejected, so the historical evidence of a later periodo can be loaded.
        first = min(p.numero for p in a.periodos)
        for p in a.periodos:
            self.exec(
                insert(Term).values(
                    id=self.term_id(p),
                    academic_year_id=self.year,
                    stage=None,
                    sequence=p.numero,
                    name=p.nombre,
                    short_name=_nz(p.abreviatura),
                    starts_on=_date(p.inicio),
                    ends_on=_date(p.fin),
                    status="active" if p.numero == first else "planned",
                    grades_due_on=_date(p.fecha_entrega_notas),
                )
            )
            self.sum.periodos += 1
        # One row per day: non_teaching_days is a set of dates, so a vacation range becomes every
        # date in it. Validate already rejected duplicates.
        n = NonTeachingDay
        for d in a.dias_no_lectivos:
            desde, hasta = (d.fecha, d.fecha) if d.fecha.strip() else (d.desde, d.hasta)
            days = _days(date.fromisoformat(desde), date.fromisoformat(hasta))
            self.sum.dias_no_lectivos += self.count(
                insert(n)
                .from_select(
                    ["academic_year_id", "day", "kind", "label"],
                    select(
                        literal(self.year, n.academic_year_id.type),
                        cast(days, Date),
                        literal(d.tipo, n.kind.type),
                        literal(_nz(d.nombre), n.label.type),
                    ),
                )
                .returning(n.id)
            )

    # --------------------------------------------------------------- docentes --

    def teacher_id(self, usuario: str) -> UUID:
        return ID("teacher", self.mod, usuario)

    def docentes(self, bcrypt_cost: int) -> None:
        """Hash each password with the same bcrypt path as the login, in this same transaction:
        there is no placeholder hash and no second step that could fail after the school is
        already committed."""
        for d in self.s.docentes:
            hashed = authpkg.hash_password(d.clave, bcrypt_cost)
            display = d.nombre_visible if d.nombre_visible.strip() else f"{d.nombres} {d.apellidos}"
            user_id = ID("user", self.mod, d.usuario)
            membership_id = ID("membership", self.mod, d.usuario)
            self.exec(
                insert(User).values(
                    id=user_id,
                    email=func.lower(d.email.strip()),
                    given_name=d.nombres,
                    family_name=d.apellidos,
                    display_name=display,
                    status="active",
                    username=d.usuario,
                    password_hash=hashed,
                    password_changed_at=func.now(),
                    failed_login_count=0,
                )
            )
            self.exec(
                insert(Membership).values(
                    id=membership_id,
                    user_id=user_id,
                    role="teacher",
                    status="active",
                    joined_at=func.now(),
                )
            )
            self.exec(
                insert(Teacher).values(
                    id=self.teacher_id(d.usuario),
                    membership_id=membership_id,
                    employee_code=_nz(d.codigo_empleado),
                    display_name=display,
                    title=_nz(d.cargo),
                    hired_on=_date(d.fecha_ingreso),
                    status="active",
                )
            )
            self.sum.docentes += 1
            self.sum.usuarios.append(d.usuario)

    # ------------------------------------------------------------------ áreas --

    def areas(self) -> None:
        """Copy each área's competency tree from the catalog: the subject row is the school's (its
        name and icon are school decisions), but the competencies, capabilities and their order
        come from the CNEB. Legacy criteria stay possible at area level."""
        self.scales()
        for i, a in enumerate(self.s.areas, start=1):
            cat_area = self.cat.area[a.codigo]
            subject_id = ID("subject", self.mod, a.codigo)
            self.exec(
                insert(Subject).values(
                    id=subject_id,
                    code=a.codigo,
                    name=a.nombre,
                    area_curricular=a.nombre,
                    icon_key=_nz(a.icono),
                    is_tutoria=a.es_tutoria,
                    sort_order=i,
                )
            )
            self.sum.areas += 1
            for j, cc in enumerate(cat_area["competencias"], start=1):
                self.competencia(cc["codigo"], self.cat.competencias[cc["numero_cneb"]],
                                 subject_id, "area", j)  # fmt: skip
            for j, cr in enumerate(a.criterios_legacy, start=1):
                self.criterio_legacy(cr, j)
        # Transversales hang off no área and no single teacher, and never count toward
        # promotion; competencies_transversal_has_no_subject needs the null subject.
        for j, code in enumerate(self.s.competencias_transversales, start=1):
            comp = self.cat.competencia_by_code(code)
            if comp is None:
                raise RuntimeError(f"competencia transversal {code}: no está en el catálogo")
            self.competencia(code, comp, None, "transversal", j)

    def competencia(
        self, codigo: str, comp: dict[str, Any], subject_id: UUID | None, kind: str, order: int
    ) -> None:
        """One competency and its capabilities from the catalog. Names are the official ones,
        stored verbatim; the capability code is <competency code>-CAP<numero>."""
        comp_id = ID("competency", self.mod, codigo)
        self.exec(
            insert(Competency).values(
                id=comp_id,
                subject_id=subject_id,
                code=codigo,
                name=comp["nombre"],
                kind=kind,
                sort_order=order,
                is_active=True,
            )
        )
        self.sum.competencias += 1
        for k, cap in enumerate(comp["capacidades"], start=1):
            cap_code = capability_code(codigo, cap["numero"])
            self.exec(
                insert(Capability).values(
                    id=ID("capability", self.mod, cap_code),
                    competency_id=comp_id,
                    code=cap_code,
                    name=cap["nombre"],
                    sort_order=k,
                )
            )
            self.sum.capacidades += 1

    def criterio_legacy(self, cr: CriterioLegacy, order: int) -> None:
        # The capability code is <competency code>-CAP<numero>, so the competency code is
        # everything before the last "-CAP".
        comp_codigo = cr.capacidad[: cr.capacidad.rindex("-CAP")]
        self.exec(
            insert(EvaluationCriterion).values(
                id=ID("criterion", self.mod, cr.codigo),
                competency_id=ID("competency", self.mod, comp_codigo),
                capability_id=ID("capability", self.mod, cr.capacidad),
                code=cr.codigo,
                description=cr.descripcion,
                sort_order=order,
            )
        )
        self.sum.criterios += 1

    # ------------------------------------------------- desempeños y estándares --

    def curriculum_data(self) -> None:
        """For every competency the school has: its learning standards (levels 1-8), the
        grade-level performances of the school's grades with the derived stance, and the
        (modality, cycle) -> expected level mapping for the cycles those grades belong to."""
        grades: list[tuple[dict[str, Any], UUID]] = []
        for g in self.s.grados:
            cg = self.cat.grado.get(g.grado_cneb)
            if cg is None:
                raise RuntimeError(
                    f'grado {g.codigo}: grado_cneb "{g.grado_cneb}" no está en el catálogo'
                )
            grades.append((cg, ID("grade", self.mod, g.codigo)))
        seen: set[str] = set()
        for cg, _ in grades:
            if cg["ciclo"] in seen:
                continue
            seen.add(cg["ciclo"])
            level = self.cat.expected_level(DEFAULT_MODALITY, cg["ciclo"])
            if level is None:
                raise RuntimeError(
                    f"ciclo {cg['ciclo']}: el catálogo no declara el nivel esperado para la "
                    f"modalidad {DEFAULT_MODALITY}"
                )
            self.exec(
                insert(StandardLevelMapping).values(
                    id=ID("standard_level_mapping", self.mod, f"{DEFAULT_MODALITY}:{cg['ciclo']}"),
                    modality=DEFAULT_MODALITY,
                    cycle=cg["ciclo"],
                    expected_level=level,
                )
            )
        for a in self.s.areas:
            for cc in self.cat.area[a.codigo]["competencias"]:
                self.curriculum_of_competency(cc["codigo"], grades)
        for code in self.s.competencias_transversales:
            # Transversals have no grade-level performances (deferred); their standards still
            # serve the descriptive conclusion.
            comp = self.cat.competencia_by_code(code)
            if comp is None:
                raise RuntimeError(f"competencia transversal {code}: no está en el catálogo")
            self.standards(code, comp)

    def curriculum_of_competency(
        self, codigo: str, grades: list[tuple[dict[str, Any], UUID]]
    ) -> None:
        comp = self.cat.competencia_by_code(codigo)
        if comp is None:
            raise RuntimeError(f"competencia {codigo}: no está en el catálogo")
        self.standards(codigo, comp)
        comp_id = ID("competency", self.mod, codigo)
        for cg, level_id in grades:
            en_proceso = self.cat.en_proceso(cg["codigo"])
            expected = self.cat.expected_level(DEFAULT_MODALITY, cg["ciclo"])
            for d in comp["desempenos"]:
                if d["grado"] != cg["codigo"]:
                    continue
                suggested = None
                if d.get("capacidad_sugerida") is not None:
                    suggested = ID(
                        "capability", self.mod, capability_code(codigo, d["capacidad_sugerida"])
                    )
                self.exec(
                    insert(GradeLevelPerformance).values(
                        id=ID("performance", self.mod, f"{codigo}:{cg['codigo']}:{d['orden']}"),
                        competency_id=comp_id,
                        grade_level_id=level_id,
                        sort_order=d["orden"],
                        official_text=d["texto"],
                        en_proceso=en_proceso,
                        expected_standard_level=expected,
                        suggested_capability_id=suggested,
                    )
                )
                self.sum.desempenos += 1

    def standards(self, codigo: str, comp: dict[str, Any]) -> None:
        """Store a competency's learning standards verbatim. A standard's text may be a note
        instead of a description; it is stored verbatim like any other text."""
        comp_id = ID("competency", self.mod, codigo)
        for e in comp["estandares"]:
            self.exec(
                insert(LearningStandard).values(
                    id=ID("standard", self.mod, f"{codigo}:{e['nivel']}"),
                    competency_id=comp_id,
                    level=e["nivel"],
                    official_text=e["texto"],
                )
            )
            self.sum.estandares += 1

    def scales(self) -> None:
        """The one scale every school needs: AD/A/B/C are levels of achievement, the only thing
        that goes to SIAGIE. Marks given to an evidence are never a scale of their own."""
        scale_id = ID("scale", self.mod, SCALE_MINEDU)
        self.exec(
            insert(GradeScale).values(
                id=scale_id,
                code=SCALE_MINEDU,
                name="Escala MINEDU AD/A/B/C",
                kind="ordinal",
                min_value=1,
                max_value=4,
                decimals=0,
            )
        )
        for code, label, ordinal, min_norm, max_norm, color in MINEDU_LEVELS:
            self.exec(
                insert(GradeScaleLevel).values(
                    id=ID("scale_level", self.mod, f"{SCALE_MINEDU}:{code}"),
                    scale_id=scale_id,
                    code=code,
                    label=label,
                    short_label=code,
                    ordinal=ordinal,
                    min_normalized=min_norm,
                    max_normalized=max_norm,
                    color_key=color,
                )
            )

    # ------------------------------------------------------------------ aulas --

    def section_id(self, aula_key: str) -> UUID:
        return ID("section", self.mod, f"{self.anio}:{aula_key}")

    def aulas(self) -> None:
        for g in self.s.grados:
            # stage and cycle come from the catalog grade, not from the file: they are
            # curriculum facts, and the file's nivel is only what the school calls it.
            cg = self.cat.grado[g.grado_cneb]
            self.exec(
                insert(GradeLevel).values(
                    id=ID("grade", self.mod, g.codigo),
                    code=g.codigo,
                    label=g.etiqueta,
                    long_label=g.nombre_largo,
                    stage=cg["nivel"],
                    cycle=cg["ciclo"],
                    ordinal=g.orden,
                )
            )
        for a in self.s.aulas:
            tutor = self.teacher_id(a.tutor) if a.tutor else None
            section = self.section_id(a.key())
            self.exec(
                insert(Section).values(
                    id=section,
                    academic_year_id=self.year,
                    grade_level_id=ID("grade", self.mod, a.grado),
                    label=a.seccion,
                    name=a.nombre,
                    tutor_teacher_id=tutor,
                    shift=a.turno or "manana",
                    capacity=a.capacidad if a.capacidad > 0 else None,
                    status="active",
                )
            )
            self.sum.aulas += 1
            for e in a.estudiantes:
                self.estudiante(e, section)

    def estudiante(self, e: Estudiante, section_id: UUID) -> None:
        matricula = _date(e.fecha_matricula or self.s.anio_escolar.inicio)
        student_id = ID("student", self.mod, e.codigo)
        self.exec(
            insert(Student).values(
                id=student_id,
                student_code=e.codigo,
                siagie_code=_nz(e.codigo_siagie),
                given_name=e.nombres,
                paternal_surname=e.apellido_paterno,
                maternal_surname=_nz(e.apellido_materno),
                preferred_name=_nz(e.nombre_preferido),
                birthdate=_date(e.fecha_nacimiento),
                sex=_nz(e.sexo),
                document_type=_nz(e.tipo_documento),
                document_number=_nz(e.numero_documento),
                enrolled_on=matricula,
                status="active",
                inclusion_support=e.apoyo_inclusion,
            )
        )
        # The roster of a class is derived from section_memberships, so every class in this aula
        # shares these students without duplicating a row.
        self.exec(
            insert(SectionMembership).values(
                student_id=student_id,
                section_id=section_id,
                academic_year_id=self.year,
                joined_on=matricula,
                status="active",
            )
        )
        self.sum.estudiantes += 1

    # ----------------------------------------------------------------- clases --

    def class_id(self, codigo: str) -> UUID:
        return ID("class", self.mod, f"{self.anio}:{codigo}")

    def schedule_id(self, clase_codigo: str, dia: int, inicio: str) -> UUID:
        return ID("schedule", self.mod, f"{self.anio}:{clase_codigo}:{dia}:{_clock(inicio)}")

    def clases(self) -> None:
        aulas = {a.key(): a for a in self.s.aulas}
        areas = {a.codigo: a for a in self.s.areas}
        grados = {g.codigo: g for g in self.s.grados}
        courses: set[str] = set()
        for c in self.s.clases:
            aula, area = aulas[c.aula], areas[c.area]
            grade_id = ID("grade", self.mod, aula.grado)
            # One course per área and grado; every class of that pair shares it.
            course_key = f"{self.anio}:{c.area}:{aula.grado}"
            course_id = ID("course", self.mod, course_key)
            if course_key not in courses:
                self.exec(
                    insert(Course).values(
                        id=course_id,
                        academic_year_id=self.year,
                        subject_id=ID("subject", self.mod, c.area),
                        grade_level_id=grade_id,
                        name=f"{area.nombre} {grados[aula.grado].etiqueta}",
                        weekly_hours=c.horas_semanales if c.horas_semanales > 0 else None,
                    )
                )
                courses.add(course_key)
            class_id = self.class_id(c.codigo)
            self.exec(
                insert(Class).values(
                    id=class_id,
                    academic_year_id=self.year,
                    grade_level_id=grade_id,
                    course_id=course_id,
                    section_id=self.section_id(c.aula),
                    name=c.nombre,
                    code=c.codigo,
                    default_room=_nz(c.salon),
                    status="active",
                )
            )
            self.exec(
                insert(ClassTeacher).values(
                    class_id=class_id,
                    teacher_id=self.teacher_id(c.docente),
                    role="titular",
                    starts_on=self.first_day,
                )
            )
            self.sum.clases += 1
            for f in c.horario:
                dia = _weekday(f.dia)
                self.exec(
                    insert(ClassSchedule).values(
                        id=self.schedule_id(c.codigo, dia, f.inicio),
                        class_id=class_id,
                        weekday=dia,
                        starts_at=_time(f.inicio),
                        ends_at=_time(f.fin),
                        room=_nz(_room_for(c, f)),
                        effective_from=self.first_day,
                    )
                )
                self.sum.franjas += 1

    # ---------------------------------------------------------------- sesiones --

    def sesiones(self) -> None:
        """Materialise the lessons. The app only ever reads class_sessions, it never creates
        them, so without this a freshly loaded teacher would see no lesson at all. One session per
        horario franja per matching date inside each periodo, all 'scheduled', skipping the días
        no lectivos; the time zone conversion is Postgres' so the dates line up with how the app
        computes "today" in the school's zone."""
        tz = self.s.colegio.zona_horaria or "America/Lima"
        cs, n = ClassSession, NonTeachingDay
        for c in self.s.clases:
            class_id = self.class_id(c.codigo)
            for f in c.horario:
                dia = _weekday(f.dia)
                start, end = _clock(f.inicio), _clock(f.fin)
                for p in self.s.anio_escolar.periodos:
                    g = _days(date.fromisoformat(p.inicio), date.fromisoformat(p.fin))
                    day = cast(g, Date)
                    # The id is md5('session:<modular>:<year>:<class>:<date>:<start>')::uuid, the
                    # rule seed_demo.sql relies on.
                    prefix = f"session:{self.mod}:{self.anio}:{c.codigo}:"
                    session_id = cast(
                        func.md5(literal(prefix, Text) + cast(day, Text) + ":" + start), PgUUID
                    )

                    def at(clock: str, day: Any = day) -> Any:
                        """The date at a local wall-clock time, in the school's zone."""
                        local = cast(day, DateTime) + timedelta(minutes=parse_clock(clock))
                        return func.timezone(tz, local)

                    holiday = (
                        select(1)
                        .where(
                            n.academic_year_id == self.year,
                            n.day == day,
                            n.deleted_at.is_(None),
                        )
                        .exists()
                    )
                    self.sum.sesiones += self.count(
                        insert(cs)
                        .from_select(
                            [
                                "id",
                                "academic_year_id",
                                "class_id",
                                "schedule_id",
                                "term_id",
                                "session_date",
                                "scheduled_start_at",
                                "scheduled_end_at",
                                "status",
                                "room",
                            ],
                            select(
                                session_id,
                                literal(self.year, cs.academic_year_id.type),
                                literal(class_id, cs.class_id.type),
                                literal(
                                    self.schedule_id(c.codigo, dia, f.inicio), cs.schedule_id.type
                                ),
                                literal(self.term_id(p), cs.term_id.type),
                                day,
                                at(start),
                                at(end),
                                literal("scheduled", cs.status.type),
                                literal(_nz(_room_for(c, f)), cs.room.type),
                            ).where(extract("isodow", g) == dia, ~holiday),
                        )
                        .returning(cs.id)
                    )
            # A tema names the first session of its date: when a class meets twice on one day,
            # the first block is the one the plan refers to.
            for s in c.sesiones:
                first = (
                    select(cs.id)
                    .where(cs.class_id == class_id, cs.session_date == date.fromisoformat(s.fecha))
                    .order_by(cs.scheduled_start_at)
                    .limit(1)
                    .scalar_subquery()
                )
                rows = self.conn.execute(
                    update(cs).where(cs.id == first).values(topic=s.tema.strip())
                ).rowcount
                if rows != 1:
                    raise RuntimeError(
                        f'clase {c.codigo}: no hay sesión el {s.fecha} para ponerle el tema "{s.tema}"'
                    )
                self.sum.sesiones_con_tema += 1
