"""What a class is taught as: subject, grade level, academic year (shared by terms and planning)."""

from uuid import UUID

from psycopg import AsyncConnection

from db import fetch_required


async def load_class_context(conn: AsyncConnection, class_id: UUID) -> dict:
    """subject_id, grade_level_id, year_id, grade_code, stage, cycle for a class."""
    return await fetch_required(
        conn,
        """
        select co.subject_id, co.grade_level_id, cl.academic_year_id as year_id,
               gl.code as grade_code, gl.stage, gl.cycle
          from classes cl
          join courses co on co.id = cl.course_id
          join grade_levels gl on gl.id = co.grade_level_id
         where cl.id = %s and cl.deleted_at is null
        """,
        (class_id,),
    )
