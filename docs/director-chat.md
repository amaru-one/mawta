# The director chat

A school director asks questions about their school, in Spanish, and gets answers built from
Mawta's data, streamed over Server-Sent Events. The chat is part of the app (`src/chat/`), not a
separate service. It uses the same session cookie as the rest of the app, and only the director
role may use it.

It is a LangGraph agent: the model reads the question, calls read-only tools, and writes the
answer. The numbers and tables come from the tools, never from the model's memory.

## Where its limits are enforced

| Limit | How |
|---|---|
| Who | Every route except `/health` goes through `authenticate` and `require_director`. A teacher gets 403 `not_a_director` |
| What it reads | Its tools run inside `Database.chat_tx`, which enters the role `mawta_chat` with `SET LOCAL ROLE`. That role can read only the `chat_api` views and write only the `chat` schema |
| Whose chats | Row-level security (`owner_only`) on `chat.threads` and `chat.messages`: each director sees only their own chats, even through the database |
| How long | `chat_tx` sets `statement_timeout` 15s, `lock_timeout` 2s and `idle_in_transaction_session_timeout` 30s for the transaction only. Nothing carries over to the next transaction on the pooled connection |
| How much | `CHAT_MAX_CONCURRENT` questions are answered at once, and one more gets 429 `chat_busy`. `CHAT_MAX_MODEL_CALLS` caps the model calls per question |
| Without a model | Without `CHAT_MODEL` (or without the OpenRouter key an `openrouter:` model needs), asking answers 503 `chat_unavailable`. The rest of the chat (listing, renaming, deleting) and the rest of the app keep working |

## Memory

LangGraph keeps each chat's state (its checkpoints) in schema `langgraph` of the **school's own
database**. It connects there as `mawta_langgraph` (`LANGGRAPH_DATABASE_URL`, with
`options=-c search_path=langgraph`) and creates its tables on the first start. A thread's key is
`<user id>:<thread id>`. Deleting a chat also deletes its checkpoints.

## API

All routes are under `/api/v1/chat`.

| Route | |
|---|---|
| `GET /health` | The chat's status (no session needed) |
| `GET /threads` | The director's chats, most recent first |
| `POST /threads` | A new empty chat (201) |
| `PATCH /threads/{id}` | Renames a chat: `{"title": "..."}`, at most 200 characters |
| `DELETE /threads/{id}` | Deletes a chat and its checkpoints (204) |
| `GET /threads/{id}/messages` | The messages, as protocol v1 blocks |
| `POST /threads/{id}/messages` | Asks a question: `{"texto": "..."}`. The answer streams as SSE |

Someone else's chat answers 404, never 403.

**Protocol v1** (`protocol.py`). Every event carries `"version": 1` and a `tipo`:
- `estado`: what the chat is doing, for example "Consultando los datos del colegio…";
- `texto`: a piece of the answer, in `delta`;
- `tabla`, `barras_apiladas` and `matriz`: blocks from a tool;
- `error`;
- `fin`: the last event, with the saved message's `message_id`.

The UI ignores any `tipo` it does not know.

## Tools

The tools are read-only, as defined by decision D003. Each one applies the glossary in its own SQL,
because the `chat_api` views only hand over clean data. Each returns one fixed kind of block.

When what the director wrote matches several things, or nothing, the tool answers with the options
(`necesita_aclaracion`), so the model asks. Students are listed by section and surname, never
ranked.

| Tool | Answers | Block |
|---|---|---|
| `datos_del_colegio` | Periods (which is current, which have levels), sections, tutors, teachers per class, students per section | `tabla` |
| `resumen_de_niveles` | AD/A/B/C counts by área, competency or section in a period, and the competencies with no level | `barras_apiladas` |
| `alumnos_con_c` | Students with C in at least one competency of a period | `tabla` |
| `riesgo_por_competencia` | C in the same competency in consecutive periods. A period with no level breaks the streak | `tabla` |
| `proyeccion_de_promocion` | Each secondary student's projected situation, with its reason. 1.°, 3.° and 4.° follow one rule; 2.° and 5.° follow the stricter end-of-cycle rule (cuadro 5.1.3.A, RVM 048-2024) | `tabla` |
| `historial_del_alumno` | One student's level per competency and period. An empty cell means no level yet, never C | `matriz` |

Without a period, a tool uses the last one with levels. Teachers assert levels when a period
closes, so the current period usually has none yet.

## Configuration

| Variable | |
|---|---|
| `CHAT_MODEL` | `provider:model`, for example `openrouter:<model>` or `local:<model>`. Empty makes the chat unavailable |
| `CHAT_REASONING_EFFORT` | Sent to the model only when set |
| `LANGGRAPH_DATABASE_URL` | Required when `CHAT_MODEL` is set |
| `CHAT_MAX_CONCURRENT` | Default 3 |
| `CHAT_MAX_MODEL_CALLS` | Default 6. Each tool round is one more call |
| `CHAT_MAX_TOKENS` | Default 16000 |
| `OPENROUTER_API_KEY`, `LOCAL_LLM_URL`, `LOCAL_LLM_API_KEY` | Shared with the agents |

## Tests

`tests/chat/` runs against its own database: the test school plus `tests/fixtures_levels.py`, two
terms of achievement levels. A scripted fake replaces the model, so no test calls a provider.
- `test_tools.py`: one case per glossary rule.
- `test_ask.py` and `test_threads.py`: the HTTP flow.
- `test_boundaries.py`: every limit in the table above.
