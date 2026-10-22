"""The national curriculum (CNEB) catalog every school loads from: the grades with their cycles, the
(modality, cycle) -> expected-standard-level mapping, the areas with their school-facing competency
codes, and one file per CNEB competency holding its capacities, learning standards and grade-level
performances.

Competency names, capacities and standards are the CNEB text (RM 281-2016 as modified by RM
159-2017), section IV, with obvious typos corrected and footnote call numbers dropped; Educación
Religiosa standards and the desempeños come from the RM 649-2016 programmes, since the CNEB has
neither. The loader stores the text as is and validation only checks consistency. A competency is stored once because the same CNEB competency belongs to different
areas depending on the level; areas only reference competencies.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_MODALITY = "ebr"
_DATA = Path(__file__).parent / "cneb"
CNEB_PATH = "cneb/cneb.json"
AREAS_PATH = "cneb/areas.json"
COMPETENCIAS_DIR = "cneb/competencias"

_NIVELES = ("inicial", "primaria", "secundaria")
_CICLOS = ("ciclo_i", "ciclo_ii", "ciclo_iii", "ciclo_iv", "ciclo_v", "ciclo_vi", "ciclo_vii")


class CatalogError(Exception):
    """Every problem found in the catalog data, one line each."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__(
            f"el catálogo CNEB tiene {len(errors)} problema(s):\n  - " + "\n  - ".join(errors)
        )


def capability_code(competency_code: str, numero: int) -> str:
    """MAT-C1 + 1 -> MAT-C1-CAP1. The convention is the one schools and seed_demo.sql use, so the
    md5-derived ids do not change."""
    return f"{competency_code}-CAP{numero}"


@dataclass
class Catalog:
    fuente: str = ""
    grados: list[dict[str, Any]] = field(default_factory=list)
    grado: dict[str, dict[str, Any]] = field(default_factory=dict)
    niveles_esperados: list[dict[str, Any]] = field(default_factory=list)
    areas: list[dict[str, Any]] = field(default_factory=list)
    area: dict[str, dict[str, Any]] = field(default_factory=dict)
    transversales: list[dict[str, Any]] = field(default_factory=list)
    transversal: dict[str, dict[str, Any]] = field(default_factory=dict)
    competencias: dict[int, dict[str, Any]] = field(default_factory=dict)
    # school-facing competency code ("MAT-C1", "TR-C1") -> CNEB number
    numero_by_code: dict[str, int] = field(default_factory=dict)
    # area code -> every capability code its competencies define
    capability_codes_by_area: dict[str, set[str]] = field(default_factory=dict)

    def competencia_by_code(self, code: str) -> dict[str, Any] | None:
        n = self.numero_by_code.get(code)
        return self.competencias.get(n) if n is not None else None

    def expected_level(self, modality: str, ciclo: str) -> int | None:
        for n in self.niveles_esperados:
            if n["modalidad"] == modality and n["ciclo"] == ciclo:
                return n["nivel"]
        return None

    def last_grade_of_cycle(self, ciclo: str) -> str | None:
        """The last grade of a cycle in catalog order: the grade whose programme describes
        reaching the cycle's standard."""
        last = None
        for g in self.grados:
            if g["ciclo"] == ciclo:
                last = g["codigo"]
        return last

    def en_proceso(self, grado: str) -> bool:
        """Whether a grade's performances are "in progress towards" the cycle standard rather
        than "reaching" it: only the last grade of a cycle reaches it."""
        g = self.grado.get(grado)
        if g is None:
            return False
        last = self.last_grade_of_cycle(g["ciclo"])
        return last is not None and grado != last

    def grade_list(self) -> str:
        return ", ".join(g["codigo"] for g in self.grados)


def _read(path: Path, name: str, errors: list[str], allowed: dict[str, Any] | None = None):
    try:
        data = json.loads(path.read_text())
    except OSError as exc:
        errors.append(f"leer {name}: {exc}")
        return None
    except ValueError as exc:
        errors.append(f"{name}: JSON mal formado: {exc}")
        return None
    return data


def _strict(obj: Any, allowed: set[str], name: str, errors: list[str]) -> bool:
    """Reject unknown keys: a misspelled "capacidaades" would otherwise drop a whole competency's
    capacities and nobody would notice until a teacher cannot pick one."""
    if not isinstance(obj, dict):
        errors.append(f"{name}: se esperaba un objeto")
        return False
    unknown = sorted(set(obj) - allowed)
    for key in unknown:
        errors.append(f"{name}: campo desconocido {key!r}; revisa el nombre de la clave")
    return not unknown


def load(root: Path | None = None) -> Catalog:
    """Decode and validate the shipped catalog (or the one under `root`). Call it once at startup
    and fail fast: a process carrying a broken catalog must refuse to load any school."""
    root = root or _DATA
    errors: list[str] = []
    c = Catalog()

    doc = _read(root / "cneb.json", CNEB_PATH, errors)
    areas_doc = _read(root / "areas.json", AREAS_PATH, errors)
    if doc is None or areas_doc is None:
        raise CatalogError(errors)
    if _strict(doc, {"fuente", "grados", "niveles_esperados"}, CNEB_PATH, errors):
        c.fuente = doc.get("fuente", "")
        c.grados = doc.get("grados") or []
        c.niveles_esperados = doc.get("niveles_esperados") or []
    if _strict(areas_doc, {"areas", "transversales"}, AREAS_PATH, errors):
        c.areas = areas_doc.get("areas") or []
        c.transversales = areas_doc.get("transversales") or []
    errors += _check_grades(c)
    errors += _check_competencias(c, root / "competencias")
    errors += _check_areas(c)
    if errors:
        raise CatalogError(errors)
    if not c.fuente:
        raise CatalogError(
            [f"{CNEB_PATH}.fuente: es obligatorio (nombra la RM 281-2016 y la RM 649-2016)"]
        )
    return c


def _check_grades(c: Catalog) -> list[str]:
    errs: list[str] = []
    if not c.grados:
        errs.append(f"{CNEB_PATH}.grados: debe haber al menos un grado")
    seen: dict[str, str] = {}
    ciclos: list[str] = []
    for i, g in enumerate(c.grados):
        path = f"{CNEB_PATH}.grados[{i}]"
        if not _strict(g, {"codigo", "nivel", "ciclo"}, path, errs):
            continue
        if not g.get("codigo"):
            errs.append(f"{path}.codigo: es obligatorio")
            continue
        if g["codigo"] in seen:
            errs.append(
                f"{path}.codigo: el grado {g['codigo']!r} está repetido (ya aparece en "
                f"{seen[g['codigo']]})"
            )
            continue
        seen[g["codigo"]] = path
        if g.get("nivel") not in _NIVELES:
            errs.append(
                f"{path}.nivel: {g.get('nivel')!r} no es un nivel válido; usa inicial, primaria "
                "o secundaria"
            )
        if g.get("ciclo") not in _CICLOS:
            errs.append(
                f"{path}.ciclo: {g.get('ciclo')!r} no es un ciclo válido; usa ciclo_i a ciclo_vii"
            )
        elif g["ciclo"] not in ciclos:
            ciclos.append(g["ciclo"])
        c.grado[g["codigo"]] = g
    seen_level: dict[str, str] = {}
    for i, n in enumerate(c.niveles_esperados):
        path = f"{CNEB_PATH}.niveles_esperados[{i}]"
        if not _strict(n, {"modalidad", "ciclo", "nivel"}, path, errs):
            continue
        if not n.get("modalidad"):
            errs.append(f"{path}.modalidad: es obligatoria")
        if n.get("ciclo") not in _CICLOS:
            errs.append(
                f"{path}.ciclo: {n.get('ciclo')!r} no es un ciclo válido; usa ciclo_i a ciclo_vii"
            )
        if not isinstance(n.get("nivel"), int) or not 1 <= n["nivel"] <= 8:
            errs.append(f"{path}.nivel: {n.get('nivel')!r} no está entre 1 y 8")
        key = f"{n.get('modalidad')}|{n.get('ciclo')}"
        if key in seen_level:
            errs.append(
                f"{path}: la combinación modalidad {n.get('modalidad')!r} y ciclo "
                f"{n.get('ciclo')!r} está repetida (ya aparece en {seen_level[key]})"
            )
        else:
            seen_level[key] = path
    for ciclo in ciclos:
        if not any(n.get("ciclo") == ciclo for n in c.niveles_esperados):
            first = next(g["codigo"] for g in c.grados if g.get("ciclo") == ciclo)
            errs.append(
                f"{CNEB_PATH}.niveles_esperados: falta el ciclo {ciclo!r} (lo usa el grado {first})"
            )
    return errs


def competencia_file(numero: int) -> str:
    return f"c{numero:02d}.json"


def _check_competencias(c: Catalog, directory: Path) -> list[str]:
    errs: list[str] = []
    if not directory.is_dir():
        return [f"leer {COMPETENCIAS_DIR}: no existe"]
    seen: dict[int, str] = {}
    for file in sorted(directory.glob("*.json")):
        name = f"{COMPETENCIAS_DIR}/{file.name}"
        comp = _read(file, name, errs)
        if comp is None:
            continue
        allowed = {"numero_cneb", "nombre", "capacidades", "estandares", "desempenos"}
        if not _strict(comp, allowed, name, errs):
            continue
        errs += _check_competencia(c, name, file.name, comp)
        numero = comp.get("numero_cneb")
        if not isinstance(numero, int) or numero <= 0:
            continue
        if numero in seen:
            errs.append(
                f"{name}.numero_cneb: la competencia {numero} está repetida (ya aparece en "
                f"{seen[numero]})"
            )
            continue
        seen[numero] = name
        c.competencias[numero] = comp
    return errs


def _check_competencia(c: Catalog, name: str, file_name: str, comp: dict[str, Any]) -> list[str]:
    errs: list[str] = []
    numero = comp.get("numero_cneb")
    if not isinstance(numero, int) or numero <= 0:
        errs.append(
            f"{name}.numero_cneb: debe ser el número de la competencia en el CNEB, mayor que 0"
        )
    elif file_name != competencia_file(numero):
        errs.append(
            f"{name}.numero_cneb: el archivo se llama {file_name!r} pero la competencia dice ser "
            f"la número {numero}; renómbralo a {competencia_file(numero)!r} o corrige el número"
        )
    if not comp.get("nombre"):
        errs.append(f"{name}.nombre: es obligatorio")
    capacidades = comp.get("capacidades") or []
    if not capacidades:
        errs.append(f"{name}.capacidades: la competencia debe tener al menos una capacidad")
    seen_cap: dict[int, str] = {}
    for i, cap in enumerate(capacidades):
        path = f"{name}.capacidades[{i}]"
        if not _strict(cap, {"numero", "nombre"}, path, errs):
            continue
        n = cap.get("numero")
        if not isinstance(n, int) or n < 1:
            errs.append(f"{path}.numero: debe ser mayor que 0")
            continue
        if n in seen_cap:
            errs.append(
                f"{path}.numero: la capacidad {n} está repetida (ya aparece en {seen_cap[n]})"
            )
            continue
        seen_cap[n] = path
        if not cap.get("nombre"):
            errs.append(f"{path}.nombre: es obligatorio")
    seen_level: dict[int, str] = {}
    for i, e in enumerate(comp.get("estandares") or []):
        path = f"{name}.estandares[{i}]"
        if not _strict(e, {"nivel", "texto"}, path, errs):
            continue
        nivel = e.get("nivel")
        if not isinstance(nivel, int) or not 1 <= nivel <= 8:
            errs.append(f"{path}.nivel: {nivel!r} no está entre 1 y 8")
            continue
        if nivel in seen_level:
            errs.append(
                f"{path}.nivel: el nivel {nivel} está repetido (ya aparece en {seen_level[nivel]})"
            )
            continue
        seen_level[nivel] = path
        if not e.get("texto"):
            errs.append(f"{path}.texto: es obligatorio")
    seen_orden: dict[str, str] = {}
    for i, d in enumerate(comp.get("desempenos") or []):
        path = f"{name}.desempenos[{i}]"
        if not _strict(d, {"grado", "orden", "texto", "capacidad_sugerida"}, path, errs):
            continue
        if d.get("grado") not in c.grado:
            errs.append(
                f"{path}.grado: {d.get('grado')!r} no es un grado del catálogo; los grados de "
                f"cneb.json son: {c.grade_list()}"
            )
        orden = d.get("orden")
        if not isinstance(orden, int) or orden < 1:
            errs.append(f"{path}.orden: debe ser mayor que 0")
        else:
            key = f"{d.get('grado')}|{orden}"
            if key in seen_orden:
                errs.append(
                    f"{path}.orden: el orden {orden} del grado {d.get('grado')!r} está repetido "
                    f"(ya aparece en {seen_orden[key]})"
                )
                continue
            seen_orden[key] = path
        if not d.get("texto"):
            errs.append(f"{path}.texto: es obligatorio")
        sug = d.get("capacidad_sugerida")
        if sug is not None and sug not in seen_cap:
            errs.append(
                f"{path}.capacidad_sugerida: {sug} no es una capacidad de la competencia {numero}"
            )
    return errs


def _check_areas(c: Catalog) -> list[str]:
    errs: list[str] = []
    seen_area: dict[str, str] = {}
    seen_code: dict[str, str] = {}
    for i, a in enumerate(c.areas):
        path = f"{AREAS_PATH}.areas[{i}]"
        if not _strict(a, {"codigo", "nombre", "niveles", "competencias"}, path, errs):
            continue
        if not a.get("codigo"):
            errs.append(f"{path}.codigo: es obligatorio")
            continue
        if a["codigo"] in seen_area:
            errs.append(
                f"{path}.codigo: el código de área {a['codigo']!r} está repetido (ya aparece en "
                f"{seen_area[a['codigo']]})"
            )
            continue
        seen_area[a["codigo"]] = path
        if not a.get("nombre"):
            errs.append(f"{path}.nombre: es obligatorio")
        if not a.get("niveles"):
            errs.append(f"{path}.niveles: el área debe declarar al menos un nivel")
        for j, n in enumerate(a.get("niveles") or []):
            if n not in _NIVELES:
                errs.append(
                    f"{path}.niveles[{j}]: {n!r} no es un nivel válido; usa inicial, primaria o "
                    "secundaria"
                )
        if not a.get("competencias"):
            errs.append(f"{path}.competencias: el área debe tener al menos una competencia")
        codes: set[str] = set()
        cap_codes: set[str] = set()
        for j, cc in enumerate(a.get("competencias") or []):
            cpath = f"{path}.competencias[{j}]"
            if not _strict(cc, {"codigo", "numero_cneb"}, cpath, errs):
                continue
            code = cc.get("codigo")
            if not code:
                errs.append(f"{cpath}.codigo: es obligatorio")
                continue
            if code in codes:
                errs.append(
                    f"{cpath}.codigo: el código de competencia {code!r} está repetido en el área "
                    f"{a['codigo']}"
                )
                continue
            codes.add(code)
            if code in seen_code:
                errs.append(
                    f"{cpath}.codigo: el código de competencia {code!r} ya está definido en "
                    f"{seen_code[code]}; un código no puede aparecer en dos áreas"
                )
                continue
            seen_code[code] = cpath
            comp = c.competencias.get(cc.get("numero_cneb"))
            if comp is None:
                errs.append(
                    f"{cpath}.numero_cneb: la competencia CNEB {cc.get('numero_cneb')} no tiene "
                    f"archivo en {COMPETENCIAS_DIR}"
                )
                continue
            c.numero_by_code[code] = cc["numero_cneb"]
            cap_codes.update(capability_code(code, cap["numero"]) for cap in comp["capacidades"])
        c.capability_codes_by_area[a["codigo"]] = cap_codes
        c.area[a["codigo"]] = a
    for i, t in enumerate(c.transversales):
        path = f"{AREAS_PATH}.transversales[{i}]"
        if not _strict(t, {"codigo", "numero_cneb"}, path, errs):
            continue
        if not t.get("codigo"):
            errs.append(f"{path}.codigo: es obligatorio")
            continue
        if t["codigo"] in seen_code:
            errs.append(
                f"{path}.codigo: el código de competencia {t['codigo']!r} ya está definido en "
                f"{seen_code[t['codigo']]}; un código no puede aparecer en dos áreas"
            )
            continue
        seen_code[t["codigo"]] = path
        if t.get("numero_cneb") not in c.competencias:
            errs.append(
                f"{path}.numero_cneb: la competencia CNEB {t.get('numero_cneb')} no tiene archivo "
                f"en {COMPETENCIAS_DIR}"
            )
            continue
        c.numero_by_code[t["codigo"]] = t["numero_cneb"]
        c.transversal[t["codigo"]] = t
    return errs
