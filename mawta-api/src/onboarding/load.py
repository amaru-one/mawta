"""Write a whole school inside one transaction.

The caller owns the transaction: it commits, or rolls back for a dry run. The connection must
bypass row security (a superuser connection, as `useradd` uses): the first users/memberships rows
of a tenant cannot be written by mawta_app. Nothing is written unless the file validates and the
school does not exist yet; any failure part-way leaves the transaction for the caller to roll
back, so there is never a half-installed school.
"""

from dataclasses import dataclass, field
from typing import Any, LiteralString
from uuid import UUID

import psycopg
from psycopg.rows import DictRow

import auth as authpkg
from curriculum import DEFAULT_MODALITY, Catalog, capability_code
from db import returned
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
    tenant_id: UUID | None = None
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

    def __str__(self) -> str:
        return (
            f"Colegio:        {self.colegio} ({self.tenant_id})\n"
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


def load(conn: psycopg.Connection[DictRow], spec: Spec, cat: Catalog, bcrypt_cost: int) -> Summary:
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
        except psycopg.Error as exc:
            raise RuntimeError(f"{name}: {exc.diag.message_primary or exc}") from exc
    return loader.sum


class _Loader:
    def __init__(self, conn: psycopg.Connection[DictRow], spec: Spec, cat: Catalog) -> None:
        self.conn = conn
        self.s = spec
        self.cat = cat
        self.mod = spec.colegio.codigo_modular
        self.anio = str(spec.anio_escolar.anio)
        self.tenant = ID("tenant", self.mod, "")
        self.year = ID("year", self.mod, self.anio)
        self.sum = Summary(colegio=spec.colegio.nombre, tenant_id=self.tenant)
        # earliest periodo start: when titulars and horarios begin (ISO dates sort as strings)
        self.first_day = min(p.inicio for p in spec.anio_escolar.periodos)

    def exec(self, sql: LiteralString, params: tuple[Any, ...] | dict[str, Any] = ()) -> int:
        return self.conn.execute(sql, params).rowcount

    def precheck(self) -> None:
        """Refuse a school or an account that already exists, before writing anything, with a
        message about the file rather than a constraint."""
        exists = returned(
            self.conn.execute(
                "select exists (select 1 from tenants where modular_code = %s and deleted_at is null)"
                " as ok",
                (self.mod,),
            ).fetchone()
        )["ok"]
        if exists:
            raise ValidationErrors(
                [
                    f"colegio.codigo_modular: el colegio {self.mod} ya existe en esta base. Este "
                    "cargador solo instala colegios nuevos y no modificó nada."
                ]
            )
        usuarios = [d.usuario.lower() for d in self.s.docentes]
        emails = [d.email.strip().lower() for d in self.s.docentes]
        rows = self.conn.execute(
            """
            select coalesce(lower(username), '') as u, lower(email) as e from users
             where deleted_at is null
               and (lower(username) = any(%s::text[]) or lower(email) = any(%s::text[]))
            """,
            (usuarios, emails),
        ).fetchall()
        errs: list[str] = []
        for r in rows:
            for i, (u, e) in enumerate(zip(usuarios, emails, strict=True)):
                path = f"docentes[{i}]"
                if r["u"] and r["u"] == u:
                    errs.append(f'{path}.usuario: "{u}" ya existe en Mawta; elige otro')
                if r["e"] == e:
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
        tz = c.zona_horaria or "America/Lima"
        self.exec(
            """
            insert into tenants (id, name, legal_name, modular_code, kind, city, region, timezone,
                                 status)
            values (%s, %s, %s, %s, %s, %s, %s, %s, 'active')
            """,
            (self.tenant, c.nombre, _nz(c.razon_social), c.codigo_modular, c.tipo, _nz(c.ciudad),
             _nz(c.region), tz),
        )  # fmt: skip
        a = self.s.anio_escolar
        self.exec(
            """
            insert into academic_years (id, tenant_id, year, name, starts_on, ends_on,
                                        term_structure, status)
            values (%s, %s, %s, %s, %s::date, %s::date, %s, 'active')
            """,
            (self.year, self.tenant, a.anio, a.nombre, a.inicio, a.fin, a.estructura),
        )
        # Only the first periodo of the year goes in 'active' (terms_one_active_key allows one
        # per nivel); the rest are 'planned'. 'planned' still accepts scores, only 'closed' and
        # 'archived' are rejected, so the historical evidence of a later periodo can be loaded.
        first = min(p.numero for p in a.periodos)
        for p in a.periodos:
            self.exec(
                """
                insert into terms (id, tenant_id, academic_year_id, stage, sequence, name,
                                   short_name, starts_on, ends_on, status, grades_due_on)
                values (%s, %s, %s, null, %s, %s, %s, %s::date, %s::date, %s, %s::date)
                """,
                (self.term_id(p), self.tenant, self.year, p.numero, p.nombre, _nz(p.abreviatura),
                 p.inicio, p.fin, "active" if p.numero == first else "planned",
                 _nz(p.fecha_entrega_notas)),
            )  # fmt: skip
            self.sum.periodos += 1
        # One row per day: non_teaching_days is a set of dates, so a vacation range becomes every
        # date in it. Validate already rejected duplicates.
        for d in a.dias_no_lectivos:
            desde, hasta = (d.fecha, d.fecha) if d.fecha.strip() else (d.desde, d.hasta)
            self.sum.dias_no_lectivos += self.exec(
                """
                insert into non_teaching_days (tenant_id, academic_year_id, day, kind, label)
                select %s, %s, g.d::date, %s, %s
                  from generate_series(%s::date, %s::date, interval '1 day') as g(d)
                """,
                (self.tenant, self.year, d.tipo, _nz(d.nombre), desde, hasta),
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
                """
                insert into users (id, email, given_name, family_name, display_name, status,
                                   username, password_hash, password_changed_at,
                                   failed_login_count)
                values (%s, lower(%s), %s, %s, %s, 'active', %s, %s, now(), 0)
                """,
                (user_id, d.email.strip(), d.nombres, d.apellidos, display, d.usuario, hashed),
            )
            self.exec(
                """
                insert into memberships (id, tenant_id, user_id, role, status, joined_at)
                values (%s, %s, %s, 'teacher', 'active', now())
                """,
                (membership_id, self.tenant, user_id),
            )
            self.exec(
                """
                insert into teachers (id, tenant_id, membership_id, employee_code, display_name,
                                      title, hired_on, status)
                values (%s, %s, %s, %s, %s, %s, %s::date, 'active')
                """,
                (self.teacher_id(d.usuario), self.tenant, membership_id, _nz(d.codigo_empleado),
                 display, _nz(d.cargo), _nz(d.fecha_ingreso)),
            )  # fmt: skip
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
                """
                insert into subjects (id, tenant_id, code, name, area_curricular, icon_key,
                                      is_tutoria, sort_order)
                values (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (subject_id, self.tenant, a.codigo, a.nombre, a.nombre, _nz(a.icono),
                 a.es_tutoria, i),
            )  # fmt: skip
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
            """
            insert into competencies (id, tenant_id, subject_id, code, name, kind, sort_order,
                                      is_active)
            values (%s, %s, %s, %s, %s, %s, %s, true)
            """,
            (comp_id, self.tenant, subject_id, codigo, comp["nombre"], kind, order),
        )
        self.sum.competencias += 1
        for k, cap in enumerate(comp["capacidades"], start=1):
            cap_code = capability_code(codigo, cap["numero"])
            self.exec(
                """
                insert into capabilities (id, tenant_id, competency_id, code, name, sort_order)
                values (%s, %s, %s, %s, %s, %s)
                """,
                (ID("capability", self.mod, cap_code), self.tenant, comp_id, cap_code,
                 cap["nombre"], k),
            )  # fmt: skip
            self.sum.capacidades += 1

    def criterio_legacy(self, cr: CriterioLegacy, order: int) -> None:
        # The capability code is <competency code>-CAP<numero>, so the competency code is
        # everything before the last "-CAP".
        comp_codigo = cr.capacidad[: cr.capacidad.rindex("-CAP")]
        self.exec(
            """
            insert into evaluation_criteria (id, tenant_id, competency_id, capability_id, code,
                                             description, sort_order)
            values (%s, %s, %s, %s, %s, %s, %s)
            """,
            (ID("criterion", self.mod, cr.codigo), self.tenant, ID("competency", self.mod, comp_codigo),
             ID("capability", self.mod, cr.capacidad), cr.codigo, cr.descripcion, order),
        )  # fmt: skip
        self.sum.criterios += 1

    # ------------------------------------------------- desempeños y estándares --

    def curriculum_data(self) -> None:
        """For every competency the school has: its learning standards (levels 1-8), the
        grade-level performances of the school's grades with the derived stance, and the
        (modality, cycle) -> expected level mapping for the cycles those grades belong to."""
        grades = []
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
                """
                insert into standard_level_mappings (id, tenant_id, modality, cycle,
                                                     expected_level)
                values (%s, %s, %s, %s, %s)
                """,
                (ID("standard_level_mapping", self.mod, f"{DEFAULT_MODALITY}:{cg['ciclo']}"),
                 self.tenant, DEFAULT_MODALITY, cg["ciclo"], level),
            )  # fmt: skip
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
                    """
                    insert into grade_level_performances
                      (id, tenant_id, competency_id, grade_level_id, sort_order, official_text,
                       en_proceso, expected_standard_level, suggested_capability_id)
                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (ID("performance", self.mod, f"{codigo}:{cg['codigo']}:{d['orden']}"),
                     self.tenant, comp_id, level_id, d["orden"], d["texto"], en_proceso, expected,
                     suggested),
                )  # fmt: skip
                self.sum.desempenos += 1

    def standards(self, codigo: str, comp: dict[str, Any]) -> None:
        """Store a competency's learning standards verbatim. A standard's text may be a note
        instead of a description; it is stored verbatim like any other text."""
        comp_id = ID("competency", self.mod, codigo)
        for e in comp["estandares"]:
            self.exec(
                """
                insert into learning_standards (id, tenant_id, competency_id, level, official_text)
                values (%s, %s, %s, %s, %s)
                """,
                (ID("standard", self.mod, f"{codigo}:{e['nivel']}"), self.tenant, comp_id,
                 e["nivel"], e["texto"]),
            )  # fmt: skip
            self.sum.estandares += 1

    def scales(self) -> None:
        """The one scale every school needs: AD/A/B/C are levels of achievement, the only thing
        that goes to SIAGIE. Marks given to an evidence are never a scale of their own."""
        scale_id = ID("scale", self.mod, SCALE_MINEDU)
        self.exec(
            """
            insert into grade_scales (id, tenant_id, code, name, kind, min_value, max_value,
                                      decimals)
            values (%s, %s, %s, 'Escala MINEDU AD/A/B/C', 'ordinal', 1, 4, 0)
            """,
            (scale_id, self.tenant, SCALE_MINEDU),
        )
        for code, label, ordinal, min_norm, max_norm, color in MINEDU_LEVELS:
            self.exec(
                """
                insert into grade_scale_levels (id, tenant_id, scale_id, code, label, short_label,
                                                ordinal, min_normalized, max_normalized, color_key)
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (ID("scale_level", self.mod, f"{SCALE_MINEDU}:{code}"), self.tenant, scale_id,
                 code, label, code, ordinal, min_norm, max_norm, color),
            )  # fmt: skip

    # ------------------------------------------------------------------ aulas --

    def section_id(self, aula_key: str) -> UUID:
        return ID("section", self.mod, f"{self.anio}:{aula_key}")

    def aulas(self) -> None:
        for g in self.s.grados:
            # stage and cycle come from the catalog grade, not from the file: they are
            # curriculum facts, and the file's nivel is only what the school calls it.
            cg = self.cat.grado[g.grado_cneb]
            self.exec(
                """
                insert into grade_levels (id, tenant_id, code, label, long_label, stage, cycle,
                                          ordinal)
                values (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (ID("grade", self.mod, g.codigo), self.tenant, g.codigo, g.etiqueta,
                 g.nombre_largo, cg["nivel"], cg["ciclo"], g.orden),
            )  # fmt: skip
        for a in self.s.aulas:
            tutor = self.teacher_id(a.tutor) if a.tutor else None
            section = self.section_id(a.key())
            self.exec(
                """
                insert into sections (id, tenant_id, academic_year_id, grade_level_id, label, name,
                                      tutor_teacher_id, shift, capacity, status)
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'active')
                """,
                (section, self.tenant, self.year, ID("grade", self.mod, a.grado), a.seccion,
                 a.nombre, tutor, a.turno or "manana", a.capacidad if a.capacidad > 0 else None),
            )  # fmt: skip
            self.sum.aulas += 1
            for e in a.estudiantes:
                self.estudiante(e, section)

    def estudiante(self, e: Estudiante, section_id: UUID) -> None:
        matricula = e.fecha_matricula or self.s.anio_escolar.inicio
        student_id = ID("student", self.mod, e.codigo)
        self.exec(
            """
            insert into students (id, tenant_id, student_code, siagie_code, given_name,
                                  paternal_surname, maternal_surname, preferred_name, birthdate,
                                  sex, document_type, document_number, enrolled_on, status,
                                  inclusion_support)
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s::date, %s, %s, %s, %s::date, 'active', %s)
            """,
            (student_id, self.tenant, e.codigo, _nz(e.codigo_siagie), e.nombres, e.apellido_paterno,
             _nz(e.apellido_materno), _nz(e.nombre_preferido), _nz(e.fecha_nacimiento),
             _nz(e.sexo), _nz(e.tipo_documento), _nz(e.numero_documento), matricula,
             e.apoyo_inclusion),
        )  # fmt: skip
        # The roster of a class is derived from section_memberships, so every class in this aula
        # shares these students without duplicating a row.
        self.exec(
            """
            insert into section_memberships (tenant_id, student_id, section_id, academic_year_id,
                                             joined_on, status)
            values (%s, %s, %s, %s, %s::date, 'active')
            """,
            (self.tenant, student_id, section_id, self.year, matricula),
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
                    """
                    insert into courses (id, tenant_id, academic_year_id, subject_id,
                                         grade_level_id, name, weekly_hours)
                    values (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (course_id, self.tenant, self.year, ID("subject", self.mod, c.area), grade_id,
                     f"{area.nombre} {grados[aula.grado].etiqueta}",
                     c.horas_semanales if c.horas_semanales > 0 else None),
                )  # fmt: skip
                courses.add(course_key)
            class_id = self.class_id(c.codigo)
            self.exec(
                """
                insert into classes (id, tenant_id, academic_year_id, grade_level_id, course_id,
                                     section_id, name, code, default_room, status)
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'active')
                """,
                (class_id, self.tenant, self.year, grade_id, course_id, self.section_id(c.aula),
                 c.nombre, c.codigo, _nz(c.salon)),
            )  # fmt: skip
            self.exec(
                """
                insert into class_teachers (tenant_id, class_id, teacher_id, role, starts_on)
                values (%s, %s, %s, 'titular', %s::date)
                """,
                (self.tenant, class_id, self.teacher_id(c.docente), self.first_day),
            )
            self.sum.clases += 1
            for f in c.horario:
                dia = _weekday(f.dia)
                self.exec(
                    """
                    insert into class_schedules (id, tenant_id, class_id, weekday, starts_at,
                                                 ends_at, room, effective_from)
                    values (%s, %s, %s, %s, %s::time, %s::time, %s, %s::date)
                    """,
                    (self.schedule_id(c.codigo, dia, f.inicio), self.tenant, class_id, dia,
                     _clock(f.inicio), _clock(f.fin), _nz(_room_for(c, f)), self.first_day),
                )  # fmt: skip
                self.sum.franjas += 1

    # ---------------------------------------------------------------- sesiones --

    def sesiones(self) -> None:
        """Materialise the lessons. The app only ever reads class_sessions, it never creates
        them, so without this a freshly loaded teacher would see no lesson at all. One session per
        horario franja per matching date inside each periodo, all 'scheduled', skipping the días
        no lectivos; the time zone conversion is Postgres' so the dates line up with how the app
        computes "today" in the school's zone."""
        tz = self.s.colegio.zona_horaria or "America/Lima"
        for c in self.s.clases:
            class_id = self.class_id(c.codigo)
            for f in c.horario:
                dia = _weekday(f.dia)
                for p in self.s.anio_escolar.periodos:
                    self.sum.sesiones += self.exec(
                        """
                        insert into class_sessions (id, tenant_id, academic_year_id, class_id,
                               schedule_id, term_id, session_date, scheduled_start_at,
                               scheduled_end_at, status, room)
                        select md5(%(prefix)s::text || g.d::date::text || ':' || %(start)s::text)::uuid,
                               %(tenant)s, %(year)s, %(class)s, %(schedule)s, %(term)s, g.d::date,
                               (g.d::date + %(start)s::text::time) at time zone %(tz)s::text,
                               (g.d::date + %(end)s::text::time) at time zone %(tz)s::text,
                               'scheduled', %(room)s
                          from generate_series(%(from)s::date, %(to)s::date,
                                               interval '1 day') as g(d)
                         where extract(isodow from g.d) = %(dia)s
                           and not exists (select 1 from non_teaching_days n
                                            where n.tenant_id = %(tenant)s
                                              and n.academic_year_id = %(year)s
                                              and n.day = g.d::date and n.deleted_at is null)
                        """,
                        {
                            "prefix": f"session:{self.mod}:{self.anio}:{c.codigo}:",
                            "start": _clock(f.inicio),
                            "end": _clock(f.fin),
                            "tenant": self.tenant,
                            "year": self.year,
                            "class": class_id,
                            "schedule": self.schedule_id(c.codigo, dia, f.inicio),
                            "term": self.term_id(p),
                            "tz": tz,
                            "room": _nz(_room_for(c, f)),
                            "from": p.inicio,
                            "to": p.fin,
                            "dia": dia,
                        },
                    )
            # A tema names the first session of its date: when a class meets twice on one day,
            # the first block is the one the plan refers to.
            for s in c.sesiones:
                rows = self.exec(
                    """
                    update class_sessions set topic = %(topic)s
                     where id = (select id from class_sessions
                                  where class_id = %(class)s and session_date = %(date)s::date
                                  order by scheduled_start_at limit 1)
                    """,
                    {"topic": s.tema.strip(), "class": class_id, "date": s.fecha},
                )
                if rows != 1:
                    raise RuntimeError(
                        f'clase {c.codigo}: no hay sesión el {s.fecha} para ponerle el tema "{s.tema}"'
                    )
                self.sum.sesiones_con_tema += 1
