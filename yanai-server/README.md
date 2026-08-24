# Yanai API

Go API powering the six screens in `yanai-views.html` (Home, Class dashboard,
Lesson/attendance, Student grades, Notifications, Profile) on top of the
Postgres schema in `migrations/`. Stack: `chi` + `pgx/v5`, hand-written SQL
(no ORM/sqlc), an in-process Postgres-backed job queue, forced row-level
security per tenant.

## Prereqs

- Go 1.22+
- The seeded local Postgres from `docs/postgres-setup.md` (container `yanai-pg`,
  migrations applied, `seed/seed_demo_tenant.sql` run).

## Quick start

```sh
go run ./cmd/api
curl localhost:8080/healthz
```

Config comes from `.env` (already populated for the local container) — see
that file for all variables.

## Auth (dev headers)

Every `/api/v1/*` route requires `X-Tenant-ID` and `X-Actor-ID` (UUIDs); the
actor must have an active teaching membership in the tenant. Both are fixed by
the seed and survive a reseed:

- Tenant (demo tenant): `11111111-1111-4111-8111-111111111111`
- Actor (demo teacher `janice.quispe@cristorey.edu.pe`): `22222222-2222-4222-8222-222222222222`

## Endpoints

| Route | Screen |
|---|---|
| `GET /me` | topbar |
| `GET /home`, `GET /classes?q=` | 01 Inicio |
| `GET /classes/{id}/dashboard`, `GET /classes/{id}/sessions`, `POST /sessions/{id}/start\|complete` | 02 Clase |
| `GET /sessions/{id}?q=`, `PUT .../attendance/{sid}`, `POST .../mark-all-present`, `PUT .../observations/{sid}`, `POST .../voice-notes`, `GET/POST /voice-notes/{id}/...` | 03 Lección |
| `GET /classes/{id}/students/{sid}/grades`, `POST /classes/{id}/assessments`, `POST /assessments/{id}/scores`, `POST /scores/{id}/correct`, `POST .../summary` | 04 Notas |
| `GET /notifications`, `.../unread-count`, `POST .../read\|dismiss` | 05 Notificaciones |
| `GET /profile` | 06 Perfil |

Every write sets Postgres session GUCs (`app.tenant_id`, `app.actor_id`,
`app.request_id`) inside its transaction via `internal/db.WithTenantTx` —
that's what makes RLS and audit correlation work. Reads returning
identifiable student rows log a `student.read` event in the same tx.

## Worker

In-process job queue (`internal/worker`), claimed via `SELECT ... FOR UPDATE
SKIP LOCKED`. Toggle with `WORKER_ENABLED=false` to run API-only.

- **`grade.recompute`** — the real weighted computation: component weights,
  `drop_lowest_n`, aggregation (mean/weighted_mean/best/last/sum), retake
  resolution (none/best/last/capped), `min_evaluated_weight_for_grade`,
  rounding. **Not implemented**: late penalties, per-competency grades.
- **`risk.detect`** — consecutive absences and level-drop rules from
  `risk_rules.params`.
- **`notification.sweep`** — attendance-unmarked and grades-pending
  reminders, deduped by `dedupe_key`.
- **`note_summary.generate`** — deterministic extractive summary (first
  sentence of each saved voice note's transcript, newest first, max 5
  bullets). No AI provider this stage — transcription happens in the
  browser; the client uploads transcript text via `.../transcript`.
- **`retention.sweep`** — non-destructive: logs counts of records past
  `retention_until`.

## Verification

```sh
T=11111111-1111-4111-8111-111111111111
A=22222222-2222-4222-8222-222222222222
H='-H "X-Tenant-ID: '$T'" -H "X-Actor-ID: '$A'"'

curl $H localhost:8080/api/v1/me
curl $H "localhost:8080/api/v1/classes/<inglés-class-id>/dashboard?date=2026-08-08"
curl $H "localhost:8080/api/v1/sessions/<8-aug-session-id>?q=agus"
```

Expect: 10-student roster and two classes (Inglés 5to B, Matemática 5to B),
each with 2 completed and 6 upcoming sessions and a full set of published,
unscored assessments (Inglés: 4 listening / 2 reading / 2 writing / 1 speaking;
Matemática: 4 quizzes / 2 tareas / 1 examen final). Score a student and the
worker recomputes their grade within ~2s.

## Notes

- **Append-only**: `scores` and `computed_grades` are never updated in
  place. `POST /scores/{id}/correct` stamps `superseded_at` on the old row,
  then inserts the replacement — same order the DB trigger requires.
- **Soft delete only**: hard `DELETE` is blocked by trigger everywhere
  except `jobs`.
- **Audio** lands under `STORAGE_DIR/<tenant>/<session>/<uuid>.<ext>`
  (default `./data/audio`, gitignored).
