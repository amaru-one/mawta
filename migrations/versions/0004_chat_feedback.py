# pyright: reportAttributeAccessIssue=false
# (alembic_utils adds op.create_entity / op.drop_entity at runtime, so pyright cannot see them.)
"""Add trace_id on chat.messages and chat.message_feedback for director feedback.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-28

Stores each answer's Langfuse trace_id alongside the saved message and adds chat.message_feedback
(one editable vote per answer, protected by the same owner_only RLS policy as threads and
messages).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from alembic_utils.pg_policy import PGPolicy
from alembic_utils.pg_trigger import PGTrigger

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

chat_message_feedback_set_updated_at = PGTrigger(
    schema="chat",
    signature="set_updated_at",
    on_entity="chat.message_feedback",
    is_constraint=False,
    definition="BEFORE UPDATE ON chat.message_feedback FOR EACH ROW EXECUTE FUNCTION app.set_updated_at()",
)

chat_message_feedback_owner_only = PGPolicy(
    schema="chat",
    signature="owner_only",
    on_entity="chat.message_feedback",
    definition="AS PERMISSIVE FOR ALL TO public USING ((user_id = app.current_actor_id())) WITH CHECK ((user_id = app.current_actor_id()))",
)


def upgrade() -> None:
    op.add_column("messages", sa.Column("trace_id", sa.Text(), nullable=True), schema="chat")
    op.create_table(
        "message_feedback",
        sa.Column("message_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("rating", sa.SmallInteger(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "comment",
            sa.Text(),
            nullable=True,
            comment="PII (menor y adulto): texto libre. Comentario opcional del director sobre la respuesta.",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("(rating = ANY (ARRAY[-1, 1]))", name="message_feedback_rating_check"),
        sa.CheckConstraint(
            "((reason IS NULL) OR (reason = ANY (ARRAY['dato_incorrecto'::text, 'falto_contexto'::text, 'grafico_innecesario'::text, 'sin_sugerencia'::text, 'otro'::text])))",
            name="message_feedback_reason_check",
        ),
        sa.CheckConstraint(
            "((comment IS NULL) OR (char_length(comment) <= 500))",
            name="message_feedback_comment_check",
        ),
        sa.ForeignKeyConstraint(
            ["message_id"],
            ["chat.messages.id"],
            name="message_feedback_message_fk",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="message_feedback_user_id_fkey"),
        sa.PrimaryKeyConstraint("message_id", name="message_feedback_pkey"),
        schema="chat",
        comment="Feedback del director sobre una respuesta de Mawta (útil o mejorable, motivo y comentario opcional). Un voto editable por respuesta, privado por RLS.",
    )
    op.create_index(
        "message_feedback_rating_idx",
        "message_feedback",
        ["rating", "created_at"],
        unique=False,
        schema="chat",
    )
    op.create_entity(chat_message_feedback_set_updated_at)
    op.create_entity(chat_message_feedback_owner_only)
    op.execute("alter table chat.message_feedback enable row level security")
    op.execute("alter table chat.message_feedback force row level security")
    op.execute("grant select, insert, update, delete on chat.message_feedback to mawta_chat")
    op.execute(
        "comment on policy owner_only on chat.message_feedback is 'Cada directivo ve, cambia y borra solo su propio feedback (app.actor_id de la transacción).'"
    )


def downgrade() -> None:
    op.drop_entity(chat_message_feedback_owner_only)
    op.drop_entity(chat_message_feedback_set_updated_at)
    op.drop_index("message_feedback_rating_idx", table_name="message_feedback", schema="chat")
    op.drop_table("message_feedback", schema="chat")
    op.drop_column("messages", "trace_id", schema="chat")
