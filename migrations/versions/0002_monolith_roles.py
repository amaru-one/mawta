"""Monolith: the app enters mawta_chat itself, and LangGraph lives in this database.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-05

The director chat is no longer a separate service with its own login. The app connects as
mawta_app and switches to mawta_chat with SET LOCAL ROLE for the chat's work, so the LLM's
tools still read only the chat_api views. The grant gives SET but not INHERIT: mawta_app can
become mawta_chat, it does not gain mawta_chat's privileges.

LangGraph's checkpoints (the conversation memory) move from a separate database into schema
langgraph, owned by mawta_langgraph, so one pg_dump backs up a whole school. LangGraph creates
its own tables there on startup; Alembic never looks at this schema.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("grant mawta_chat to mawta_app with inherit false, set true")
    op.execute("alter role mawta_chat nologin")
    # Roles are global to the cluster; catch the race between parallel test databases.
    op.execute(
        """do $$
begin
  create role mawta_langgraph login connection limit 5;
exception
  when duplicate_object then null;
  when unique_violation then null;
end
$$"""
    )
    op.execute("create schema langgraph authorization mawta_langgraph")
    op.execute(
        "comment on schema langgraph is 'Checkpoints del chat de dirección (LangGraph): la"
        " memoria de cada conversación. LangGraph crea y administra sus propias tablas aquí;"
        " Alembic no las gestiona.'"
    )


def downgrade() -> None:
    op.execute("drop schema langgraph cascade")
    # mawta_langgraph stays: roles are shared by every database in the cluster.
    op.execute("alter role mawta_chat login")
    op.execute("revoke mawta_chat from mawta_app")
