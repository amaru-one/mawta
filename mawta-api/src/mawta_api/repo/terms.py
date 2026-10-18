"""Resolving the term a screen is about."""

from uuid import UUID

from psycopg import AsyncConnection

from mawta_api.db import fetch_one
from mawta_api.errors import AppError
from mawta_api.repo.classctx import load_class_context


def _term_not_found() -> AppError:
    return AppError(404, "not_found", "no se encontró el periodo")


async def resolve_term(conn: AsyncConnection, class_id: UUID | None, term_id: UUID | None) -> dict:
    """The term identified by term_id if it belongs to the class; with no term_id, the
    class's current term: the active term of the class's academic year and stage (a term
    with no stage applies to every stage).

    A stage with no active term is valid (between terms, end of year), so rather than
    failing it falls back to the latest closed term, and as a last resort the first
    planned one. class_id may be None for screens that belong to the teacher and not to a
    class (the profile): the scope is then the tenant's active academic year, any stage.
    Returns {id, starts_on, ends_on}.
    """
    year_id: UUID | None = None
    stage: str | None = None
    if class_id is not None:
        cc = await load_class_context(conn, class_id)
        year_id, stage = cc["year_id"], cc["stage"]

    if term_id is not None:
        # An explicit term must belong to the class: same academic year, and a stage the
        # class takes. Anything else is "not found", not an empty screen.
        row = await fetch_one(
            conn,
            """
            select id, starts_on, ends_on from terms
             where id = %(term)s and deleted_at is null
               and (%(year)s::uuid is null or academic_year_id = %(year)s::uuid)
               and (%(stage)s::text is null or stage is null or stage = %(stage)s::text)
            """,
            {"term": term_id, "year": year_id, "stage": stage},
        )
        if row is None:
            raise _term_not_found()
        return row

    if class_id is None:
        active = await fetch_one(
            conn, "select id from academic_years where status = 'active' and deleted_at is null"
        )
        if active is None:
            raise _term_not_found()
        year_id = active["id"]

    row = await fetch_one(
        conn,
        """
        select id, starts_on, ends_on
          from terms
         where academic_year_id = %(year)s::uuid and deleted_at is null
           and (%(stage)s::text is null or stage is null or stage = %(stage)s::text)
         order by case status when 'active' then 0 when 'planned' then 2 else 1 end,
                  stage is null,
                  case when status = 'planned' then starts_on end,
                  ends_on desc
         limit 1
        """,
        {"year": year_id, "stage": stage},
    )
    if row is None:
        raise _term_not_found()
    return row
