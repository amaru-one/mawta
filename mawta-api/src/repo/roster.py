"""The canonical roster-as-of-date join."""

from datetime import date
from uuid import UUID

from psycopg import AsyncConnection

from db import fetch_all


async def roster_as_of(conn: AsyncConnection, class_id: UUID, d: date) -> list[UUID]:
    """The student ids belonging to a class's section on date d."""
    rows = await fetch_all(
        conn,
        """
        select sm.student_id
          from section_memberships sm
          join classes c on c.section_id = sm.section_id
         where c.id = %(class)s
           and sm.joined_on <= %(d)s
           and (sm.left_on is null or sm.left_on > %(d)s)
           and sm.deleted_at is null
        """,
        {"class": class_id, "d": d},
    )
    return [r["student_id"] for r in rows]
