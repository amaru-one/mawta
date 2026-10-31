"""The blocks a tool shows the director (protocol v1). Each tool always returns the same kind
(D003): the model never chooses or builds a chart."""

from typing import Any

LEVELS = ("AD", "A", "B", "C")


def table(title: str, columns: list[str], rows: list[list[Any]], note: str) -> dict[str, Any]:
    return {"tipo": "tabla", "titulo": title, "columnas": columns, "filas": rows, "nota": note}


def stacked_bars(title: str, groups: list[tuple[str, list[int]]], note: str) -> dict[str, Any]:
    """One bar per group, split into AD/A/B/C counts (drawn at 100 %)."""
    return {
        "tipo": "barras_apiladas",
        "titulo": title,
        "categorias": list(LEVELS),
        "grupos": [{"etiqueta": label, "valores": values} for label, values in groups],
        "nota": note,
    }


def matrix(
    title: str, columns: list[str], rows: list[tuple[str, str, list[str | None]]], note: str
) -> dict[str, Any]:
    """Rows (grouped under a heading) × columns, one value per cell; None is an empty cell."""
    return {
        "tipo": "matriz",
        "titulo": title,
        "columnas": columns,
        "filas": [
            {"grupo": group, "etiqueta": label, "celdas": cells} for group, label, cells in rows
        ],
        "nota": note,
    }
