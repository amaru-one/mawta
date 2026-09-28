# Mawta API

Go API powering the Mawta app on top of the Postgres schema in `migrations/`. Stack: `chi` +
`pgx/v5`, hand-written SQL (no ORM/sqlc), an in-process Postgres-backed job
queue, forced row-level security per tenant.

## Prereqs

- Go 1.26+
- A local Postgres from `docs/local-postgres-setup.md` (container `mawta-pg`, migrations applied).
  There is no seed any more — create an account with `cmd/useradd` (below).

## Quick start

```sh
go run ./cmd/api
curl localhost:8080/healthz
```

Config comes from `.env` (already populated for the local container) — see
that file for all variables.

## Logging

The API emits structured JSON logs to stdout — one JSON object per line. Each
entry includes a timestamp, log level, message, and a `service` field set to
`mawta-server`.

### LOG_LEVEL

The `LOG_LEVEL` environment variable controls which log levels are emitted:

| Value    | Emits                       |
|----------|-----------------------------|
| `debug`  | debug, info, warn, error    |
| `info`   | info, warn, error (default) |
| `warn`   | warn, error                 |
| `error`  | error only                  |

An invalid value falls back to `info` and prints a warning at startup.

```sh
LOG_LEVEL=debug go run ./cmd/api
```

### Inspecting logs locally

Pipe stdout through `jq` to filter and format JSON logs:

```sh
# Pretty-print all logs
go run ./cmd/api 2>&1 | jq .

# Show only errors
go run ./cmd/api 2>&1 | jq 'select(.level=="error")'

# Filter by HTTP route
go run ./cmd/api 2>&1 | jq 'select(.route)'

# Show request log entries with their route and duration
go run ./cmd/api 2>&1 | jq 'select(.msg=="request") | {method, route, status, duration_ms}'

# Filter worker job outcomes
go run ./cmd/api 2>&1 | jq 'select(.kind) | {msg, job_id, kind, attempt, duration_ms}'

# Correlate a request by ID
go run ./cmd/api 2>&1 | jq 'select(.request_id=="abc-123")'
```

### Logged fields

**HTTP requests** produce one log entry per request with:

| Field        | Source                                        |
|--------------|-----------------------------------------------|
| `request_id` | `X-Request-ID` header or generated UUID       |
| `method`     | HTTP method (GET, POST, etc.)                 |
| `route`      | Chi route pattern (e.g. `/api/v1/classes/{classID}/students`) |
| `status`     | HTTP response status code                     |
| `duration_ms`| Request duration in milliseconds              |

**Worker jobs** produce one log entry per job outcome with:

| Field        | Source                                        |
|--------------|-----------------------------------------------|
| `job_id`     | Database row ID                               |
| `kind`       | Job type (e.g. `grade.recompute`)             |
| `attempt`    | Attempt number                                |
| `duration_ms`| Job processing duration in milliseconds        |

No log entry contains passwords, session tokens, cookies, API keys,
authorization headers, request bodies, audio, transcripts, student data,
or full job payloads.

## Auth

Real authentication: username + bcrypt password hash, an HttpOnly session
cookie (`mawta_session`), a server-side `user_sessions` table. `POST
/auth/login` and `POST /auth/logout` are the only two routes outside the
session check; every other `/api/v1/*` route requires the cookie, resolved
to an active `teacher` membership. See `internal/httpapi/SPEC.md` for the
full login sequence and error codes, and `migrations/SPEC.md` for the schema.

Create the first account (the tenant must already exist):

```sh
go run ./cmd/useradd -tenant <tenant-uuid> -username jquispe \
  -email janice.quispe@cristorey.edu.pe -given-name Janice -family-name Quispe \
  -role teacher -password 'a real password, 10+ chars'
```

`cmd/useradd -h` lists every flag, including `-generate-password` and
`-reset-password`. See `cmd/useradd/SPEC.md`.

## Verification

```sh
curl -i -c cookies.txt -X POST localhost:8080/api/v1/auth/login \
  -H 'Content-Type: application/json' -d '{"username":"jquispe","password":"..."}'
curl -b cookies.txt localhost:8080/api/v1/me
curl -b cookies.txt "localhost:8080/api/v1/classes/<class-id>/dashboard"
```

Expect: `POST /auth/login` sets an `HttpOnly` `mawta_session` cookie and
returns the same shape `GET /me` does; subsequent requests with that cookie
succeed, and the same request with no cookie 401s (`missing_session`). There
is no seeded data any more — the roster and classes above depend on whatever
you've loaded against the tenant `useradd` pointed at.

## Notes

- **Append-only**: `scores` and `computed_grades` are never updated in
  place. `POST /scores/{id}/correct` stamps `superseded_at` on the old row,
  then inserts the replacement — same order the DB trigger requires.
- **Soft delete only**: hard `DELETE` is blocked by trigger everywhere
  except `jobs`.
- **Audio** lands under `STORAGE_DIR/<tenant>/<session>/<uuid>.<ext>`
  (default `./data/audio`, gitignored).
