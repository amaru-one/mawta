"""Resolving the term a screen is about."""

from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, case, or_, select
from sqlalchemy.ext.asyncio import AsyncConnection

from db import fetch_one
from errors import AppError
from mawta_schema.tables import AcademicYear, Term
from repo.classctx import load_class_context


def _term_not_found() -> AppError:
    return AppError(404, "not_found", "no se encontró el periodo")


def _in_stage(stage: str | None) -> list[ColumnElement[bool]]:
    """A term with no stage applies to every stage."""
    return [] if stage is None else [or_(Term.stage.is_(None), Term.stage == stage)]


async def resolve_term(
    conn: AsyncConnection, class_id: UUID | None, term_id: UUID | None
) -> dict[str, Any]:
    """The term identified by term_id if it belongs to the class; with no term_id, the
    class's current term: the active term of the class's academic year and stage (a term
    with no stage applies to every stage).

    A stage with no active term is valid (between terms, end of year), so rather than
    failing it falls back to the latest closed term, and as a last resort the first
    planned one. class_id may be None for screens that belong to the teacher and not to a
    class (the profile): the scope is then the school's active academic year, any stage.
    Returns {id, starts_on, ends_on}.
    """
    year_id: UUID | None = None
    stage: str | None = None
    if class_id is not None:
        cc = await load_class_context(conn, class_id)
        year_id, stage = cc["year_id"], cc["stage"]

    columns = (Term.id, Term.starts_on, Term.ends_on)
    if term_id is not None:
        # An explicit term must belong to the class: same academic year, and a stage the
        # class takes. Anything else is "not found", not an empty screen.
        in_year = [] if year_id is None else [Term.academic_year_id == year_id]
        row = await fetch_one(
            conn,
            select(*columns).where(
                Term.id == term_id, Term.deleted_at.is_(None), *in_year, *_in_stage(stage)
            ),
        )
        if row is None:
            raise _term_not_found()
        return dict(row)

    if class_id is None:
        active = await fetch_one(
            conn,
            select(AcademicYear.id).where(
                AcademicYear.status == "active", AcademicYear.deleted_at.is_(None)
            ),
        )
        if active is None:
            raise _term_not_found()
        year_id = active["id"]

    row = await fetch_one(
        conn,
        select(*columns)
        .where(Term.academic_year_id == year_id, Term.deleted_at.is_(None), *_in_stage(stage))
        .order_by(
            case((Term.status == "active", 0), (Term.status == "planned", 2), else_=1),
            Term.stage.is_(None),
            case((Term.status == "planned", Term.starts_on)),
            Term.ends_on.desc(),
        )
        .limit(1),
    )
    if row is None:
        raise _term_not_found()
    return dict(row)
