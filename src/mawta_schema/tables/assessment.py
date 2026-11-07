"""Grading: scales, criteria, assessments, scores, achievement levels and conclusions."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Numeric,
    PrimaryKeyConstraint,
    SmallInteger,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID, ExcludeConstraint
from sqlalchemy.orm import Mapped, mapped_column

from mawta_schema.base import Base


class GradeScale(Base):
    __tablename__ = "grade_scales"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="grade_scales_pkey"),
        CheckConstraint(
            "((decimals >= 0) AND (decimals <= 4))", name="grade_scales_decimals_check"
        ),
        CheckConstraint(
            "(kind = ANY (ARRAY['ordinal'::text, 'numeric'::text, 'percentage'::text]))",
            name="grade_scales_kind_check",
        ),
        CheckConstraint("(max_value > min_value)", name="grade_scales_range_valid"),
        Index(
            "grade_scales_code_key",
            "code",
            unique=True,
            postgresql_where=text("(deleted_at IS NULL)"),
        ),
        {
            "comment": "Cómo expresa un colegio una nota. ordinal = MINEDU AD/A/B/C, numeric = vigesimal 0-20, percentage = 0-100. Toda escala se mapea al mismo eje normalizado 0-1."
        },
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), server_default=text("gen_random_uuid()")
    )
    code: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(
        Text,
        comment="Solo afecta la presentación. ordinal muestra el código del nivel, numeric muestra el valor, percentage muestra un porcentaje. Las tres se normalizan de forma idéntica.",
    )
    min_value: Mapped[Decimal] = mapped_column(
        Numeric(8, 4),
        comment="El valor más bajo que la escala puede expresar: 0 para vigesimal, y para una escala ordinal el piso numérico de su banda más baja.",
    )
    max_value: Mapped[Decimal] = mapped_column(Numeric(8, 4))
    decimals: Mapped[int] = mapped_column(
        SmallInteger,
        server_default=text("0"),
        comment="Precisión de presentación. Lo vigesimal normalmente se reporta como número entero aunque las scores en crudo sean decimales.",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GradeScaleLevel(Base):
    __tablename__ = "grade_scale_levels"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="grade_scale_levels_pkey"),
        ExcludeConstraint(
            ("scale_id", "="),
            (text("numrange(min_normalized, max_normalized, '[)'::text)"), "&&"),
            name="grade_scale_levels_no_gap_overlap",
            using="gist",
            where=text("(deleted_at IS NULL)"),
        ),
        ForeignKeyConstraint(["scale_id"], ["grade_scales.id"], name="grade_scale_levels_scale_fk"),
        CheckConstraint("(max_normalized > min_normalized)", name="grade_scale_levels_band_valid"),
        CheckConstraint(
            "((max_normalized >= (0)::numeric) AND (max_normalized <= (1)::numeric))",
            name="grade_scale_levels_max_normalized_check",
        ),
        CheckConstraint(
            "((min_normalized >= (0)::numeric) AND (min_normalized <= (1)::numeric))",
            name="grade_scale_levels_min_normalized_check",
        ),
        Index(
            "grade_scale_levels_lookup_idx",
            "scale_id",
            "min_normalized",
            "max_normalized",
            postgresql_where=text("(deleted_at IS NULL)"),
        ),
        Index(
            "grade_scale_levels_scale_code_key",
            "scale_id",
            "code",
            unique=True,
            postgresql_where=text("(deleted_at IS NULL)"),
        ),
        {
            "comment": 'Las bandas de una escala. Para AD/A/B/C estas son las notas reportadas; para una escala numérica son las bandas de color detrás del número. "Distribución de logros" agrupa por esta tabla, y "Logro esperado / A" lee label y code de una sola fila.'
        },
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), server_default=text("gen_random_uuid()")
    )
    scale_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    code: Mapped[str] = mapped_column(
        Text, comment='Lo que se imprime en la etiqueta: "AD", "A", "B", "C".'
    )
    label: Mapped[str] = mapped_column(
        Text,
        comment='Texto completo: "Logro destacado", "Logro esperado", "En proceso", "En inicio". Se muestran el label y el code juntos.',
    )
    short_label: Mapped[str | None] = mapped_column(Text)
    ordinal: Mapped[int] = mapped_column(SmallInteger)
    min_normalized: Mapped[Decimal] = mapped_column(
        Numeric(6, 5),
        comment="Límite inferior inclusivo en el eje 0-1. Las bandas son semiabiertas [min, max), así que un valor cae en exactamente una banda.",
    )
    max_normalized: Mapped[Decimal] = mapped_column(
        Numeric(6, 5),
        comment="Límite superior exclusivo, salvo en la banda más alta, que la búsqueda trata como cerrada para que un puntaje perfecto tenga un nivel.",
    )
    color_key: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EvaluationCriterion(Base):
    __tablename__ = "evaluation_criteria"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="evaluation_criteria_pkey"),
        ForeignKeyConstraint(
            ["competency_id", "capability_id"],
            ["capabilities.competency_id", "capabilities.id"],
            name="evaluation_criteria_capability_fk",
        ),
        ForeignKeyConstraint(
            ["competency_id"], ["competencies.id"], name="evaluation_criteria_competency_fk"
        ),
        ForeignKeyConstraint(
            ["experience_id"], ["learning_experiences.id"], name="evaluation_criteria_experience_fk"
        ),
        ForeignKeyConstraint(
            ["competency_id", "performance_id"],
            ["grade_level_performances.competency_id", "grade_level_performances.id"],
            name="evaluation_criteria_performance_fk",
        ),
        CheckConstraint(
            "(proposed_by = ANY (ARRAY['mawta'::text, 'teacher'::text]))",
            name="evaluation_criteria_proposed_by_check",
        ),
        Index(
            "evaluation_criteria_capability_idx",
            "capability_id",
            postgresql_where=text("(deleted_at IS NULL)"),
        ),
        Index(
            "evaluation_criteria_competency_idx",
            "competency_id",
            postgresql_where=text("(deleted_at IS NULL)"),
        ),
        Index(
            "evaluation_criteria_experience_idx",
            "experience_id",
            postgresql_where=text("((experience_id IS NOT NULL) AND (deleted_at IS NULL))"),
        ),
        Index(
            "evaluation_criteria_performance_idx",
            "performance_id",
            postgresql_where=text("((performance_id IS NOT NULL) AND (deleted_at IS NULL))"),
        ),
        {
            "comment": 'Un criterio de evaluación: el precisado propio del docente de un desempeño, ej. "Explica su punto de vista citando el texto" bajo la capacidad "Reflexiona y evalúa la forma, el contenido y contexto del texto". Esta es la capa que los docentes cargan en el sistema para evaluar una competencia.'
        },
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), server_default=text("gen_random_uuid()")
    )
    competency_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    capability_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        comment="DEPRECATED: el vínculo criterio ↔ capacidad vive en evaluation_criterion_capabilities, que permite varias capacidades por criterio. Esta columna se mantiene (nullable, no eliminada) para que el código actual siga corriendo mientras las pantallas nuevas la reemplazan; la migración copió su valor a la tabla de join.",
    )
    code: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(SmallInteger, server_default=text("0"))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    experience_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        comment="La experiencia a la que pertenece este criterio. Null para los criterios globales por competencia que ya existían: siguen siendo válidos y visibles en las pantallas actuales hasta que el flujo de planificación los reemplace.",
    )
    performance_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        comment="El desempeño de grado del que este criterio deriva (decisión 2 del flujo): un criterio es el precisado del docente de ese desempeño en la situación de la experiencia. Null cuando el docente lo escribió sin partir de un desempeño cargado. La FK compuesta (competency_id, performance_id) prueba que el desempeño es de la misma competencia del criterio.",
    )
    proposed_by: Mapped[str] = mapped_column(
        Text,
        server_default=text("'teacher'::text"),
        comment="Quién redactó el criterio: 'mawta' (propuesta del asistente) o 'teacher' (el docente). El default es 'teacher' para que los criterios existentes, migrados sin este dato, no aparezcan como propuestas de la máquina.",
    )
    accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        comment="Cuándo el docente aceptó o editó la propuesta. Null mientras la propuesta está pendiente: una propuesta de Mawta no es un criterio hasta que el docente la acepta o la edita.",
    )


class EvaluationCriterionCapability(Base):
    __tablename__ = "evaluation_criterion_capabilities"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="evaluation_criterion_capabilities_pkey"),
        UniqueConstraint(
            "criterion_id", "id", name="evaluation_criterion_capabilities_criterion_key"
        ),
        ForeignKeyConstraint(
            ["competency_id", "capability_id"],
            ["capabilities.competency_id", "capabilities.id"],
            name="evaluation_criterion_capabilities_capability_fk",
        ),
        ForeignKeyConstraint(
            ["criterion_id"],
            ["evaluation_criteria.id"],
            name="evaluation_criterion_capabilities_criterion_fk",
        ),
        Index(
            "evaluation_criterion_capabilities_capability_idx",
            "capability_id",
            postgresql_where=text("(deleted_at IS NULL)"),
        ),
        Index(
            "evaluation_criterion_capabilities_pair_key",
            "criterion_id",
            "capability_id",
            unique=True,
            postgresql_where=text("(deleted_at IS NULL)"),
        ),
        {
            "comment": "Qué capacidades mira un criterio de evaluación. Un criterio mira una o más capacidades de su competencia (N:M, decisión 2 del flujo): ser competente es usar las capacidades de forma combinada, así que un criterio puede mirar más de una. competency_id se desnormaliza del criterio para que la FK compuesta hacia capabilities pueda probar que la capacidad pertenece a la misma competencia."
        },
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), server_default=text("gen_random_uuid()")
    )
    criterion_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    competency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        comment="Desnormalizado desde el criterio. No es una fuente independiente de verdad: existe para que la FK compuesta (competency_id, capability_id) haga estructuralmente imposible vincular una capacidad de otra competencia.",
    )
    capability_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Assessment(Base):
    __tablename__ = "assessments"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="assessments_pkey"),
        ForeignKeyConstraint(["class_id"], ["classes.id"], name="assessments_class_fk"),
        ForeignKeyConstraint(["created_by_id"], ["teachers.id"], name="assessments_created_by_fk"),
        ForeignKeyConstraint(
            ["planned_evidence_id"],
            ["planned_evidences.id"],
            name="assessments_planned_evidence_fk",
        ),
        ForeignKeyConstraint(["session_id"], ["class_sessions.id"], name="assessments_session_fk"),
        ForeignKeyConstraint(["student_id"], ["students.id"], name="assessments_student_fk"),
        ForeignKeyConstraint(["term_id"], ["terms.id"], name="assessments_term_fk"),
        CheckConstraint(
            "((status = 'closed'::text) = (closed_at IS NOT NULL))",
            name="assessments_closed_consistent",
        ),
        CheckConstraint(
            "(kind = ANY (ARRAY['produccion'::text, 'actuacion'::text]))",
            name="assessments_kind_check",
        ),
        CheckConstraint("(max_score > (0)::numeric)", name="assessments_max_score_check"),
        CheckConstraint(
            "((value_scale = 'numeric'::text) = (max_score IS NOT NULL))",
            name="assessments_max_score_matches_scale",
        ),
        CheckConstraint(
            "((status = ANY (ARRAY['published'::text, 'closed'::text])) <= (published_at IS NOT NULL))",
            name="assessments_published_consistent",
        ),
        CheckConstraint(
            "(status = ANY (ARRAY['draft'::text, 'published'::text, 'closed'::text, 'cancelled'::text]))",
            name="assessments_status_check",
        ),
        CheckConstraint(
            "(value_scale = ANY (ARRAY['numeric'::text, 'ordinal'::text]))",
            name="assessments_value_scale_check",
        ),
        Index(
            "assessments_class_term_idx",
            "class_id",
            "term_id",
            "status",
            postgresql_where=text("(deleted_at IS NULL)"),
        ),
        Index(
            "assessments_due_idx",
            "due_at",
            postgresql_where=text("((status = 'published'::text) AND (deleted_at IS NULL))"),
        ),
        Index(
            "assessments_planned_evidence_key",
            "planned_evidence_id",
            unique=True,
            postgresql_where=text("((planned_evidence_id IS NOT NULL) AND (deleted_at IS NULL))"),
        ),
        Index(
            "assessments_session_idx",
            "session_id",
            postgresql_where=text("((session_id IS NOT NULL) AND (deleted_at IS NULL))"),
        ),
        Index(
            "assessments_student_idx",
            "class_id",
            "term_id",
            "student_id",
            postgresql_where=text("((student_id IS NOT NULL) AND (deleted_at IS NULL))"),
        ),
        {
            "comment": 'DATOS PERSONALES DE MENORES (académico, cuando student_id está definido). Una evidencia de una class: lo que los estudiantes producen o actúan y que el docente valora contra criterios de evaluación. Nace de una evidencia planificada (planned_evidence_id) o la crea el docente con "Añadir evidencia". Se valora en una sola escala (value_scale) y nunca lleva peso: informa el juicio del docente sobre el nivel de logro de la competencia y no lo calcula. Con student_id definido es evidencia de un solo estudiante, ej. una tarea de recuperación, y por eso la tabla se declara portadora de datos de menores.'
        },
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), server_default=text("gen_random_uuid()")
    )
    class_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    term_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        comment="El term al que pertenece esta evidencia. Nulable: una recuperación pedagógica o evaluación de subsanación suele ocurrir fuera del periodo lectivo regular, así que no tiene term que cerrar.",
    )
    session_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    student_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        comment="Null significa que la evidencia aplica a toda la class, que es el caso original y sigue siendo el más común. Si está definido, es evidencia solo para ese estudiante, ej. una tarea de recuperación dada a uno solo.",
    )
    kind: Mapped[str] = mapped_column(
        Text,
        server_default=text("'produccion'::text"),
        comment="Producción (algo que los estudiantes elaboran) o actuación (algo que hacen frente a otros): los dos tipos de evidencia que nombra la RVM 094-2020 (glosario p.9). Mismo vocabulario que planned_evidences.kind.",
    )
    value_scale: Mapped[str] = mapped_column(
        Text,
        server_default=text("'numeric'::text"),
        comment="Cómo se valora esta evidencia, y es una propiedad de la evidencia, no de la pantalla. 'numeric': una nota cruda sobre max_score (el máximo lo fija el docente), que la interfaz presenta como porcentaje. 'ordinal': un nivel AD/A/B/C sobre esa evidencia. Ninguno de los dos es un nivel de logro: el nivel de una competencia se afirma en competency_term_levels por un docente que ha leído todo el periodo, y nada puede derivarlo de estos valores.",
    )
    max_score: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 4),
        comment="El denominador sobre el que se mide cada score de esta evidencia, ej. 20 o 18. Solo aplica a value_scale = 'numeric'; null cuando es 'ordinal'.",
    )
    due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        comment="Fecha límite. Define qué evidencias cuentan como pendientes de valorar en el dashboard de la class.",
    )
    status: Mapped[str] = mapped_column(
        Text,
        server_default=text("'draft'::text"),
        comment="draft es invisible para el docente en la pantalla de valoración. Una evidencia debe publicarse antes de poder recibir scores.",
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    planned_evidence_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        comment="La evidencia planificada de la que esta assessment se materializó al planificar la experiencia. Null para la evidencia registrada a mano. A lo sumo una assessment viva por evidencia planificada (assessments_planned_evidence_key).",
    )


class AssessmentCriterion(Base):
    __tablename__ = "assessment_criteria"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="assessment_criteria_pkey"),
        UniqueConstraint("assessment_id", "criterion_id", name="assessment_criteria_key"),
        ForeignKeyConstraint(
            ["assessment_id"], ["assessments.id"], name="assessment_criteria_assessment_fk"
        ),
        ForeignKeyConstraint(
            ["criterion_id"], ["evaluation_criteria.id"], name="assessment_criteria_criterion_fk"
        ),
        Index("assessment_criteria_criterion_idx", "criterion_id"),
        {
            "comment": 'A qué criterios de evaluación habla una evidencia, ej. una "Tarea 1" etiquetada contra dos criterios de "Resuelve problemas de cantidad". Toda evidencia tiene al menos un criterio: es lo que la hace llegar a una competencia (el servidor lo exige al crearla).'
        },
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), server_default=text("gen_random_uuid()")
    )
    assessment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    criterion_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Score(Base):
    __tablename__ = "scores"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="scores_pkey"),
        ForeignKeyConstraint(["assessment_id"], ["assessments.id"], name="scores_assessment_fk"),
        ForeignKeyConstraint(["class_id"], ["classes.id"], name="scores_class_fk"),
        ForeignKeyConstraint(["recorded_by_id"], ["teachers.id"], name="scores_recorded_by_fk"),
        ForeignKeyConstraint(
            ["scale_level_id"], ["grade_scale_levels.id"], name="scores_scale_level_fk"
        ),
        ForeignKeyConstraint(["student_id"], ["students.id"], name="scores_student_fk"),
        ForeignKeyConstraint(["supersedes_id"], ["scores.id"], name="scores_supersedes_fk"),
        ForeignKeyConstraint(["term_id"], ["terms.id"], name="scores_term_fk"),
        CheckConstraint(
            "((max_value IS NULL) OR (max_value > (0)::numeric))", name="scores_max_value_positive"
        ),
        CheckConstraint(
            "((raw_value IS NULL) OR (scale_level_id IS NULL))", name="scores_single_value"
        ),
        CheckConstraint(
            "(source = ANY (ARRAY['manual'::text, 'bulk'::text, 'import'::text, 'voice'::text, 'auto'::text]))",
            name="scores_source_check",
        ),
        CheckConstraint(
            "(status = ANY (ARRAY['graded'::text, 'excused'::text, 'absent'::text, 'not_submitted'::text]))",
            name="scores_status_check",
        ),
        CheckConstraint(
            "((raw_value IS NULL) OR ((max_value IS NOT NULL) AND (raw_value >= (0)::numeric) AND (raw_value <= max_value)))",
            name="scores_value_in_range",
        ),
        CheckConstraint(
            "((status = 'graded'::text) = ((raw_value IS NOT NULL) OR (scale_level_id IS NOT NULL)))",
            name="scores_value_matches_status",
        ),
        Index(
            "scores_assessment_idx",
            "assessment_id",
            postgresql_where=text("((superseded_at IS NULL) AND (deleted_at IS NULL))"),
        ),
        Index(
            "scores_class_term_idx",
            "class_id",
            "term_id",
            postgresql_where=text("((superseded_at IS NULL) AND (deleted_at IS NULL))"),
        ),
        Index(
            "scores_live_key",
            "assessment_id",
            "student_id",
            unique=True,
            postgresql_where=text("((superseded_at IS NULL) AND (deleted_at IS NULL))"),
        ),
        Index(
            "scores_student_term_idx",
            "student_id",
            "term_id",
            postgresql_where=text("((superseded_at IS NULL) AND (deleted_at IS NULL))"),
        ),
        Index(
            "scores_supersedes_idx",
            "supersedes_id",
            postgresql_where=text("(supersedes_id IS NOT NULL)"),
        ),
        {
            "comment": "DATOS PERSONALES DE MENORES (académico). De solo inserción. La valoración de un estudiante en una evidencia: una nota cruda sobre el máximo (raw_value, max_value) o un nivel AD/A/B/C (scale_level_id), según value_scale de la evidencia, y nada derivado — sin porcentaje, sin peso. Corregir una score inserta una fila nueva que reemplaza a la anterior."
        },
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), server_default=text("gen_random_uuid()")
    )
    assessment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    student_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    class_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        comment="Desnormalizado desde la evidencia. Se mantiene por trigger; permite que los agregados por class se salten un join.",
    )
    term_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        comment="Desnormalizado desde la evidencia. Nulable: una score de recuperación o subsanación puede registrarse contra una evidencia sin term (ver assessments.term_id).",
    )
    status: Mapped[str] = mapped_column(
        Text,
        server_default=text("'graded'::text"),
        comment="graded lleva un valor. not_submitted, absent y excused no llevan ninguno: son información para el docente sobre por qué falta la valoración.",
    )
    raw_value: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 4),
        comment="El número que escribió el docente, sobre max_value, ej. 14 sobre 18. Solo cuando la evidencia es numeric y status = graded.",
    )
    max_value: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 4),
        comment="Copiado de la evidencia al momento de escribir y congelado, así que cambiar después el máximo de una evidencia no puede reinterpretar notas ya ingresadas.",
    )
    scale_level_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        comment="El nivel AD/A/B/C que el docente dio a esta evidencia, como fila de grade_scale_levels. Solo cuando la evidencia es ordinal y status = graded. No es el nivel de logro de la competencia.",
    )
    feedback: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text, server_default=text("'manual'::text"))
    recorded_by_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        comment="La fila que esta reemplaza tras una corrección. El enlace apunta solo hacia atrás: un superseded_by_id hacia adelante tendría que escribirse en el mismo momento que superseded_at.",
    )
    superseded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        comment="Se establece cuando una fila más nueva reemplaza a esta. Una fila con superseded_at null y deleted_at null es el valor vigente. Se escribe antes de insertar el reemplazo — ver scores_live_key.",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CompetencyTermLevel(Base):
    __tablename__ = "competency_term_levels"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="competency_term_levels_pkey"),
        ForeignKeyConstraint(["asserted_by_id"], ["teachers.id"], name="ctl_asserted_by_fk"),
        ForeignKeyConstraint(
            ["academic_year_id", "class_id"],
            ["classes.academic_year_id", "classes.id"],
            name="ctl_class_year_fk",
        ),
        ForeignKeyConstraint(["competency_id"], ["competencies.id"], name="ctl_competency_fk"),
        ForeignKeyConstraint(["scale_level_id"], ["grade_scale_levels.id"], name="ctl_level_fk"),
        ForeignKeyConstraint(["student_id"], ["students.id"], name="ctl_student_fk"),
        ForeignKeyConstraint(
            ["supersedes_id"], ["competency_term_levels.id"], name="ctl_supersedes_fk"
        ),
        ForeignKeyConstraint(
            ["academic_year_id", "term_id"],
            ["terms.academic_year_id", "terms.id"],
            name="ctl_term_year_fk",
        ),
        ForeignKeyConstraint(["academic_year_id"], ["academic_years.id"], name="ctl_year_fk"),
        Index(
            "ctl_class_term_idx",
            "class_id",
            "term_id",
            postgresql_where=text("((superseded_at IS NULL) AND (deleted_at IS NULL))"),
        ),
        Index(
            "ctl_recuperacion_key",
            "student_id",
            "competency_id",
            "academic_year_id",
            unique=True,
            postgresql_where=text(
                "((term_id IS NULL) AND (superseded_at IS NULL) AND (deleted_at IS NULL))"
            ),
        ),
        Index(
            "ctl_regular_key",
            "student_id",
            "competency_id",
            "term_id",
            unique=True,
            postgresql_where=text(
                "((term_id IS NOT NULL) AND (superseded_at IS NULL) AND (deleted_at IS NULL))"
            ),
        ),
        Index(
            "ctl_student_idx",
            "student_id",
            "term_id",
            postgresql_where=text("((superseded_at IS NULL) AND (deleted_at IS NULL))"),
        ),
        {
            "comment": "DATOS PERSONALES DE MENORES (académico, oficial). El nivel de logro de una competencia para un estudiante en un periodo — la fila que va a SIAGIE y, al cierre del año, decide la situación final. Escrito por el juicio de un docente sobre la evidencia del periodo (5.1.1.3 p.2-3), nunca por un cálculo. Una competencia no desarrollada ni evaluada explícitamente en el periodo simplemente no tiene fila (5.1.2.2 p.1) — la ausencia es significativa y no debe leerse como C."
        },
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), server_default=text("gen_random_uuid()")
    )
    student_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    competency_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    academic_year_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        comment="Copiado del academic_year_id de la class desde la que se afirmó el nivel. Existe para que ctl_recuperacion_key pueda acotar la unicidad de las filas sin term (recuperación) a un año, ya que term_id nulo no sirve por sí solo para eso, y para que ctl_term_year_fk/ctl_class_year_fk sean compuestas sobre esta columna — así una fila del año 2026 no puede apuntar a un term o class de otro año.",
    )
    term_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        comment="El periodo regular para el que se afirmó este nivel. Nulable: un nivel proveniente de recuperación pedagógica o evaluación de subsanación puede afirmarse sin un term regular detrás. ctl_regular_key cubre las filas con term; ctl_recuperacion_key cubre las filas sin term, acotadas por academic_year_id en su lugar — un índice único no puede comparar dos NULL como iguales, así que term_id solo no bastaría para dar la misma garantía a esas filas.",
    )
    class_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        comment="Desde qué class afirmó el docente, para trazabilidad y permisos. No forma parte de la identidad del registro: la norma conoce competencias y periodos, no classes, y una competencia obtiene exactamente un nivel por periodo.",
    )
    scale_level_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        comment="El nivel afirmado, como una fila de grade_scale_levels (AD/A/B/C en la escala ordinal MINEDU). El único valor que es oficial.",
    )
    asserted_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        comment="El docente que hizo el juicio. Nulable: una competencia transversal no está adscrita a un solo docente, así que su nivel puede afirmarse sin uno.",
    )
    asserted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    note: Mapped[str | None] = mapped_column(Text)
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    superseded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        comment="Se establece cuando una corrección reemplaza esta fila. Null significa vigente. Se escribe antes de insertar el reemplazo, ya que ctl_regular_key/ctl_recuperacion_key admiten solo una fila vigente por estudiante, competencia y term (o año, sin term).",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DescriptiveConclusion(Base):
    __tablename__ = "descriptive_conclusions"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="descriptive_conclusions_pkey"),
        ForeignKeyConstraint(["authored_by_id"], ["teachers.id"], name="dc_authored_by_fk"),
        ForeignKeyConstraint(["class_id"], ["classes.id"], name="dc_class_fk"),
        ForeignKeyConstraint(["competency_id"], ["competencies.id"], name="dc_competency_fk"),
        ForeignKeyConstraint(["generation_id"], ["agent_generations.id"], name="dc_generation_fk"),
        ForeignKeyConstraint(["student_id"], ["students.id"], name="dc_student_fk"),
        ForeignKeyConstraint(
            ["supersedes_id"], ["descriptive_conclusions.id"], name="dc_supersedes_fk"
        ),
        ForeignKeyConstraint(["term_id"], ["terms.id"], name="dc_term_fk"),
        ForeignKeyConstraint(["academic_year_id"], ["academic_years.id"], name="dc_year_fk"),
        CheckConstraint("(btrim(body) <> ''::text)", name="dc_body_not_blank"),
        CheckConstraint(
            "((deleted_at IS NOT NULL) OR (((char_length(body) >= 10) AND (char_length(body) <= 350)) AND (body !~ '[\\r\\n]'::text)))",
            name="dc_body_siagie",
        ),
        CheckConstraint(
            "(requirement = ANY (ARRAY['level_c'::text, 'level_b'::text, 'level_a'::text, 'cycle_i_mandatory'::text, 'consecutive_c'::text, 'inclusion_support'::text, 'optional'::text]))",
            name="descriptive_conclusions_requirement_check",
        ),
        CheckConstraint(
            "(status = ANY (ARRAY['draft'::text, 'final'::text]))",
            name="descriptive_conclusions_status_check",
        ),
        Index(
            "dc_recuperacion_key",
            "student_id",
            "competency_id",
            "academic_year_id",
            unique=True,
            postgresql_where=text(
                "((term_id IS NULL) AND (superseded_at IS NULL) AND (deleted_at IS NULL))"
            ),
        ),
        Index(
            "dc_regular_key",
            "student_id",
            "competency_id",
            "term_id",
            unique=True,
            postgresql_where=text(
                "((term_id IS NOT NULL) AND (superseded_at IS NULL) AND (deleted_at IS NULL))"
            ),
        ),
        Index(
            "dc_term_idx",
            "term_id",
            "class_id",
            postgresql_where=text("((superseded_at IS NULL) AND (deleted_at IS NULL))"),
        ),
        {
            "comment": "DATOS PERSONALES DE MENORES (académico, oficial). La conclusión descriptiva de una competencia en un periodo: \"juicio docente basado en evidencias […] Señala avances, dificultades y recomendaciones\" (094-2020, glosario). Toda conclusión debe llevar recomendaciones personalizadas dentro del propio body (\"En todos los casos, las conclusiones descriptivas deben incluir recomendaciones personalizadas orientadas al desarrollo de cada competencia\", 5.1.1.3 p.7) — no hay una columna aparte que lo afirme, porque nada puede verificar que un texto libre realmente contenga una recomendación; es responsabilidad del docente al redactar body, igual que siempre. Va a SIAGIE junto al nivel. Solo una fila 'final' satisface un requisito obligatorio; un 'draft' no desbloquea el cierre del periodo."
        },
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), server_default=text("gen_random_uuid()")
    )
    student_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    competency_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    academic_year_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        comment="Copiado del academic_year_id de la class desde la que se escribió la conclusión. Existe por la misma razón que en competency_term_levels: dc_recuperacion_key acota la unicidad de las filas sin term (recuperación) a un año, y dc_year_fk/dc_term_fk componen sobre esta columna para que una fila del año 2026 no apunte a un term de otro año.",
    )
    term_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        comment="El periodo regular de esta conclusión. Nulable por la misma razón que competency_term_levels.term_id: una conclusión escrita a partir de recuperación pedagógica o evaluación de subsanación puede no tener un term regular detrás — el caso que hace obligatoria una conclusión de un estudiante que sigue en C tras la recuperación, o de inclusion_support en todo periodo, incluido uno de recuperación.",
    )
    class_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    body: Mapped[str] = mapped_column(Text)
    requirement: Mapped[str] = mapped_column(
        Text,
        server_default=text("'optional'::text"),
        comment="Por qué existe esta conclusión, y su obligatoriedad varía por nivel educativo. 'level_c': la competencia está en C — obligatoria en Secundaria, Primaria e Inicial Ciclo II. 'level_b': obligatoria en Primaria e Inicial Ciclo II. 'level_a': obligatoria en Inicial Ciclo II. 'cycle_i_mandatory': toda competencia en Inicial Ciclo I lleva una, sin importar el nivel. 'consecutive_c': C en dos o más periodos consecutivos — obligatoria *y* el texto debe justificar por qué no hay progreso (5.1.1.3 p.3). 'inclusion_support': el estudiante enfrenta barreras educativas, así que es obligatoria en todo periodo y debe indicar los apoyos y ajustes razonables brindados (5.1.1.3 p.7). 'optional': el nivel supera el mínimo obligatorio para el nivel educativo del estudiante, escrita porque el docente lo consideró conveniente. La establece el servidor a partir del nivel vigente, el grado del estudiante, y el estudiante, nunca se confía en el cliente.",
    )
    status: Mapped[str] = mapped_column(Text, server_default=text("'draft'::text"))
    authored_by_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    authored_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    generation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        comment="La generación de conclusions de la que el docente partió al escribir este body, si partió de una. El texto sigue siendo del docente (authored_by_id); esto deja trazable qué leyó el agente para proponerlo.",
    )
    generated_from_voice_notes: Mapped[bool] = mapped_column(
        Boolean,
        server_default=text("false"),
        comment="Verdadero cuando la conclusión partió de una propuesta de Mawta (conclusions) que usó al menos una nota de voz. Lo fija el servidor al guardar, a partir de agent_generations.result.used_voice_note_ids; el cliente no lo envía. Es un registro interno, no se muestra al docente.",
    )


class CompetencyYearSnapshot(Base):
    __tablename__ = "competency_year_snapshots"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="competency_year_snapshots_pkey"),
        ForeignKeyConstraint(["closed_by_id"], ["teachers.id"], name="cys_closed_by_fk"),
        ForeignKeyConstraint(["competency_id"], ["competencies.id"], name="cys_competency_fk"),
        ForeignKeyConstraint(["scale_level_id"], ["grade_scale_levels.id"], name="cys_level_fk"),
        ForeignKeyConstraint(
            ["source_level_id"], ["competency_term_levels.id"], name="cys_source_level_fk"
        ),
        ForeignKeyConstraint(["source_term_id"], ["terms.id"], name="cys_source_term_fk"),
        ForeignKeyConstraint(["student_id"], ["students.id"], name="cys_student_fk"),
        ForeignKeyConstraint(["academic_year_id"], ["academic_years.id"], name="cys_year_fk"),
        Index(
            "cys_key",
            "student_id",
            "competency_id",
            "academic_year_id",
            unique=True,
            postgresql_where=text("(deleted_at IS NULL)"),
        ),
        {
            "comment": "DATOS PERSONALES DE MENORES (académico, oficial). El nivel de cierre de año, congelado, de una competencia, tomado del último periodo en que se trabajó (5.1.2.2 p.3). Inmutable una vez escrito: es a partir de esto que se emiten el Acta Oficial y el Certificado de Estudios."
        },
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), server_default=text("gen_random_uuid()")
    )
    student_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    competency_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    academic_year_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    scale_level_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    source_term_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        comment="El último periodo en que se trabajó esta competencia — de donde se copió el nivel. Nulable: la fila de competency_term_levels de origen puede no llevar term (un nivel afirmado a partir de evidencia de recuperación), en cuyo caso no hay periodo regular que registrar aquí.",
    )
    source_level_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        comment="La fila exacta de competency_term_levels copiada, para poder rastrear el snapshot hasta el docente que la afirmó.",
    )
    closed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    closed_by_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class YearFinalSituation(Base):
    __tablename__ = "year_final_situations"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="year_final_situations_pkey"),
        ForeignKeyConstraint(["closed_by_id"], ["teachers.id"], name="yfs_closed_by_fk"),
        ForeignKeyConstraint(["grade_level_id"], ["grade_levels.id"], name="yfs_grade_level_fk"),
        ForeignKeyConstraint(["student_id"], ["students.id"], name="yfs_student_fk"),
        ForeignKeyConstraint(["academic_year_id"], ["academic_years.id"], name="yfs_year_fk"),
        CheckConstraint(
            "(situation = ANY (ARRAY['PRO'::text, 'PER'::text, 'RR'::text]))",
            name="year_final_situations_situation_check",
        ),
        CheckConstraint(
            "(stage = ANY (ARRAY['year_end'::text, 'post_recuperacion'::text]))",
            name="year_final_situations_stage_check",
        ),
        CheckConstraint(
            "((stage <> 'post_recuperacion'::text) OR (situation = ANY (ARRAY['PRO'::text, 'PER'::text])))",
            name="yfs_post_recuperacion_situation_check",
        ),
        Index(
            "yfs_key",
            "student_id",
            "academic_year_id",
            "stage",
            unique=True,
            postgresql_where=text("(deleted_at IS NULL)"),
        ),
        {
            "comment": "DATOS PERSONALES DE MENORES (académico, oficial). La situación final que lleva el Acta Oficial: PRO (promovido), PER (permanece) o RR (requiere recuperación) — las siglas que la norma nombra en 5.1.2.1.c p.5. Inmutable una vez escrita."
        },
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), server_default=text("gen_random_uuid()")
    )
    student_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    academic_year_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    grade_level_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        comment='El grado en que estaba el estudiante, porque la regla misma depende de esto: 1.°, 3.° y 4.° promueven con "B en la mitad o más de cada área", mientras que 2.° y 5.° — los grados de fin de ciclo — requieren "A o AD en la mitad o más de tres áreas y B en el resto" (cuadro 5.1.3.A, 048-2024).',
    )
    situation: Mapped[str] = mapped_column(Text)
    stage: Mapped[str] = mapped_column(
        Text,
        server_default=text("'year_end'::text"),
        comment="'year_end': la situación al cierre del periodo lectivo, donde PRO/PER/RR son las tres posibles. 'post_recuperacion': recalculada tras el acompañamiento o evaluación de recuperación, que la norma trata como una determinación aparte que produce su propia acta (5.2.1.A p.4-6) — ahí solo PRO o PER son situaciones legales, nunca RR de nuevo, y yfs_post_recuperacion_situation_check lo hace cumplir.",
    )
    breakdown: Mapped[Any] = mapped_column(
        JSONB,
        server_default=text("'{}'::jsonb"),
        comment="Los conteos por área a partir de los cuales se tomó la decisión, capturados como JSON: qué competencias se consideraron, en qué nivel, y qué áreas cumplieron la condición.",
    )
    closed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    closed_by_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    document_ref: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CompetencyExemption(Base):
    __tablename__ = "competency_exemptions"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="competency_exemptions_pkey"),
        ForeignKeyConstraint(
            ["authorized_by_id"], ["teachers.id"], name="competency_exemptions_authorized_by_fk"
        ),
        ForeignKeyConstraint(
            ["competency_id"], ["competencies.id"], name="competency_exemptions_competency_fk"
        ),
        ForeignKeyConstraint(
            ["student_id"], ["students.id"], name="competency_exemptions_student_fk"
        ),
        ForeignKeyConstraint(
            ["academic_year_id"], ["academic_years.id"], name="competency_exemptions_year_fk"
        ),
        Index(
            "competency_exemptions_key",
            "student_id",
            "competency_id",
            "academic_year_id",
            unique=True,
            postgresql_where=text("(deleted_at IS NULL)"),
        ),
        {
            "comment": "DATOS PERSONALES DE MENORES (académico, oficial). Una exoneración autorizada por la UGEL de una competencia para un estudiante en un año escolar (RVM 094-2020: exoneraciones de competencias asociadas a las áreas curriculares, ej. Educación Religiosa, Educación Física). El cierre de año lee esto para excluir el área del conteo de PRO/PER/RR en vez de tratarla como no evaluada."
        },
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), server_default=text("gen_random_uuid()")
    )
    student_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    competency_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    academic_year_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    reason: Mapped[str] = mapped_column(
        Text,
        comment='Por qué se otorgó la exoneración, ej. "Objeción religiosa" o una excepción médica para Educación Física.',
    )
    document_ref: Mapped[str | None] = mapped_column(
        Text,
        comment="Referencia al documento de autorización de la UGEL, cuando el colegio conserva uno en archivo.",
    )
    authorized_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        comment="El miembro del personal que registró la exoneración en Mawta. No es la autoridad de la UGEL en sí — document_ref es donde se rastrea esa autorización.",
    )
    authorized_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
