"""Lesson planning: learning experiences, planned evidences and the session outline."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Numeric,
    PrimaryKeyConstraint,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID, ExcludeConstraint
from sqlalchemy.orm import Mapped, mapped_column

from mawta_schema.base import Base


class LearningExperience(Base):
    __tablename__ = "learning_experiences"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="learning_experiences_pkey"),
        UniqueConstraint("class_id", "id", name="learning_experiences_class_key"),
        UniqueConstraint("academic_year_id", "id", name="learning_experiences_year_key"),
        ExcludeConstraint(
            ("class_id", "="),
            (text("daterange(starts_on, ends_on, '[]'::text)"), "&&"),
            name="learning_experiences_no_overlap",
            using="gist",
            where=text("(deleted_at IS NULL)"),
        ),
        ForeignKeyConstraint(["class_id"], ["classes.id"], name="learning_experiences_class_fk"),
        ForeignKeyConstraint(
            ["academic_year_id", "term_id"],
            ["terms.academic_year_id", "terms.id"],
            name="learning_experiences_term_fk",
        ),
        ForeignKeyConstraint(
            ["academic_year_id"], ["academic_years.id"], name="learning_experiences_year_fk"
        ),
        CheckConstraint("(starts_on <= ends_on)", name="learning_experiences_range_valid"),
        CheckConstraint(
            "(status = ANY (ARRAY['borrador'::text, 'planificada'::text]))",
            name="learning_experiences_status_check",
        ),
        Index(
            "learning_experiences_class_range_idx",
            "class_id",
            "starts_on",
            "ends_on",
            postgresql_where=text("(deleted_at IS NULL)"),
        ),
        Index(
            "learning_experiences_term_idx",
            "term_id",
            postgresql_where=text("(deleted_at IS NULL)"),
        ),
        {
            "comment": "Una experiencia de aprendizaje: la unidad con la que un docente planifica un periodo para una class. Nace de la idea del docente (idea_text), se concreta en una situación (situation_text) y trabaja una o más competencias del área de la class (experience_competencies). Vive dentro de un term y sus fechas no pueden solaparse con las de otra experiencia de la misma class."
        },
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), server_default=text("gen_random_uuid()")
    )
    class_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    academic_year_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        comment="Copiado del term. No es una fuente independiente de verdad: existe para que learning_experiences_term_fk sea compuesta sobre él, lo que hace estructuralmente imposible que una experiencia apunte a un term de otro año escolar.",
    )
    term_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    title: Mapped[str] = mapped_column(
        Text,
        comment='Título con el que el docente reconoce la experiencia, ej. "La feria matemática del 5to B".',
    )
    idea_text: Mapped[str] = mapped_column(
        Text,
        comment='La idea original del docente, tal como la escribió en "Tengo una idea". Es la semilla de la experiencia y no se reescribe: la propuesta de Mawta se acepta o se edita aparte.',
    )
    situation_text: Mapped[str | None] = mapped_column(
        Text,
        comment="La situación significativa en la que la experiencia se desarrolla (CNEB). Null mientras aún no se ha redactado: la propuesta de Mawta puede llenarla, y el docente siempre decide.",
    )
    starts_on: Mapped[date] = mapped_column(
        Date,
        comment="Primer día de la experiencia, inclusive. Debe caer dentro del term (check_experience_inside_term) y no solaparse con otra experiencia de la misma class (learning_experiences_no_overlap).",
    )
    ends_on: Mapped[date] = mapped_column(
        Date, comment="Último día de la experiencia, inclusive. Misma regla que starts_on."
    )
    status: Mapped[str] = mapped_column(
        Text,
        server_default=text("'borrador'::text"),
        comment='borrador: la experiencia se está armando y cada paso ya quedó guardado. planificada: el docente la confirmó en "Revisar y guardar". El solapamiento de fechas se exige en ambos estados, así que un borrador también reserva sus semanas.',
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    context_text: Mapped[str | None] = mapped_column(
        Text,
        comment="Evento o contexto que escribe el docente. Única fuente permitida de un evento en lo que genera el agente; nulo = ningún evento.",
    )


class ExperienceCompetency(Base):
    __tablename__ = "experience_competencies"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="experience_competencies_pkey"),
        UniqueConstraint("competency_id", "id", name="experience_competencies_competency_key"),
        UniqueConstraint("experience_id", "id", name="experience_competencies_experience_key"),
        ForeignKeyConstraint(
            ["competency_id"], ["competencies.id"], name="experience_competencies_competency_fk"
        ),
        ForeignKeyConstraint(
            ["experience_id"],
            ["learning_experiences.id"],
            name="experience_competencies_experience_fk",
        ),
        Index(
            "experience_competencies_competency_idx",
            "competency_id",
            postgresql_where=text("(deleted_at IS NULL)"),
        ),
        Index(
            "experience_competencies_pair_key",
            "experience_id",
            "competency_id",
            unique=True,
            postgresql_where=text("(deleted_at IS NULL)"),
        ),
        {
            "comment": "Qué competencias trabaja una experiencia de aprendizaje. Una experiencia trabaja una o más competencias del área de la class (decisión 1 del flujo); esta tabla es ese vínculo N:M y es lo que hace computable el seguimiento entre periodos: qué competencia se trabajó en qué term es una consulta sobre esta tabla, sin tabla resumen."
        },
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), server_default=text("gen_random_uuid()")
    )
    experience_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    competency_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PlannedEvidence(Base):
    __tablename__ = "planned_evidences"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="planned_evidences_pkey"),
        UniqueConstraint("experience_id", "id", name="planned_evidences_experience_key"),
        ForeignKeyConstraint(
            ["experience_id"], ["learning_experiences.id"], name="planned_evidences_experience_fk"
        ),
        ForeignKeyConstraint(
            ["experience_id", "session_entry_id"],
            ["session_outline_entries.experience_id", "session_outline_entries.id"],
            name="planned_evidences_session_entry_fk",
            use_alter=True,
        ),
        CheckConstraint(
            "(kind = ANY (ARRAY['produccion'::text, 'actuacion'::text]))",
            name="planned_evidences_kind_check",
        ),
        CheckConstraint("(max_score > (0)::numeric)", name="planned_evidences_max_score_check"),
        CheckConstraint(
            "((value_scale = 'numeric'::text) = (max_score IS NOT NULL))",
            name="planned_evidences_max_score_matches_scale",
        ),
        CheckConstraint(
            "(proposed_by = ANY (ARRAY['mawta'::text, 'teacher'::text]))",
            name="planned_evidences_proposed_by_check",
        ),
        CheckConstraint(
            "(value_scale = ANY (ARRAY['numeric'::text, 'ordinal'::text]))",
            name="planned_evidences_value_scale_check",
        ),
        Index(
            "planned_evidences_experience_idx",
            "experience_id",
            postgresql_where=text("(deleted_at IS NULL)"),
        ),
        {
            "comment": "Una evidencia planificada dentro de una experiencia: qué se va a observar (name), de qué tipo (kind) y contra qué criterios (planned_evidence_criteria). Es una PROMESA, no la evidencia real: la evidencia valorable es la assessment en la que se materializa al planificar la experiencia (assessments.planned_evidence_id)."
        },
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), server_default=text("gen_random_uuid()")
    )
    experience_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    name: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(
        Text,
        comment='Los dos tipos que nombra la norma: "Evidencias. Producciones y/o actuaciones realizadas por los estudiantes" (RVM 094-2020, glosario p.9). produccion: algo que los estudiantes elaboran (maqueta, informe, portafolio, una prueba escrita). actuacion: algo que hacen frente a otros (exposición, debate, demostración). Es el mismo vocabulario que assessments.kind, así que la evidencia planificada se materializa con su tipo sin traducirlo.',
    )
    value_scale: Mapped[str] = mapped_column(
        Text,
        server_default=text("'numeric'::text"),
        comment="Cómo se valorará esta evidencia cuando se materialice como assessment: numeric (nota sobre max_score) u ordinal (AD/A/B/C). Se elige al planificar, porque los criterios y la tarea se comunican a los estudiantes con anticipación.",
    )
    max_score: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 4),
        server_default=text("20"),
        comment="El máximo de la nota cuando value_scale = numeric (por defecto 20). Null cuando es ordinal.",
    )
    session_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        comment="La entrada del esquema de sesiones donde se planea recoger esta evidencia. Null cuando aún no se ha ubicado en una sesión. La FK es compuesta (experience_id, session_entry_id), así que la evidencia no puede ubicarse en una sesión de otra experiencia.",
    )
    proposed_by: Mapped[str] = mapped_column(
        Text,
        server_default=text("'teacher'::text"),
        comment="Quién propuso la evidencia: 'mawta' (el asistente) o 'teacher' (el docente). El default es 'teacher'.",
    )
    accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        comment="Cuándo el docente aceptó o editó la propuesta. Null mientras está pendiente.",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SessionOutlineEntry(Base):
    __tablename__ = "session_outline_entries"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="session_outline_entries_pkey"),
        UniqueConstraint("experience_id", "id", name="session_outline_entries_experience_key"),
        ForeignKeyConstraint(
            ["experience_id", "planned_evidence_id"],
            ["planned_evidences.experience_id", "planned_evidences.id"],
            name="session_outline_entries_evidence_fk",
        ),
        ForeignKeyConstraint(
            ["experience_id"],
            ["learning_experiences.id"],
            name="session_outline_entries_experience_fk",
        ),
        CheckConstraint(
            "(proposed_by = ANY (ARRAY['mawta'::text, 'teacher'::text]))",
            name="session_outline_entries_proposed_by_check",
        ),
        Index(
            "session_outline_entries_date_key",
            "experience_id",
            "class_date",
            unique=True,
            postgresql_where=text("(deleted_at IS NULL)"),
        ),
        Index(
            "session_outline_entries_evidence_idx",
            "planned_evidence_id",
            postgresql_where=text("((planned_evidence_id IS NOT NULL) AND (deleted_at IS NULL))"),
        ),
        {
            "comment": "El esquema de sesiones de una experiencia: una entrada por fecha de clase, con un título y una línea de temas. Es deliberadamente ligero: no reemplaza a class_sessions (que son las sesiones reales con asistencia y audio) sino que planifica qué se hará en cada fecha. Las fechas sin entrada quedan permitidas: el esquema no tiene que cubrir todo."
        },
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), server_default=text("gen_random_uuid()")
    )
    experience_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    class_date: Mapped[date] = mapped_column(
        Date,
        comment="La fecha de clase. Debe caer dentro del rango de la experiencia (check_session_entry_date): una entrada fuera del rango es rechazada. La unicidad session_outline_entries_date_key es por fecha y no por franja horaria porque un bloque doble es una sola sesión (decisión 15 del flujo).",
    )
    title: Mapped[str] = mapped_column(
        Text, comment='Título de la sesión, ej. "Lanzamiento de la situación".'
    )
    topics: Mapped[str | None] = mapped_column(
        Text, comment="Línea de temas, texto libre. Null cuando aún no se ha redactado."
    )
    planned_evidence_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        comment="La evidencia planificada que se recogerá en esta sesión, si ya se decidió. La FK es compuesta (experience_id, planned_evidence_id), así que no puede apuntar a una evidencia de otra experiencia.",
    )
    proposed_by: Mapped[str] = mapped_column(
        Text,
        server_default=text("'teacher'::text"),
        comment="Quién propuso la entrada: 'mawta' (el asistente) o 'teacher' (el docente). El default es 'teacher'.",
    )
    accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        comment="Cuándo el docente aceptó o editó la propuesta. Null mientras está pendiente.",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PlannedEvidenceCriterion(Base):
    __tablename__ = "planned_evidence_criteria"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="planned_evidence_criteria_pkey"),
        UniqueConstraint("criterion_id", "id", name="planned_evidence_criteria_criterion_key"),
        UniqueConstraint("evidence_id", "id", name="planned_evidence_criteria_evidence_key"),
        ForeignKeyConstraint(
            ["criterion_id"],
            ["evaluation_criteria.id"],
            name="planned_evidence_criteria_criterion_fk",
        ),
        ForeignKeyConstraint(
            ["evidence_id"], ["planned_evidences.id"], name="planned_evidence_criteria_evidence_fk"
        ),
        Index(
            "planned_evidence_criteria_criterion_idx",
            "criterion_id",
            postgresql_where=text("(deleted_at IS NULL)"),
        ),
        Index(
            "planned_evidence_criteria_pair_key",
            "evidence_id",
            "criterion_id",
            unique=True,
            postgresql_where=text("(deleted_at IS NULL)"),
        ),
        {
            "comment": "Qué criterios observa una evidencia planificada. Los criterios pueden venir de competencias distintas de la misma experiencia: una misma evidencia puede observar varias competencias (decisión 11 del flujo). El requisito de que el criterio pertenezca a la misma experiencia se exige por trigger: la FK compuesta hacia evaluation_criteria no puede ver experience_id."
        },
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), server_default=text("gen_random_uuid()")
    )
    evidence_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    criterion_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
