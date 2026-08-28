-- Criterio-based evaluation, per RVM 094-2020 (mod. RVM 048-2024).
--
-- The norm determines achievement by the teacher's judgement of evidence
-- against criterios de evaluación, one set per competencia. There is no
-- weighted average anywhere in it. Migration 00002 built the criterio layer
-- but at the wrong grain for that: evaluation_criterion_scores.assessment_id
-- was `not null` and ecs_live_key was unique on
-- (assessment_id, criterion_id, student_id), so a criterio level could only
-- exist as a per-quiz cell. The norm's grain is one level per criterio per
-- *periodo*, judged from everything the period produced.
--
-- This migration:
--   1. Makes assessment_id nullable, so a criterio level can be either
--      evidence from one specific assessment or the teacher's holistic
--      judgement for the period. Two live keys, one per shape.
--   2. Drops the projection columns on computed_grades. computed_grades
--      itself survives as the school's own internal system (D.S. 009-2006-ED
--      art. 37.4.f) -- but never as the official record, and never as a
--      forecast.
--   3. Drops the whole predictive subsystem: risk_rules, risk_flags,
--      risk_flag_evidence, and notifications.risk_flag_id.
--
-- Deliberately kept: competency_year_snapshots and year_final_situations.
-- Those are the official year-end acta records the norm requires (5.1.3), not
-- forecasts. They are left without a writer by this change rather than
-- dropped, because the concept is normative and the tables are correct.

-- +goose Up

-- ---------------------------------------------------------------------------
-- 1. evaluation_criterion_scores: allow a period-grain criterio level
-- ---------------------------------------------------------------------------

alter table evaluation_criterion_scores alter column assessment_id drop not null;

-- With no assessment to copy from, the caller must supply the scope itself.
alter table evaluation_criterion_scores
  add constraint ecs_scope_supplied_without_assessment
  check (assessment_id is not null or (class_id is not null and term_id is not null));

comment on column evaluation_criterion_scores.assessment_id is
  'The assessment this level was judged from, when it came from one. Null for the teacher''s holistic judgement of the criterio over the whole periodo -- which is the grain RVM 094-2020 actually works in, since the judgement rests on all of the period''s evidence rather than on a single quiz.';
comment on column evaluation_criterion_scores.class_id is
  'Denormalised from the assessment when there is one; supplied by the caller otherwise (ecs_scope_supplied_without_assessment).';
comment on column evaluation_criterion_scores.term_id is
  'Denormalised from the assessment when there is one; supplied by the caller otherwise. The periodo the judgement covers.';

comment on table evaluation_criterion_scores is
  'MINORS'' PERSONAL DATA (academic). Append-only. One student''s level against one criterio de evaluación, on the tenant''s AD/A/B/C scale (grade_scale_levels) -- the same scale competency_term_levels reports on. Two shapes: with assessment_id, the level read off one specific piece of evidence; without it, the teacher''s judgement of that criterio for the whole periodo. Neither is the official record: competency_term_levels is, and it is asserted by the teacher looking at these, never computed from them.';

-- The old key only ever covered the assessment-anchored shape; scope it
-- explicitly so it stops being a partial index over a now-nullable column
-- that silently admits unlimited period-grain rows.
drop index ecs_live_key;

create unique index ecs_live_assessment_key
  on evaluation_criterion_scores (assessment_id, criterion_id, student_id)
  where assessment_id is not null and superseded_at is null and deleted_at is null;

-- One live period-level per criterio per student per term. This is the row
-- the teacher fills in and the one the competency assertion is judged against.
create unique index ecs_live_term_key
  on evaluation_criterion_scores (criterion_id, student_id, term_id)
  where assessment_id is null and superseded_at is null and deleted_at is null;

-- The denormalisation trigger has to stop assuming an assessment exists. The
-- closed-term and draft-assessment guards stay exactly where they were, in
-- this same function, for the reason 00002 documented: as separate BEFORE
-- INSERT triggers they would fire in name order and read a still-null term.
-- +goose StatementBegin
create or replace function app.sync_criterion_score_denormalised() returns trigger
  language plpgsql
  as $fn$
  declare
    v_assessment_status text;
    v_term_status       text;
  begin
    if new.assessment_id is not null then
      select a.class_id, a.term_id, a.status, t.status
        into new.class_id, new.term_id, v_assessment_status, v_term_status
        from assessments a
        join terms t on t.id = a.term_id
       where a.id = new.assessment_id
         and a.tenant_id = new.tenant_id;

      if not found then
        raise exception 'assessment % not found in tenant %', new.assessment_id, new.tenant_id
          using errcode = 'foreign_key_violation';
      end if;

      if v_assessment_status = 'draft' then
        raise exception 'assessment % is still a draft and cannot be scored', new.assessment_id
          using errcode = 'check_violation';
      end if;
    else
      -- Period-grain judgement: the caller supplied class_id and term_id
      -- (ecs_scope_supplied_without_assessment guarantees they are present).
      select t.status into v_term_status
        from terms t
       where t.id = new.term_id
         and t.tenant_id = new.tenant_id;

      if not found then
        raise exception 'term % not found in tenant %', new.term_id, new.tenant_id
          using errcode = 'foreign_key_violation';
      end if;
    end if;

    if v_term_status in ('closed', 'archived') then
      raise exception 'term % is closed; levels cannot be added or changed', new.term_id
        using errcode = 'restrict_violation',
              hint = 'Reopen the term explicitly, which is an audited action.';
    end if;

    return new;
  end;
  $fn$;
-- +goose StatementEnd

-- ---------------------------------------------------------------------------
-- 2. computed_grades: the forecast goes
-- ---------------------------------------------------------------------------

alter table computed_grades drop constraint computed_grades_projection_ordered;
alter table computed_grades drop column projected_min_normalized;
alter table computed_grades drop column projected_max_normalized;

comment on table computed_grades is
  'MINORS'' PERSONAL DATA (academic, derived). NOT the official record. The school''s own internal weighted system (D.S. 009-2006-ED art. 37.4.f lets a private IE run one), kept for schools that want a numeric mark alongside the norm. RVM 094-2020 determines achievement per competencia from the teacher''s judgement against criterios -- see competency_term_levels, which is the official record and is never derived from this table. One row per student per class per term, rewritten as a new row whenever the result changes.';

-- ---------------------------------------------------------------------------
-- 3. The predictive subsystem goes entirely
-- ---------------------------------------------------------------------------

alter table notifications drop constraint notifications_alert_has_evidence;
alter table notifications drop column risk_flag_id;

drop table risk_flag_evidence;
drop table risk_flags;
drop table risk_rules;

-- +goose Down

-- ---------------------------------------------------------------------------
-- 3. Restore the predictive subsystem
-- ---------------------------------------------------------------------------

create table risk_rules (
  id           uuid primary key default gen_random_uuid(),
  tenant_id    uuid not null references tenants (id),
  code         text not null,
  name         text not null,
  description  text,
  kind         text not null default 'rule' check (kind in ('rule', 'model')),
  version      text not null default '1',
  params       jsonb not null default '{}'::jsonb,
  severity     text not null default 'medium' check (severity in ('info', 'low', 'medium', 'high')),
  window_days  smallint check (window_days > 0),
  is_active    boolean not null default true,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now(),
  deleted_at   timestamptz,
  constraint risk_rules_tenant_id_key unique (tenant_id, id)
);

create unique index risk_rules_tenant_code_version_key
  on risk_rules (tenant_id, code, version) where deleted_at is null;

select app.enable_tenant_rls('risk_rules');
select app.attach_updated_at('risk_rules');
select app.attach_soft_delete_guard('risk_rules');

create table risk_flags (
  id                uuid primary key default gen_random_uuid(),
  tenant_id         uuid not null references tenants (id),
  student_id        uuid not null,
  class_id          uuid,
  rule_id           uuid not null,
  rule_version      text not null,
  severity          text not null default 'medium' check (severity in ('info', 'low', 'medium', 'high')),
  reason_code       text not null,
  reason_text       text not null,
  model_score       numeric(6, 5) check (model_score between 0 and 1),
  opened_at         timestamptz not null default now(),
  last_evaluated_at timestamptz not null default now(),
  status            text not null default 'active'
                      check (status in ('active', 'resolved', 'dismissed', 'expired')),
  resolved_at       timestamptz,
  dismissed_at      timestamptz,
  dismissed_by_id   uuid,
  dismissal_reason  text check (dismissal_reason in ('not_a_concern', 'already_handled', 'incorrect_data', 'wrong_call', 'other')),
  dismissal_note    text,
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now(),
  deleted_at        timestamptz,
  constraint risk_flags_tenant_id_key unique (tenant_id, id),
  constraint risk_flags_student_fk foreign key (tenant_id, student_id)
    references students (tenant_id, id),
  constraint risk_flags_class_fk foreign key (tenant_id, class_id)
    references classes (tenant_id, id),
  constraint risk_flags_rule_fk foreign key (tenant_id, rule_id)
    references risk_rules (tenant_id, id),
  constraint risk_flags_dismissed_by_fk foreign key (tenant_id, dismissed_by_id)
    references teachers (tenant_id, id),
  constraint risk_flags_dismissed_consistent
    check ((status = 'dismissed') = (dismissed_at is not null)),
  constraint risk_flags_dismissed_has_actor
    check (dismissed_at is null or dismissed_by_id is not null),
  constraint risk_flags_resolved_consistent
    check ((status = 'resolved') = (resolved_at is not null))
);

create unique index risk_flags_open_key
  on risk_flags (student_id, coalesce(class_id, '00000000-0000-0000-0000-000000000000'::uuid), rule_id)
  where status = 'active' and deleted_at is null;
create index risk_flags_class_active_idx
  on risk_flags (class_id, severity) where status = 'active' and deleted_at is null;
create index risk_flags_tenant_active_idx
  on risk_flags (tenant_id, student_id) where status = 'active' and deleted_at is null;
create index risk_flags_dismissed_idx
  on risk_flags (rule_id, dismissed_at) where dismissed_at is not null;

select app.enable_tenant_rls('risk_flags');
select app.attach_updated_at('risk_flags');
select app.attach_soft_delete_guard('risk_flags');

create table risk_flag_evidence (
  id            uuid primary key default gen_random_uuid(),
  tenant_id     uuid not null references tenants (id),
  risk_flag_id  uuid not null,
  entity_type   text not null
                  check (entity_type in ('attendance_record', 'score', 'computed_grade',
                                         'session_observation', 'voice_note', 'class_session',
                                         'competency_term_level')),
  entity_id     uuid not null,
  occurred_at   timestamptz not null,
  detail        jsonb not null default '{}'::jsonb,
  weight        numeric(6, 5) check (weight between 0 and 1),
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now(),
  constraint rfe_flag_fk foreign key (tenant_id, risk_flag_id)
    references risk_flags (tenant_id, id) on delete cascade
);

create index rfe_flag_idx on risk_flag_evidence (risk_flag_id, occurred_at desc);
create index rfe_entity_idx on risk_flag_evidence (entity_type, entity_id);

select app.enable_tenant_rls('risk_flag_evidence');
select app.attach_updated_at('risk_flag_evidence');

alter table notifications add column risk_flag_id uuid;
alter table notifications add constraint notifications_risk_flag_fk
  foreign key (tenant_id, risk_flag_id) references risk_flags (tenant_id, id);
alter table notifications add constraint notifications_alert_has_evidence
  check (kind <> 'alert' or source = 'teacher' or risk_flag_id is not null);

-- ---------------------------------------------------------------------------
-- 2. Restore the projection columns
-- ---------------------------------------------------------------------------

alter table computed_grades add column projected_min_normalized numeric(6, 5)
  check (projected_min_normalized between 0 and 1);
alter table computed_grades add column projected_max_normalized numeric(6, 5)
  check (projected_max_normalized between 0 and 1);
alter table computed_grades add constraint computed_grades_projection_ordered
  check (projected_max_normalized is null or projected_min_normalized is null
         or projected_max_normalized >= projected_min_normalized);

comment on table computed_grades is
  'MINORS'' PERSONAL DATA (academic, derived). One row per student per class per term, rewritten as a new row whenever the result changes. Records which grading scheme version produced it, so a grade can always be re-explained against the rules that were in force — not the rules in force today.';

-- ---------------------------------------------------------------------------
-- 1. evaluation_criterion_scores back to the assessment-only grain
-- ---------------------------------------------------------------------------

-- Period-grain rows cannot survive a column that is about to go back to NOT
-- NULL; they have no assessment to attribute them to.
delete from evaluation_criterion_scores where assessment_id is null;

drop index ecs_live_term_key;
drop index ecs_live_assessment_key;

create unique index ecs_live_key
  on evaluation_criterion_scores (assessment_id, criterion_id, student_id)
  where superseded_at is null and deleted_at is null;

alter table evaluation_criterion_scores drop constraint ecs_scope_supplied_without_assessment;
alter table evaluation_criterion_scores alter column assessment_id set not null;

comment on column evaluation_criterion_scores.assessment_id is null;
comment on column evaluation_criterion_scores.class_id is 'Denormalised from the assessment. Maintained by trigger.';
comment on column evaluation_criterion_scores.term_id is 'Denormalised from the assessment. Maintained by trigger.';

comment on table evaluation_criterion_scores is
  'MINORS'' PERSONAL DATA (academic). Append-only. One student''s rubric-level result against one criterio de evaluación on one assessment, on the tenant''s existing AD/A/B/C scale (grade_scale_levels) -- the same scale competency_term_levels reports on. Evidence a teacher can lean on when asserting a nivel de logro; never itself the official record. Correcting a result inserts a new row that supersedes the old one, exactly like scores.';

-- +goose StatementBegin
create or replace function app.sync_criterion_score_denormalised() returns trigger
  language plpgsql
  as $fn$
  declare
    v_assessment_status text;
    v_term_status       text;
  begin
    select a.class_id, a.term_id, a.status, t.status
      into new.class_id, new.term_id, v_assessment_status, v_term_status
      from assessments a
      join terms t on t.id = a.term_id
     where a.id = new.assessment_id
       and a.tenant_id = new.tenant_id;

    if not found then
      raise exception 'assessment % not found in tenant %', new.assessment_id, new.tenant_id
        using errcode = 'foreign_key_violation';
    end if;

    if v_assessment_status = 'draft' then
      raise exception 'assessment % is still a draft and cannot be scored', new.assessment_id
        using errcode = 'check_violation';
    end if;

    if v_term_status in ('closed', 'archived') then
      raise exception 'term % is closed; grades cannot be added or changed', new.term_id
        using errcode = 'restrict_violation',
              hint = 'Reopen the term explicitly, which is an audited action, or record the change as a subsanación in the current term.';
    end if;

    return new;
  end;
  $fn$;
-- +goose StatementEnd
