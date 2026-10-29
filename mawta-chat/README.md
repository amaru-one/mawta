# mawta-chat

The director chat service: a school director asks questions about their school and gets answers built from Mawta's data, streamed over Server-Sent Events.

Python 3.14, FastAPI, LangGraph and an open model through any OpenAI-compatible provider (the school's own model server — Ollama or vLLM, on a laptop, a DGX Spark or a cloud server — or OpenRouter, `CHAT_MODEL=provider:model`), managed with [`uv`](https://docs.astral.sh/uv/). It is a separate service from `mawta-api` (Python) and shares only:

- **the login** — the director signs in to Mawta, and `mawta-api` issues a short-lived chat token (`GET /api/v1/auth/chat-token`, Ed25519). This service only verifies it with the public key;
- **the `mawta` database** — connected as the `mawta_chat` role, which can read only the `chat_api` views and write only the `chat` schema (migration `00006`). Postgres RLS limits every query to the director's school and chats.

LangGraph's checkpoints (the conversation state of each chat) live in their own database, `langgraph`, which LangGraph creates and migrates with `.setup()` at startup.

## Layout

| File | What it does |
|---|---|
| `src/main.py` | FastAPI app and routes |
| `src/auth.py` | Chat token verification |
| `src/db.py` | `mawta_chat` pool; `tenant_tx` sets `app.tenant_id` / `app.actor_id` per transaction |
| `src/graph.py` | LangGraph graph (agent ↔ tools) and the system prompt |
| `src/llm.py` | The model through the OpenAI-compatible API (streaming, tool calls), behind a small interface |
| `src/providers.py` | `provider:model`: which provider (`local` or `openrouter`) a model runs on |
| `src/tools.py` | The chat's tools (reads `chat_api` only) |
| `src/protocol.py` | Protocol v1 events streamed to the UI |
| `src/repo.py` | Queries on the `chat` schema |

## API

Every route except `/health` needs `Authorization: Bearer <chat token>`.

| Route | |
|---|---|
| `GET /health` | Service status |
| `GET /threads` | The director's chats, most recent first |
| `POST /threads` | New empty chat |
| `PATCH /threads/{id}` | Rename (`{"title": "..."}`) |
| `DELETE /threads/{id}` | Delete (soft) and drop its checkpoints |
| `GET /threads/{id}/messages` | Messages, as protocol v1 blocks |
| `POST /threads/{id}/messages` | Ask (`{"texto": "..."}`); the answer streams as SSE |

Streamed events (`protocol.py`): `estado`, `texto` (`delta`), `tabla`, `grafico`, `error`, `fin` (`message_id`). Each carries `"version": 1`.

## Running it locally

Against the local Postgres container from `mawta-api/docs/local-postgres-setup.md` (`mawta-pg`, migrated to at least `00006`):

```sh
# once: a password for mawta_chat, and LangGraph's own database
docker exec mawta-pg psql -U postgres -d mawta -c "alter role mawta_chat password 'mawta_chat';"
docker exec mawta-pg psql -U postgres -c "create database langgraph;"

cp .env.example .env   # then fill in the values
uv run mawta-chat      # http://127.0.0.1:8001
```

`CHAT_TOKEN_PUBLIC_KEYS` must hold the public key matching the `CHAT_TOKEN_SIGNING_KEY` your local `mawta-api` uses (`uv run chatkey --kid k-local` in `mawta-api` prints both).

Or in a container, next to the rest of the local stack: `docker compose -f docker-compose.local.yml --profile chat up`.

## Production

Deployed with the rest of Mawta on every push to `main` (`.github/workflows/deploy.yml`): the image `ghcr.io/amaru-one/mawta-chat:<sha>` runs as the `chat` service of `deploy/docker-compose.prod.yml`, with a 512 MB memory limit, and Caddy serves it at `https://<domain>/chat-api/*` (prefix stripped, SSE flushed immediately). The deploy smoke test checks `/chat-api/health` and that `/chat-api/threads` refuses a request without a token.

`/srv/mawta/.env` on the droplet must define (the compose file refuses to start without them):

| Variable | |
|---|---|
| `MAWTA_CHAT_PASSWORD` | Password of the `mawta_chat` role (migration `00006` creates the role without one) |
| `LANGGRAPH_PASSWORD` | Password of the `mawta_langgraph` role, owner of the `langgraph` database |
| `CHAT_TOKEN_PUBLIC_KEYS` | `{"k1":"<base64 public key>"}`, matching `CHAT_TOKEN_SIGNING_KEY` / `CHAT_TOKEN_KEY_ID` |
| `CHAT_MODEL` | `provider:model`; on the demo droplet an `openrouter:` model |
| `OPENROUTER_API_KEY` | Needed by an `openrouter:` model; shared with `mawta-api`'s agents |

The `langgraph` database is not a goose migration (it is not part of the `mawta` database). It was created once, by hand:

```sh
docker exec -i mawta-postgres-1 psql -U postgres <<'SQL'
create role mawta_langgraph login connection limit 5 password '<LANGGRAPH_PASSWORD>';
create database langgraph owner mawta_langgraph;
SQL
```

**Rotating the token key** (chat-director D002): generate a pair with a new `-kid`, add its public key to `CHAT_TOKEN_PUBLIC_KEYS` next to the old one and redeploy, switch `CHAT_TOKEN_SIGNING_KEY` / `CHAT_TOKEN_KEY_ID`, and remove the old public key after an hour.

## Tests

```sh
uv run ruff check . && uv run ruff format --check .
MAWTA_TEST_ADMIN_URL='postgres://postgres:postgres@localhost:55499/postgres?sslmode=disable' uv run pytest
```

The tests create two throwaway databases, apply `mawta-api`'s migrations and test fixture (`tests/fixture.sql`), and replace the model with a scripted fake, so they never call a provider. Without `MAWTA_TEST_ADMIN_URL` the database tests are skipped.
