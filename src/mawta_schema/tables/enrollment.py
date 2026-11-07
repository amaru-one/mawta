"""Sections and the students enrolled in them."""

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Index,
    PrimaryKeyConstraint,
    SmallInteger,
    Text,
    UniqueConstraint,
    literal_column,
    text,
)
from sqlalchemy.dialects.postgresql import UUID, ExcludeConstraint
from sqlalchemy.orm import Mapped, mapped_column

from mawta_schema.base import Base


class Section(Base):
    __tablename__ = "sections"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="sections_pkey"),
        UniqueConstraint(
            "academic_year_id", "grade_level_id", "id", name="sections_year_grade_key"
        ),
        UniqueConstraint("academic_year_id", "id", name="sections_year_key"),
        ForeignKeyConstraint(
            ["grade_level_id"], ["grade_levels.id"], name="sections_grade_level_fk"
        ),
        ForeignKeyConstraint(["tutor_teacher_id"], ["teachers.id"], name="sections_tutor_fk"),
        ForeignKeyConstraint(["academic_year_id"], ["academic_years.id"], name="sections_year_fk"),
        CheckConstraint("(capacity > 0)", name="sections_capacity_check"),
        CheckConstraint(
            "(shift = ANY (ARRAY['manana'::text, 'tarde'::text, 'noche'::text, 'completo'::text]))",
            name="sections_shift_check",
        ),
        CheckConstraint(
            "(status = ANY (ARRAY['active'::text, 'archived'::text]))", name="sections_status_check"
        ),
        Index(
            "sections_natural_key",
            "academic_year_id",
            "grade_level_id",
            "label",
            unique=True,
            postgresql_where=text("(deleted_at IS NULL)"),
        ),
        Index(
            "sections_tutor_idx", "tutor_teacher_id", postgresql_where=text("(deleted_at IS NULL)")
        ),
        {
            "comment": 'Un grupo de estudiantes que avanza junto en todas las asignaturas durante un año escolar, ej. "5to B". El roster: un estudiante pertenece a una section, y por lo tanto a cada class dictada a esa section.'
        },
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), server_default=text("gen_random_uuid()")
    )
    academic_year_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    grade_level_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    label: Mapped[str] = mapped_column(Text, comment='Solo la letra de la section, ej. "B".')
    name: Mapped[str] = mapped_column(
        Text,
        comment='Forma de presentación que combina grado y letra, ej. "5to B". Se almacena en vez de derivarse porque cada colegio usa su propio espaciado y abreviaturas.',
    )
    tutor_teacher_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        comment="Tutor de aula. Distinto del docente de la clase de Tutoría, que se programa por separado.",
    )
    shift: Mapped[str] = mapped_column(Text, server_default=text("'manana'::text"))
    capacity: Mapped[int | None] = mapped_column(SmallInteger)
    status: Mapped[str] = mapped_column(Text, server_default=text("'active'::text"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Student(Base):
    __tablename__ = "students"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="students_pkey"),
        CheckConstraint(
            "((document_type IS NULL) = (document_number IS NULL))", name="students_document_pair"
        ),
        CheckConstraint(
            "(document_type = ANY (ARRAY['DNI'::text, 'CE'::text, 'PAS'::text, 'PTP'::text, 'otro'::text]))",
            name="students_document_type_check",
        ),
        CheckConstraint(
            "((left_on IS NULL) OR (enrolled_on IS NULL) OR (left_on >= enrolled_on))",
            name="students_left_after_enrolled",
        ),
        CheckConstraint(
            "(sex = ANY (ARRAY['F'::text, 'M'::text, 'X'::text, 'unspecified'::text]))",
            name="students_sex_check",
        ),
        CheckConstraint("(siagie_code ~ '^[0-9]{14}$'::text)", name="students_siagie_code_check"),
        CheckConstraint(
            "(status = ANY (ARRAY['active'::text, 'withdrawn'::text, 'transferred'::text, 'graduated'::text]))",
            name="students_status_check",
        ),
        Index(
            "students_code_key",
            "student_code",
            unique=True,
            postgresql_where=text("((student_code IS NOT NULL) AND (deleted_at IS NULL))"),
        ),
        Index(
            "students_document_key",
            "document_type",
            "document_number",
            unique=True,
            postgresql_where=text("((document_number IS NOT NULL) AND (deleted_at IS NULL))"),
        ),
        # The name search box: its operator class is in postgresql_ops so Alembic can compare it.
        Index(
            "students_name_trgm_idx",
            literal_column(
                "((((COALESCE(given_name, ''::text) || ' '::text) || COALESCE(paternal_surname, ''::text)) || ' '::text) || COALESCE(maternal_surname, ''::text))"
            ).label("full_name"),
            postgresql_using="gin",
            postgresql_ops={"full_name": "gin_trgm_ops"},
        ),
        Index(
            "students_siagie_code_key",
            "siagie_code",
            unique=True,
            postgresql_where=text("((siagie_code IS NOT NULL) AND (deleted_at IS NULL))"),
        ),
        {
            "comment": "DATOS PERSONALES DE MENORES. Cada fila es un niño o niña. Contiene: nombres legales, fecha de nacimiento, sexo y documento nacional de identidad. Se procesa bajo la Ley 29733 (Perú) con consentimiento parental que conserva el colegio. Cada lectura debe registrarse en events (action='student.read')."
        },
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), server_default=text("gen_random_uuid()")
    )
    student_code: Mapped[str | None] = mapped_column(
        Text, comment="PII (menor): identificador. Código de matrícula interno del colegio."
    )
    siagie_code: Mapped[str | None] = mapped_column(
        Text,
        comment='PII (menor): identificador. El código SIAGIE de 14 dígitos, el identificador nacional de MINEDU para estudiantes, ej. "12345678920001". Nulable: no todos los estudiantes tienen uno asignado todavía. Único en el colegio.',
    )
    given_name: Mapped[str] = mapped_column(Text, comment="PII (menor): nombre.")
    paternal_surname: Mapped[str] = mapped_column(
        Text,
        comment="PII (menor): nombre. La convención peruana mantiene los dos apellidos por separado; concatenarlos pierde información.",
    )
    maternal_surname: Mapped[str | None] = mapped_column(Text, comment="PII (menor): nombre.")
    preferred_name: Mapped[str | None] = mapped_column(
        Text, comment="PII (menor): nombre. Cómo llama realmente el docente al estudiante."
    )
    birthdate: Mapped[date | None] = mapped_column(
        Date,
        comment="PII (menor): sensible. Está presente porque la edad determina tanto la ubicación curricular como el régimen de consentimiento; no se necesita para las pantallas principales de la aplicación.",
    )
    sex: Mapped[str | None] = mapped_column(Text, comment="PII (menor): sensible.")
    document_type: Mapped[str | None] = mapped_column(Text)
    document_number: Mapped[str | None] = mapped_column(
        Text,
        comment="PII (menor): identificador estatal. DNI o equivalente. La columna de mayor riesgo en el esquema.",
    )
    enrolled_on: Mapped[date | None] = mapped_column(Date)
    left_on: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(Text, server_default=text("'active'::text"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    inclusion_support: Mapped[bool] = mapped_column(
        Boolean,
        server_default=text("false"),
        comment="DATOS PERSONALES DE MENORES (sensible). True cuando el estudiante enfrenta barreras educativas y recibe apoyos educativos / ajustes razonables. Hace obligatoria una conclusión descriptiva en todo periodo sin importar el nivel alcanzado, y esa conclusión debe indicar los apoyos brindados (RVM 048-2024, 5.1.1.3 p.7 último párrafo). Deliberadamente es una bandera, no un diagnóstico: el esquema registra la obligación, no la condición.",
    )


class SectionMembership(Base):
    __tablename__ = "section_memberships"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="section_memberships_pkey"),
        ExcludeConstraint(
            ("student_id", "="),
            ("academic_year_id", "="),
            (text("daterange(joined_on, left_on, '[)'::text)"), "&&"),
            name="section_memberships_one_at_a_time",
            using="gist",
            where=text("(deleted_at IS NULL)"),
        ),
        ForeignKeyConstraint(
            ["section_id"], ["sections.id"], name="section_memberships_section_fk"
        ),
        ForeignKeyConstraint(
            ["student_id"], ["students.id"], name="section_memberships_student_fk"
        ),
        ForeignKeyConstraint(
            ["academic_year_id"], ["academic_years.id"], name="section_memberships_year_fk"
        ),
        CheckConstraint(
            "((status = 'active'::text) = (left_on IS NULL))",
            name="section_memberships_active_consistent",
        ),
        CheckConstraint(
            "((left_on IS NULL) OR (left_on >= joined_on))", name="section_memberships_range_valid"
        ),
        CheckConstraint(
            "(status = ANY (ARRAY['active'::text, 'withdrawn'::text, 'transferred'::text, 'promoted'::text]))",
            name="section_memberships_status_check",
        ),
        Index(
            "section_memberships_section_idx",
            "section_id",
            "joined_on",
            "left_on",
            postgresql_where=text("(deleted_at IS NULL)"),
        ),
        Index(
            "section_memberships_student_idx",
            "student_id",
            postgresql_where=text("(deleted_at IS NULL)"),
        ),
        {
            "comment": "DATOS PERSONALES DE MENORES (asociación). El roster temporal: qué estudiante estuvo en qué section, durante qué fechas dentro de un año escolar. El roster de una clase se deriva de aquí, así que los denominadores de asistencia siempre se evalúan a la fecha de la sesión y no a la fecha de hoy."
        },
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), server_default=text("gen_random_uuid()")
    )
    student_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    section_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    academic_year_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    joined_on: Mapped[date] = mapped_column(Date)
    left_on: Mapped[date | None] = mapped_column(
        Date,
        comment="Fecha de fin exclusiva. Null mientras el estudiante sigue en la section. Un estudiante que se va a mitad de bimestre conserva toda fila previa de asistencia y de score.",
    )
    status: Mapped[str] = mapped_column(Text, server_default=text("'active'::text"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
