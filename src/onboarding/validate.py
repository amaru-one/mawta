"""Everything that can be checked in an onboarding file without a database: formats, allowed values,
every cross-reference, date ranges and overlapping horarios. Most of these the schema enforces too,
but a Postgres constraint name means nothing to the person who filled in the file.

Every problem found is reported, one line each, prefixed with the JSON path of the offending
value, so the onboarding team fixes them all in one pass.
"""

import re
import zoneinfo
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import auth as authpkg
from curriculum import Catalog
from onboarding.spec import (
    AnioEscolar,
    Area,
    Aula,
    Clase,
    Colegio,
    Docente,
    Estudiante,
    Grado,
    Spec,
)


class ValidationErrors(Exception):
    errors: list[str]

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("\n".join(errors))


_RE_MODULAR = re.compile(r"^[0-9]{7}$")
_RE_USERNAME = re.compile(r"^[a-z0-9._-]{3,64}$")
_RE_SIAGIE = re.compile(r"^[0-9]{14}$")
_RE_DNI = re.compile(r"^[0-9]{8}$")

_WEEKDAYS = {
    "lunes": 1, "martes": 2, "miercoles": 3, "jueves": 4,
    "viernes": 5, "sabado": 6, "domingo": 7,
}  # fmt: skip
_WEEKDAY_NAMES = ["", "lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
_MAX_PERIODOS = {"bimestre": 4, "trimestre": 3, "semestre": 2}


def parse_date(value: str) -> date:
    text = value.strip()
    if len(text) != 10:
        raise ValueError(text)
    return date.fromisoformat(text)


def parse_clock(value: str) -> int:
    """ "08:00" -> minutes since midnight."""
    t = datetime.strptime(value.strip(), "%H:%M")
    return t.hour * 60 + t.minute


def parse_weekday(value: str) -> int | None:
    """ "lunes", "Miércoles", "sabado" -> ISO 1..7."""
    text = value.strip().lower().translate(str.maketrans("áéíóú", "aeiou"))
    return _WEEKDAYS.get(text)


def _is_placeholder(value: str) -> bool:
    """Template text left unfilled, like "<nombre del colegio>"."""
    v = value.strip()
    return v.startswith("<") and v.endswith(">")


@dataclass
class _Slot:
    path: str
    aula: str
    docente: str
    dia: int
    inicio: int
    fin: int


class _Checker:
    cat: Catalog

    def __init__(self, cat: Catalog) -> None:
        self.cat = cat
        self.errs: list[str] = []

    def addf(self, path: str, message: str) -> None:
        self.errs.append(f"{path}: {message}")

    def required(self, path: str, value: str) -> bool:
        if not value.strip():
            self.addf(path, "es obligatorio")
            return False
        if _is_placeholder(value):
            self.addf(path, f'falta completar (todavía dice "{value}")')
            return False
        return True

    def optional(self, path: str, value: str) -> bool:
        """Filled in; empty is fine, a leftover placeholder is not."""
        if _is_placeholder(value):
            self.addf(path, f'falta completar o dejar vacío (todavía dice "{value}")')
            return False
        return bool(value.strip())

    def one_of(self, path: str, value: str, *allowed: str) -> None:
        if value not in allowed:
            self.addf(path, f'"{value}" no es válido; usa uno de: {", ".join(allowed)}')

    def need_date(self, path: str, value: str) -> date | None:
        if not self.required(path, value):
            return None
        try:
            return parse_date(value)
        except ValueError:
            self.addf(
                path,
                f'"{value}" no es una fecha válida; usa el formato AAAA-MM-DD, por ejemplo '
                "2026-03-02",
            )
            return None

    def optional_date(self, path: str, value: str) -> date | None:
        if not self.optional(path, value):
            return None
        return self.need_date(path, value)

    def clock(self, path: str, value: str) -> int | None:
        if not self.required(path, value):
            return None
        try:
            return parse_clock(value)
        except ValueError:
            self.addf(
                path,
                f'"{value}" no es una hora válida; usa HH:MM en formato de 24 horas, por ejemplo '
                "08:00 o 14:30",
            )
            return None

    def unique(self, seen: dict[str, str], path: str, what: str, value: str) -> None:
        if not value:
            return
        if value in seen:
            self.addf(path, f'{what} "{value}" está repetido (ya aparece en {seen[value]})')
            return
        seen[value] = path

    # ---------------------------------------------------------------- colegio --

    def colegio(self, c: Colegio) -> None:
        self.required("colegio.nombre", c.nombre)
        self.optional("colegio.razon_social", c.razon_social)
        if self.required("colegio.codigo_modular", c.codigo_modular) and not _RE_MODULAR.match(
            c.codigo_modular
        ):
            self.addf(
                "colegio.codigo_modular",
                f'"{c.codigo_modular}" debe tener exactamente 7 dígitos (código modular MINEDU)',
            )
        if self.required("colegio.tipo", c.tipo):
            self.one_of("colegio.tipo", c.tipo, "publica", "privada", "parroquial", "internacional")
        self.optional("colegio.ciudad", c.ciudad)
        self.optional("colegio.region", c.region)
        if self.optional("colegio.zona_horaria", c.zona_horaria):
            try:
                if c.zona_horaria == "Local":
                    raise ValueError
                zoneinfo.ZoneInfo(c.zona_horaria)
            except (zoneinfo.ZoneInfoNotFoundError, ValueError):
                self.addf(
                    "colegio.zona_horaria",
                    f'"{c.zona_horaria}" no es una zona horaria IANA; en Perú es America/Lima',
                )

    # ------------------------------------------------------------ año escolar --

    def anio(self, a: AnioEscolar) -> list[tuple[int, date, date]]:
        if a.anio < 2000 or a.anio > 2100:
            self.addf("anio_escolar.anio", f"{a.anio} no es un año válido")
        self.required("anio_escolar.nombre", a.nombre)
        inicio = self.need_date("anio_escolar.inicio", a.inicio)
        fin = self.need_date("anio_escolar.fin", a.fin)
        if inicio and fin and not fin > inicio:
            self.addf("anio_escolar.fin", "debe ser posterior a anio_escolar.inicio")
        if inicio and inicio.year != a.anio:
            self.addf("anio_escolar.inicio", f"{a.inicio} no cae en el año {a.anio}")
        maximo = 6
        if self.required("anio_escolar.estructura", a.estructura):
            self.one_of(
                "anio_escolar.estructura", a.estructura, "bimestre", "trimestre", "semestre"
            )
            maximo = _MAX_PERIODOS.get(a.estructura, maximo)

        if not a.periodos:
            self.addf(
                "anio_escolar.periodos",
                "debe haber al menos un periodo (bimestre, trimestre o semestre) con su horario",
            )
            return []
        out: list[tuple[int, date, date]] = []
        numeros: dict[str, str] = {}
        for i, p in enumerate(a.periodos):
            path = f"anio_escolar.periodos[{i}]"
            if p.numero < 1 or p.numero > maximo:
                self.addf(
                    f"{path}.numero",
                    f'{p.numero} no es válido; con estructura "{a.estructura}" va de 1 a {maximo}',
                )
            self.unique(numeros, f"{path}.numero", "el número de periodo", str(p.numero))
            self.required(f"{path}.nombre", p.nombre)
            self.optional(f"{path}.abreviatura", p.abreviatura)
            pi = self.need_date(f"{path}.inicio", p.inicio)
            pf = self.need_date(f"{path}.fin", p.fin)
            self.optional_date(f"{path}.fecha_entrega_notas", p.fecha_entrega_notas)
            if pi is None or pf is None:
                continue
            if not pf > pi:
                self.addf(f"{path}.fin", f"debe ser posterior a {path}.inicio")
                continue
            if inicio and fin and (pi < inicio or pf > fin):
                self.addf(
                    path,
                    f"del {p.inicio} al {p.fin} se sale del año escolar ({a.inicio} a {a.fin})",
                )
            for j, (_, prev_i, prev_f) in enumerate(out):
                # Both ends inclusive, as terms_no_overlap compares them.
                if not pi > prev_f and not prev_i > pf:
                    self.addf(
                        path,
                        f"se superpone con anio_escolar.periodos[{j}]; un periodo debe empezar "
                        "después del día en que termina el anterior",
                    )
            out.append((p.numero, pi, pf))
        return out

    # -------------------------------------------------------- días no lectivos --

    def dias_no_lectivos(self, a: AnioEscolar) -> dict[str, str]:
        """The school's days without class by date, each with the path that declared it, so a
        session tema on one of those days can name where the day came from."""
        out: dict[str, str] = {}
        try:
            inicio, fin = parse_date(a.inicio), parse_date(a.fin)
            year_known = True
        except ValueError:
            inicio = fin = date.min
            year_known = False
        for i, d in enumerate(a.dias_no_lectivos):
            path = f"anio_escolar.dias_no_lectivos[{i}]"
            if self.required(f"{path}.tipo", d.tipo):
                self.one_of(f"{path}.tipo", d.tipo, "feriado", "vacaciones", "gestion")
            self.optional(f"{path}.nombre", d.nombre)
            has_fecha = bool(d.fecha.strip())
            has_rango = bool(d.desde.strip() or d.hasta.strip())
            if has_fecha and has_rango:
                self.addf(path, "usa fecha (un día) o desde y hasta (un rango), no ambos")
                continue
            if has_fecha:
                f = self.need_date(f"{path}.fecha", d.fecha)
                if f is None:
                    continue
                desde = hasta = f
            elif has_rango:
                de = self.need_date(f"{path}.desde", d.desde)
                ha = self.need_date(f"{path}.hasta", d.hasta)
                if de is None or ha is None:
                    continue
                if ha < de:
                    self.addf(f"{path}.hasta", f"{d.hasta} es anterior a desde ({d.desde})")
                    continue
                desde, hasta = de, ha
            else:
                self.addf(path, "falta fecha (un día) o desde y hasta (un rango)")
                continue
            if year_known and (desde < inicio or hasta > fin):
                self.addf(
                    path,
                    f"del {desde.isoformat()} al {hasta.isoformat()} se sale del año escolar "
                    f"({a.inicio} a {a.fin})",
                )
                continue
            day = desde
            while day <= hasta:
                key = day.isoformat()
                if key in out:
                    self.addf(
                        path,
                        f"el día {key} ya está en {out[key]}; cada día no lectivo se declara una "
                        "sola vez",
                    )
                else:
                    out[key] = path
                day += timedelta(days=1)
        return out

    # --------------------------------------------------------------- docentes --

    def docentes(self, ds: list[Docente]) -> set[str]:
        known: set[str] = set()
        if not ds:
            self.addf("docentes", "debe haber al menos un docente")
        usuarios: dict[str, str] = {}
        emails: dict[str, str] = {}
        codigos: dict[str, str] = {}
        for i, d in enumerate(ds):
            path = f"docentes[{i}]"
            if self.required(f"{path}.usuario", d.usuario):
                if not _RE_USERNAME.match(d.usuario):
                    self.addf(
                        f"{path}.usuario",
                        f'"{d.usuario}" solo puede tener minúsculas, números, punto, guion o '
                        "guion bajo, entre 3 y 64 caracteres",
                    )
                self.unique(usuarios, f"{path}.usuario", "el usuario", d.usuario)
                known.add(d.usuario)
            if self.required(f"{path}.clave", d.clave):
                try:
                    authpkg.validate_password(d.clave)
                except authpkg.PasswordLengthError:
                    self.addf(
                        f"{path}.clave",
                        f"debe tener entre {authpkg.MIN_PASSWORD_LEN} y {authpkg.MAX_PASSWORD_LEN} "
                        f"caracteres (tiene {len(d.clave.encode())})",
                    )
            if self.required(f"{path}.email", d.email):
                if "@" not in d.email:
                    self.addf(f"{path}.email", f'"{d.email}" no parece un correo')
                self.unique(emails, f"{path}.email", "el correo", d.email.strip().lower())
            self.required(f"{path}.nombres", d.nombres)
            self.required(f"{path}.apellidos", d.apellidos)
            self.optional(f"{path}.nombre_visible", d.nombre_visible)
            self.optional(f"{path}.cargo", d.cargo)
            if self.optional(f"{path}.codigo_empleado", d.codigo_empleado):
                self.unique(
                    codigos, f"{path}.codigo_empleado", "el código de empleado", d.codigo_empleado
                )
            self.optional_date(f"{path}.fecha_ingreso", d.fecha_ingreso)
        return known

    # ------------------------------------------------------------------ áreas --

    def areas(self, areas: list[Area], transversales: list[str]) -> set[str]:
        """Each área against the catalog: the code must name a catalog area, and the legacy
        criteria (if any) must point at capabilities the catalog defines for that area."""
        known: set[str] = set()
        if not areas:
            self.addf("areas", "debe haber al menos un área")
        area_codes: dict[str, str] = {}
        # Criterio codes are unique across the whole school, not just within their parent.
        crits: dict[str, str] = {}
        for i, a in enumerate(areas):
            path = f"areas[{i}]"
            if self.required(f"{path}.codigo", a.codigo):
                self.unique(area_codes, f"{path}.codigo", "el código de área", a.codigo)
                known.add(a.codigo)
                if a.codigo not in self.cat.area:
                    listing = ", ".join(x["codigo"] for x in self.cat.areas)
                    self.addf(
                        f"{path}.codigo",
                        f'"{a.codigo}" no es un área del catálogo CNEB; las áreas disponibles '
                        f"son: {listing}",
                    )
            self.required(f"{path}.nombre", a.nombre)
            self.optional(f"{path}.icono", a.icono)
            for j, cr in enumerate(a.criterios_legacy):
                cpath = f"{path}.criterios_legacy[{j}]"
                if self.required(f"{cpath}.codigo", cr.codigo):
                    self.unique(crits, f"{cpath}.codigo", "el código de criterio", cr.codigo)
                self.required(f"{cpath}.descripcion", cr.descripcion)
                if self.required(f"{cpath}.capacidad", cr.capacidad):
                    if cr.capacidad not in self.cat.capability_codes_by_area.get(a.codigo, set()):
                        self.addf(
                            f"{cpath}.capacidad",
                            f'"{cr.capacidad}" no es una capacidad del área {a.codigo} en el '
                            "catálogo CNEB",
                        )
        seen: dict[str, str] = {}
        for i, code in enumerate(transversales):
            cpath = f"competencias_transversales[{i}]"
            if self.required(cpath, code):
                self.unique(seen, cpath, "la competencia transversal", code)
                if code not in self.cat.transversal:
                    listing = ", ".join(t["codigo"] for t in self.cat.transversales)
                    self.addf(
                        cpath,
                        f'"{code}" no es una competencia transversal del catálogo CNEB; las '
                        f"disponibles son: {listing}",
                    )
        return known

    # ----------------------------------------------------------------- grados --

    def grados(self, gs: list[Grado]) -> dict[str, Grado]:
        known: dict[str, Grado] = {}
        if not gs:
            self.addf("grados", "debe haber al menos un grado")
        codes: dict[str, str] = {}
        ordenes: dict[str, str] = {}
        for i, g in enumerate(gs):
            path = f"grados[{i}]"
            if self.required(f"{path}.codigo", g.codigo):
                self.unique(codes, f"{path}.codigo", "el código de grado", g.codigo)
                known[g.codigo] = g
            self.required(f"{path}.etiqueta", g.etiqueta)
            self.required(f"{path}.nombre_largo", g.nombre_largo)
            if self.required(f"{path}.nivel", g.nivel):
                self.one_of(f"{path}.nivel", g.nivel, "inicial", "primaria", "secundaria", "otro")
            if g.orden < 1:
                self.addf(
                    f"{path}.orden", "debe ser un número mayor que 0 (1ro de secundaria es 7)"
                )
            else:
                self.unique(ordenes, f"{path}.orden", "el orden", str(g.orden))
            # grado_cneb names a catalog grade: it sets grade_levels.stage and cycle, and
            # selects which performances the loader copies.
            if self.required(f"{path}.grado_cneb", g.grado_cneb):
                if g.grado_cneb not in self.cat.grado:
                    self.addf(
                        f"{path}.grado_cneb",
                        f'"{g.grado_cneb}" no es un grado del catálogo CNEB; los grados son: '
                        f"{self.cat.grade_list()}",
                    )
        return known

    # ------------------------------------------------------------------ aulas --

    def aulas(
        self, aulas: list[Aula], grados: dict[str, Grado], docentes: set[str], anio: AnioEscolar
    ) -> dict[str, Aula]:
        known: dict[str, Aula] = {}
        if not aulas:
            self.addf("aulas", "debe haber al menos un aula")
        keys: dict[str, str] = {}
        codes: dict[str, str] = {}
        siagies: dict[str, str] = {}
        docs: dict[str, str] = {}
        try:
            anio_inicio: date | None = parse_date(anio.inicio)
            anio_fin: date | None = parse_date(anio.fin)
        except ValueError:
            anio_inicio = anio_fin = None
        for i, a in enumerate(aulas):
            path = f"aulas[{i}]"
            ok_g = self.required(f"{path}.grado", a.grado)
            if ok_g and a.grado not in grados:
                self.addf(f"{path}.grado", f'"{a.grado}" no está en la lista de grados')
            if self.required(f"{path}.seccion", a.seccion) and ok_g:
                self.unique(keys, path, "el aula", a.key())
                known[a.key()] = a
            self.required(f"{path}.nombre", a.nombre)
            if self.optional(f"{path}.tutor", a.tutor) and a.tutor not in docentes:
                self.addf(f"{path}.tutor", f'"{a.tutor}" no está en la lista de docentes')
            if a.turno:
                self.one_of(f"{path}.turno", a.turno, "manana", "tarde", "noche", "completo")
            if a.capacidad < 0:
                self.addf(f"{path}.capacidad", "no puede ser negativa")
            if a.capacidad > 0 and len(a.estudiantes) > a.capacidad:
                self.addf(
                    f"{path}.estudiantes",
                    f"hay {len(a.estudiantes)} estudiantes y la capacidad del aula es {a.capacidad}",
                )
            for j, e in enumerate(a.estudiantes):
                self.estudiante(
                    f"{path}.estudiantes[{j}]", e, codes, siagies, docs, anio_inicio, anio_fin
                )
        return known

    def estudiante(
        self,
        path: str,
        e: Estudiante,
        codes: dict[str, str],
        siagies: dict[str, str],
        docs: dict[str, str],
        anio_inicio: date | None,
        anio_fin: date | None,
    ) -> None:
        if self.required(f"{path}.codigo", e.codigo):
            self.unique(codes, f"{path}.codigo", "el código de estudiante", e.codigo)
        if self.optional(f"{path}.codigo_siagie", e.codigo_siagie):
            if not _RE_SIAGIE.match(e.codigo_siagie):
                self.addf(
                    f"{path}.codigo_siagie",
                    f'"{e.codigo_siagie}" debe tener exactamente 14 dígitos',
                )
            self.unique(siagies, f"{path}.codigo_siagie", "el código SIAGIE", e.codigo_siagie)
        self.required(f"{path}.nombres", e.nombres)
        self.required(f"{path}.apellido_paterno", e.apellido_paterno)
        self.optional(f"{path}.apellido_materno", e.apellido_materno)
        self.optional(f"{path}.nombre_preferido", e.nombre_preferido)
        self.optional_date(f"{path}.fecha_nacimiento", e.fecha_nacimiento)
        if e.sexo:
            self.one_of(f"{path}.sexo", e.sexo, "F", "M", "X", "unspecified")
        has_type = self.optional(f"{path}.tipo_documento", e.tipo_documento)
        has_num = self.optional(f"{path}.numero_documento", e.numero_documento)
        if has_type != has_num:
            self.addf(
                path,
                "tipo_documento y numero_documento van juntos: completa ambos o deja ambos vacíos",
            )
        elif has_type:
            self.one_of(
                f"{path}.tipo_documento", e.tipo_documento, "DNI", "CE", "PAS", "PTP", "otro"
            )
            if e.tipo_documento == "DNI" and not _RE_DNI.match(e.numero_documento):
                self.addf(
                    f"{path}.numero_documento",
                    f'"{e.numero_documento}" no es un DNI: debe tener 8 dígitos',
                )
            self.unique(
                docs,
                f"{path}.numero_documento",
                "el documento",
                f"{e.tipo_documento} {e.numero_documento}",
            )
        d = self.optional_date(f"{path}.fecha_matricula", e.fecha_matricula)
        if d and anio_inicio and anio_fin and (d < anio_inicio or d > anio_fin):
            self.addf(f"{path}.fecha_matricula", f"{e.fecha_matricula} está fuera del año escolar")

    # ----------------------------------------------------------------- clases --

    def clases(
        self,
        cs: list[Clase],
        areas: set[str],
        aulas: dict[str, Aula],
        docentes: set[str],
        periodos: list[tuple[int, date, date]],
        no_lectivos: dict[str, str],
    ) -> None:
        if not cs:
            self.addf("clases", "debe haber al menos una clase")
        nombres: dict[str, str] = {}
        codigos: dict[str, str] = {}
        pares: dict[str, str] = {}
        horas: dict[str, tuple[str, float]] = {}
        slots: list[_Slot] = []
        for i, c in enumerate(cs):
            path = f"clases[{i}]"
            # classes.name is NOT NULL and is what the teacher reads in "mis clases".
            if self.required(f"{path}.nombre", c.nombre):
                self.unique(nombres, f"{path}.nombre", "el nombre de clase", c.nombre)
            if self.required(f"{path}.codigo", c.codigo):
                self.unique(codigos, f"{path}.codigo", "el código de clase", c.codigo)
            ok_a = self.required(f"{path}.area", c.area)
            if ok_a and c.area not in areas:
                self.addf(f"{path}.area", f'"{c.area}" no está en la lista de áreas')
                ok_a = False
            aula = aulas.get(c.aula)
            if self.required(f"{path}.aula", c.aula) and aula is None:
                self.addf(
                    f"{path}.aula",
                    f'"{c.aula}" no existe; un aula se nombra grado-sección, por ejemplo "1S-A"',
                )
            if self.required(f"{path}.docente", c.docente) and c.docente not in docentes:
                self.addf(f"{path}.docente", f'"{c.docente}" no está en la lista de docentes')
            # classes_course_section_key: one class per área per aula.
            if ok_a and aula is not None:
                self.unique(pares, path, "la combinación área-aula", f"{c.area} en {c.aula}")
                # Classes of the same área and grado share one course, and
                # courses.weekly_hours is a single number.
                key = f"{c.area}|{aula.grado}"
                prev = horas.get(key)
                if prev is not None and prev[1] != c.horas_semanales:
                    self.addf(
                        f"{path}.horas_semanales",
                        f"{c.horas_semanales:g} no coincide con {prev[1]:g} en {prev[0]}: las "
                        "clases de la misma área y grado comparten las horas semanales",
                    )
                elif prev is None:
                    horas[key] = (path, c.horas_semanales)
            if c.horas_semanales < 0:
                self.addf(f"{path}.horas_semanales", "no puede ser negativo")
            self.optional(f"{path}.salon", c.salon)

            if not c.horario:
                self.addf(
                    f"{path}.horario", "la clase debe tener al menos una franja en el horario"
                )
            dias: set[int] = set()
            for j, f in enumerate(c.horario):
                fpath = f"{path}.horario[{j}]"
                dia = None
                if self.required(f"{fpath}.dia", f.dia):
                    dia = parse_weekday(f.dia)
                    if dia is None:
                        self.addf(
                            f"{fpath}.dia",
                            f'"{f.dia}" no es un día; usa lunes, martes, miércoles, jueves, '
                            "viernes, sábado o domingo",
                        )
                ini = self.clock(f"{fpath}.inicio", f.inicio)
                fin = self.clock(f"{fpath}.fin", f.fin)
                self.optional(f"{fpath}.salon", f.salon)
                if ini is not None and fin is not None and fin <= ini:
                    self.addf(f"{fpath}.fin", "debe ser posterior a la hora de inicio")
                    continue
                if dia is not None and ini is not None and fin is not None:
                    dias.add(dia)
                    slots.append(_Slot(fpath, c.aula, c.docente, dia, ini, fin))

            fechas: dict[str, str] = {}
            for j, s in enumerate(c.sesiones):
                spath = f"{path}.sesiones[{j}]"
                self.required(f"{spath}.tema", s.tema)
                d = self.need_date(f"{spath}.fecha", s.fecha)
                if d is None:
                    continue
                self.unique(fechas, f"{spath}.fecha", "la fecha de sesión", d.isoformat())
                if not any(pi <= d <= pf for _, pi, pf in periodos):
                    self.addf(
                        f"{spath}.fecha",
                        f"{s.fecha} no cae dentro de ningún periodo del año escolar",
                    )
                if dias and d.isoweekday() not in dias:
                    listing = ", ".join(_WEEKDAY_NAMES[x] for x in sorted(dias))
                    self.addf(
                        f"{spath}.fecha",
                        f"{s.fecha} es {_WEEKDAY_NAMES[d.isoweekday()]} y la clase no tiene "
                        f"horario ese día; sus días son: {listing}",
                    )
                if d.isoformat() in no_lectivos:
                    self.addf(
                        f"{spath}.fecha",
                        f"{s.fecha} es un día no lectivo ({no_lectivos[d.isoformat()]}); ese día "
                        "no hay sesión para ponerle tema",
                    )
        self.overlaps(slots)

    def overlaps(self, slots: list[_Slot]) -> None:
        """Two franjas at the same time for the same aula (the same students can't be in two
        classes) or for the same docente (double-booking)."""
        for i, a in enumerate(slots):
            for b in slots[i + 1 :]:
                if a.dia != b.dia or a.fin <= b.inicio or b.fin <= a.inicio:
                    continue
                if a.aula == b.aula:
                    self.addf(
                        b.path,
                        f"se cruza con {a.path}: el aula {b.aula} no puede tener dos clases a la vez",
                    )
                elif a.docente == b.docente:
                    self.addf(
                        b.path,
                        f"se cruza con {a.path}: el docente {b.docente} no puede dictar dos clases "
                        "a la vez",
                    )


def validate(spec: Spec, cat: Catalog) -> None:
    """Raise ValidationErrors listing everything wrong with the file."""
    v = _Checker(cat)
    v.colegio(spec.colegio)
    periodos = v.anio(spec.anio_escolar)
    no_lectivos = v.dias_no_lectivos(spec.anio_escolar)
    docentes = v.docentes(spec.docentes)
    areas = v.areas(spec.areas, spec.competencias_transversales)
    grados = v.grados(spec.grados)
    aulas = v.aulas(spec.aulas, grados, docentes, spec.anio_escolar)
    v.clases(spec.clases, areas, aulas, docentes, periodos, no_lectivos)
    if v.errs:
        raise ValidationErrors(v.errs)
