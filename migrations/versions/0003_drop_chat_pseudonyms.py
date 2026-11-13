"""Drop chat.pseudonyms: the chat sends real names to the school's own models.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-12

Decision D001 gave every student and teacher a stable alias so the model never saw a real name.
D004 replaced it: the models are the school's own, so the chat uses real names, and nothing
writes or reads this table any more. The comments that still described pseudonyms (schema chat,
question_bank.question) are corrected here too.

The downgrade recreates the table empty, with the grant 0001 gave it.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

QUESTION_COMMENT = (
    "PII (menor y adulto): texto libre. La pregunta tal como la escribió el director."
)
OLD_QUESTION_COMMENT = "PII (menor y adulto): texto libre. La pregunta tal como la vio el modelo, seudonimizada (D001)."
SCHEMA_COMMENT = (
    "Datos propios del chat de dirección: hilos, mensajes y banco de preguntas. Solo mawta_chat "
    "los lee y escribe; la app entra a ese rol con SET LOCAL ROLE."
)
OLD_SCHEMA_COMMENT = (
    "Datos propios del servicio del chat de dirección: hilos, mensajes, banco de preguntas y "
    "seudónimos. Solo mawta_chat los lee y escribe; mawta_app (Go) no tiene acceso."
)


def upgrade() -> None:
    op.drop_table("pseudonyms", schema="chat")
    op.alter_column(
        "question_bank",
        "question",
        existing_type=sa.Text(),
        existing_nullable=False,
        comment=QUESTION_COMMENT,
        existing_comment=OLD_QUESTION_COMMENT,
        schema="chat",
    )
    op.execute(f"comment on schema chat is '{SCHEMA_COMMENT}'")


def downgrade() -> None:
    op.execute(f"comment on schema chat is '{OLD_SCHEMA_COMMENT}'")
    op.alter_column(
        "question_bank",
        "question",
        existing_type=sa.Text(),
        existing_nullable=False,
        comment=OLD_QUESTION_COMMENT,
        existing_comment=QUESTION_COMMENT,
        schema="chat",
    )
    op.create_table(
        "pseudonyms",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("entity_id", sa.UUID(), nullable=False),
        sa.Column("alias", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(entity_type = ANY (ARRAY['student'::text, 'teacher'::text]))",
            name="pseudonyms_entity_type_check",
        ),
        sa.CheckConstraint(
            "((char_length(alias) >= 1) AND (char_length(alias) <= 40))",
            name="pseudonyms_alias_check",
        ),
        sa.PrimaryKeyConstraint("id", name="pseudonyms_pkey"),
        sa.UniqueConstraint("alias", name="pseudonyms_alias_key"),
        sa.UniqueConstraint("entity_type", "entity_id", name="pseudonyms_entity_key"),
        schema="chat",
        comment="Seudónimos estables por colegio (D001): el modelo nunca recibe nombres reales de alumnos ni profesores, solo estos alias. entity_id apunta a students.id o teachers.id según entity_type; no lleva FK porque cubre dos tablas.",
    )
    op.execute("grant select, insert, update, delete on chat.pseudonyms to mawta_chat")
