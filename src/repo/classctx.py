"""What a class is taught as: subject, grade level, academic year (shared by terms and planning)."""

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection

from db import fetch_required
from mawta_schema.tables import Class, Course, GradeLevel


async def load_class_context(conn: AsyncConnection, class_id: UUID) -> dict[str, Any]:
    """subject_id, grade_level_id, year_id, grade_code, stage, cycle for a class."""
    row = await fetch_required(
        conn,
        select(
            Course.subject_id,
            Course.grade_level_id,
            Class.academic_year_id.label("year_id"),
            GradeLevel.code.label("grade_code"),
            GradeLevel.stage,
            GradeLevel.cycle,
        )
        .select_from(Class)
        .join(Course, Course.id == Class.course_id)
        .join(GradeLevel, GradeLevel.id == Course.grade_level_id)
        .where(Class.id == class_id, Class.deleted_at.is_(None)),
    )
    return dict(row)
