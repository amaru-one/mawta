"""The onboarding file: a whole school (colegio, año escolar, docentes, áreas, aulas con
estudiantes, clases, horario y las sesiones que ese horario produce) filled in by the onboarding
team. Keys are in Spanish because the people filling it in are;
entries point at each other by code (area "MAT", aula "1S-A", docente "jeffrey"), never by id.
The curriculum tree is not typed in the file: each área names a catalog area by codigo.
"""

import json
import types
import typing
from dataclasses import dataclass, field, fields
from typing import Any


@dataclass
class Colegio:
    nombre: str = ""
    razon_social: str = ""
    codigo_modular: str = ""
    tipo: str = ""
    ciudad: str = ""
    region: str = ""
    zona_horaria: str = ""


@dataclass
class DiaNoLectivo:
    """A day, or an inclusive range of days, without class: feriados, vacaciones and días de
    gestión. Either fecha is set (one day) or desde and hasta are (a range)."""

    fecha: str = ""
    desde: str = ""
    hasta: str = ""
    tipo: str = ""  # feriado | vacaciones | gestion
    nombre: str = ""


@dataclass
class Periodo:
    numero: int = 0
    nombre: str = ""
    abreviatura: str = ""
    inicio: str = ""
    fin: str = ""
    fecha_entrega_notas: str = ""


@dataclass
class AnioEscolar:
    anio: int = 0
    nombre: str = ""
    inicio: str = ""
    fin: str = ""
    estructura: str = ""
    periodos: list[Periodo] = field(default_factory=list)
    dias_no_lectivos: list[DiaNoLectivo] = field(default_factory=list)


@dataclass
class Docente:
    usuario: str = ""
    clave: str = ""
    email: str = ""
    nombres: str = ""
    apellidos: str = ""
    nombre_visible: str = ""
    cargo: str = ""
    codigo_empleado: str = ""
    fecha_ingreso: str = ""


@dataclass
class CriterioLegacy:
    """An evaluation criterion the school already uses, kept so seed_demo.sql and existing schools
    keep working. It points at a capability by code (<competency code>-CAP<numero>)."""

    codigo: str = ""
    descripcion: str = ""
    capacidad: str = ""


@dataclass
class Area:
    codigo: str = ""  # catalog area code, e.g. MAT
    nombre: str = ""  # how the school names the subject
    icono: str = ""
    es_tutoria: bool = False
    criterios_legacy: list[CriterioLegacy] = field(default_factory=list)


@dataclass
class Grado:
    """A grade as the school names it. grado_cneb names the catalog grade (e.g. "1S"), which sets
    grade_levels.stage and grade_levels.cycle and selects which performances are copied."""

    codigo: str = ""
    etiqueta: str = ""
    nombre_largo: str = ""
    nivel: str = ""
    orden: int = 0
    grado_cneb: str = ""


@dataclass
class Estudiante:
    codigo: str = ""
    codigo_siagie: str = ""
    nombres: str = ""
    apellido_paterno: str = ""
    apellido_materno: str = ""
    nombre_preferido: str = ""
    fecha_nacimiento: str = ""
    sexo: str = ""
    tipo_documento: str = ""
    numero_documento: str = ""
    fecha_matricula: str = ""
    apoyo_inclusion: bool = False


@dataclass
class Aula:
    grado: str = ""
    seccion: str = ""
    nombre: str = ""
    tutor: str = ""
    turno: str = ""
    capacidad: int = 0
    estudiantes: list[Estudiante] = field(default_factory=list)

    def key(self) -> str:
        """How a clase points at its aula: grado and sección joined, "1S-A"."""
        return f"{self.grado}-{self.seccion}"


@dataclass
class Franja:
    dia: str = ""
    inicio: str = ""
    fin: str = ""
    salon: str = ""


@dataclass
class Sesion:
    fecha: str = ""
    tema: str = ""


@dataclass
class Clase:
    nombre: str = ""
    codigo: str = ""
    area: str = ""
    aula: str = ""
    docente: str = ""
    horas_semanales: float = 0.0
    salon: str = ""
    horario: list[Franja] = field(default_factory=list)
    sesiones: list[Sesion] = field(default_factory=list)


@dataclass
class Spec:
    colegio: Colegio = field(default_factory=Colegio)
    anio_escolar: AnioEscolar = field(default_factory=AnioEscolar)
    docentes: list[Docente] = field(default_factory=list)
    areas: list[Area] = field(default_factory=list)
    competencias_transversales: list[str] = field(default_factory=list)
    grados: list[Grado] = field(default_factory=list)
    aulas: list[Aula] = field(default_factory=list)
    clases: list[Clase] = field(default_factory=list)


class DecodeError(Exception):
    pass


def _build(cls: type, data: Any, path: str) -> Any:
    """Build a dataclass from a JSON object, rejecting unknown keys and wrong types: a misspelled
    "apellido_paterrno" would otherwise load a student with no surname and nobody would notice
    until the report card."""
    if data is None:
        return cls()
    if not isinstance(data, dict):
        raise DecodeError(f"el campo {path!r} espera un objeto")
    hints = typing.get_type_hints(cls)
    known = {f.name for f in fields(cls)}
    for key in data:
        if key not in known:
            where = f"{path}." if path else ""
            raise DecodeError(f'campo desconocido "{where}{key}"; revisa el nombre de la clave')
    kwargs = {}
    for name, value in data.items():
        kwargs[name] = _coerce(hints[name], value, f"{path}.{name}" if path else name)
    return cls(**kwargs)


def _coerce(tp: Any, value: Any, path: str) -> Any:
    origin = typing.get_origin(tp)
    if value is None:
        return [] if origin is list else tp()
    if origin is list or origin is types.GenericAlias:
        (item,) = typing.get_args(tp)
        if not isinstance(value, list):
            raise DecodeError(f"el campo {path!r} espera una lista, no {_kind(value)}")
        return [_coerce(item, v, f"{path}[{i}]") for i, v in enumerate(value)]
    if tp is float and isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    if tp is int and isinstance(value, int) and not isinstance(value, bool):
        return value
    if tp in (str, bool) and isinstance(value, tp):
        return value
    if isinstance(tp, type) and hasattr(tp, "__dataclass_fields__"):
        return _build(tp, value, path)
    raise DecodeError(f"el campo {path!r} espera un valor de tipo {tp.__name__}, no {_kind(value)}")


def _kind(value: Any) -> str:
    return {
        str: "string",
        bool: "bool",
        int: "number",
        float: "number",
        list: "array",
        dict: "object",
    }.get(type(value), type(value).__name__)


def decode(text: str) -> Spec:
    """Read one onboarding file."""
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise DecodeError(
            f"JSON mal formado en la línea {exc.lineno}: {exc.msg} "
            "(revisa comas, comillas y llaves)"
        ) from None
    return _build(Spec, raw, "")
