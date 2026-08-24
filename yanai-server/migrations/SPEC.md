## Purpose
The complete database schema as goose SQL migrations, applied in order against PostgreSQL 16 + pgvector.

## Contents
- `00001_bootstrap.sql` — roles, `app` schema/helpers, extensions.
- `00002_tenancy_and_identity.sql` — tenants, persons, teachers, memberships, RLS scaffolding.
- `00003_academic_calendar.sql` — academic years, terms.
- `00004_curriculum.sql` — subjects/curriculum.
- `00005_sections_and_students.sql` — sections, students, section_memberships.
- `00006_classes_and_schedule.sql` — classes, class_teachers, schedules.
- `00007_sessions_and_attendance.sql` — class_sessions, attendance_records.
- `00008_grading_policy.sql` — grade_scales, grading_schemes, versions, component weights, class_effective_grading_schemes.
- `00009_assessments_and_scores.sql` — assessments, scores (append-only with supersession), retake_authorizations.
- `00010_computed_grades.sql` — computed_grades + computed_grade_components (append-only, superseded_at).
- `00011_observations_and_voice_notes.sql` — observations, flag types, voice_notes (with pgvector embedding).
- `00012_risk_and_notifications.sql` — risk_rules, risk_flags (+evidence), notifications with dedupe keys.
- `00013_events_and_jobs.sql` — the events audit table, `app.log_event`, and the `jobs` work queue (claimed via FOR UPDATE SKIP LOCKED).
- `00014_privacy_and_retention.sql` — privacy schema, deletion_requests, retention columns.
- `00015_audio_in_db.sql` — voice-note audio stored in the database.
- `00016_practice_scores.sql` — unofficial practice scores.
- `ANALYSIS.md` — design notes: verified up/down/up cleanliness, expected-painful queries, ambiguities in the HTML spec, argued constraints.

## Inputs / Outputs
Applied with goose (`GOOSE_MIGRATION_DIR` points here in production). Downstream consumers: every Go package, `seed/seed_demo_tenant.sql`.

## Conventions & Constraints
- Migrations are schema only — seed/demo data lives in `seed/`, never here.
- Append-only, never edit an applied migration; add a new numbered file.
- Text + CHECK "enums" in SQL are mirrored as constants in `internal/domain/consts.go` (cascade when adding values).
- Every tenant table gets FORCE ROW LEVEL SECURITY; `jobs` deliberately has no RLS (nullable tenant_id, workers span tenants).
- Column/table `comment on` strings are load-bearing documentation — keep them current.

## Change Log
- 2026-08-24: Initial spec created retroactively, describing current contents.

## Open Questions
- None.
