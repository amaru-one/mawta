-- Criterio levels are gone. A criterio is not graded.
--
-- What 00002 and 00003 built was a judgement per (evidencia, criterio,
-- student) on the AD/A/B/C scale, on the reading that RVM 094-2020 5.1.1.3 p.3
-- values evidence *through* the criterio. That sentence is true and this table
-- was still the wrong shape for it. "Through" describes how a teacher reads a
-- piece of work; it does not make the criterio a thing that carries a level of
-- its own. The norm asks for exactly one recorded judgement, the nivel de logro
-- per competencia (competency_term_levels), and everything else in the period
-- is material the teacher weighs to arrive at it.
--
-- Keeping the table had a concrete cost, not just a conceptual one. It gave the
-- app two ordinal records that looked alike and meant different things, and it
-- invited the arithmetic the whole design exists to refuse: three criterios at
-- A "adding up" to an A. It also made marking a class an N x M grid, which is
-- what the UI had become.
--
-- What stays:
--   evaluation_criteria   the criterios themselves, still written by teachers
--   assessment_criteria   which criterios a piece of evidencia speaks to
--
-- Those two are the whole of the criterio layer now: a criterio says what to
-- look at in a piece of work, and an evidencia is tagged with the ones it
-- shows. That tag is what lets the student screen group evidence under the
-- competencia it informs.
--
-- The demo tenant is the only place rows exist, so this drops rather than
-- archives. A deployment holding real evaluation_criterion_scores must archive
-- the table instead (rename it out of the way) and take that up with the IE,
-- because those rows are part of a student's academic history.

-- +goose Up

drop trigger if exists sync_denormalised on evaluation_criterion_scores;
drop trigger if exists forbid_mutation on evaluation_criterion_scores;
drop function if exists app.sync_criterion_score_denormalised();
drop function if exists app.forbid_criterion_score_mutation();

drop table if exists evaluation_criterion_scores;

comment on table assessment_criteria is
  'Which criterios de evaluación a piece of evidencia speaks to: the teacher''s note of what to look at in this work. It is a tag, not a score. No level is ever recorded per criterio: the one recorded judgement is the nivel de logro of the competencia, in competency_term_levels, asserted by the teacher after reading the period''s evidence. The weight column is vestigial and read by nothing.';

-- +goose Down

-- The rows are not recoverable; only the shape is. Anything that depended on
-- the old data has to be restored from a dump.
create table evaluation_criterion_scores (
  id             uuid primary key default gen_random_uuid(),
  tenant_id      uuid not null references tenants (id),
  assessment_id  uuid,
  criterion_id   uuid not null,
  student_id     uuid not null,
  class_id       uuid,
  term_id        uuid,
  scale_level_id uuid not null,
  note           text,
  source         text not null default 'manual'
    check (source in ('manual', 'bulk', 'import', 'voice', 'auto')),
  recorded_by_id uuid not null,
  recorded_at    timestamptz not null default now(),
  supersedes_id  uuid,
  superseded_at  timestamptz,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now(),
  deleted_at     timestamptz,
  constraint ecs_tenant_id_key unique (tenant_id, id),
  constraint ecs_assessment_fk foreign key (tenant_id, assessment_id)
    references assessments (tenant_id, id),
  constraint ecs_criterion_fk foreign key (tenant_id, criterion_id)
    references evaluation_criteria (tenant_id, id),
  constraint ecs_student_fk foreign key (tenant_id, student_id)
    references students (tenant_id, id),
  constraint ecs_class_fk foreign key (tenant_id, class_id)
    references classes (tenant_id, id),
  constraint ecs_term_fk foreign key (tenant_id, term_id)
    references terms (tenant_id, id),
  constraint ecs_level_fk foreign key (tenant_id, scale_level_id)
    references grade_scale_levels (tenant_id, id),
  constraint ecs_recorded_by_fk foreign key (tenant_id, recorded_by_id)
    references teachers (tenant_id, id),
  constraint ecs_supersedes_fk foreign key (tenant_id, supersedes_id)
    references evaluation_criterion_scores (tenant_id, id),
  constraint ecs_scope_supplied_without_assessment
    check (assessment_id is not null or (class_id is not null and term_id is not null))
);

create unique index ecs_live_assessment_key
  on evaluation_criterion_scores (assessment_id, criterion_id, student_id)
  where assessment_id is not null and superseded_at is null and deleted_at is null;

create unique index ecs_live_term_key
  on evaluation_criterion_scores (criterion_id, student_id, term_id)
  where assessment_id is null and superseded_at is null and deleted_at is null;

select app.enable_tenant_rls('evaluation_criterion_scores');
select app.attach_updated_at('evaluation_criterion_scores');

comment on table assessment_criteria is null;
