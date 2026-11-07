"""The chat_api views as read-only Table objects, for SQLAlchemy Core queries.

They live in their own MetaData so Alembic never tries to create them as tables; the
views themselves are defined in mawta_schema.views.
"""

from sqlalchemy import Boolean, Column, Date, MetaData, SmallInteger, Table, Text
from sqlalchemy.dialects.postgresql import UUID

api_views = MetaData(schema="chat_api")

school = Table(
    "school",
    api_views,
    Column("id", UUID(as_uuid=True)),
    Column("name", Text),
    Column("city", Text),
    Column("region", Text),
    Column("timezone", Text),
)

sections = Table(
    "sections",
    api_views,
    Column("id", UUID(as_uuid=True)),
    Column("academic_year", SmallInteger),
    Column("academic_year_status", Text),
    Column("grade", Text),
    Column("grade_long", Text),
    Column("stage", Text),
    Column("section", Text),
    Column("name", Text),
    Column("shift", Text),
    Column("status", Text),
)

terms = Table(
    "terms",
    api_views,
    Column("id", UUID(as_uuid=True)),
    Column("academic_year", SmallInteger),
    Column("academic_year_status", Text),
    Column("stage", Text),
    Column("sequence", SmallInteger),
    Column("name", Text),
    Column("short_name", Text),
    Column("starts_on", Date),
    Column("ends_on", Date),
    Column("status", Text),
    Column("is_current", Boolean),
    Column("has_levels", Boolean),
)

classes = Table(
    "classes",
    api_views,
    Column("id", UUID(as_uuid=True)),
    Column("academic_year", SmallInteger),
    Column("academic_year_status", Text),
    Column("grade", Text),
    Column("grade_long", Text),
    Column("grade_ordinal", SmallInteger),
    Column("stage", Text),
    Column("section_id", UUID(as_uuid=True)),
    Column("section", Text),
    Column("section_name", Text),
    Column("shift", Text),
    Column("subject_code", Text),
    Column("subject_name", Text),
    Column("is_tutoria", Boolean),
    Column("teacher", Text),
    Column("tutor", Text),
)

students = Table(
    "students",
    api_views,
    Column("student_id", UUID(as_uuid=True)),
    Column("given_name", Text),
    Column("preferred_name", Text),
    Column("paternal_surname", Text),
    Column("maternal_surname", Text),
    Column("full_name", Text),
    Column("academic_year", SmallInteger),
    Column("academic_year_status", Text),
    Column("grade", Text),
    Column("grade_long", Text),
    Column("grade_ordinal", SmallInteger),
    Column("stage", Text),
    Column("section_id", UUID(as_uuid=True)),
    Column("section", Text),
    Column("section_name", Text),
    Column("joined_on", Date),
    Column("left_on", Date),
    Column("membership_status", Text),
)

competencies = Table(
    "competencies",
    api_views,
    Column("id", UUID(as_uuid=True)),
    Column("subject_code", Text),
    Column("subject_name", Text),
    Column("subject_order", SmallInteger),
    Column("code", Text),
    Column("name", Text),
    Column("sort_order", SmallInteger),
)

levels = Table(
    "levels",
    api_views,
    Column("id", UUID(as_uuid=True)),
    Column("student_id", UUID(as_uuid=True)),
    Column("full_name", Text),
    Column("paternal_surname", Text),
    Column("maternal_surname", Text),
    Column("academic_year", SmallInteger),
    Column("academic_year_status", Text),
    Column("grade", Text),
    Column("grade_long", Text),
    Column("grade_ordinal", SmallInteger),
    Column("stage", Text),
    Column("section_id", UUID(as_uuid=True)),
    Column("section", Text),
    Column("section_name", Text),
    Column("subject_code", Text),
    Column("subject_name", Text),
    Column("subject_order", SmallInteger),
    Column("competency_code", Text),
    Column("competency_name", Text),
    Column("competency_order", SmallInteger),
    Column("term_id", UUID(as_uuid=True)),
    Column("term_sequence", SmallInteger),
    Column("term_name", Text),
    Column("term_short_name", Text),
    Column("level", Text),
    Column("level_ordinal", SmallInteger),
)
