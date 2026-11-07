"""Voice notes, their redactions and teacher notifications."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    PrimaryKeyConstraint,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from mawta_schema.base import Base


class VoiceNote(Base):
    __tablename__ = "voice_notes"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="voice_notes_pkey"),
        ForeignKeyConstraint(["class_id"], ["classes.id"], name="voice_notes_class_fk"),
        ForeignKeyConstraint(["session_id"], ["class_sessions.id"], name="voice_notes_session_fk"),
        ForeignKeyConstraint(["student_id"], ["students.id"], name="voice_notes_student_fk"),
        ForeignKeyConstraint(["teacher_id"], ["teachers.id"], name="voice_notes_teacher_fk"),
        CheckConstraint(
            "(attribution_status = ANY (ARRAY['pending'::text, 'ok'::text, 'discarded'::text, 'confirmed'::text, 'reassigned'::text]))",
            name="voice_notes_attribution_status_check",
        ),
        CheckConstraint("(byte_size >= 0)", name="voice_notes_byte_size_check"),
        CheckConstraint(
            "((attribution_status = 'discarded'::text) = (discard_reason IS NOT NULL))",
            name="voice_notes_discard_consistent",
        ),
        CheckConstraint(
            "(discard_reason = ANY (ARRAY['mentions_other_student'::text, 'unreadable'::text]))",
            name="voice_notes_discard_reason_check",
        ),
        CheckConstraint("(duration_ms >= 0)", name="voice_notes_duration_ms_check"),
        CheckConstraint(
            "((attribution_status <> ALL (ARRAY['ok'::text, 'confirmed'::text, 'reassigned'::text])) OR (transcript_redacted IS NOT NULL))",
            name="voice_notes_redacted_consistent",
        ),
        CheckConstraint(
            "((transcription_status = 'completed'::text) <= (transcript IS NOT NULL))",
            name="voice_notes_transcript_consistent",
        ),
        CheckConstraint(
            "(transcription_status = ANY (ARRAY['pending'::text, 'queued'::text, 'processing'::text, 'completed'::text, 'failed'::text, 'skipped'::text]))",
            name="voice_notes_transcription_status_check",
        ),
        Index(
            "voice_notes_attribution_idx",
            "student_id",
            "attribution_status",
            postgresql_where=text("(deleted_at IS NULL)"),
        ),
        Index(
            "voice_notes_session_idx", "session_id", postgresql_where=text("(deleted_at IS NULL)")
        ),
        Index(
            "voice_notes_student_idx",
            "student_id",
            text("recorded_at DESC"),
            postgresql_where=text("(deleted_at IS NULL)"),
        ),
        Index(
            "voice_notes_teacher_idx",
            "teacher_id",
            "recorded_at",
            postgresql_where=text("(deleted_at IS NULL)"),
        ),
        Index(
            "voice_notes_transcription_idx",
            "transcription_status",
            postgresql_where=text(
                "((transcription_status = ANY (ARRAY['pending'::text, 'queued'::text, 'failed'::text])) AND (deleted_at IS NULL))"
            ),
        ),
        {
            "comment": "DATOS PERSONALES DE MENORES (conductual, vía la transcripción). Una nota hablada del docente sobre un estudiante, grabada durante una sesión. El audio es la voz del docente; la transcripción es habla libre sobre un menor, la columna de mayor riesgo en el esquema después de los datos de identificación propios de los estudiantes."
        },
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), server_default=text("gen_random_uuid()")
    )
    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    student_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    class_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    teacher_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    duration_ms: Mapped[int] = mapped_column(
        Integer,
        comment='Duración en milisegundos. Se muestra como "0:04" junto al control de reproducción.',
    )
    storage_key: Mapped[str | None] = mapped_column(
        Text,
        comment="Puntero heredado a disco, de antes de que el audio pasara a esta tabla. Se deja en su lugar para que las grabaciones previas a la migración en STORAGE_DIR sigan siendo reproducibles; las filas nuevas lo dejan null.",
    )
    audio: Mapped[bytes | None] = mapped_column(
        LargeBinary,
        comment="El audio grabado en sí. No es PII de un menor: es la voz del docente, grabada con su conocimiento mientras narra una observación — la parte sensible es el contenido hablado (ver la columna transcript), no la huella de voz. Sustituye a storage_key: se escribe aquí dentro de la misma transacción que la inserción de la fila, así que una nota y su audio nunca pueden desincronizarse como sí podría pasar entre una fila de BD y un archivo en disco.",
    )
    mime_type: Mapped[str | None] = mapped_column(Text)
    byte_size: Mapped[int | None] = mapped_column(BigInteger)
    transcription_status: Mapped[str] = mapped_column(Text, server_default=text("'pending'::text"))
    transcript: Mapped[str | None] = mapped_column(
        Text,
        comment="PII (menor): habla libre sobre un niño o niña. Nulable y purgable por separado del audio, para que un colegio pueda eliminar transcripciones y conservar las duraciones para analítica.",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    transcript_redacted: Mapped[str | None] = mapped_column(
        Text,
        comment="PII (menor): la transcripción después del barrido de nombres: el estudiante asignado es [ESTUDIANTE], los compañeros de la sección [COMPAÑERO_n] y cualquier otra persona [PERSONA]. Es lo único que lee el agente de conclusiones. Sigue siendo habla libre sobre un menor.",
    )
    attribution_status: Mapped[str] = mapped_column(
        Text,
        server_default=text("'pending'::text"),
        comment="Si la nota se puede usar como evidencia del estudiante asignado. pending: aún no se barre. ok: barrida y atribuida. discarded: el barrido indica que no es de este estudiante o no se entiende (ver discard_reason); queda fuera de las conclusiones sin preguntarle al docente. confirmed: el docente dijo que sí es de este estudiante. reassigned: el docente la movió a otro estudiante y se volvió a barrer.",
    )
    discard_reason: Mapped[str | None] = mapped_column(
        Text,
        comment="Por qué se descartó. mentions_other_student: nombra solo a compañeros de la sección y nunca al estudiante asignado. unreadable: la transcripción está vacía o no tiene sentido.",
    )
    attribution_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), comment="Cuándo se fijó attribution_status por última vez."
    )


class VoiceNoteRedaction(Base):
    __tablename__ = "voice_note_redactions"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="voice_note_redactions_pkey"),
        ForeignKeyConstraint(
            ["generation_id"], ["agent_generations.id"], name="voice_note_redactions_generation_fk"
        ),
        ForeignKeyConstraint(
            ["matched_student_id"], ["students.id"], name="voice_note_redactions_matched_student_fk"
        ),
        ForeignKeyConstraint(
            ["student_id"], ["students.id"], name="voice_note_redactions_student_fk"
        ),
        ForeignKeyConstraint(
            ["voice_note_id"], ["voice_notes.id"], name="voice_note_redactions_voice_note_fk"
        ),
        CheckConstraint(
            "((refers_to = 'classmate'::text) <= (matched_student_id IS NOT NULL))",
            name="voice_note_redactions_classmate_matched",
        ),
        CheckConstraint("(method = 'model'::text)", name="voice_note_redactions_method_check"),
        CheckConstraint("(end_offset > start_offset)", name="voice_note_redactions_offsets"),
        CheckConstraint(
            "(refers_to = ANY (ARRAY['assigned_student'::text, 'classmate'::text, 'other_person'::text]))",
            name="voice_note_redactions_refers_to_check",
        ),
        CheckConstraint("(start_offset >= 0)", name="voice_note_redactions_start_offset_check"),
        Index(
            "voice_note_redactions_note_idx",
            "voice_note_id",
            postgresql_where=text("(superseded_at IS NULL)"),
        ),
        {
            "comment": "DATOS PERSONALES DE MENORES (nombres dentro de notas de voz). Una fila por cada reemplazo que hizo el barrido en una transcripción: qué texto original, en qué posición, por qué marca se cambió y a quién se asoció. Existe para que una persona pueda revisar, con una consulta, cada decisión del barrido comparando transcript con transcript_redacted. El modelo solo señala fragmentos; el servidor calcula las posiciones y hace el reemplazo."
        },
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), server_default=text("gen_random_uuid()")
    )
    voice_note_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    generation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        comment="La generación de redaction que produjo la fila; de ahí salen el modelo y la versión del prompt.",
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        comment="El estudiante al que estaba asignada la nota cuando se barrió. Si la nota se reasigna, se vuelve a barrer y estas filas quedan superseded.",
    )
    original_text: Mapped[str] = mapped_column(
        Text,
        comment="PII (menor): el fragmento tal como aparece en la transcripción, ej. un nombre mal escrito por la transcripción o un apodo.",
    )
    start_offset: Mapped[int] = mapped_column(
        Integer,
        comment="Posición del fragmento en voice_notes.transcript, en caracteres (runas), desde 0.",
    )
    end_offset: Mapped[int] = mapped_column(Integer, comment="Posición final, exclusiva.")
    replacement: Mapped[str] = mapped_column(
        Text,
        comment="La marca que quedó en transcript_redacted: [ESTUDIANTE], [COMPAÑERO_n] o [PERSONA].",
    )
    refers_to: Mapped[str] = mapped_column(
        Text,
        comment="A quién se refiere el fragmento según el barrido: el estudiante asignado, un compañero de la sección, u otra persona (apodo no reconocible, familiar, otro docente).",
    )
    matched_student_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        comment="El compañero de la sección al que el barrido asoció el fragmento. Obligatorio cuando refers_to = classmate.",
    )
    method: Mapped[str] = mapped_column(
        Text,
        server_default=text("'model'::text"),
        comment="Cómo se detectó el fragmento. Por ahora solo model: el barrido lo hace un modelo con el contexto de la sección.",
    )
    superseded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        comment="Se fija cuando la nota se vuelve a barrer (ej. tras reasignarla). Null significa vigente.",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="notifications_pkey"),
        ForeignKeyConstraint(
            ["assessment_id"], ["assessments.id"], name="notifications_assessment_fk"
        ),
        ForeignKeyConstraint(["class_id"], ["classes.id"], name="notifications_class_fk"),
        ForeignKeyConstraint(
            ["recipient_teacher_id"], ["teachers.id"], name="notifications_recipient_fk"
        ),
        ForeignKeyConstraint(
            ["session_id"], ["class_sessions.id"], name="notifications_session_fk"
        ),
        ForeignKeyConstraint(["student_id"], ["students.id"], name="notifications_student_fk"),
        CheckConstraint(
            "(kind = ANY (ARRAY['alert'::text, 'reminder'::text]))", name="notifications_kind_check"
        ),
        CheckConstraint(
            "(severity = ANY (ARRAY['info'::text, 'low'::text, 'medium'::text, 'high'::text]))",
            name="notifications_severity_check",
        ),
        CheckConstraint(
            "(source = ANY (ARRAY['system'::text, 'rule'::text, 'model'::text, 'teacher'::text]))",
            name="notifications_source_check",
        ),
        Index(
            "notifications_feed_idx",
            "recipient_teacher_id",
            text("created_at DESC"),
            postgresql_where=text("(deleted_at IS NULL)"),
        ),
        Index(
            "notifications_student_idx",
            "student_id",
            postgresql_where=text("(student_id IS NOT NULL)"),
        ),
        Index(
            "notifications_unread_idx",
            "recipient_teacher_id",
            "kind",
            postgresql_where=text(
                "((read_at IS NULL) AND (dismissed_at IS NULL) AND (deleted_at IS NULL))"
            ),
        ),
        {
            "comment": 'DATOS PERSONALES DE MENORES (derivado). El feed de notificaciones. Los títulos y cuerpos de las alertas nombran estudiantes individuales y declaran inferencias sobre ellos, así que una fila de notification es dato de estudiante aunque esté dirigida a un docente. kind determina los filtros de Alertas/Recordatorios; read_at determina el punto de no leído y el estado atenuado "Leído". Cada fila lleva la entidad que la disparó, para que al tocarla se llegue al estudiante o la class en vez de a un callejón sin salida.'
        },
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), server_default=text("gen_random_uuid()")
    )
    recipient_teacher_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    kind: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(
        Text,
        comment="Subtipo legible por máquina dentro de kind. Sobre esto agrupa y filtra el cliente; title y body son para humanos.",
    )
    severity: Mapped[str] = mapped_column(Text, server_default=text("'info'::text"))
    title: Mapped[str] = mapped_column(Text)
    body: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[Any] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    student_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    class_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    session_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    assessment_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    source: Mapped[str] = mapped_column(Text, server_default=text("'system'::text"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
