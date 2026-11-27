## Project

Mawta's backend: one Python service per school, with the API, the job worker, the AI agents and the
director chat. Each school has its own Postgres database, and there is no tenant anywhere.

Stack:
- Python 3.14 with `uv`, Starlette and uvicorn.
- SQLAlchemy 2 **Core**. The typed models in `src/mawta_schema/` are used without an ORM `Session`.
- psycopg 3, Alembic and alembic_utils.
- LangGraph for the chat.
- Tooling: `ruff`, `pyright` and `pytest` against a real Postgres.

Read `README.md`, then `docs/schema.md` before touching the schema, and `docs/director-chat.md`
before touching `src/chat/`.

### Conventions

- The schema changes in `src/mawta_schema/` first. Then generate the migration with
  `alembic revision --autogenerate`, read it and fix it by hand (`docs/schema.md`).
  `alembic check` must stay clean.
- Queries go in `src/repo/` (or `src/chat/`), written in SQLAlchemy Core. Do not use an ORM
  Session, and do not keep `.sql` files in this repo.
- Requests run through `Database.user_tx` / `auth_tx` as `mawta_app`. The chat's tools run through
  `chat_tx`, as `mawta_chat`, and may read only the `chat_api` views.
- Run the database tests with `MAWTA_TEST_ADMIN_URL` set and `pytest -rs`. A run with skipped tests
  verified nothing. The tests read it from the environment, not through `Settings`; a git-ignored
  `.env` that sets it works with `uv run --env-file .env pytest -rs`.
- If the linter or the language server (LSP) shows a warning, fix it.
- Write prompts and Markdown documentation in English. User-facing text and the chat's tools stay
  in Spanish. Keep literal identifiers, commands, schema values and file paths as they are.

### Commits

Follow [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/):
`<type>(<scope>): <description>`.

- Types: `feat`, `fix`, `test`, `docs`, `refactor`, `perf`, `chore`, `ci`, `build`.
- The scope is optional and names the area touched: `chat`, `agent`, `api`, `schema`, `cli`,
  `eval`.
- The description is in English, in the imperative, lowercase, with no final period.
- A breaking change adds `!` after the type or scope (`feat(api)!: ...`) and a `BREAKING CHANGE:`
  footer that explains it.
