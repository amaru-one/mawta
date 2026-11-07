"""Row-level security that survives single-school: each director owns their chats."""

from alembic_utils.pg_policy import PGPolicy

POLICIES = [
    PGPolicy(
        schema="chat",
        signature="owner_only",
        on_entity="chat.messages",
        definition="AS PERMISSIVE FOR ALL TO public USING ((user_id = app.current_actor_id())) WITH CHECK ((user_id = app.current_actor_id()))",
    ),
    PGPolicy(
        schema="chat",
        signature="owner_only",
        on_entity="chat.threads",
        definition="AS PERMISSIVE FOR ALL TO public USING ((user_id = app.current_actor_id())) WITH CHECK ((user_id = app.current_actor_id()))",
    ),
]
