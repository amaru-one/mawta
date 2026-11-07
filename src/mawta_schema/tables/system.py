"""Audit events, the job queue and the agents' generations."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Identity,
    Index,
    Integer,
    PrimaryKeyConstraint,
    SmallInteger,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from mawta_schema.base import Base


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (
        PrimaryKeyConstraint("id", "occurred_at", name="events_pkey"),
        CheckConstraint(
            "(actor_type = ANY (ARRAY['user'::text, 'system'::text, 'job'::text, 'model'::text, 'import'::text]))",
            name="events_actor_type_check",
        ),
        Index("events_action_time_idx", "action", text("occurred_at DESC")),
        Index("events_class_time_idx", "class_id", text("occurred_at DESC")),
        Index("events_entity_idx", "entity_type", "entity_id", text("occurred_at DESC")),
        Index("events_student_time_idx", "student_id", text("occurred_at DESC")),
        Index("events_time_idx", text("occurred_at DESC")),
        {
            "postgresql_partition_by": "RANGE (occurred_at)",
            "comment": "Registro de solo inserción de cada acción relevante, incluyendo cada lectura de un registro de estudiante. Particionado por mes e indexado para acceso como serie de tiempo porque es el corpus de entrenamiento para detección de riesgo y proyección de notas, no solo un registro de auditoría. Nunca se actualiza, nunca se elimina — los meses antiguos se desconectan (DETACH).",
        },
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), server_default=text("gen_random_uuid()")
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("now()"),
        comment="Cuándo ocurrió la acción, en UTC. También es la clave de partición, así que forma parte de la llave primaria.",
    )
    actor_type: Mapped[str] = mapped_column(Text, server_default=text("'user'::text"))
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        comment="La fila de users que actuó. Null para actores system y job. No es una FK: los events sobreviven a las filas que referencian, y un event nunca debe bloquearse ni propagarse en cascada por un cambio en el actor.",
    )
    actor_teacher_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    action: Mapped[str] = mapped_column(
        Text,
        comment="Verbo en forma entidad.verbo: student.read, score.recorded, session.started, attendance.marked, voice_note.saved. La columna más importante para el entrenamiento de modelos, así que es una taxonomía de texto libre en vez de un enum restringido que necesitaría una migración por cada verbo nuevo.",
    )
    entity_type: Mapped[str] = mapped_column(Text)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    student_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        comment='Sujeto desnormalizado de la acción. Presente para que "todo lo que le pasó a este estudiante" sea un solo recorrido de índice en vez de una búsqueda en jsonb, y para que una solicitud de acceso bajo la Ley 29733 pueda responderse directamente.',
    )
    class_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        comment="Contexto de class desnormalizado, para series de actividad por class sin desempaquetar payload.",
    )
    session_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    term_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    request_id: Mapped[str | None] = mapped_column(
        Text,
        comment="Correlaciona los events escritos durante una misma solicitud a la API, que es lo que convierte una lista de filas en una secuencia causal.",
    )
    payload: Mapped[Any] = mapped_column(
        JSONB,
        server_default=text("'{}'::jsonb"),
        comment="Detalle específico de la acción. Deliberadamente sin esquema: restringirlo convertiría agregar una acción en una migración.",
    )


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="jobs_pkey"),
        CheckConstraint("(attempts >= 0)", name="jobs_attempts_check"),
        CheckConstraint("(jsonb_typeof(errors) = 'array'::text)", name="jobs_errors_is_array"),
        CheckConstraint(
            "((status = ANY (ARRAY['completed'::text, 'cancelled'::text, 'discarded'::text])) = (finalized_at IS NOT NULL))",
            name="jobs_finalized_consistent",
        ),
        CheckConstraint("(max_attempts > 0)", name="jobs_max_attempts_check"),
        CheckConstraint("((priority >= 1) AND (priority <= 4))", name="jobs_priority_check"),
        CheckConstraint(
            "(status = ANY (ARRAY['available'::text, 'running'::text, 'retryable'::text, 'scheduled'::text, 'completed'::text, 'cancelled'::text, 'discarded'::text]))",
            name="jobs_status_check",
        ),
        Index(
            "jobs_claim_idx",
            "queue",
            "priority",
            "run_after",
            "id",
            postgresql_where=text(
                "(status = ANY (ARRAY['available'::text, 'retryable'::text, 'scheduled'::text]))"
            ),
        ),
        Index(
            "jobs_finalized_idx",
            "finalized_at",
            postgresql_where=text("(finalized_at IS NOT NULL)"),
        ),
        Index("jobs_kind_idx", "kind", text("created_at DESC")),
        Index(
            "jobs_unique_key_idx",
            "kind",
            "unique_key",
            unique=True,
            postgresql_where=text(
                "((unique_key IS NOT NULL) AND (status = ANY (ARRAY['available'::text, 'retryable'::text, 'scheduled'::text, 'running'::text])))"
            ),
        ),
        {
            "comment": "La cola de trabajo, en Postgres. La transcripción de notas de voz y las generaciones de los agentes pasan por aquí. Se reclama con SELECT ... FOR UPDATE SKIP LOCKED, que es la única razón por la que una cola en la base de datos primaria es viable a esta escala."
        },
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True))
    kind: Mapped[str] = mapped_column(
        Text,
        comment="Qué handler ejecuta el job. Los tipos vigentes son 'voice_note.transcribe' (transcripción de voz a texto en español para una nota grabada) y 'agent.generate' (una generación de los agentes de Mawta). Texto libre sin CHECK: las filas de tipos retirados fallan como 'unknown job kind' en vez de reescribirse.",
    )
    queue: Mapped[str] = mapped_column(Text, server_default=text("'default'::text"))
    priority: Mapped[int] = mapped_column(
        SmallInteger,
        server_default=text("1"),
        comment="El menor corre primero. La transcripción de una nota que el docente está viendo tiene prioridad sobre un trabajo de mantenimiento nocturno.",
    )
    payload: Mapped[Any] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    status: Mapped[str] = mapped_column(Text, server_default=text("'available'::text"))
    attempts: Mapped[int] = mapped_column(SmallInteger, server_default=text("0"))
    max_attempts: Mapped[int] = mapped_column(SmallInteger, server_default=text("20"))
    run_after: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("now()"),
        comment="El momento más temprano en que este job puede reclamarse. Sirve tanto para programación como para el backoff exponencial.",
    )
    attempted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempted_by: Mapped[str | None] = mapped_column(
        Text,
        comment="Identidad del worker que sostiene el lease actual, para diagnosticar un job atascado.",
    )
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    errors: Mapped[Any] = mapped_column(
        JSONB,
        server_default=text("'[]'::jsonb"),
        comment="Arreglo de solo inserción de registros de fallo, uno por intento. Se conserva completo porque un job que eventualmente tuvo éxito tras tres fallos de transcripción es en sí mismo una señal sobre la calidad del audio.",
    )
    tags: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'::text[]"))
    unique_key: Mapped[str | None] = mapped_column(
        Text,
        comment="Clave de deduplicación. Evita que una ráfaga de ediciones de score encole cuarenta recomputaciones de notas idénticas para el mismo estudiante.",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


class AgentGeneration(Base):
    __tablename__ = "agent_generations"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="agent_generations_pkey"),
        ForeignKeyConstraint(["class_id"], ["classes.id"], name="agent_generations_class_fk"),
        ForeignKeyConstraint(
            ["competency_id"], ["competencies.id"], name="agent_generations_competency_fk"
        ),
        ForeignKeyConstraint(
            ["experience_id"], ["learning_experiences.id"], name="agent_generations_experience_fk"
        ),
        ForeignKeyConstraint(
            ["requested_by"], ["teachers.id"], name="agent_generations_requested_by_fk"
        ),
        ForeignKeyConstraint(["student_id"], ["students.id"], name="agent_generations_student_fk"),
        ForeignKeyConstraint(["term_id"], ["terms.id"], name="agent_generations_term_fk"),
        ForeignKeyConstraint(
            ["voice_note_id"], ["voice_notes.id"], name="agent_generations_voice_note_fk"
        ),
        CheckConstraint(
            "(agent = ANY (ARRAY['planning'::text, 'redaction'::text, 'conclusions'::text]))",
            name="agent_generations_agent_check",
        ),
        CheckConstraint("(attempts >= 0)", name="agent_generations_attempts_check"),
        CheckConstraint(
            "(cache_read_tokens >= 0)", name="agent_generations_cache_read_tokens_check"
        ),
        CheckConstraint(
            "(cache_write_tokens >= 0)", name="agent_generations_cache_write_tokens_check"
        ),
        CheckConstraint(
            "((agent <> 'conclusions'::text) OR ((kind = 'conclusion'::text) AND (student_id IS NOT NULL) AND (competency_id IS NOT NULL) AND (term_id IS NOT NULL)))",
            name="agent_generations_conclusions_kind",
        ),
        CheckConstraint(
            "((status <> 'failed'::text) OR (error IS NOT NULL))",
            name="agent_generations_error_consistent",
        ),
        CheckConstraint(
            "((status = ANY (ARRAY['completed'::text, 'failed'::text])) = (finished_at IS NOT NULL))",
            name="agent_generations_finished_consistent",
        ),
        CheckConstraint("(input_tokens >= 0)", name="agent_generations_input_tokens_check"),
        CheckConstraint("(output_tokens >= 0)", name="agent_generations_output_tokens_check"),
        CheckConstraint(
            "((agent <> 'planning'::text) OR (kind = ANY (ARRAY['experience'::text, 'criteria'::text, 'evidences'::text, 'sessions'::text])))",
            name="agent_generations_planning_kind",
        ),
        CheckConstraint(
            "((agent <> 'redaction'::text) OR ((kind = 'voice_note'::text) AND (voice_note_id IS NOT NULL) AND (student_id IS NOT NULL)))",
            name="agent_generations_redaction_kind",
        ),
        CheckConstraint(
            "((status <> 'completed'::text) OR (result IS NOT NULL))",
            name="agent_generations_result_consistent",
        ),
        CheckConstraint(
            "(status = ANY (ARRAY['pending'::text, 'running'::text, 'completed'::text, 'failed'::text]))",
            name="agent_generations_status_check",
        ),
        Index("agent_generations_class_idx", "class_id", text("created_at DESC")),
        Index(
            "agent_generations_conclusion_scope_idx",
            "student_id",
            "competency_id",
            "term_id",
            text("created_at DESC"),
            postgresql_where=text("(agent = 'conclusions'::text)"),
        ),
        Index(
            "agent_generations_target_key",
            "target_key",
            unique=True,
            postgresql_where=text("(status = ANY (ARRAY['pending'::text, 'running'::text]))"),
        ),
        Index(
            "agent_generations_voice_note_idx",
            "voice_note_id",
            postgresql_where=text("(voice_note_id IS NOT NULL)"),
        ),
        {
            "comment": 'DATOS PERSONALES DE MENORES (vía redaction y conclusions). Un pedido a un agente de Mawta ("✦ Generar con Mawta") y su resultado. Los agentes son acotados: reciben datos curados de la base, responden en un formato fijo que el servidor valida, y lo que proponen queda pendiente hasta que el docente lo acepta o lo edita. planning nunca recibe datos de estudiantes ni sugiere niveles de logro. redaction recibe la transcripción de una nota de voz con los nombres de la sección, porque reconocer un nombre mal transcrito o un apodo exige ese contexto; devuelve fragmentos, nunca texto reescrito. conclusions recibe evidencias, el nivel afirmado por el docente y transcripciones ya barridas, con el estudiante seudonimizado como [ESTUDIANTE]; nunca sugiere ni discute el nivel.'
        },
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), server_default=text("gen_random_uuid()")
    )
    agent: Mapped[str] = mapped_column(
        Text,
        comment="Qué agente atiende el pedido: planning, redaction (barrido de nombres de una nota de voz) o conclusions (propuesta de conclusión descriptiva).",
    )
    kind: Mapped[str] = mapped_column(
        Text,
        comment="Qué genera, según el agente. planning: experience, criteria, evidences o sessions. redaction: voice_note. conclusions: conclusion.",
    )
    class_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    experience_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        comment="La experiencia sobre la que se genera. Null en kind = experience: la propuesta todavía no es una experiencia.",
    )
    requested_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        comment="El docente que pidió la generación. Solo para rastro: el acceso se decide por la clase, como en el resto de la planificación.",
    )
    target_key: Mapped[str] = mapped_column(
        Text,
        comment="Identifica el objetivo de la generación (ej. exp:<id>:criteria:<competencia>). Con agent_generations_target_key garantiza una sola generación en curso por objetivo.",
    )
    status: Mapped[str] = mapped_column(Text, server_default=text("'pending'::text"))
    input: Mapped[Any] = mapped_column(
        JSONB,
        server_default=text("'{}'::jsonb"),
        comment="Lo que pidió el docente. Solo ids y parámetros: nunca transcripciones ni nombres.",
    )
    result: Mapped[Any | None] = mapped_column(
        JSONB,
        comment="Lo que hizo una generación completada. planning: la propuesta o los ids insertados como pendientes. redaction: conteos y el estado de atribución resultante. conclusions: la propuesta (body, secciones con citas, avisos), que vive aquí hasta que el docente la guarda como conclusión.",
    )
    error: Mapped[str | None] = mapped_column(
        Text,
        comment="Mensaje para el docente, en español, cuando la generación falla. Se expone en la API.",
    )
    error_detail: Mapped[str | None] = mapped_column(
        Text, comment="Causa técnica del fallo, para soporte. Nunca se expone en la API."
    )
    model: Mapped[str | None] = mapped_column(Text)
    prompt_version: Mapped[str | None] = mapped_column(Text)
    input_tokens: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    output_tokens: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    cache_read_tokens: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    cache_write_tokens: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    attempts: Mapped[int] = mapped_column(SmallInteger, server_default=text("0"))
    deadline_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("(now() + '00:05:00'::interval)"),
        comment="Después de esta hora una generación sin terminar se da por fallida: el worker no la empieza y la API la muestra como failed. Cubre el caso de un worker que muere a mitad de camino.",
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    student_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        comment="El estudiante sobre el que trabaja una generación de redaction o conclusions. Null en planning.",
    )
    competency_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), comment="La competencia de una generación de conclusions."
    )
    term_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), comment="El periodo de una generación de conclusions."
    )
    voice_note_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), comment="La nota de voz que barre una generación de redaction."
    )
