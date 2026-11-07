"""The canonical roster-as-of-date join."""

from datetime import date
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncConnection

from mawta_schema.tables import Class, SectionMembership


async def roster_as_of(conn: AsyncConnection, class_id: UUID, d: date) -> list[UUID]:
    """The student ids belonging to a class's section on date d."""
    result = await conn.execute(
        select(SectionMembership.student_id)
        .join(Class, Class.section_id == SectionMembership.section_id)
        .where(
            Class.id == class_id,
            SectionMembership.joined_on <= d,
            or_(SectionMembership.left_on.is_(None), SectionMembership.left_on > d),
            SectionMembership.deleted_at.is_(None),
        )
    )
    return list(result.scalars())
