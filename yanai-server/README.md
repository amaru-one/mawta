# Yanai API

Go API powering the Yanai app's eight screens (Home, Class dashboard,
Lesson/attendance, Criterios, Evidence grid, Student grades, Notifications,
Profile) on top of the Postgres schema in `migrations/`. Stack: `chi` +
`pgx/v5`, hand-written SQL (no ORM/sqlc), an in-process Postgres-backed job
queue, forced row-level security per tenant.

## Prereqs

- Go 1.26+
- A local Postgres from `docs/postgres-setup.md` (container `yanai-pg`, migrations applied).
  There is no seed any more — create an account with `cmd/useradd` (below).

## Quick start

```sh
go run ./cmd/api
curl localhost:8080/healthz
```

Config comes from `.env` (already populated for the local container) — see
that file for all variables.

## Auth

Real authentication: username + bcrypt password hash, an HttpOnly session
cookie (`yanai_session`), a server-side `user_sessions` table. `POST
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

## Endpoints

| Route | Screen |
|---|---|
| `GET /me` | topbar |
| `GET /home` | 01 Inicio |
| `GET /classes/{id}/dashboard`, `POST /sessions/{id}/start` | 02 Clase |
| `GET /sessions/{id}?q=`, `PUT .../attendance/{sid}`, `POST .../mark-all-present`, `POST .../voice-notes`, `GET/POST /voice-notes/{id}/...` | 03 Lección |
| `GET /classes/{id}/students/{sid}/grades`, `GET /classes/{id}/grading-components`, `POST /classes/{id}/assessments`, `POST /assessments/{id}/delete`, `POST /assessments/{id}/scores`, `POST /scores/{id}/correct`, `POST /classes/{id}/students/{sid}/practice-scores`, `POST /practice-scores/{id}/delete` | 04 Notas |
| `GET /classes/{id}/students/{sid}/competencies`, `POST .../competency-levels`, `POST .../conclusions` | 05 Competencias |
| `GET /classes/{id}/criteria`, `POST /classes/{id}/competencies/{cid}/criteria`, `POST /criteria/{id}/delete`, `POST /classes/{id}/students/{sid}/criterion-levels`, `GET /assessments/{id}/criteria-grid` | 06 Criterios |
| `GET /notifications`, `POST .../read`, `POST /notifications/read-all` | 07 Notificaciones |
| `GET /profile` | 08 Perfil |

Every write sets Postgres session GUCs (`app.tenant_id`, `app.actor_id`,
`app.request_id`) inside its transaction via `internal/db.WithTenantTx` —
that's what makes RLS and audit correlation work. Reads returning
identifiable student rows log a `student.read` event in the same tx.

## Worker

In-process job queue (`internal/worker`), claimed via `SELECT ... FOR UPDATE
SKIP LOCKED`. Toggle with `WORKER_ENABLED=false` to run API-only.

- **`grade.recompute`** — the weighted computation behind the school's
  *optional internal system*: component weights, `drop_lowest_n`, aggregation
  (mean/weighted_mean/best/last/sum), retake resolution
  (none/best/last/capped), `min_evaluated_weight_for_grade`, rounding.
  **Not implemented**: late penalties.

That is the only job kind. Under RVM 094-2020 achievement is the teacher's
judgement of evidence against the criterios de evaluación, recorded per
competencia in `competency_term_levels` through the API — no job writes,
derives or suggests a nivel de logro, and nothing here forecasts one.

Retired kinds whose rows may still be in `jobs`: `risk.detect`,
`risk.term_failure`, `risk.promotion_projection`, `notification.sweep`,
`note_summary.generate`, `retention.sweep`. They fail as "unknown job kind"
until discarded, which is expected.

## Verification

```sh
curl -i -c cookies.txt -X POST localhost:8080/api/v1/auth/login \
  -H 'Content-Type: application/json' -d '{"username":"jquispe","password":"..."}'
curl -b cookies.txt localhost:8080/api/v1/me
curl -b cookies.txt "localhost:8080/api/v1/classes/<class-id>/dashboard"
```

Expect: `POST /auth/login` sets an `HttpOnly` `yanai_session` cookie and
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
