# Prompt: generate the Yanai database schema

---

You are a senior backend engineer designing the initial PostgreSQL schema for **Yanai**, a mobile-first assistant for secondary school teachers in Peru.

## Step 0 — read the spec before writing anything

A file named `yanai-views.html` accompanies this prompt. It is a static gallery of the six screens of the current app version. **Read it in full before writing any SQL.** It is the authoritative specification of what the product does; this prompt only summarizes it.

Read it as a data modeler, not as a frontend developer. For every screen:

- Every value rendered on screen must be derivable from your schema.
- Every button implies a write path — identify the table and columns it touches.
- Every count, percentage, and progress bar implies either a stored aggregate or a query you must be able to write efficiently.
- Every empty or pending state (`Sin evaluar`, `Sin iniciar`, `Asistencia sin marcar`, `3 notas pendientes`) implies a nullable column or a status enum, not a missing row.

The interface is in Spanish. Use English identifiers in the schema, but preserve domain terms where they are specific to the Peruvian system (`bimestre`, `recuperacion`, `subsanacion`) rather than mistranslating them.

Note that some screens show state the UI implies but does not label — for example, a trend indicator next to a student's level, and a "students being tracked" count on the profile screen. Work out what has to be stored for those to exist.

## Stack context

- PostgreSQL 16, targeting a single shared database, multi-tenant by school
- Go backend using `pgx/v5` and `sqlc` — plain SQL, no ORM
- Migrations via `goose`
- `pgvector` will be used later for semantic search over voice-note transcripts and teacher observations
- Deployed as a small container; assume tens of schools, thousands of teachers, hundreds of thousands of students

## Domain notes the HTML will not tell you

Peru's MINEDU competency-based system uses the qualitative scale **AD / A / B / C** (AD = logro destacado, A = logro esperado, B = en proceso, C = en inicio). The app currently shows this scale, but private and international schools use the 0–20 vigesimal scale or percentages, and Yanai must support all of them without schema changes.

The academic year is divided into **bimestres** (four per year) at most schools, but some use trimesters. Retake mechanisms (`recuperación`, `subsanación`) are standard and legally required.

## Non-negotiable design constraints

These come from prior architecture decisions. Follow them exactly, and say so explicitly if you believe one is wrong.

**1. Multi-tenancy is shared-schema.** Every tenant-scoped table carries `tenant_id uuid not null`. No database-per-school, no schema-per-school. Write PostgreSQL row-level security policies keyed on a `current_setting('app.tenant_id')` session variable, so a query that forgets its tenant filter returns nothing rather than another school's students.

**2. Grading policy is data, not schema.** Different schools have different components and weights. Model grade scales and weighting schemes as rows. Constrain component weights within a scheme to sum to 1.

**3. Grading schemes are versioned and immutable.** Changing a school's weights inserts a new version with `effective_from`/`effective_to`; it never mutates an existing row. Any computed final grade records which scheme version produced it, so a report card issued in April never silently changes in June.

**4. Store raw scores only.** A score row holds the raw value and the assessment's maximum. Never store a percentage or a pre-weighted contribution. Everything else is computed and then snapshotted when a term closes.

**5. Grades are temporal.** Every change to a score is a new row with actor and timestamp, never an `UPDATE` in place. Nothing is hard-deleted anywhere in the schema — use soft deletes.

**6. Append-only event log from day one.** A single `events` table (`tenant_id`, `actor_id`, `action`, `entity_type`, `entity_id`, `occurred_at`, `payload jsonb`) capturing every meaningful action. This is the training data for the risk-detection and grade-forecasting models, so design it to be queryable as a time series, not just as an audit trail.

**7. A `normalized_value numeric` column on every computed grade**, mapping the grade to 0–1 regardless of the school's scale, so models can train across all tenants with a plain `SELECT`.

**8. Postgres is the job queue.** Include a `jobs` table compatible with the River library's approach (`kind`, `payload jsonb`, `status`, `attempts`, `run_after`), claimed via `FOR UPDATE SKIP LOCKED`. Voice-note transcription, summary generation, and risk detection all run through it.

**9. All timestamps are `timestamptz`, stored UTC.** Store the school's IANA timezone on the tenant.

## Modeling requirements to handle explicitly

- **Assessment edge cases:** excused scores (excluded from the denominator, distinct from a zero), drop-lowest-N per component, late penalties, and retake attempts stored as additional attempts against the same assessment rather than overwriting the original. The fact that a student needed a retake is a strong risk signal and must survive.
- **Recurring schedule vs. actual sessions:** a class has a weekly recurring pattern; a session is a concrete dated instance with a lifecycle (not started → in progress → completed) and a topic. Cancellations and reschedules must be representable.
- **Voice notes:** attached to a student within a session, with duration, storage key, transcript, transcription status, and a `vector` column reserved for embeddings. Include the AI-generated summary as a separate entity that references the set of notes it summarized.
- **Per-session observations:** participation level and behavior flags are recorded per student per session, separately from graded assessments.
- **Notifications:** system-generated, typed (alert vs. reminder), with read state, a reference to the entity that triggered them, and — for AI- or rule-generated alerts — the evidence that produced them, so a teacher can see why a student was flagged.
- **Risk flags:** which students are under tracking, since when, why, by which rule or model version, and whether a teacher dismissed the flag. Dismissals are training signal; keep them.
- **Curriculum:** subject → course → unit → competency, per tenant, with assessments linking to competencies.

## Minors' data

Every subject in this database is a child. Apply Peru's Ley 29733 as a floor. Concretely: mark columns holding personal data of minors so they can be found programmatically, ensure every read of a student record is capturable by the event log, and include retention and deletion columns rather than assuming rows live forever. Add a comment on each such table stating what it holds.

## Deliverables

1. Numbered `goose` migration files, each one runnable and reversible, ordered so foreign keys resolve.
2. Every table, and every non-obvious column, carries a SQL `COMMENT ON`.
3. Indexes justified by actual query patterns from the six screens — state which screen each non-obvious index serves.
4. Check constraints and foreign keys wherever an invariant can be enforced in the database rather than in Go.
5. A seed migration creating one demo tenant with two grading schemes: one using AD/A/B/C, one using 0–20 vigesimal, to prove the scheme model works for both.
6. After the SQL, a short section listing: the three queries you expect to be slowest, the assumptions you had to make where the HTML was ambiguous, and anything in these constraints you'd push back on.

## Conventions

`snake_case`; plural table names; `uuid` primary keys via `gen_random_uuid()`; `created_at`/`updated_at` on every table; enums as `text` with check constraints rather than native PostgreSQL enum types, since those are painful to alter later; money and grades as `numeric`, never `float`.

## Work in order

Propose the entity list and relationships first and stop for review. Do not write migrations until the model is agreed. If the HTML is ambiguous about something structural, ask rather than guessing.
