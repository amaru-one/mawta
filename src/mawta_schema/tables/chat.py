"""The director chat's own tables (schema chat), private to each director through RLS."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    PrimaryKeyConstraint,
    SmallInteger,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from mawta_schema.base import Base


class ChatThread(Base):
    __tablename__ = "threads"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="threads_pkey"),
        ForeignKeyConstraint(["user_id"], ["users.id"], name="threads_user_id_fkey"),
        CheckConstraint(
            "((char_length(title) >= 1) AND (char_length(title) <= 200))",
            name="threads_title_check",
        ),
        Index(
            "threads_user_idx",
            "user_id",
            text("updated_at DESC"),
            postgresql_where=text("(deleted_at IS NULL)"),
        ),
        {
            "schema": "chat",
            "comment": "Un chat del director. Un director tiene varios; cada uno empieza con contexto limpio. RLS por colegio y, además, una política restrictiva por usuario: un director solo ve sus propios chats.",
        },
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    title: Mapped[str] = mapped_column(
        Text,
        server_default=text("'Nuevo chat'::text"),
        comment="PII (adulto): texto libre. Lo genera el chat a partir de la primera pregunta (ya seudonimizada) o lo escribe el director al renombrar.",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ChatMessage(Base):
    __tablename__ = "messages"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="messages_pkey"),
        ForeignKeyConstraint(
            ["thread_id"], ["chat.threads.id"], name="messages_thread_fk", ondelete="CASCADE"
        ),
        ForeignKeyConstraint(["user_id"], ["users.id"], name="messages_user_id_fkey"),
        CheckConstraint(
            "(author = ANY (ARRAY['director'::text, 'mawta'::text]))", name="messages_author_check"
        ),
        CheckConstraint("(jsonb_typeof(blocks) = 'array'::text)", name="messages_blocks_check"),
        CheckConstraint("(input_tokens >= 0)", name="messages_input_tokens_check"),
        CheckConstraint("(latency_ms >= 0)", name="messages_latency_ms_check"),
        CheckConstraint("(output_tokens >= 0)", name="messages_output_tokens_check"),
        CheckConstraint("(protocol_version >= 1)", name="messages_protocol_version_check"),
        CheckConstraint(
            "(jsonb_typeof(tool_calls) = 'array'::text)", name="messages_tool_calls_check"
        ),
        Index("messages_thread_idx", "thread_id", "created_at"),
        {
            "schema": "chat",
            "comment": "Cada mensaje de un chat, del director o de Mawta, con todo lo necesario para auditarlo y mejorar el chat después: bloques, herramientas usadas, modelo, tokens y latencia. user_id es el dueño del chat (desnormalizado) para la política restrictiva por usuario.",
        },
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), server_default=text("gen_random_uuid()")
    )
    thread_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    author: Mapped[str] = mapped_column(Text)
    protocol_version: Mapped[int] = mapped_column(SmallInteger, server_default=text("1"))
    blocks: Mapped[Any] = mapped_column(
        JSONB,
        server_default=text("'[]'::jsonb"),
        comment="PII (menor y adulto): texto libre. Bloques del protocolo v1 (estado, texto, tabla, grafico, error, fin) tal como los vio el modelo: los nombres de alumnos y profesores van seudonimizados (D001) y se restauran solo al mostrar.",
    )
    tool_calls: Mapped[Any] = mapped_column(
        JSONB,
        server_default=text("'[]'::jsonb"),
        comment="PII (menor y adulto): resultados de herramientas. Herramientas llamadas en el turno, con argumentos y resultados, seudonimizados igual que blocks.",
    )
    model: Mapped[str | None] = mapped_column(Text)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


class ChatQuestionBank(Base):
    __tablename__ = "question_bank"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="question_bank_pkey"),
        ForeignKeyConstraint(
            ["message_id"],
            ["chat.messages.id"],
            name="question_bank_message_fk",
            ondelete="CASCADE",
        ),
        CheckConstraint("(char_length(question) > 0)", name="question_bank_question_check"),
        CheckConstraint(
            "(status = ANY (ARRAY['respondida'::text, 'necesita_tool'::text, 'parcial'::text, 'fuera_de_alcance'::text]))",
            name="question_bank_status_check",
        ),
        Index("question_bank_status_idx", "status", "created_at"),
        {
            "schema": "chat",
            "comment": "Banco de preguntas: cada pregunta del director y cómo terminó. necesita_tool marca las que el chat no pudo responder por falta de una herramienta; fuera_de_alcance, las que no le corresponden. Es a la vez el backlog de herramientas y la suite de evaluación.",
        },
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), server_default=text("gen_random_uuid()")
    )
    message_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    question: Mapped[str] = mapped_column(
        Text,
        comment="PII (menor y adulto): texto libre. La pregunta tal como la escribió el director.",
    )
    status: Mapped[str] = mapped_column(Text)
    tool_name: Mapped[str | None] = mapped_column(
        Text,
        comment="Herramienta que respondió, o la que habría hecho falta cuando status = necesita_tool.",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
