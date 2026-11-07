"""The school calendar: academic years, terms, grade levels and non-teaching days."""

import uuid
from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Index,
    PrimaryKeyConstraint,
    SmallInteger,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID, ExcludeConstraint
from sqlalchemy.orm import Mapped, mapped_column

from mawta_schema.base import Base


class AcademicYear(Base):
    __tablename__ = "academic_years"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="academic_years_pkey"),
        CheckConstraint("(ends_on > starts_on)", name="academic_years_range_valid"),
        CheckConstraint(
            "(status = ANY (ARRAY['planned'::text, 'active'::text, 'closed'::text]))",
            name="academic_years_status_check",
        ),
        CheckConstraint(
            "(term_structure = ANY (ARRAY['bimestre'::text, 'trimestre'::text, 'semestre'::text]))",
            name="academic_years_term_structure_check",
        ),
        CheckConstraint("((year >= 2000) AND (year <= 2100))", name="academic_years_year_check"),
        Index(
            "academic_years_year_key",
            "year",
            unique=True,
            postgresql_where=text("(deleted_at IS NULL)"),
        ),
        {
            "comment": "Un año escolar del colegio, ej. 2026. En Perú va aproximadamente de marzo a diciembre."
        },
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), server_default=text("gen_random_uuid()")
    )
    year: Mapped[int] = mapped_column(SmallInteger)
    name: Mapped[str] = mapped_column(Text)
    starts_on: Mapped[date] = mapped_column(Date)
    ends_on: Mapped[date] = mapped_column(Date)
    term_structure: Mapped[str] = mapped_column(
        Text,
        server_default=text("'bimestre'::text"),
        comment="Cómo se subdivide el año: bimestre, trimestre o semestre. Un colegio puede usar una estructura distinta de un año a otro.",
    )
    status: Mapped[str] = mapped_column(Text, server_default=text("'planned'::text"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Term(Base):
    __tablename__ = "terms"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="terms_pkey"),
        UniqueConstraint("academic_year_id", "id", name="terms_year_key"),
        ExcludeConstraint(
            ("academic_year_id", "="),
            (text("COALESCE(stage, ''::text)"), "="),
            (text("daterange(starts_on, ends_on, '[]'::text)"), "&&"),
            name="terms_no_overlap",
            using="gist",
            where=text("(deleted_at IS NULL)"),
        ),
        ForeignKeyConstraint(["closed_by_id"], ["teachers.id"], name="terms_closed_by_id_fkey"),
        ForeignKeyConstraint(["academic_year_id"], ["academic_years.id"], name="terms_year_fk"),
        CheckConstraint(
            "((status = ANY (ARRAY['closed'::text, 'archived'::text])) = (closed_at IS NOT NULL))",
            name="terms_closed_consistent",
        ),
        CheckConstraint("(ends_on > starts_on)", name="terms_range_valid"),
        CheckConstraint("((sequence >= 1) AND (sequence <= 6))", name="terms_sequence_check"),
        CheckConstraint(
            "(stage = ANY (ARRAY['inicial'::text, 'primaria'::text, 'secundaria'::text, 'otro'::text]))",
            name="terms_stage_check",
        ),
        CheckConstraint(
            "(status = ANY (ARRAY['planned'::text, 'active'::text, 'closed'::text, 'archived'::text]))",
            name="terms_status_check",
        ),
        Index(
            "terms_one_active_key",
            "academic_year_id",
            text("(COALESCE(stage, ''::text))"),
            unique=True,
            postgresql_where=text("((status = 'active'::text) AND (deleted_at IS NULL))"),
        ),
        Index(
            "terms_range_idx", "starts_on", "ends_on", postgresql_where=text("(deleted_at IS NULL)")
        ),
        Index(
            "terms_year_sequence_key",
            "academic_year_id",
            text("(COALESCE(stage, ''::text))"),
            "sequence",
            unique=True,
            postgresql_where=text("(deleted_at IS NULL)"),
        ),
        {
            "comment": 'Un bimestre, trimestre o semestre dentro de una fila de academic_years. name se muestra como ("Bimestre II"); acota a un solo term todo un panel de actividad.'
        },
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), server_default=text("gen_random_uuid()")
    )
    academic_year_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    stage: Mapped[str | None] = mapped_column(
        Text,
        comment="A qué nivel educativo aplica este term, para un colegio que usa estructuras de periodo distintas por nivel (ej. Primaria en trimestres, Secundaria en bimestres, en el mismo año escolar). Null significa que el term aplica a todos los niveles — el caso común de un colegio con un solo calendario.",
    )
    sequence: Mapped[int] = mapped_column(
        SmallInteger,
        comment="Posición ordinal dentro del año, acotada a (academic_year_id, stage). Bimestre II es sequence 2. Limitado a 6 para que un valor mal escrito no pueda crear un term fantasma.",
    )
    name: Mapped[str] = mapped_column(Text)
    short_name: Mapped[str | None] = mapped_column(Text)
    starts_on: Mapped[date] = mapped_column(Date)
    ends_on: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(Text, server_default=text("'planned'::text"))
    grades_due_on: Mapped[date | None] = mapped_column(
        Date,
        comment='Fecha límite para registrar notas. Impulsa los recordatorios de "notas pendientes".',
    )
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        comment="Cuándo se cerró el term. Un term cerrado rechaza nuevas scores, que es lo que evita que una nota ya reportada cambie después.",
    )
    closed_by_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GradeLevel(Base):
    __tablename__ = "grade_levels"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="grade_levels_pkey"),
        CheckConstraint(
            "(cycle = ANY (ARRAY['ciclo_i'::text, 'ciclo_ii'::text, 'ciclo_iii'::text, 'ciclo_iv'::text, 'ciclo_v'::text, 'ciclo_vi'::text, 'ciclo_vii'::text]))",
            name="grade_levels_cycle_check",
        ),
        CheckConstraint(
            "(stage = ANY (ARRAY['inicial'::text, 'primaria'::text, 'secundaria'::text, 'otro'::text]))",
            name="grade_levels_stage_check",
        ),
        Index(
            "grade_levels_code_key",
            "code",
            unique=True,
            postgresql_where=text("(deleted_at IS NULL)"),
        ),
        Index(
            "grade_levels_ordinal_key",
            "ordinal",
            unique=True,
            postgresql_where=text("(deleted_at IS NULL)"),
        ),
        {
            "comment": "Los grados tal como los nombra el colegio. Modelado como filas para que un colegio pueda usar 1ro-5to de secundaria, grados 1-11, o Year 7-11 sin cambiar el esquema."
        },
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), server_default=text("gen_random_uuid()")
    )
    code: Mapped[str] = mapped_column(Text)
    label: Mapped[str] = mapped_column(
        Text, comment='Forma corta usada dentro de un nombre de clase, ej. "5to" en "Inglés 5to B".'
    )
    long_label: Mapped[str] = mapped_column(
        Text, comment='Forma de encabezado de sección, ej. "5TO GRADO".'
    )
    stage: Mapped[str] = mapped_column(Text, server_default=text("'secundaria'::text"))
    cycle: Mapped[str | None] = mapped_column(
        Text,
        comment="Ciclo I o Ciclo II, con sentido solo cuando stage = 'inicial'. Ciclo I cubre 0-2 años, Ciclo II cubre 3-5 años; cada uno tiene su propia obligatoriedad de conclusión descriptiva.",
    )
    ordinal: Mapped[int] = mapped_column(
        SmallInteger,
        comment="Orden de clasificación para la lista de clases agrupadas. Distinto de code, que puede no ordenarse de forma natural.",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class NonTeachingDay(Base):
    __tablename__ = "non_teaching_days"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="non_teaching_days_pkey"),
        UniqueConstraint("academic_year_id", "id", name="non_teaching_days_year_key"),
        ForeignKeyConstraint(
            ["academic_year_id"], ["academic_years.id"], name="non_teaching_days_year_fk"
        ),
        CheckConstraint(
            "(kind = ANY (ARRAY['feriado'::text, 'vacaciones'::text, 'gestion'::text]))",
            name="non_teaching_days_kind_check",
        ),
        Index(
            "non_teaching_days_year_day_key",
            "academic_year_id",
            "day",
            unique=True,
            postgresql_where=text("(deleted_at IS NULL)"),
        ),
        Index(
            "non_teaching_days_year_idx",
            "academic_year_id",
            "day",
            postgresql_where=text("(deleted_at IS NULL)"),
        ),
        {
            "comment": "Los días sin clase de un año escolar: feriados, vacaciones y días de gestión. Se cargan por onboarding (el colegio los declara, la app no los inventa) y sirven para excluir del conteo de sesiones de una experiencia las fechas que no son clase. Un rango de vacaciones se carga como una fila por día: el conteo y la exclusión son por fecha, y un rango obligaría a un chequeo de solapamiento de rangos para algo que es, en el fondo, un conjunto de fechas."
        },
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), server_default=text("gen_random_uuid()")
    )
    academic_year_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    day: Mapped[date] = mapped_column(Date)
    kind: Mapped[str] = mapped_column(
        Text,
        comment="feriado: fecha cívica o feriado nacional/regional. vacaciones: día dentro de un periodo de vacaciones del año escolar. gestion: día de gestión pedagógica o administrativa (los colegios lo usan para reuniones y planificación, sin estudiantes).",
    )
    label: Mapped[str | None] = mapped_column(
        Text,
        comment='Nombre opcional para mostrar, ej. "San Pedro y San Pablo" o "Vacaciones de medio año". Null cuando el tipo basta.',
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
