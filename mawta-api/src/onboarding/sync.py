"""Bring an already-onboarded school's curriculum up to date with the catalog. Matches competencies
and capabilities by code, inserts what is missing, sets grade_levels.cycle from the explicit grade
map, and reports name differences without changing them: a school that renamed a capability did so
on purpose. A second run changes nothing.

Nothing is inferred: the grade -> grado_cneb map is declared by the caller, never guessed from
ordinals.
"""

from dataclasses import dataclass, field
from uuid import UUID

import psycopg

from curriculum import DEFAULT_MODALITY, Catalog, capability_code


@dataclass
class SyncReport:
    colegio: str = ""
    tenant_id: UUID | None = None
    grados: int = 0
    competencias: int = 0
    capacidades: int = 0
    estandares: int = 0
    desempenos: int = 0
    niveles_esperados: int = 0
    renamed: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        out = [
            f"Colegio:        {self.colegio} ({self.tenant_id})",
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


def sync_curriculum(
    conn: psycopg.Connection, cat: Catalog, modular_code: str, grade_map: dict[str, str]
) -> SyncReport:
    """The caller owns the transaction, exactly like load()."""
    if not grade_map:
        raise SyncError("sync: falta el mapeo grado → grado_cneb")
    tenant = conn.execute(
        "select id, name from tenants where modular_code = %s and deleted_at is null",
        (modular_code,),
    ).fetchone()
    if tenant is None:
        raise SyncError(f"colegio {modular_code}: no existe")
    report = SyncReport(colegio=tenant["name"], tenant_id=tenant["id"])
    tenant_id = tenant["id"]
    grades = _set_grade_cycles(conn, cat, tenant_id, grade_map, report)
    _sync_competencies(conn, cat, tenant_id, grades, report)
    _sync_mappings(conn, cat, tenant_id, grades, report)
    report.renamed.sort()
    return report


def _set_grade_cycles(conn, cat, tenant_id, grade_map, report) -> dict[str, tuple[dict, UUID]]:
    """Set grade_levels.stage and cycle from the explicit map. Only the grades the map names are
    touched."""
    grades: dict[str, tuple[dict, UUID]] = {}
    for codigo, cneb in grade_map.items():
        cg = cat.grado[cneb]
        row = conn.execute(
            """
            select id, stage, cycle from grade_levels
             where tenant_id = %s and code = %s and deleted_at is null
            """,
            (tenant_id, codigo),
        ).fetchone()
        if row is None:
            raise SyncError(f'el colegio no tiene el grado "{codigo}"')
        grades[codigo] = (cg, row["id"])
        # Only write when something changes, so a second run really changes nothing (not even
        # updated_at).
        if row["stage"] == cg["nivel"] and row["cycle"] == cg["ciclo"]:
            continue
        conn.execute(
            "update grade_levels set stage = %s, cycle = %s where tenant_id = %s and id = %s",
            (cg["nivel"], cg["ciclo"], tenant_id, row["id"]),
        )
        report.grados += 1
    return grades


def _sync_competencies(conn, cat, tenant_id, grades, report) -> None:
    """Walk every competency the school already has, matching by code, and insert what the catalog
    has and the school lacks. Competencies the school does not have are not created: which areas a
    school uses is its decision."""
    rows = conn.execute(
        """
        select c.id, c.code, c.name from competencies c
         where c.tenant_id = %s and c.deleted_at is null
         order by c.code
        """,
        (tenant_id,),
    ).fetchall()
    for c in rows:
        comp = cat.competencia_by_code(c["code"])
        if comp is None:
            # A school's own competency is not in the catalog and none of its business.
            continue
        if comp["nombre"] != c["name"]:
            report.renamed.append(
                f'competencia {c["code"]}: el colegio dice "{c["name"]}" y el catálogo '
                f'"{comp["nombre"]}"'
            )
        report.competencias += 1
        # Always the row's own id: a school installed by an earlier loader may not have the
        # md5-derived ids a fresh load would produce.
        _sync_capabilities(conn, tenant_id, c["id"], c["code"], comp, report)
        _sync_standards(conn, tenant_id, c["id"], comp, report)
        _sync_performances(conn, cat, tenant_id, c["id"], c["code"], comp, grades, report)


def _sync_capabilities(conn, tenant_id, comp_id, codigo, comp, report) -> None:
    for k, cap in enumerate(comp["capacidades"], start=1):
        cap_code = capability_code(codigo, cap["numero"])
        row = conn.execute(
            """
            select name from capabilities
             where tenant_id = %s and competency_id = %s and code = %s and deleted_at is null
            """,
            (tenant_id, comp_id, cap_code),
        ).fetchone()
        if row is not None:
            if row["name"] != cap["nombre"]:
                report.renamed.append(
                    f'capacidad {cap_code}: el colegio dice "{row["name"]}" y el catálogo '
                    f'"{cap["nombre"]}"'
                )
            continue
        conn.execute(
            """
            insert into capabilities (tenant_id, competency_id, code, name, sort_order)
            values (%s, %s, %s, %s, %s)
            """,
            (tenant_id, comp_id, cap_code, cap["nombre"], k),
        )
        report.capacidades += 1


def _sync_standards(conn, tenant_id, comp_id, comp, report) -> None:
    for e in comp["estandares"]:
        cur = conn.execute(
            """
            insert into learning_standards (tenant_id, competency_id, level, official_text)
            values (%s, %s, %s, %s)
            on conflict (tenant_id, competency_id, level) where deleted_at is null do nothing
            """,
            (tenant_id, comp_id, e["nivel"], e["texto"]),
        )
        if cur.rowcount == 1:
            report.estandares += 1


def _sync_performances(conn, cat, tenant_id, comp_id, codigo, comp, grades, report) -> None:
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
                row = conn.execute(
                    """
                    select id from capabilities
                     where tenant_id = %s and competency_id = %s and code = %s
                       and deleted_at is null
                    """,
                    (tenant_id, comp_id, capability_code(codigo, d["capacidad_sugerida"])),
                ).fetchone()
                if row is None:
                    raise SyncError(
                        f"desempeño {codigo} {cg['codigo']} #{d['orden']}: capacidad sugerida "
                        "no existe"
                    )
                suggested = row["id"]
            cur = conn.execute(
                """
                insert into grade_level_performances
                  (tenant_id, competency_id, grade_level_id, sort_order, official_text,
                   en_proceso, expected_standard_level, suggested_capability_id)
                values (%s, %s, %s, %s, %s, %s, %s, %s)
                on conflict (tenant_id, competency_id, grade_level_id, sort_order)
                  where deleted_at is null do nothing
                """,
                (tenant_id, comp_id, level_id, d["orden"], d["texto"], en_proceso, expected,
                 suggested),
            )  # fmt: skip
            if cur.rowcount == 1:
                report.desempenos += 1


def _sync_mappings(conn, cat, tenant_id, grades, report) -> None:
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
        cur = conn.execute(
            """
            insert into standard_level_mappings (tenant_id, modality, cycle, expected_level)
            values (%s, %s, %s, %s)
            on conflict (tenant_id, modality, cycle) where deleted_at is null do nothing
            """,
            (tenant_id, DEFAULT_MODALITY, cg["ciclo"], level),
        )
        if cur.rowcount == 1:
            report.niveles_esperados += 1
