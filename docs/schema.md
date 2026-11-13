# mawta-schema

Mawta's database schema, in Python. It is the single source of truth for the Postgres database
of a school: the migrations are generated from it, and the app's queries (SQLAlchemy Core) use its
tables.

Each school runs its own database, so there is no tenant anywhere: the `school` table holds
exactly one row.

## What lives where

| Path | What it declares |
|---|---|
| `src/mawta_schema/tables/` | Every table, as typed SQLAlchemy classes (`Mapped[...]`), one module per area. Used for migrations and for typed SQLAlchemy Core queries; the apps never use an ORM `Session`. |
| `src/mawta_schema/functions.py` | Functions in schema `app` (trigger functions, guards, `log_event`, `current_actor_id`). |
| `src/mawta_schema/triggers.py` | Triggers: `set_updated_at` on every table that has `updated_at`, plus the domain guards. |
| `src/mawta_schema/views.py` | Views: `chat_api.*` (the director chat's read contract) and `privacy.*` (personal-data audits). |
| `src/mawta_schema/policies.py` | Row-level security: `owner_only` on `chat.threads` and `chat.messages`, so each director sees only their own chats. |
| `src/mawta_schema/api_views.py` | The `chat_api` views as read-only `Table` objects, for the chat's Core queries. |
| `migrations/` | Alembic. `versions/0001_baseline.py` creates the whole schema, roles and grants included; `0002_monolith_roles.py` lets the app enter `mawta_chat` and creates schema `langgraph` for the chat's memory; `0003_drop_chat_pseudonyms.py` drops the unused pseudonyms table (D001 was replaced by D004). |

Functions, triggers, views and policies are [alembic_utils](https://github.com/olirice/alembic_utils)
entities, so `alembic revision --autogenerate` picks up their changes too. Roles, grants,
extensions, schemas and comments on functions, views and policies are not modelled. A migration
that changes them writes the SQL by hand with `op.execute`.

## Changing the schema

1. Edit the models or entities in `src/mawta_schema/`.
2. Generate the migration against a database at the current head:

   ```sh
   export MAWTA_MIGRATIONS_URL=postgres://postgres:<password>@localhost:55432/mawta
   uv run alembic upgrade head
   uv run alembic revision --autogenerate -m "short description"
   ```

3. **Read the generated file before committing it.** Autogenerate is a draft. Fix these by hand:
   - **A renamed column or table** appears as a drop plus an add, which loses the data. Rewrite
     it as `op.alter_column(..., new_column_name=...)` or `op.rename_table(...)`.
   - **A changed CHECK on an existing table** is not detected. Add `op.drop_constraint` and
     `op.create_check_constraint` yourself.
   - **Data changes** (backfills, moving values between columns) are always hand-written.
   - **Grants, roles and comments** on non-table objects are hand-written with `op.execute`.
4. Run the checks below. `alembic check` fails if the models and the migrations disagree.

## Checks

```sh
uv run ruff check . && uv run ruff format --check .
uv run pyright
MAWTA_TEST_ADMIN_URL=postgres://postgres:<password>@localhost:55432/postgres uv run pytest
```

The tests create and drop their own databases. Besides the schema's own promises (one school,
private chats, the chat role reading only its views), they run pytest-alembic's checks: a single
head, upgrade from empty, models equal to the migrated database, and every migration
downgrading cleanly.

Migrations run as the database owner (a superuser), from `MAWTA_MIGRATIONS_URL` or, failing
that, `ADMIN_DATABASE_URL`.
