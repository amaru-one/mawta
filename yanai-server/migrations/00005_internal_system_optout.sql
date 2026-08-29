-- The school's own grading system becomes optional, and opt-out-able per
-- piece of evidence.
--
-- Two systems coexist in this app and must never feed each other:
--
--   the official record  -- nivel de logro per competencia, judged by the
--                           teacher against the criterios de evaluación
--                           (RVM 094-2020, 5.1.1.3 p.3)
--   the school's own     -- a weighted vigesimal mark, which a private IE may
--                           run under D.S. 009-2006-ED art. 37.4.f
--
-- MINEDU itself fixes the direction of travel between them. Anexo II of RVM
-- 048-2024 converts a nivel de logro *into* a number (C=1, B=2,5, A=3, AD=4)
-- for the certificate issued to students continuing studies abroad. It never
-- converts a number into a nivel de logro. So: level -> number is a reporting
-- transform the norm defines; number -> level is not a thing, and no column
-- added here may become one.
--
-- Until now the school's system was not optional. Every class with a grading
-- scheme produced `computed_grades`, and the UI asked for a mark out of 20 on
-- every piece of evidence. A school that keeps only the MINEDU record had to
-- type numbers it does not use, and those numbers then sat next to the level
-- picker while the teacher was judging -- which is the one adjacency the norm's
-- whole framing argues against.
--
-- 1. tenants.uses_internal_grading  -- the school runs its own system, or not.
-- 2. assessments.counts_toward_internal -- this evidence feeds the school's
--    average, or only the official judgement.
--
-- Nothing here touches the criterio layer. Evidence-anchored criterio levels
-- already work: 00003 made evaluation_criterion_scores.assessment_id nullable
-- and gave the assessment-anchored shape its own live key
-- (ecs_live_assessment_key). What changes alongside this migration is which
-- shape the Go code writes -- see the comment on ecs_live_term_key below.

-- Note for whoever edits the comment strings below: goose strips everything
-- after a `- -` (no space) when deciding whether a line ends a statement, even
-- inside a quoted literal, so a comment string containing one swallows the
-- statements that follow it. Punctuate with colons and commas instead.

-- +goose Up

alter table tenants
  add column uses_internal_grading boolean not null default true;

comment on column tenants.uses_internal_grading is
  'Whether this school runs its own weighted numeric grading system alongside the official MINEDU record (D.S. 009-2006-ED art. 37.4.f permits one). True is the historical behaviour and stays the default. False means the school records only niveles de logro: the UI stops asking for a mark on each piece of evidence and hides computed_grades entirely. It never changes how the official record is produced, which is the teacher''s judgement of evidence against the criterios either way. No value of this column may cause a number to determine a nivel de logro: RVM 048-2024 Anexo II converts a level into a number, never the reverse.';

alter table assessments
  add column counts_toward_internal boolean not null default true;

comment on column assessments.counts_toward_internal is
  'Whether this evidence feeds the school''s internal weighted average. It always feeds the official judgement: a criterio level recorded against it counts regardless, because the norm knows nothing about this flag. False exists for the recovery task given to one student (assessments.student_id set). That task is legitimate evidencia of the competencia, but letting it lift only that student''s internal average hands them an opportunity the rest of the class never had. Read by worker/handlers/recompute.go, which is the only consumer.';

-- Deliberately no index for the new flag. assessments_class_term_idx stays
-- non-partial: the evidence list, the dashboard counts and the recompute all
-- read the same (class_id, term_id, status) rows, and only the last of the
-- three cares about counts_toward_internal. Narrowing the shared index to the
-- one caller would push the other two off it to serve a filter that discards
-- at most a handful of rows per class.

-- Criterio levels are recorded against a piece of evidence, not against a
-- period in the abstract. Both shapes stay legal in the schema, but only the
-- assessment-anchored one is written from here on: valuing a criterio with no
-- evidence in hand inverts 5.1.1.3 p.3, which values *evidence* through the
-- criterio. Enforced in internal/repo/criteria.go rather than by a constraint,
-- because rows written under the old rule are real history and a CHECK would
-- invalidate them retroactively.
comment on index ecs_live_term_key is
  'LEGACY, READ-ONLY. The period-grain criterio judgement, written by AssertCriterionLevel until 2026-08-28. No longer written: a criterio level now always names the evidence it was read from (ecs_live_assessment_key). Existing rows are kept and displayed as history, since they are part of a student''s academic record, but nothing may add to them.';

-- +goose Down

comment on index ecs_live_term_key is null;

alter table assessments drop column counts_toward_internal;
alter table tenants drop column uses_internal_grading;
