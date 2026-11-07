"""Bring an already-onboarded school's curriculum up to date with the catalog. Matches competencies
and capabilities by code, inserts what is missing, sets grade_levels.cycle from the explicit grade
map, and reports name differences without changing them: a school that renamed a capability did so
on purpose. A second run changes nothing.

Nothing is inferred: the grade -> grado_cneb map is declared by the caller, never guessed from
ordinals.
"""

from dataclasses import dataclass, field
from typing import Any, override
from uuid import UUID

from sqlalchemy import Connection, Executable, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from curriculum import DEFAULT_MODALITY, Catalog, capability_code
from mawta_schema.tables import (
    Capability,
    Competency,
    GradeLevel,
    GradeLevelPerformance,
    LearningStandard,
    School,
    StandardLevelMapping,
)

# Grade code -> (its catalog grado, the school's grade_levels.id).
Grades = dict[str, tuple[dict[str, Any], UUID]]


@dataclass
class SyncReport:
    colegio: str = ""
    school_id: UUID | None = None
    grados: int = 0
    competencias: int = 0
    capacidades: int = 0
    estandares: int = 0
    desempenos: int = 0
    niveles_esperados: int = 0
    renamed: list[str] = field(default_factory=list)

    @override
    def __str__(self) -> str:
        out = [
            f"Colegio:        {self.colegio} ({self.school_id})",
            f"Revisado:       {self.competencias} competencias del catálogo",
            f"Insertado:      {self.capacidades} capacidades, {self.estandares} estándares, "
            f"{self.desempenos} desempeños y {self.niveles_esperados} niveles esperados",
            f"Grados:         {self.grados} con nivel o ciclo actualizado",
        ]
        if not self.renamed:
            out.append("Nombres:        sin diferencias con el catálogo")
        else:
            out.append("Nombres distintos (NO se cambiaron; revisa y decide):")
            out += [f"  - {line}" for line in self.renamed]
        return "\n".join(out) + "\n"


class SyncError(Exception):
    pass


def _inserted(conn: Connection, stmt: Any) -> bool:
    """Whether an INSERT ... ON CONFLICT DO NOTHING wrote its row."""
    return conn.execute(stmt).first() is not None


def _run(conn: Connection, stmt: Executable) -> None:
    conn.execute(stmt)


def sync_curriculum(
    conn: Connection, cat: Catalog, modular_code: str, grade_map: dict[str, str]
) -> SyncReport:
    """The caller owns the transaction, exactly like load(). The modular code must be the one of
    this database's school: a guard against syncing the wrong school's database."""
    if not grade_map:
        raise SyncError("sync: falta el mapeo grado → grado_cneb")
    school = conn.execute(
        select(School.id, School.name, School.modular_code).where(School.deleted_at.is_(None))
    ).first()
    if school is None:
        raise SyncError("esta base no tiene un colegio instalado")
    if school.modular_code != modular_code:
        raise SyncError(
            f"colegio {modular_code}: esta base es de {school.name} ({school.modular_code})"
        )
    report = SyncReport(colegio=school.name, school_id=school.id)
    grades = _set_grade_cycles(conn, cat, grade_map, report)
    _sync_competencies(conn, cat, grades, report)
    _sync_mappings(conn, cat, grades, report)
    report.renamed.sort()
    return report


def _set_grade_cycles(
    conn: Connection, cat: Catalog, grade_map: dict[str, str], report: SyncReport
) -> Grades:
    """Set grade_levels.stage and cycle from the explicit map. Only the grades the map names are
    touched."""
    grades: Grades = {}
    for codigo, cneb in grade_map.items():
        cg = cat.grado[cneb]
        row = conn.execute(
            select(GradeLevel.id, GradeLevel.stage, GradeLevel.cycle).where(
                GradeLevel.code == codigo, GradeLevel.deleted_at.is_(None)
            )
        ).first()
        if row is None:
            raise SyncError(f'el colegio no tiene el grado "{codigo}"')
        grades[codigo] = (cg, row.id)
        # Only write when something changes, so a second run really changes nothing (not even
        # updated_at).
        if row.stage == cg["nivel"] and row.cycle == cg["ciclo"]:
            continue
        _run(
            conn,
            update(GradeLevel)
            .where(GradeLevel.id == row.id)
            .values(stage=cg["nivel"], cycle=cg["ciclo"]),
        )
        report.grados += 1
    return grades


def _sync_competencies(conn: Connection, cat: Catalog, grades: Grades, report: SyncReport) -> None:
    """Walk every competency the school already has, matching by code, and insert what the catalog
    has and the school lacks. Competencies the school does not have are not created: which areas a
    school uses is its decision."""
    rows = conn.execute(
        select(Competency.id, Competency.code, Competency.name)
        .where(Competency.deleted_at.is_(None))
        .order_by(Competency.code)
    ).all()
    for c in rows:
        comp = cat.competencia_by_code(c.code)
        if comp is None:
            # A school's own competency is not in the catalog and none of its business.
            continue
        if comp["nombre"] != c.name:
            report.renamed.append(
                f'competencia {c.code}: el colegio dice "{c.name}" y el catálogo "{comp["nombre"]}"'
            )
        report.competencias += 1
        # Always the row's own id: a school installed by an earlier loader may not have the
        # md5-derived ids a fresh load would produce.
        _sync_capabilities(conn, c.id, c.code, comp, report)
        _sync_standards(conn, c.id, comp, report)
        _sync_performances(conn, cat, c.id, c.code, comp, grades, report)


def _capability(conn: Connection, comp_id: UUID, code: str) -> Any:
    return conn.execute(
        select(Capability.id, Capability.name).where(
            Capability.competency_id == comp_id,
            Capability.code == code,
            Capability.deleted_at.is_(None),
        )
    ).first()


def _sync_capabilities(
    conn: Connection, comp_id: UUID, codigo: str, comp: dict[str, Any], report: SyncReport
) -> None:
    for k, cap in enumerate(comp["capacidades"], start=1):
        cap_code = capability_code(codigo, cap["numero"])
        row = _capability(conn, comp_id, cap_code)
        if row is not None:
            if row.name != cap["nombre"]:
                report.renamed.append(
                    f'capacidad {cap_code}: el colegio dice "{row.name}" y el catálogo '
                    f'"{cap["nombre"]}"'
                )
            continue
        _run(
            conn,
            pg_insert(Capability).values(
                competency_id=comp_id, code=cap_code, name=cap["nombre"], sort_order=k
            ),
        )
        report.capacidades += 1


def _sync_standards(
    conn: Connection, comp_id: UUID, comp: dict[str, Any], report: SyncReport
) -> None:
    s = LearningStandard
    for e in comp["estandares"]:
        if _inserted(
            conn,
            pg_insert(s)
            .values(competency_id=comp_id, level=e["nivel"], official_text=e["texto"])
            .on_conflict_do_nothing(
                index_elements=[s.competency_id, s.level], index_where=s.deleted_at.is_(None)
            )
            .returning(s.id),
        ):
            report.estandares += 1


def _sync_performances(
    conn: Connection,
    cat: Catalog,
    comp_id: UUID,
    codigo: str,
    comp: dict[str, Any],
    grades: Grades,
    report: SyncReport,
) -> None:
    p = GradeLevelPerformance
    for cg, level_id in grades.values():
        en_proceso = cat.en_proceso(cg["codigo"])
        expected = cat.expected_level(DEFAULT_MODALITY, cg["ciclo"])
        if expected is None:
            raise SyncError(
                f"ciclo {cg['ciclo']}: el catálogo no declara el nivel esperado para la modalidad "
                f"{DEFAULT_MODALITY}"
            )
        for d in comp["desempenos"]:
            if d["grado"] != cg["codigo"]:
                continue
            suggested = None
            if d.get("capacidad_sugerida") is not None:
                row = _capability(conn, comp_id, capability_code(codigo, d["capacidad_sugerida"]))
                if row is None:
                    raise SyncError(
                        f"desempeño {codigo} {cg['codigo']} #{d['orden']}: capacidad sugerida "
                        "no existe"
                    )
                suggested = row.id
            if _inserted(
                conn,
                pg_insert(p)
                .values(
                    competency_id=comp_id,
                    grade_level_id=level_id,
                    sort_order=d["orden"],
                    official_text=d["texto"],
                    en_proceso=en_proceso,
                    expected_standard_level=expected,
                    suggested_capability_id=suggested,
                )
                .on_conflict_do_nothing(
                    index_elements=[p.competency_id, p.grade_level_id, p.sort_order],
                    index_where=p.deleted_at.is_(None),
                )
                .returning(p.id),
            ):
                report.desempenos += 1


def _sync_mappings(conn: Connection, cat: Catalog, grades: Grades, report: SyncReport) -> None:
    m = StandardLevelMapping
    seen: set[str] = set()
    for cg, _ in grades.values():
        if cg["ciclo"] in seen:
            continue
        seen.add(cg["ciclo"])
        level = cat.expected_level(DEFAULT_MODALITY, cg["ciclo"])
        if level is None:
            raise SyncError(
                f"ciclo {cg['ciclo']}: el catálogo no declara el nivel esperado para la modalidad "
                f"{DEFAULT_MODALITY}"
            )
        if _inserted(
            conn,
            pg_insert(m)
            .values(modality=DEFAULT_MODALITY, cycle=cg["ciclo"], expected_level=level)
            .on_conflict_do_nothing(
                index_elements=[m.modality, m.cycle], index_where=m.deleted_at.is_(None)
            )
            .returning(m.id),
        ):
            report.niveles_esperados += 1
