"""Generate the San Felipe demo school: first grade of secondary, two sections, ten áreas.

Writes three files from the content in seed/demo/contenido/ and the CNEB catalog:

  seed/onboarding/ejemplo-san-felipe.json  the school's structure, loaded with seed/onboard.sh
  seed/seed_demo.sql                       the lived year (T-I and T-II closed, T-III open)
  seed/demo/PERFILES.md                    the answer key: every student's profile and C counts

Everything is deterministic: the same inputs always produce the same files, and every id is the
md5-derived uuid the onboarding loader uses (src/onboarding/__init__.py), or one of the same shape.
Run it from mawta-api/:

  python3 seed/demo/build.py
"""

import datetime as dt
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypedDict
from uuid import UUID

type Json = dict[str, Any]
type Row = tuple[object, ...]

ROOT = Path(__file__).resolve().parents[2]  # mawta-api/
CATALOG = ROOT / "src" / "curriculum" / "cneb"
CONTENT = Path(__file__).parent / "contenido"
OUT_JSON = ROOT / "seed" / "onboarding" / "ejemplo-san-felipe.json"
OUT_SQL = ROOT / "seed" / "seed_demo.sql"
OUT_KEY = Path(__file__).parent / "PERFILES.md"

MOD = "0723519"
YEAR = 2026
SCALE = "minedu_ad_a_b_c"
LEVELS = ["C", "B", "A", "AD"]  # ordinal 1..4
# The day the voice notes stop: later sessions get attendance from the SQL's own clock, but no
# notes, so a reload next month does not invent notes for lessons that had not happened yet.
NOTES_UNTIL = dt.date(2026, 10, 22)


def ID(kind: str, key: str) -> UUID:
    """The loader's derive_id: md5('<kind>:<modular>:<key>')::uuid."""
    return UUID(bytes=hashlib.md5(f"{kind}:{MOD}:{key}".encode()).digest())


def H(*parts: object) -> int:
    """A stable hash in 0..9999 from any key."""
    return int(hashlib.md5(":".join(str(p) for p in parts).encode()).hexdigest()[:8], 16) % 10000


def q(value: object) -> str:
    """A SQL literal."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


# --------------------------------------------------------------------------- calendar --

TERMS = [
    (1, "Trimestre I", "T-I", dt.date(2026, 3, 2), dt.date(2026, 5, 29), "2026-06-05"),
    (2, "Trimestre II", "T-II", dt.date(2026, 6, 1), dt.date(2026, 8, 28), "2026-09-04"),
    (3, "Trimestre III", "T-III", dt.date(2026, 8, 31), dt.date(2026, 12, 18), "2026-12-23"),
]
NON_TEACHING = [
    {"fecha": "2026-04-02", "tipo": "feriado", "nombre": "Jueves Santo"},
    {"fecha": "2026-04-03", "tipo": "feriado", "nombre": "Viernes Santo"},
    {"fecha": "2026-05-01", "tipo": "feriado", "nombre": "Día del Trabajo"},
    {"fecha": "2026-06-29", "tipo": "feriado", "nombre": "San Pedro y San Pablo"},
    {"fecha": "2026-07-23", "tipo": "feriado", "nombre": "Día de la Fuerza Aérea del Perú"},
    {"desde": "2026-07-27", "hasta": "2026-08-07", "tipo": "vacaciones",
     "nombre": "Vacaciones de medio año"},
    {"fecha": "2026-08-30", "tipo": "feriado", "nombre": "Santa Rosa de Lima"},
    {"fecha": "2026-10-08", "tipo": "feriado", "nombre": "Combate de Angamos"},
    {"fecha": "2026-12-08", "tipo": "feriado", "nombre": "Inmaculada Concepción"},
]  # fmt: skip
# The two experience windows of each closed term: (start, end) inclusive.
WINDOWS = {
    1: [(dt.date(2026, 3, 9), dt.date(2026, 4, 10)), (dt.date(2026, 4, 20), dt.date(2026, 5, 22))],
    2: [(dt.date(2026, 6, 8), dt.date(2026, 7, 3)), (dt.date(2026, 7, 6), dt.date(2026, 7, 24))],
}
CLOSED_AT = {1: "2026-06-08 17:00:00-05", 2: "2026-09-07 17:00:00-05"}
ASSERTED_AT = {1: "2026-06-05 12:00:00-05", 2: "2026-09-04 12:00:00-05"}


def non_teaching_days() -> set[dt.date]:
    days: set[dt.date] = set()
    for d in NON_TEACHING:
        if "fecha" in d:
            days.add(dt.date.fromisoformat(d["fecha"]))
        else:
            cur, end = dt.date.fromisoformat(d["desde"]), dt.date.fromisoformat(d["hasta"])
            while cur <= end:
                days.add(cur)
                cur += dt.timedelta(days=1)
    return days


NO_CLASS = non_teaching_days()


def term_of(day: dt.date) -> int:
    for n, _, _, start, end, _ in TERMS:
        if start <= day <= end:
            return n
    raise ValueError(day)


# ----------------------------------------------------------------------- the school --


@dataclass
class Area:
    code: str
    name: str
    icon: str
    teacher: str
    blocks: list[int]  # lengths in pedagogical hours, one per weekly franja


AREAS = [
    Area("MAT", "Matemática", "calculadora", "jeffrey", [2, 2]),
    Area("COM", "Comunicación", "libro", "mhuaman", [2, 2]),
    Area("CYT", "Ciencia y Tecnología", "matraz", "rquispe", [2, 2]),
    Area("ING", "Inglés", "idioma", "kpalomino", [2, 1]),
    Area("CCSS", "Ciencias Sociales", "globo", "gonzalo", [2, 1]),
    Area("DPCC", "Desarrollo Personal, Ciudadanía y Cívica", "personas", "lcardenas", [2]),
    Area("EF", "Educación Física", "pelota", "jmendoza", [2]),
    Area("ARTE", "Arte y Cultura", "paleta", "aflores", [2]),
    Area("ER", "Educación Religiosa", "estrella", "rchavez", [2]),
    Area("EPT", "Educación para el Trabajo", "maletin", "dramos", [2]),
]
AREA = {a.code: a for a in AREAS}

TEACHERS = [
    # usuario, nombres, apellidos, email, clave
    ("jeffrey", "Jeffrey", "Orihuela", "amaruorihuela@gmail.com", "jeffrey2026"),
    ("gonzalo", "Gonzalo", "Saavedra", "gonzaloscb7@gmail.com", "gonzalo2026"),
    ("mhuaman", "Milagros", "Huamán Torres", "mhuaman@sanfelipe.test", "mhuaman2026"),
    ("rquispe", "Raúl", "Quispe Mamani", "rquispe@sanfelipe.test", "rquispe2026"),
    ("kpalomino", "Karen", "Palomino Ríos", "kpalomino@sanfelipe.test", "kpalomino2026"),
    ("lcardenas", "Lucía", "Cárdenas Vega", "lcardenas@sanfelipe.test", "lcardenas2026"),
    ("jmendoza", "Jorge", "Mendoza Paredes", "jmendoza@sanfelipe.test", "jmendoza2026"),
    ("aflores", "Andrea", "Flores Salazar", "aflores@sanfelipe.test", "aflores2026"),
    ("rchavez", "Rosa", "Chávez Lozano", "rchavez@sanfelipe.test", "rchavez2026"),
    ("dramos", "Diego", "Ramos Cueva", "dramos@sanfelipe.test", "dramos2026"),
]
TUTORS = {"A": "gonzalo", "B": "rquispe"}
SECTIONS = ["A", "B"]

# The timetable grid: three two-hour blocks a day and one single hour after them.
DOUBLE_SLOTS = [("08:00", "09:30"), ("09:45", "11:15"), ("11:30", "13:00")]
SINGLE_SLOT = ("13:00", "13:45")
WEEKDAYS = ["lunes", "martes", "miercoles", "jueves", "viernes"]


def timetable() -> dict[tuple[str, str], list[tuple[int, str, str]]]:
    """(area, section) -> [(isoweekday, start, end)], with no clash inside a section, no clash
    for a teacher across sections, and an área's blocks on different days. A small backtracking
    search over a fixed order, so the result never changes."""
    tasks: list[tuple[str, str, int, int]] = []  # (section, area, block index, hours)
    for s in SECTIONS:
        for a in AREAS:
            for i, hours in enumerate(a.blocks):
                tasks.append((s, a.code, i, hours))
    tasks.sort(key=lambda t: (-t[3], t[1], t[0], t[2]))
    section_busy: set[tuple[str, int, str]] = set()
    teacher_busy: set[tuple[str, int, str]] = set()
    area_days: dict[tuple[str, str], set[int]] = {}
    result: dict[tuple[str, str], list[tuple[int, str, str]]] = {}

    def slots(hours: int, seed: str) -> list[tuple[int, str, str]]:
        options = [
            (d, s, e)
            for d in range(1, 6)
            for s, e in (DOUBLE_SLOTS if hours == 2 else [SINGLE_SLOT])
        ]
        return sorted(options, key=lambda o: H(seed, *o))

    def place(k: int) -> bool:
        if k == len(tasks):
            return True
        s, code, i, hours = tasks[k]
        teacher = AREA[code].teacher
        for day, start, end in slots(hours, f"{s}{code}{i}"):
            if (s, day, start) in section_busy or (teacher, day, start) in teacher_busy:
                continue
            if day in area_days.get((s, code), set()):
                continue
            section_busy.add((s, day, start))
            teacher_busy.add((teacher, day, start))
            area_days.setdefault((s, code), set()).add(day)
            result.setdefault((code, s), []).append((day, start, end))
            if place(k + 1):
                return True
            section_busy.discard((s, day, start))
            teacher_busy.discard((teacher, day, start))
            area_days[(s, code)].discard(day)
            result[(code, s)].pop()
        return False

    if not place(0):
        raise RuntimeError("no timetable fits")
    return result


TIMETABLE = timetable()


def class_code(area: str, section: str) -> str:
    return f"{area}-1{section}"


def class_dates(area: str, section: str, start: dt.date, end: dt.date) -> list[dt.date]:
    """Teaching days of a class between two dates: one per date, however many blocks meet."""
    days = {d for d, _, _ in TIMETABLE[(area, section)]}
    out: list[dt.date] = []
    cur = start
    while cur <= end:
        if cur.isoweekday() in days and cur not in NO_CLASS:
            out.append(cur)
        cur += dt.timedelta(days=1)
    return out


# ------------------------------------------------------------------------- students --


class Extra(TypedDict, total=False):
    areas: list[str]  # the áreas in C (dificultad, riesgo)
    inclusion: bool  # inclusion_support
    joined: str  # enrolment date, when after the first day


# Profiles: superdotado, media, dificultad (C in two áreas), rezagado, riesgo (C in five áreas).
# (given, paternal, maternal, sex, profile, extra)
ROSTER: dict[str, list[tuple[str, str, str, str, str, Extra]]] = {
    "A": [
        ("Valeria", "Rojas", "Huamán", "F", "superdotado", {}),
        ("Mateo", "Gutiérrez", "Salas", "M", "superdotado", {}),
        ("Camila", "Torres", "Quispe", "F", "media", {}),
        ("Sebastián", "Flores", "Medina", "M", "media", {}),
        ("Luciana", "Mendoza", "Paredes", "F", "media", {}),
        ("Diego", "Castillo", "Ramos", "M", "media", {}),
        ("Ximena", "Vargas", "León", "F", "media", {}),
        ("Thiago", "Chávez", "Rivera", "M", "media", {}),
        ("Fernanda", "Silva", "Cárdenas", "F", "media", {}),
        ("Adrián", "Morales", "Ortiz", "M", "media", {}),
        ("Renata", "Espinoza", "Vega", "F", "media", {}),
        ("Joaquín", "Díaz", "Campos", "M", "media", {}),
        ("Isabella", "Herrera", "Núñez", "F", "media", {}),
        ("Gael", "Ríos", "Palomino", "M", "media", {}),
        ("Antonella", "Cruz", "Benites", "F", "media", {}),
        ("Leonardo", "Aguilar", "Soto", "M", "media", {}),
        ("Mía", "Sánchez", "Loayza", "F", "media", {}),
        ("Santiago", "Ramírez", "Poma", "M", "media", {}),
        ("Daniela", "Peña", "Arias", "F", "dificultad", {"areas": ["MAT", "CYT"]}),
        ("Bruno", "Salazar", "Ccori", "M", "dificultad", {"areas": ["COM", "ING"]}),
        ("Kiara", "Navarro", "Inga", "F", "dificultad", {"areas": ["CCSS", "DPCC"]}),
        ("Emilio", "Cabrera", "Tito", "M", "dificultad", {"areas": ["ING", "EPT"]}),
        ("Abigail", "Paredes", "Choque", "F", "rezagado", {"inclusion": True}),
        ("Rodrigo", "Ortega", "Mamani", "M", "rezagado", {}),
        ("Nicole", "Vásquez", "Yupanqui", "F", "rezagado", {}),
        ("Gabriel", "Fernández", "Huanca", "M", "rezagado", {}),
        ("Brenda", "Quispe", "Condori", "F", "riesgo",
         {"areas": ["MAT", "COM", "CYT", "ING", "CCSS"]}),
        ("Kevin", "Huamaní", "Flores", "M", "riesgo",
         {"areas": ["MAT", "COM", "ING", "DPCC", "EPT"]}),
    ],
    "B": [
        ("Ariana", "Lozano", "Bravo", "F", "superdotado", {}),
        ("Matías", "Romero", "Valdez", "M", "superdotado", {}),
        ("Sofía", "Guerrero", "Sánchez", "F", "media", {"inclusion": True}),
        ("Alonso", "Pacheco", "Tello", "M", "media", {}),
        ("Valentina", "Medina", "Chávez", "F", "media", {}),
        ("Lucas", "Zapata", "Rojas", "M", "media", {}),
        ("Micaela", "Cáceres", "Luna", "F", "media", {}),
        ("Benjamín", "Delgado", "Ruiz", "M", "media", {}),
        ("Alessandra", "Málaga", "Pinto", "F", "media", {}),
        ("Franco", "Vera", "Gallegos", "M", "media", {}),
        ("Zoe", "Ibáñez", "Carrasco", "F", "media", {}),
        ("Dylan", "Montes", "Aguirre", "M", "media", {}),
        ("Catalina", "Rivas", "Mejía", "F", "media", {}),
        ("Ian", "Solís", "Calderón", "M", "media", {}),
        ("Josefina", "Bustamante", "Ponce", "F", "media", {}),
        ("Facundo", "Arce", "Villanueva", "M", "media", {}),
        ("Romina", "Tapia", "Salinas", "F", "media", {}),
        ("Tomás", "Rosales", "Ugarte", "M", "media", {"joined": "2026-06-01"}),
        ("Paula", "Galindo", "Ascencio", "F", "dificultad", {"areas": ["MAT", "CCSS"]}),
        ("Iker", "Montoya", "Huerta", "M", "dificultad", {"areas": ["COM", "CYT"]}),
        ("Milagros", "Cornejo", "Apaza", "F", "dificultad", {"areas": ["ING", "ARTE"]}),
        ("Jhon", "Lazo", "Ticona", "M", "dificultad", {"areas": ["MAT", "ING"]}),
        ("Yesenia", "Cahuana", "Llanos", "F", "rezagado", {}),
        ("Piero", "Saldaña", "Quiroz", "M", "rezagado", {}),
        ("Rosa", "Huillca", "Puma", "F", "rezagado", {}),
        ("Erick", "Mallma", "Laura", "M", "rezagado", {}),
        ("Lizbeth", "Ccahuana", "Rojas", "F", "riesgo",
         {"areas": ["MAT", "CYT", "CCSS", "COM", "ER"]}),
        ("Brayan", "Yauri", "Cutipa", "M", "riesgo",
         {"areas": ["COM", "ING", "MAT", "CYT", "DPCC"]}),
    ],
}  # fmt: skip


@dataclass
class Student:
    code: str
    section: str
    given: str
    paternal: str
    maternal: str
    sex: str
    profile: str
    weak_areas: list[str] = field(default_factory=list)
    inclusion: bool = False
    joined: dt.date = dt.date(2026, 3, 2)
    birthdate: str = ""
    siagie: str = ""
    dni: str = ""

    @property
    def id(self) -> UUID:
        return ID("student", self.code)

    @property
    def full(self) -> str:
        return f"{self.given} {self.paternal} {self.maternal}"


def students() -> list[Student]:
    out: list[Student] = []
    for s in SECTIONS:
        for i, (given, pat, mat, sex, profile, extra) in enumerate(ROSTER[s], start=1):
            code = f"SF26-1{s}{i:02d}"
            st = Student(code, s, given, pat, mat, sex, profile,
                         weak_areas=extra.get("areas", []),
                         inclusion=extra.get("inclusion", False))  # fmt: skip
            if "joined" in extra:
                st.joined = dt.date.fromisoformat(extra["joined"])
            born = dt.date(2013, 4, 1) + dt.timedelta(days=H(code, "born") % 365)
            st.birthdate = born.isoformat()
            st.siagie = f"{15000000000000 + H(code, 'siagie') * 1000 + i:014d}"
            st.dni = f"{78000000 + H(code, 'dni') * 100 + i:08d}"
            out.append(st)
    names = [st.given for st in out]
    if len(names) != len(set(names)):
        raise RuntimeError("given names must be unique: the voice-note redaction relies on it")
    return out


STUDENTS = students()


# ------------------------------------------------------------------------ catalog --


def load_catalog() -> tuple[dict[str, Json], dict[str, list[str]]]:
    """competency code -> catalog competency, and area -> its competency codes."""
    areas = json.loads((CATALOG / "areas.json").read_text())["areas"]
    comps: dict[str, Json] = {}
    by_area: dict[str, list[str]] = {}
    for a in areas:
        if a["codigo"] not in AREA:
            continue
        by_area[a["codigo"]] = []
        for c in a["competencias"]:
            comps[c["codigo"]] = json.loads(
                (CATALOG / "competencias" / f"c{c['numero_cneb']:02d}.json").read_text()
            )
            by_area[a["codigo"]].append(c["codigo"])
    return comps, by_area


COMPS, COMPS_BY_AREA = load_catalog()


# ---------------------------------------------------------------------- planning --


@dataclass
class Criterion:
    id: UUID
    competency: str
    capabilities: list[int]
    text: str
    performance: int | None
    mawta: bool


@dataclass
class Evidence:
    id: UUID
    name: str
    kind: str
    scale: str
    criteria: list[Criterion]
    entry_id: UUID | None = None
    date: dt.date | None = None

    @property
    def competencies(self) -> list[str]:
        return sorted({c.competency for c in self.criteria})


@dataclass
class Entry:
    id: UUID
    date: dt.date
    title: str
    topics: str
    evidence: Evidence | None = None


@dataclass
class Experience:
    id: UUID
    key: str
    area: str
    section: str
    term: int
    title: str
    idea: str
    situation: str
    context: str
    competencies: list[str]
    starts: dt.date
    ends: dt.date
    criteria: list[Criterion]
    evidences: list[Evidence]
    entries: list[Entry]


def spread(phases: list[list[str]], n: int) -> list[tuple[str, str]]:
    """Lay the content's session phases over n class dates: fewer dates keep an even subset
    (always the first and last phase), more dates repeat phases as a continuation."""
    m = len(phases)
    if n <= m:
        idx = [round(i * (m - 1) / (n - 1)) if n > 1 else m - 1 for i in range(n)]
        return [(phases[i][0], phases[i][1]) for i in idx]
    out: list[tuple[str, str]] = []
    for i in range(n):
        j = i * m // n
        title, topics = phases[j]
        if out and out[-1][0].startswith(title):
            out.append((f"{title} (continuación)", topics))
        else:
            out.append((title, topics))
    return out


def experiences() -> list[Experience]:
    out: list[Experience] = []
    for area in AREAS:
        content: Json = json.loads((CONTENT / f"{area.code}.json").read_text())
        per_term: dict[int, int] = {}
        for exp in content["experiencias"]:
            term = exp["trimestre"]
            per_term[term] = per_term.get(term, 0) + 1
            n = per_term[term]
            w_start, w_end = WINDOWS[term][n - 1]
            for s in SECTIONS:
                key = f"{class_code(area.code, s)}:T{term}E{n}"
                dates = class_dates(area.code, s, w_start, w_end)
                crits: list[Criterion] = []
                for k, c in enumerate(exp["criterios"]):
                    if c["competencia"] not in exp["competencias"]:
                        raise RuntimeError(f"{key}: criterion {k} outside the experience")
                    cat = COMPS[c["competencia"]]
                    numbers = {cap["numero"] for cap in cat["capacidades"]}
                    if not set(c["capacidades"]) <= numbers:
                        raise RuntimeError(f"{key}: criterion {k} names a missing capability")
                    perf = c.get("desempeno")
                    if perf is not None and not any(
                        d["grado"] == "1S" and d["orden"] == perf for d in cat["desempenos"]
                    ):
                        raise RuntimeError(f"{key}: criterion {k} names a missing desempeño")
                    crits.append(Criterion(ID("seed-criterion", f"{key}:{k}"), c["competencia"],
                                           c["capacidades"], c["texto"], perf,
                                           c.get("mawta", False)))  # fmt: skip
                for comp in exp["competencias"]:
                    if not any(c.competency == comp for c in crits):
                        raise RuntimeError(f"{key}: {comp} has no criterion")
                evs = [
                    Evidence(ID("seed-evidence", f"{key}:{k}"), e["nombre"], e["tipo"],
                             e["escala"], [crits[i] for i in e["criterios"]])
                    for k, e in enumerate(exp["evidencias"])
                ]  # fmt: skip
                if {c.id for c in crits} - {c.id for e in evs for c in e.criteria}:
                    raise RuntimeError(f"{key}: a criterion has no evidence")
                if len(dates) < len(evs):
                    raise RuntimeError(f"{key}: {len(dates)} class dates for {len(evs)} evidences")
                entries = [
                    Entry(ID("seed-entry", f"{key}:{d.isoformat()}"), d, t, topics)
                    for d, (t, topics) in zip(
                        dates, spread(exp["sesiones"], len(dates)), strict=True
                    )
                ]
                # Evidence is collected towards the end of its process: the last one on the last
                # date, the earlier ones spread before it, never two on one date.
                m = len(evs)
                positions: list[int] = []
                for k in range(m):
                    pos = round(len(dates) * (k + 1) / m) - 1
                    while pos in positions:
                        pos -= 1
                    positions.append(pos)
                for ev, pos in zip(evs, positions, strict=True):
                    entries[pos].evidence = ev
                    ev.entry_id, ev.date = entries[pos].id, entries[pos].date
                out.append(Experience(
                    ID("seed-experience", key), key, area.code, s, term, exp["titulo"],
                    exp["idea"], exp["situacion"], exp["contexto"], exp["competencias"],
                    dates[0], dates[-1], crits, evs, entries,
                ))  # fmt: skip
    return out


EXPERIENCES = experiences()

# competency -> terms in which some experience works it (same for both sections)
WORKED: dict[str, set[int]] = {}
for _e in EXPERIENCES:
    for _c in _e.competencies:
        WORKED.setdefault(_c, set()).add(_e.term)


# ------------------------------------------------------------------------ levels --


def target(st: Student, comp: str, term: int) -> int:
    """The level (1=C .. 4=AD) the teacher asserts for a student, competency and term. Profiles
    are fixed here first; every mark is then generated to sit in this level's band."""
    area = comp.split("-")[0]
    h = H(st.code, comp, term)
    if st.profile == "superdotado":
        return 4 if h % 100 < 75 else 3
    if st.profile == "riesgo":
        if area in st.weak_areas:
            return 1
        return 1 if h % 100 < 35 else 2
    if st.profile == "dificultad":
        if area in st.weak_areas:
            return 1
        return 3 if h % 100 < 45 else 2
    if st.profile == "rezagado":
        mine = sorted(c for c in COMPS if len(WORKED.get(c, ())) == 2)
        improving = mine[H(st.code, "up") % len(mine)]
        declining = mine[H(st.code, "down") % len(mine)]
        if declining == improving:
            declining = mine[(mine.index(improving) + 1) % len(mine)]
        if comp == improving:
            return 1 if term == 1 else 2
        if comp == declining:
            return 2 if term == 1 else 1
        return 3 if h % 100 < 20 else 2
    # media; 1S-B is a little weaker in MAT and CYT, so the director can compare sections
    a_share = 30 if st.section == "B" and area in ("MAT", "CYT") else 55
    if h % 100 < 4:
        return 4
    return 3 if h % 100 < a_share else 2


def enrolled(st: Student, term: int) -> bool:
    return st.joined <= TERMS[term - 1][4]


def started_term(st: Student, term: int) -> bool:
    """A student who joined after the term began has no evidence of it at all."""
    return st.joined <= TERMS[term - 1][3]


LEVEL_ROWS: list[tuple[Student, str, int, int]] = []  # (student, competency, term, level)
for _st in STUDENTS:
    for _comp in sorted(COMPS):
        for _term in (1, 2):
            if _term in WORKED.get(_comp, set()) and started_term(_st, _term):
                LEVEL_ROWS.append((_st, _comp, _term, target(_st, _comp, _term)))
LEVEL = {(st.code, c, t): lv for st, c, t, lv in LEVEL_ROWS}


def section_students(section: str) -> list[Student]:
    return [st for st in STUDENTS if st.section == section]


# ------------------------------------------------------------------------ scores --

BANDS = {1: (6, 10), 2: (11, 13), 3: (14, 16), 4: (17, 20)}
MISSING = {"riesgo": 11, "rezagado": 4, "dificultad": 3, "media": 1, "superdotado": 0}  # percent


def evidence_level(st: Student, ev: Evidence, term: int) -> int:
    """What one piece of evidence shows: the student's level on its competencies, with an
    occasional one-step wobble so a record is not a flat line."""
    levels = [LEVEL[(st.code, c, term)] for c in ev.competencies]
    base = sum(levels) / len(levels)
    lv = int(base + 0.5) if H(st.code, ev.id, "round") % 2 else int(base)
    wobble = H(st.code, ev.id, "wobble") % 100
    if wobble < 8:
        lv += 1
    elif wobble < 16:
        lv -= 1
    # a designed C stays a C: the evidence must sustain it
    if all(x == 1 for x in levels):
        lv = 1
    return max(1, min(4, lv))


# -------------------------------------------------------------------- conclusions --

SHORT = {
    "MAT-C1": "la resolución de problemas de cantidad",
    "MAT-C2": "los problemas de regularidad y cambio",
    "MAT-C3": "los problemas de forma y localización",
    "COM-C1": "la comunicación oral",
    "COM-C2": "la lectura de textos",
    "COM-C3": "la escritura de textos",
    "ING-C1": "la comunicación oral en inglés",
    "ING-C2": "la lectura en inglés",
    "CYT-C1": "la indagación científica",
    "CYT-C2": "la explicación del mundo físico",
    "CCSS-C1": "la interpretación histórica",
    "CCSS-C2": "la gestión del espacio y el ambiente",
    "DPCC-C1": "la construcción de su identidad",
    "DPCC-C2": "la convivencia y participación",
    "EF-C1": "su desenvolvimiento motriz",
    "EF-C2": "los hábitos de vida saludable",
    "EF-C3": "el juego en equipo",
    "ARTE-C1": "la apreciación artística",
    "ARTE-C2": "la creación de proyectos artísticos",
    "ER-C1": "la comprensión de su fe",
    "ER-C2": "la vivencia de su fe en comunidad",
    "EPT-C1": "la gestión de su proyecto de emprendimiento",
}

CONCLUSION_TEXT = {
    "consecutive_c": [
        "{n} sigue en inicio en {c} por segundo periodo. Reconoce lo que se le pide, pero no "
        "sostiene el proceso sin guía y el refuerzo en grupo no bastó. Se recomienda "
        "acompañamiento individual semanal y coordinar con la familia un horario de estudio.",
        "{n} no muestra avance en {c} respecto al periodo anterior: entrega incompleto y se "
        "detiene ante la primera dificultad. Las estrategias en pares no funcionaron. Se "
        "recomienda tutoría personalizada y tareas graduadas con revisión frecuente.",
    ],
    "inclusion_support": [
        "{n} alcanza el nivel {lv} en {c} con tiempo adicional y consignas divididas en pasos. "
        "Aún necesita apoyo en tareas de varios pasos. Se recomienda mantener los ajustes y "
        "sumar organizadores visuales.",
        "{n} logra el nivel {lv} en {c} cuando trabaja con material concreto y un compañero de "
        "apoyo. Le cuesta organizar el tiempo. Se recomienda mantener los ajustes y anticipar "
        "las actividades con una agenda visual.",
    ],
    "level_c": [
        "{n} participa y entrega sus trabajos, pero en {c} todavía requiere acompañamiento para "
        "completar el proceso sin ayuda. Se recomienda retomar sus tareas señalando dónde se "
        "interrumpe y practicar con situaciones más sencillas.",
        "{n} muestra interés, aunque en {c} aún no aplica lo trabajado en situaciones nuevas. "
        "Se recomienda revisar con la docente los errores frecuentes y practicar en casa con "
        "ejercicios guiados.",
    ],
    "optional": [
        "{n} se desempeña con autonomía en {c} y fundamenta sus decisiones con evidencia. Ayuda "
        "a sus compañeros a comprender. Se recomienda proponerle retos de mayor complejidad.",
        "{n} destaca en {c}: propone soluciones propias y explica su razonamiento con claridad. "
        "Se recomienda ofrecerle proyectos de profundización y roles de liderazgo.",
    ],
}

PRECEDENCE = ["consecutive_c", "inclusion_support", "level_c", "optional"]


def requirement(st: Student, comp: str, term: int, lv: int) -> str | None:
    prev = LEVEL.get((st.code, comp, term - 1))
    if lv == 1 and prev == 1:
        return "consecutive_c"
    if st.inclusion:
        return "inclusion_support"
    if lv == 1:
        return "level_c"
    if lv == 4 and H(st.code, comp, term, "opt") % 100 < 40:
        return "optional"
    return None


def conclusion_body(st: Student, comp: str, term: int, lv: int, req: str) -> str:
    options = CONCLUSION_TEXT[req]
    text = options[H(st.code, comp, term, "dc") % len(options)]
    body = text.format(n=st.given, c=SHORT[comp], lv=LEVELS[lv - 1])
    if not 10 <= len(body) <= 350 or "\n" in body:
        raise RuntimeError(f"conclusion out of SIAGIE bounds ({len(body)}): {body}")
    return body


# --------------------------------------------------------------------- voice notes --

ACTIVITY = {
    "MAT": ["resolver la práctica", "explicar su procedimiento en la pizarra", "trabajar la ficha en parejas"],
    "COM": ["leer en voz alta", "escribir el borrador", "participar en el debate"],
    "CYT": ["registrar los datos del experimento", "trabajar en el laboratorio", "explicar su hipótesis"],
    "ING": ["practicar el diálogo", "leer el texto en inglés", "presentarse en inglés"],
    "CCSS": ["analizar la fuente", "trabajar con el mapa", "explicar el proceso histórico"],
    "DPCC": ["participar en el círculo de diálogo", "analizar el caso", "proponer acuerdos"],
    "EF": ["hacer el circuito", "jugar en equipo", "ensayar la secuencia"],
    "ARTE": ["trabajar en su proyecto", "presentar su boceto", "ensayar con su grupo"],
    "ER": ["compartir su reflexión", "leer el texto bíblico", "participar en la oración"],
    "EPT": ["trabajar en su prototipo", "calcular los costos", "coordinar con su equipo"],
}  # fmt: skip

NOTE_TEXT = {
    1: [
        "{n} hoy no terminó la actividad al {a}. Se quedó mirando el cuaderno y cuando me acerqué me dijo que no entendía desde el inicio. Le expliqué de nuevo, avanzó un poco pero se volvió a detener.",
        "Otra vez {n} no trajo la tarea. Al {a} se distrajo conversando y tuve que llamarle la atención dos veces. Hay que hablar con la familia.",
        "{n} intentó {a} pero se frustró rápido y dejó la hoja en blanco. Me dijo que siempre le va mal en este curso. Necesita mucho acompañamiento.",
        "Al {a}, {n} copió lo que hizo {c} sin entenderlo. Cuando le pregunté cómo lo hizo no supo explicarlo.",
        "{n} llegó tarde y no se integró a su grupo. Al {a} se mantuvo callado y no aportó. Le noto desmotivado esta semana.",
    ],
    2: [
        "{n} al {a} avanzó con ayuda. Entiende la idea general pero se equivoca en los detalles. Si le doy un ejemplo lo resuelve.",
        "{n} trabajó bien con {c} al {a}, aunque dependió bastante de lo que proponía {c}. Tiene que animarse a hacerlo solo.",
        "Hoy {n} participó más que otras veces. Al {a} cometió algunos errores pero los corrigió cuando se los señalé.",
        "{n} entregó incompleto, le faltó la parte final. Al {a} mostró que sí entiende, pero se demora mucho.",
    ],
    3: [
        "{n} al {a} lo hizo bien y sin ayuda. Explicó su respuesta con claridad.",
        "Buen trabajo de {n} hoy. Al {a} se organizó con {c} y terminaron a tiempo.",
        "{n} cumplió con todo lo pedido. Al {a} hizo una pregunta interesante que ayudó a la clase.",
    ],
    4: [
        "{n} terminó antes que todos al {a} y luego ayudó a {c} a entender el procedimiento. Explica con mucha claridad.",
        "Excelente participación de {n}. Al {a} propuso una forma distinta de resolverlo que no habíamos visto en clase.",
        "{n} al {a} fue más allá de lo pedido: investigó por su cuenta y trajo información extra. Hay que darle retos más complejos.",
    ],
}

# Notes that name only a classmate: the redaction agent must discard them as
# mentions_other_student. Pending in T-III.
CLASSMATE_ONLY = [
    "{c} hoy estuvo muy inquieto, se paró varias veces y distrajo a su grupo al {a}.",
    "Al {a}, {c} ayudó mucho a su grupo y explicó el procedimiento a los demás.",
]


@dataclass
class Note:
    id: UUID
    student: Student
    area: str
    day: dt.date
    transcript: str
    redacted: str | None
    status: str  # attribution_status
    duration_ms: int


def notes() -> list[Note]:
    out: list[Note] = []
    by_section = {s: section_students(s) for s in SECTIONS}
    for area in AREAS:
        for s in SECTIONS:
            roster = by_section[s]
            for term in (1, 2, 3):
                _, _, _, t_start, t_end, _ = TERMS[term - 1]
                dates = [d for d in class_dates(area.code, s, t_start, min(t_end, NOTES_UNTIL))]
                if not dates:
                    continue
                for st in roster:
                    if st.joined > dates[-1]:
                        continue
                    lv_term = term if term < 3 else 2
                    comps = [c for c in COMPS_BY_AREA[area.code] if (st.code, c, lv_term) in LEVEL]
                    if not comps:
                        tone = 2
                    else:
                        tone = round(sum(LEVEL[(st.code, c, lv_term)] for c in comps) / len(comps))
                    h = H(st.code, area.code, term, "notes")
                    if st.profile == "riesgo":
                        count = 2 + h % 2 if area.code in st.weak_areas else 1
                    elif st.profile == "dificultad":
                        count = 2 + h % 2 if area.code in st.weak_areas else h % 2
                    elif st.profile == "superdotado":
                        count = 1 + (h % 3 == 0)
                    elif st.profile == "rezagado":
                        count = 1 + h % 2
                    else:
                        count = 1 if h % 100 < 15 else 0
                    eligible = [d for d in dates if d >= st.joined]
                    chosen = sorted(eligible, key=lambda d: H(st.code, area.code, d))[:count]
                    templates = NOTE_TEXT[tone]
                    first = H(st.code, area.code, term, "tpl")
                    for i, day in enumerate(sorted(chosen)):
                        mates = [m for m in roster if m.code != st.code and m.joined <= day]
                        mate = mates[H(st.code, day, "mate") % len(mates)]
                        # consecutive templates, so one student's notes in a term never repeat
                        text = templates[(first + i) % len(templates)]
                        acts = ACTIVITY[area.code]
                        act = acts[H(st.code, day, "act") % len(acts)]
                        transcript = text.format(n=st.given, c=mate.given, a=act)
                        redacted = text.format(n="[ESTUDIANTE]", c="[COMPAÑERO_1]", a=act)
                        if term < 3:
                            redacted_value, status = redacted, "ok"
                        else:
                            redacted_value, status = None, "pending"
                        words = len(transcript.split())
                        out.append(Note(ID("seed-note", f"{st.code}:{area.code}:{day}"), st,
                                        area.code, day, transcript, redacted_value, status,
                                        words * 420 + H(st.code, day, "ms") % 1500))  # fmt: skip
        # a few T-III notes that name only a classmate, for the discard path
    for k, st in enumerate([st for st in STUDENTS if st.profile == "media"][:6]):
        code = AREAS[k % len(AREAS)].code
        days = class_dates(code, st.section, dt.date(2026, 9, 14), NOTES_UNTIL)
        day = days[H(st.code, "mate-only") % len(days)]
        mates = [m for m in section_students(st.section) if m.code != st.code]
        mate = mates[H(st.code, "mate-only-who") % len(mates)]
        acts = ACTIVITY[code]
        text = CLASSMATE_ONLY[k % len(CLASSMATE_ONLY)].format(c=mate.given, a=acts[k % len(acts)])
        out.append(Note(ID("seed-note", f"{st.code}:{code}:{day}:mate"), st, code, day, text,
                        None, "pending", len(text.split()) * 420))  # fmt: skip
    return out


NOTES = notes()


# ------------------------------------------------------------------ onboarding JSON --


def onboarding() -> Json:
    return {
        "colegio": {
            "nombre": "I.E. San Felipe",
            "razon_social": "",
            "codigo_modular": MOD,
            "tipo": "publica",
            "ciudad": "Miraflores",
            "region": "Lima",
            "zona_horaria": "America/Lima",
        },
        "anio_escolar": {
            "anio": YEAR,
            "nombre": f"Año escolar {YEAR}",
            "inicio": "2026-03-02",
            "fin": "2026-12-18",
            "estructura": "trimestre",
            "periodos": [
                {
                    "numero": n,
                    "nombre": name,
                    "abreviatura": short,
                    "inicio": start.isoformat(),
                    "fin": end.isoformat(),
                    "fecha_entrega_notas": due,
                }
                for n, name, short, start, end, due in TERMS
            ],  # fmt: skip
            "dias_no_lectivos": NON_TEACHING,
        },
        "docentes": [
            {
                "usuario": u,
                "clave": pw,
                "email": email,
                "nombres": given,
                "apellidos": family,
                "nombre_visible": f"{given} {family.split()[0]}",
                "cargo": "Docente de Secundaria",
                "codigo_empleado": "",
                "fecha_ingreso": "",
            }
            for u, given, family, email, pw in TEACHERS
        ],  # fmt: skip
        "areas": [
            {
                "codigo": a.code,
                "nombre": a.name,
                "icono": a.icon,
                "es_tutoria": False,
                "criterios_legacy": [],
            }
            for a in AREAS
        ],  # fmt: skip
        "competencias_transversales": ["TR-C1", "TR-C2"],
        "grados": [
            {
                "codigo": "1S",
                "etiqueta": "1ro",
                "nombre_largo": "Primero de Secundaria",
                "nivel": "secundaria",
                "orden": 7,
                "grado_cneb": "1S",
            }
        ],  # fmt: skip
        "aulas": [
            {
                "grado": "1S",
                "seccion": s,
                "nombre": f"1ro {s}",
                "tutor": TUTORS[s],
                "turno": "manana",
                "capacidad": 30,
                "estudiantes": [
                    {
                        "codigo": st.code,
                        "codigo_siagie": st.siagie,
                        "nombres": st.given,
                        "apellido_paterno": st.paternal,
                        "apellido_materno": st.maternal,
                        "nombre_preferido": "",
                        "fecha_nacimiento": st.birthdate,
                        "sexo": st.sex,
                        "tipo_documento": "DNI",
                        "numero_documento": st.dni,
                        "fecha_matricula": st.joined.isoformat(),
                        "apoyo_inclusion": st.inclusion,
                    }
                    for st in section_students(s)
                ],
            }
            for s in SECTIONS
        ],  # fmt: skip
        "clases": [
            {
                "nombre": f"{a.name} 1ro {s}",
                "codigo": class_code(a.code, s),
                "area": a.code,
                "aula": f"1S-{s}",
                "docente": a.teacher,
                "horas_semanales": float(sum(a.blocks)),
                "salon": f"Aula 1{s}" if a.code != "EF" else "Losa deportiva",
                "horario": [
                    {"dia": WEEKDAYS[d - 1], "inicio": start, "fin": end, "salon": ""}
                    for d, start, end in sorted(TIMETABLE[(a.code, s)])
                ],
                "sesiones": [],
            }
            for s in SECTIONS
            for a in AREAS
        ],  # fmt: skip
    }


# ------------------------------------------------------------------------- SQL --

TENANT = ID("tenant", "")
YEAR_ID = ID("year", str(YEAR))


def term_id(n: int) -> UUID:
    return ID("term", f"{YEAR}:{n}")


def class_id(area: str, section: str) -> UUID:
    return ID("class", f"{YEAR}:{class_code(area, section)}")


def teacher_id(user: str) -> UUID:
    return ID("teacher", user)


def scale_level(lv: int) -> UUID:
    return ID("scale_level", f"{SCALE}:{LEVELS[lv - 1]}")


def values(rows: list[Row]) -> str:
    return ",\n".join("  (" + ", ".join(q(v) for v in r) + ")" for r in rows)


def insert(table: str, cols: list[str], rows: list[Row], chunk: int = 500) -> str:
    out: list[str] = []
    for i in range(0, len(rows), chunk):
        out.append(
            f"insert into {table} ({', '.join(cols)}) values\n{values(rows[i : i + chunk])};"
        )
    return "\n".join(out)


def ts(day: dt.date, clock: str = "08:00") -> str:
    return f"{day.isoformat()} {clock}:00-05"


def build_sql() -> tuple[str, dict[str, int]]:
    stats: dict[str, int] = {}
    parts: list[str] = []
    w = parts.append

    w(SQL_HEADER)

    # §1 experiences -----------------------------------------------------------------
    exp_rows: list[Row] = []
    comp_rows: list[Row] = []
    crit_rows: list[Row] = []
    cap_rows: list[Row] = []
    ev_rows: list[Row] = []
    evc_rows: list[Row] = []
    entry_rows: list[Row] = []
    for e in EXPERIENCES:
        cid = class_id(e.area, e.section)
        accepted = ts(e.starts - dt.timedelta(days=7), "18:00")
        exp_rows.append((e.id, TENANT, cid, YEAR_ID, term_id(e.term), e.title, e.idea,
                         e.situation, e.context or None, e.starts.isoformat(),
                         e.ends.isoformat(), "planificada"))  # fmt: skip
        for comp in e.competencies:
            comp_rows.append((ID("seed-exp-comp", f"{e.key}:{comp}"), TENANT, e.id,
                              ID("competency", comp)))  # fmt: skip
        for k, c in enumerate(e.criteria, start=1):
            perf = (
                ID("performance", f"{c.competency}:1S:{c.performance}") if c.performance else None
            )
            crit_rows.append((c.id, TENANT, ID("competency", c.competency), c.text, k, e.id, perf,
                              "mawta" if c.mawta else "teacher", accepted))  # fmt: skip
            for n in c.capabilities:
                cap_rows.append((ID("seed-crit-cap", f"{c.id}:{n}"), TENANT, c.id,
                                 ID("competency", c.competency),
                                 ID("capability", f"{c.competency}-CAP{n}")))  # fmt: skip
        for ev in e.evidences:
            ev_rows.append((ev.id, TENANT, e.id, ev.name, ev.kind, ev.scale,
                            20 if ev.scale == "numeric" else None, "teacher", accepted))  # fmt: skip
            for c in ev.criteria:
                evc_rows.append((ID("seed-ev-crit", f"{ev.id}:{c.id}"), TENANT, ev.id, c.id))
        for en in e.entries:
            entry_rows.append((en.id, TENANT, e.id, en.date.isoformat(), en.title, en.topics,
                               en.evidence.id if en.evidence else None, "teacher", accepted))  # fmt: skip
    w(SECTION_PLAN)
    w(insert("learning_experiences",
             ["id", "tenant_id", "class_id", "academic_year_id", "term_id", "title", "idea_text",
              "situation_text", "context_text", "starts_on", "ends_on", "status"], exp_rows))  # fmt: skip
    w(insert("experience_competencies", ["id", "tenant_id", "experience_id", "competency_id"],
             comp_rows))  # fmt: skip
    w(insert("evaluation_criteria",
             ["id", "tenant_id", "competency_id", "description", "sort_order", "experience_id",
              "performance_id", "proposed_by", "accepted_at"], crit_rows))  # fmt: skip
    w(insert("evaluation_criterion_capabilities",
             ["id", "tenant_id", "criterion_id", "competency_id", "capability_id"], cap_rows))  # fmt: skip
    w(insert("planned_evidences",
             ["id", "tenant_id", "experience_id", "name", "kind", "value_scale", "max_score",
              "proposed_by", "accepted_at"], ev_rows))  # fmt: skip
    w(insert("planned_evidence_criteria", ["id", "tenant_id", "evidence_id", "criterion_id"],
             evc_rows))  # fmt: skip
    w(insert("session_outline_entries",
             ["id", "tenant_id", "experience_id", "class_date", "title", "topics",
              "planned_evidence_id", "proposed_by", "accepted_at"], entry_rows))  # fmt: skip
    w(
        """
-- La ubicación de cada evidencia apunta en los dos sentidos (planned_evidences.session_entry_id
-- y session_outline_entries.planned_evidence_id), como la deja repo/planning.py al ubicarla.
update planned_evidences pe
   set session_entry_id = e.id
  from session_outline_entries e
 where e.planned_evidence_id = pe.id
   and pe.tenant_id = '"""
        + str(TENANT)
        + """';
"""
    )
    stats.update(
        experiencias=len(exp_rows),
        criterios=len(crit_rows),
        evidencias=len(ev_rows),
        sesiones_esquema=len(entry_rows),
    )

    # §2 planning_sync ----------------------------------------------------------------
    w(SECTION_SYNC.format(tenant=TENANT))

    # §3 sessions and attendance -------------------------------------------------------
    rates = values([(st.id, *ATTENDANCE[st.profile]) for st in STUDENTS])
    w(SECTION_ATTENDANCE.format(tenant=TENANT, rates=rates))

    # §4 scores -----------------------------------------------------------------------
    score_rows: list[Row] = []
    ord_rows: list[Row] = []
    for e in EXPERIENCES:
        teacher = teacher_id(AREA[e.area].teacher)
        for ev in e.evidences:
            assert ev.date is not None
            asm = ID("seed-assessment", str(ev.id))
            for st in section_students(e.section):
                if st.joined > ev.date:
                    continue
                h = H(st.code, ev.id, "miss") % 100
                recorded = ts(ev.date + dt.timedelta(days=3), "19:00")
                sid = ID("seed-score", f"{asm}:{st.code}")
                if h < MISSING[st.profile]:
                    status = "absent" if h % 3 == 0 else "not_submitted"
                    score_rows.append((sid, TENANT, asm, st.id, status, None,
                                       20 if ev.scale == "numeric" else None, teacher, recorded))  # fmt: skip
                    continue
                lv = evidence_level(st, ev, e.term)
                if ev.scale == "numeric":
                    lo, hi = BANDS[lv]
                    value = lo + H(st.code, ev.id, "val") % (hi - lo + 1)
                    score_rows.append((sid, TENANT, asm, st.id, "graded", value, 20, teacher,
                                       recorded))  # fmt: skip
                else:
                    ord_rows.append((sid, TENANT, asm, st.id, "graded", scale_level(lv), teacher,
                                     recorded))  # fmt: skip
    w(SECTION_SCORES)
    w(insert("scores", ["id", "tenant_id", "assessment_id", "student_id", "status", "raw_value",
                        "max_value", "recorded_by_id", "recorded_at"], score_rows))  # fmt: skip
    w(insert("scores", ["id", "tenant_id", "assessment_id", "student_id", "status",
                        "scale_level_id", "recorded_by_id", "recorded_at"], ord_rows))  # fmt: skip
    stats.update(notas=len(score_rows) + len(ord_rows))

    # §5 levels -----------------------------------------------------------------------
    ctl_rows: list[Row] = []
    for st, comp, term, lv in LEVEL_ROWS:
        area = comp.split("-")[0]
        if (st.code, comp, term) == CORRECTED_LEVEL:
            lv = max(1, lv - 1)  # the first assertion; §8 supersedes it with the real level
        ctl_rows.append((ID("seed-ctl", f"{st.code}:{comp}:{term}"), TENANT, st.id,
                         ID("competency", comp), YEAR_ID, term_id(term),
                         class_id(area, st.section), scale_level(lv),
                         teacher_id(AREA[area].teacher), ASSERTED_AT[term]))  # fmt: skip
    for st in STUDENTS:
        for term in (1, 2):
            if not started_term(st, term):
                continue
            for comp in ("TR-C1", "TR-C2"):
                if st.profile == "superdotado":
                    lv = 4
                elif st.profile in ("riesgo", "rezagado"):
                    lv = 2
                else:
                    lv = 3 if H(st.code, comp, term) % 100 < 60 else 2
                ctl_rows.append((ID("seed-ctl", f"{st.code}:{comp}:{term}"), TENANT, st.id,
                                 ID("competency", comp), YEAR_ID, term_id(term), None,
                                 scale_level(lv), None, ASSERTED_AT[term]))  # fmt: skip
    w(SECTION_LEVELS)
    w(insert("competency_term_levels",
             ["id", "tenant_id", "student_id", "competency_id", "academic_year_id", "term_id",
              "class_id", "scale_level_id", "asserted_by_id", "asserted_at"], ctl_rows))  # fmt: skip
    stats.update(niveles=len(ctl_rows))

    # §6 conclusions ------------------------------------------------------------------
    dc_rows: list[Row] = []
    draft_done = False
    for st, comp, term, lv in LEVEL_ROWS:
        req = requirement(st, comp, term, lv)
        if req is None:
            continue
        area = comp.split("-")[0]
        status = "final"
        if req == "level_c" and term == 2 and not draft_done:
            status, draft_done = "draft", True
        dc_rows.append((ID("seed-dc", f"{st.code}:{comp}:{term}"), TENANT, st.id,
                        ID("competency", comp), YEAR_ID, term_id(term), class_id(area, st.section),
                        conclusion_body(st, comp, term, lv, req), req, status,
                        teacher_id(AREA[area].teacher),
                        ASSERTED_AT[term].replace("12:00", "15:00")))  # fmt: skip
    w(SECTION_CONCLUSIONS)
    w(insert("descriptive_conclusions",
             ["id", "tenant_id", "student_id", "competency_id", "academic_year_id", "term_id",
              "class_id", "body", "requirement", "status", "authored_by_id", "authored_at"],
             dc_rows))  # fmt: skip
    stats.update(conclusiones=len(dc_rows))

    # §7 voice notes ------------------------------------------------------------------
    note_rows: list[Row] = []
    for n in NOTES:
        note_rows.append((n.id, n.student.id, n.area, n.student.section, n.day.isoformat(),
                          n.duration_ms, n.transcript, n.redacted, n.status))  # fmt: skip
    w(SECTION_NOTES.format(tenant=TENANT, rows=values(note_rows),
                           classes=values([(class_id(a.code, s), a.code, s,
                                            teacher_id(a.teacher))
                                           for a in AREAS for s in SECTIONS])))  # fmt: skip
    stats.update(notas_de_voz=len(note_rows))

    # §8 corrections and close ---------------------------------------------------------
    w(correction_sql())
    w(
        SECTION_CLOSE.format(
            tenant=TENANT, closed1=CLOSED_AT[1], closed2=CLOSED_AT[2], closer=teacher_id("gonzalo")
        )
    )
    return "\n".join(parts), stats


# Absence profile in permille: (absent, late, justified, excused).
ATTENDANCE = {
    "superdotado": (10, 20, 10, 5),
    "media": (25, 50, 15, 5),
    "dificultad": (40, 60, 15, 5),
    "rezagado": (70, 80, 20, 5),
    "riesgo": (170, 90, 30, 5),
}


CORRECTED_STUDENT = "SF26-1A05"
CORRECTED_LEVEL = (CORRECTED_STUDENT, "MAT-C2", 2)


def correction_sql() -> str:
    """One corrected score and one corrected level, so the supersession paths have data. Both
    in T-II, before the term closes (a closed term rejects new scores)."""
    st = next(s for s in STUDENTS if s.code == CORRECTED_STUDENT)
    ev = next(ev for e in EXPERIENCES if e.key == "MAT-1A:T2E1" for ev in e.evidences
              if ev.scale == "numeric")  # fmt: skip
    asm = ID("seed-assessment", str(ev.id))
    old = ID("seed-score", f"{asm}:{st.code}")
    new = ID("seed-score-fix", str(old))
    _, comp, term = CORRECTED_LEVEL
    lv = LEVEL[CORRECTED_LEVEL]
    old_ctl = ID("seed-ctl", f"{st.code}:{comp}:{term}")
    new_ctl = ID("seed-ctl-fix", str(old_ctl))
    return f"""
-- §8 ==================================================================
-- ---------------------------------------------------------------------------
-- Correcciones: la cadena de supersesión.
--
-- scores y competency_term_levels son append-only: una corrección marca
-- superseded_at en la fila vigente e inserta el reemplazo con supersedes_id.
-- Va antes del cierre de T-II, porque un trimestre cerrado no admite notas.
--
-- 1. {st.given} ({st.code}): la nota de "{ev.name}" se recalifica.
-- 2. El mismo estudiante en {comp}, T-II: el docente afirmó primero
--    {LEVELS[max(1, lv - 1) - 1]} y lo corrigió a {LEVELS[lv - 1]} al revisar la evidencia completa.
-- ---------------------------------------------------------------------------

update scores set superseded_at = timestamptz '2026-07-10 09:30:00-05'
 where id = '{old}' and status = 'graded';

insert into scores (id, tenant_id, assessment_id, student_id, status, raw_value, max_value,
                    feedback, source, recorded_by_id, recorded_at, supersedes_id)
select '{new}', sc.tenant_id, sc.assessment_id, sc.student_id, 'graded',
       least(20, sc.raw_value + 2), sc.max_value,
       'Recalificación: la pregunta 3 estaba bien resuelta y no se había sumado.',
       'manual', sc.recorded_by_id, timestamptz '2026-07-10 09:30:00-05', sc.id
  from scores sc
 where sc.id = '{old}' and sc.status = 'graded';

update competency_term_levels set superseded_at = timestamptz '2026-09-04 18:00:00-05'
 where id = '{old_ctl}';

insert into competency_term_levels
  (id, tenant_id, student_id, competency_id, academic_year_id, term_id, class_id,
   scale_level_id, asserted_by_id, asserted_at, supersedes_id, note)
select '{new_ctl}', c.tenant_id, c.student_id, c.competency_id, c.academic_year_id, c.term_id,
       c.class_id, '{scale_level(lv)}', c.asserted_by_id,
       timestamptz '2026-09-04 18:00:00-05', c.id,
       'Corregido al revisar la evidencia completa del trimestre.'
  from competency_term_levels c
 where c.id = '{old_ctl}';
"""


SQL_HEADER = f"""-- ===========================================================================
-- Mawta — datos de demostración para I.E. San Felipe, 1ro de secundaria (A y B), año 2026.
--
-- GENERADO por seed/demo/build.py a partir de seed/demo/contenido/*.json y del
-- catálogo CNEB. No se edita a mano: se cambia el generador o el contenido y se
-- vuelve a correr `python3 seed/demo/build.py`.
--
-- QUÉ ES ESTO
--   Un año escolar vivido para dos secciones con diez áreas: planificación real
--   de T-I y T-II (experiencias, criterios, evidencias, esquema de sesiones),
--   las evaluaciones que esa planificación produce, notas, asistencia, niveles
--   de logro, conclusiones descriptivas y notas de voz (solo texto). T-III queda
--   ABIERTO y SIN PLANIFICAR, para probar el agente de planificación.
--   seed/demo/PERFILES.md es la hoja de respuestas: el perfil de cada estudiante.
--
-- NO CORRE SOLO
--   Requiere el colegio instalado desde seed/onboarding/ejemplo-san-felipe.json
--   (mismo generador). Si no encuentra esa estructura, aborta sin insertar nada.
--
-- CÓMO SE EJECUTA
--   Como superusuario, contra la base que ya tiene el colegio:
--     psql "$ADMIN_DATABASE_URL" -v ON_ERROR_STOP=1 -f seed/seed_demo.sql
--
-- EL CORTE PASADO/FUTURO
--   Sesiones dictadas y asistencia llegan hasta la fecha real en Lima, así que
--   T-III avanza solo. Las notas de voz llegan hasta {NOTES_UNTIL.isoformat()}.
--
-- DATOS FICTICIOS
--   Ningún estudiante corresponde a una persona real. NO EJECUTAR CONTRA UNA BASE
--   CON DATOS REALES.
-- ===========================================================================

begin;

do $$
begin
  if not exists (select 1 from classes where id = '{class_id("MAT", "B")}') then
    raise exception 'Falta el colegio de ejemplo. Instálalo primero con seed/onboard.sh y '
                    'seed/onboarding/ejemplo-san-felipe.json.';
  end if;
  if exists (select 1 from learning_experiences where tenant_id = '{TENANT}') then
    raise exception 'Los datos de demostración ya están cargados. Este archivo espera una '
                    'estructura recién instalada; no borra nada.';
  end if;
end
$$;
"""

SECTION_PLAN = """
-- §1 ==================================================================
-- ---------------------------------------------------------------------------
-- Planificación de T-I y T-II: dos experiencias por trimestre en cada clase,
-- con el mismo contenido en 1A y 1B (las planifica el mismo docente).
--
-- Todo queda aceptado y la experiencia 'planificada', que es el estado en que
-- la planificación se vuelve evaluación (§2). Algunos criterios llevan
-- proposed_by = 'mawta': el docente aceptó lo que propuso el agente. Algunos
-- llevan performance_id: el desempeño del grado del que derivan.
--
-- Una competencia por área de tres o más competencias no se trabaja en todo el
-- primer semestre (MAT-C4, CCSS-C3, ING-C3, CYT-C3): no tiene ni una fila de
-- nivel, y leer esa ausencia como "C" sería inventar un juicio.
-- ---------------------------------------------------------------------------
"""

SECTION_SYNC = """
-- §2 ==================================================================
-- ---------------------------------------------------------------------------
-- De la planificación a la evaluación: lo mismo que hace
-- src/repo/planning_sync.py (sync_experience) con una experiencia planificada.
--
--   * cada sesión con entrada en el esquema toma su título como tema;
--   * cada evidencia planificada se vuelve una assessment ligada a la sesión de
--     su fecha (la primera del día), con due_at = fin de esa sesión, y con los
--     criterios de la evidencia en assessment_criteria.
--
-- Las de T-I y T-II van 'closed': su trimestre se cierra en §9.
-- ---------------------------------------------------------------------------

update class_sessions cs
   set topic = e.title
  from session_outline_entries e
  join learning_experiences x on x.id = e.experience_id
 where x.tenant_id = '{tenant}'
   and cs.class_id = x.class_id and cs.session_date = e.class_date;

insert into assessments (id, tenant_id, class_id, term_id, session_id, title, kind, value_scale,
                         max_score, due_at, status, published_at, closed_at, planned_evidence_id)
select md5('seed-assessment:0723519:' || pe.id::text)::uuid,
       pe.tenant_id, x.class_id, x.term_id, s.id, pe.name, pe.kind, pe.value_scale, pe.max_score,
       s.scheduled_end_at, 'closed', pe.accepted_at,
       case t.sequence when 1 then timestamptz '2026-06-08 17:00:00-05'
                       else timestamptz '2026-09-07 17:00:00-05' end,
       pe.id
  from planned_evidences pe
  join learning_experiences x on x.id = pe.experience_id
  join terms t on t.id = x.term_id
  join session_outline_entries e on e.id = pe.session_entry_id
  join lateral (
    select id, scheduled_end_at from class_sessions
     where class_id = x.class_id and session_date = e.class_date
       and deleted_at is null and status <> 'cancelled'
     order by scheduled_start_at limit 1
  ) s on true
 where pe.tenant_id = '{tenant}';

insert into assessment_criteria (tenant_id, assessment_id, criterion_id)
select pc.tenant_id, a.id, pc.criterion_id
  from planned_evidence_criteria pc
  join assessments a on a.planned_evidence_id = pc.evidence_id
 where pc.tenant_id = '{tenant}';
"""

SECTION_ATTENDANCE = """
-- §3 ==================================================================
-- ---------------------------------------------------------------------------
-- Sesiones dictadas y asistencia, hasta HOY EN LIMA (también en T-III).
--
-- El corte es la fecha actual en Lima, no current_date: el servidor corre en
-- UTC. La asistencia se reparte por un hash del par (sesión, estudiante) con
-- tasas que dependen del perfil: un estudiante en riesgo falta mucho más.
-- El roster se evalúa a la fecha de la sesión (joined_on), así que el
-- estudiante que llegó en T-II no tiene asistencia de T-I.
-- ---------------------------------------------------------------------------

update class_sessions cs
   set status                 = 'completed',
       actual_start_at        = cs.scheduled_start_at,
       actual_end_at          = cs.scheduled_end_at,
       started_by_id          = ct.teacher_id,
       attendance_taken_at    = cs.scheduled_end_at,
       attendance_taken_by_id = ct.teacher_id
  from class_teachers ct
 where ct.class_id = cs.class_id
   and ct.role = 'titular'
   and cs.tenant_id = '{tenant}'
   and cs.session_date < (now() at time zone 'America/Lima')::date;

with tasas (student_id, ausente, tarde, justificada, excusada) as (values
{rates}
)
insert into attendance_records
  (id, tenant_id, session_id, student_id, class_id, session_date,
   status, minutes_late, source, recorded_by_id, recorded_at)
select md5('att:' || cs.id::text || ':' || sm.student_id::text)::uuid,
       cs.tenant_id, cs.id, sm.student_id, cs.class_id, cs.session_date,
       v.status,
       case when v.status = 'late' then 5 + (v.bucket % 20) end,
       'manual', cs.attendance_taken_by_id, cs.attendance_taken_at
  from class_sessions cs
  join classes c on c.id = cs.class_id
  join section_memberships sm
    on sm.section_id = c.section_id
   and sm.joined_on <= cs.session_date
   and (sm.left_on is null or sm.left_on > cs.session_date)
  join tasas r on r.student_id::uuid = sm.student_id
  cross join lateral (
    select b, case
                when b < r.ausente then 'absent'
                when b < r.ausente + r.tarde then 'late'
                when b < r.ausente + r.tarde + r.justificada then 'justified'
                when b < r.ausente + r.tarde + r.justificada + r.excusada then 'excused'
                else 'present'
              end
      from (select ('x' || substr(md5('att:' || cs.id::text || ':' || sm.student_id::text), 1, 8))::bit(32)::bigint % 1000 as b) q
  ) as v(bucket, status)
 where cs.status = 'completed'
   and cs.tenant_id = '{tenant}';
"""

SECTION_SCORES = """
-- §4 ==================================================================
-- ---------------------------------------------------------------------------
-- Notas de las evaluaciones de T-I y T-II.
--
-- El generador fija primero el nivel de cada estudiante por competencia y
-- trimestre (según su perfil) y luego genera cada nota dentro de la banda de
-- ese nivel (C 6-10, B 11-13, A 14-16, AD 17-20), con un tambaleo ocasional de
-- un nivel. Una C diseñada se sostiene siempre con evidencia en C. Las
-- evidencias ordinales se valoran con AD/A/B/C sobre esa evidencia.
-- Hay entregas faltantes ('absent', 'not_submitted'), más en los perfiles bajos.
-- class_id y term_id los copia un trigger desde la assessment.
-- ---------------------------------------------------------------------------
"""

SECTION_LEVELS = """
-- §5 ==================================================================
-- ---------------------------------------------------------------------------
-- Niveles de logro por competencia y trimestre: el registro oficial.
--
-- Solo T-I y T-II, solo competencias trabajadas en el trimestre, y solo para
-- quien estaba matriculado al empezar el trimestre. Las transversales (TR-C1,
-- TR-C2) no tienen clase ni docente: asserted_by_id y class_id quedan nulos.
-- ---------------------------------------------------------------------------
"""

SECTION_CONCLUSIONS = """
-- §6 ==================================================================
-- ---------------------------------------------------------------------------
-- Conclusiones descriptivas. Obligatorias en secundaria con C, con C en dos
-- periodos consecutivos (deben justificar la falta de progreso) y para todo
-- estudiante con apoyo de inclusión en todo periodo. Algunas AD llevan una
-- opcional. Precedencia: consecutive_c > inclusion_support > level_c > optional.
-- Una sola queda en 'draft' a propósito: un draft no satisface el requisito.
-- ---------------------------------------------------------------------------
"""

SECTION_NOTES = """
-- §7 ==================================================================
-- ---------------------------------------------------------------------------
-- Notas de voz: SOLO TEXTO. No hay audio (audio, storage_key y mime_type
-- nulos), así que la ruta del audio responde 404; la transcripción es la
-- evidencia. Se concentran en estudiantes con dificultades y en los
-- destacados, como pasa en un aula real.
--
--   T-I y T-II: ya barridas (transcript_redacted con [ESTUDIANTE] y
--               [COMPAÑERO_1]) y atribuidas ('ok'): el agente de conclusiones
--               las puede leer.
--   T-III:      'pending', para probar el agente de barrido. Unas pocas nombran
--               solo a un compañero y deben terminar descartadas
--               (mentions_other_student).
--
-- Cada nota cuelga de la primera sesión de su fecha y solo entra si esa sesión
-- ya se dictó.
-- ---------------------------------------------------------------------------

with clases (class_id, area, seccion, teacher_id) as (values
{classes}
),
notas (id, student_id, area, seccion, fecha, duration_ms, transcript, redacted, estado) as (values
{rows}
)
insert into voice_notes
  (id, tenant_id, session_id, student_id, class_id, teacher_id, recorded_at, duration_ms,
   transcription_status, transcript, transcript_redacted, attribution_status,
   attribution_checked_at)
select n.id::uuid, '{tenant}', s.id, n.student_id::uuid, c.class_id::uuid, c.teacher_id::uuid,
       s.scheduled_start_at + interval '20 minutes', n.duration_ms, 'completed', n.transcript,
       n.redacted, n.estado, case when n.estado = 'ok' then s.scheduled_end_at end
  from notas n
  join clases c on c.area = n.area and c.seccion = n.seccion
  join lateral (
    select id, scheduled_start_at, scheduled_end_at from class_sessions
     where class_id = c.class_id::uuid and session_date = n.fecha::date and status = 'completed'
     order by scheduled_start_at limit 1
  ) s on true;
"""

SECTION_CLOSE = """
-- §9 ==================================================================
-- ---------------------------------------------------------------------------
-- Cierre de T-I y T-II. VA AL FINAL: un trimestre cerrado rechaza toda nota
-- nueva. El onboarding deja activo solo el primer periodo, así que al cerrar I
-- y II hay que activar T-III.
-- ---------------------------------------------------------------------------

update terms
   set status = 'closed',
       closed_at = case sequence when 1 then timestamptz '{closed1}'
                                 when 2 then timestamptz '{closed2}' end,
       closed_by_id = '{closer}'
 where tenant_id = '{tenant}'
   and sequence in (1, 2);

update terms set status = 'active'
 where tenant_id = '{tenant}' and sequence = 3;

commit;
"""


# ----------------------------------------------------------------------- answer key --


def answer_key(stats: dict[str, int]) -> str:
    worked = sorted(c for c in COMPS if c in WORKED)
    lines = [
        "# San Felipe 2026 — hoja de respuestas del dataset",
        "",
        "Generado por `seed/demo/build.py`; no se edita a mano. Describe lo que el dataset",
        "contiene a propósito, para comparar con lo que responde el chat del director.",
        "",
        f"- Tenant (San Felipe, modular {MOD}): `{TENANT}`",
        "- 1° de secundaria, secciones A y B, 28 estudiantes cada una (B tiene un estudiante que",
        "  llegó en T-II). Tutores: 1S-A gonzalo, 1S-B rquispe.",
        f"- {len(worked)} competencias trabajadas en T-I y T-II; sin trabajar en todo el primer "
        "semestre: " + ", ".join(sorted(c for c in COMPS if c not in WORKED)) + ".",
        "- T-I y T-II cerrados; T-III abierto, sin experiencias, evaluaciones ni niveles.",
        "- Regla de 1° (cuadro 5.1.3.A, RVM 048-2024): promueve con B o más en la mitad o más de",
        "  las competencias de cada área. Un área con C en más de la mitad de sus competencias va",
        "  a recuperación; el perfil *riesgo* tiene C en todas las competencias de cinco áreas.",
        "",
        "Volumen: " + ", ".join(f"{v} {k.replace('_', ' ')}" for k, v in stats.items()) + ".",
        "",
        "## Perfiles",
        "",
        "| Perfil | Qué significa |",
        "|---|---|",
        "| superdotado | AD en ~75 % de las competencias, A en el resto |",
        "| media | A o B; nunca C. En 1S-B, MAT y CYT un poco más bajos |",
        "| dificultad | C en todas las competencias de dos áreas, en T-I y T-II (C consecutiva) |",
        "| rezagado | Sobre todo B; una competencia mejora (C→B) y otra empeora (B→C) |",
        "| riesgo | C en todas las competencias de cinco áreas en T-I y T-II; más C sueltas; "
        "asistencia baja |",
        "",
        "## Estudiantes",
        "",
        "| Código | Estudiante | Sección | Perfil | Áreas con C | C T-I | C T-II | C consecutivas | Notas |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for st in STUDENTS:
        c1 = [c for c in worked if LEVEL.get((st.code, c, 1)) == 1]
        c2 = [c for c in worked if LEVEL.get((st.code, c, 2)) == 1]
        consec = [c for c in c2 if c in c1]
        areas = sorted({c.split("-")[0] for c in c1 + c2})
        extra: list[str] = []
        if st.inclusion:
            extra.append("apoyo de inclusión")
        if st.joined > TERMS[0][3]:
            extra.append(f"llegó el {st.joined.isoformat()} (sin T-I)")
        lines.append(
            f"| {st.code} | {st.full} | 1S-{st.section} | {st.profile} | "
            f"{', '.join(areas) or '—'} | {len(c1)} | {len(c2)} | "
            f"{', '.join(consec) or '—'} | {'; '.join(extra) or ''} |"
        )
    lines += ["", "## Riesgo por competencia (C consecutivas en T-I y T-II)", ""]
    by_comp: dict[str, list[str]] = {}
    for st in STUDENTS:
        for c in worked:
            if LEVEL.get((st.code, c, 1)) == 1 and LEVEL.get((st.code, c, 2)) == 1:
                by_comp.setdefault(c, []).append(f"{st.given} {st.paternal} (1S-{st.section})")
    lines += ["| Competencia | Estudiantes |", "|---|---|"]
    for c in sorted(by_comp):
        lines.append(f"| {c} | {', '.join(by_comp[c])} |")
    lines += ["", "## Horario", ""]
    for s in SECTIONS:
        lines.append(f"**1S-{s}**: " + "; ".join(
            f"{a.code} " + ", ".join(f"{WEEKDAYS[d - 1]} {st_}-{en}"
                                     for d, st_, en in sorted(TIMETABLE[(a.code, s)]))
            for a in AREAS))  # fmt: skip
        lines.append("")
    return "\n".join(lines) + "\n"


def main() -> None:
    OUT_JSON.write_text(json.dumps(onboarding(), ensure_ascii=False, indent=2) + "\n")
    sql, stats = build_sql()
    OUT_SQL.write_text(sql)
    OUT_KEY.write_text(answer_key(stats))
    print(f"tenant {TENANT}")
    for k, v in stats.items():
        print(f"{k}: {v}")


if __name__ == "__main__":
    main()
