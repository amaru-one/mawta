-- Assessments and scores.
--
-- Constraint 4 of the design brief lives here: a score row holds the raw value
-- and the assessment's maximum, and nothing else. No percentage, no weighted
-- contribution, no late penalty already applied. Screen 04's "10 / 20 · 50%"
-- stores the 10 and the 20; the 50% is arithmetic.

-- +goose Up

-- ---------------------------------------------------------------------------
-- assessment_templates
-- ---------------------------------------------------------------------------
-- A teacher who gives the same quiz to 5to A and 5to B authors it once and
-- instantiates it per class. The instances grade independently.
create table assessment_templates (
  id                         uuid primary key default gen_random_uuid(),
  tenant_id                  uuid not null references tenants (id),
  course_id                  uuid,
  scheme_id                  uuid not null,
  component_id               uuid not null,
  author_teacher_id          uuid,
  title                      text not null,
  description                text,
  kind                       text not null default 'otro'
                               check (kind in ('quiz', 'examen', 'practica', 'tarea', 'proyecto',
                                               'exposicion', 'participacion', 'rubrica', 'otro')),
  max_score                  numeric(8, 4) not null check (max_score > 0),
  weight_within_component    numeric(9, 6) not null default 1 check (weight_within_component > 0),
  allows_retake              boolean not null default true,
  is_shared                  boolean not null default false,
  created_at                 timestamptz not null default now(),
  updated_at                 timestamptz not null default now(),
  deleted_at                 timestamptz,
  constraint assessment_templates_tenant_id_key unique (tenant_id, id),
  constraint assessment_templates_course_fk foreign key (tenant_id, course_id)
    references courses (tenant_id, id),
  constraint assessment_templates_component_fk foreign key (tenant_id, scheme_id, component_id)
    references grading_components (tenant_id, scheme_id, id),
  constraint assessment_templates_author_fk foreign key (tenant_id, author_teacher_id)
    references teachers (tenant_id, id)
);

comment on table assessment_templates is 'A reusable assessment definition. Instantiated into one assessments row per class, so a quiz given to three sections is one authoring act and three independent grade columns.';
comment on column assessment_templates.course_id is 'Restricts the template to one course. Null makes it available across the teacher''s classes, which is what a generic "Participación" template wants.';
comment on column assessment_templates.is_shared is 'Whether other teachers in the school may instantiate it. Personal drafts stay private.';

create index assessment_templates_course_idx
  on assessment_templates (tenant_id, course_id) where deleted_at is null;
create index assessment_templates_author_idx
  on assessment_templates (author_teacher_id) where deleted_at is null;

select app.enable_tenant_rls('assessment_templates');
select app.attach_updated_at('assessment_templates');
select app.attach_soft_delete_guard('assessment_templates');

create table assessment_template_competencies (
  id             uuid primary key default gen_random_uuid(),
  tenant_id      uuid not null references tenants (id),
  template_id    uuid not null,
  competency_id  uuid not null,
  weight         numeric(9, 6) not null default 1 check (weight > 0),
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now(),
  deleted_at     timestamptz,
  constraint atc_template_fk foreign key (tenant_id, template_id)
    references assessment_templates (tenant_id, id),
  constraint atc_competency_fk foreign key (tenant_id, competency_id)
    references competencies (tenant_id, id)
);

comment on table assessment_template_competencies is 'Default competency links copied onto each instantiated assessment. Editing the template does not retro-edit instances already being graded.';

create unique index atc_key on assessment_template_competencies (template_id, competency_id)
  where deleted_at is null;

select app.enable_tenant_rls('assessment_template_competencies');
select app.attach_updated_at('assessment_template_competencies');
select app.attach_soft_delete_guard('assessment_template_competencies');

-- ---------------------------------------------------------------------------
-- assessments
-- ---------------------------------------------------------------------------
create table assessments (
  id                        uuid primary key default gen_random_uuid(),
  tenant_id                 uuid not null references tenants (id),
  class_id                  uuid not null,
  term_id                   uuid not null,
  template_id               uuid,
  scheme_id                 uuid not null,
  component_id              uuid not null,
  unit_id                   uuid,
  session_id                uuid,
  title                     text not null,
  description               text,
  kind                      text not null default 'otro'
                              check (kind in ('quiz', 'examen', 'practica', 'tarea', 'proyecto',
                                              'exposicion', 'participacion', 'rubrica', 'otro')),
  max_score                 numeric(8, 4) not null check (max_score > 0),
  weight_within_component   numeric(9, 6) not null default 1 check (weight_within_component > 0),
  due_at                    timestamptz,
  status                    text not null default 'draft'
                              check (status in ('draft', 'published', 'closed', 'cancelled')),
  published_at              timestamptz,
  closed_at                 timestamptz,
  allows_retake             boolean not null default true,
  late_penalty_pct_per_day  numeric(5, 4) check (late_penalty_pct_per_day between 0 and 1),
  late_penalty_max_pct      numeric(5, 4) check (late_penalty_max_pct between 0 and 1),
  created_by_id             uuid,
  created_at                timestamptz not null default now(),
  updated_at                timestamptz not null default now(),
  deleted_at                timestamptz,
  constraint assessments_tenant_id_key unique (tenant_id, id),
  constraint assessments_class_fk foreign key (tenant_id, class_id)
    references classes (tenant_id, id),
  constraint assessments_term_fk foreign key (tenant_id, term_id)
    references terms (tenant_id, id),
  constraint assessments_template_fk foreign key (tenant_id, template_id)
    references assessment_templates (tenant_id, id),
  constraint assessments_component_fk foreign key (tenant_id, scheme_id, component_id)
    references grading_components (tenant_id, scheme_id, id),
  constraint assessments_unit_fk foreign key (tenant_id, unit_id)
    references units (tenant_id, id),
  constraint assessments_session_fk foreign key (tenant_id, session_id)
    references class_sessions (tenant_id, id),
  constraint assessments_created_by_fk foreign key (tenant_id, created_by_id)
    references teachers (tenant_id, id),
  constraint assessments_published_consistent
    check ((status in ('published', 'closed')) <= (published_at is not null)),
  constraint assessments_closed_consistent
    check ((status = 'closed') = (closed_at is not null))
);

comment on table assessments is 'A graded item for one class: "Quiz 1", "Examen final", "Participación". Screen 04 lists these under EVALUACIONES with the component weight beside each. "Añadir evaluación" inserts here.';
comment on column assessments.scheme_id is 'Denormalised from the component so the composite FK can prove the component belongs to the intended scheme. Set from the class''s resolved grading policy at creation.';
comment on column assessments.max_score is 'The denominator shown on screen 04 as the "20" in "10 / 20". Copied onto every score row, so re-scoring an assessment out of 25 later cannot silently reinterpret grades already entered.';
comment on column assessments.weight_within_component is 'Relative weight against other assessments in the same component, used when the component aggregates by weighted_mean. Not a share of the final grade — that is the component''s weight.';
comment on column assessments.due_at is 'Deadline. Drives scores.late_days, and defines which assessments count in the "expected grades so far" denominator behind screen 02''s "Notas reg." tile.';
comment on column assessments.status is 'draft is invisible to grade computation. An assessment must be published before it contributes unevaluated weight to screen 04''s "falta 40%".';
comment on column assessments.late_penalty_pct_per_day is 'Per-assessment override of the scheme version''s late policy. Null inherits.';

-- Screen 04: this student's assessments for this class and term, in component order.
create index assessments_class_term_idx
  on assessments (class_id, term_id, status) where deleted_at is null;
-- Screen 02 "Notas reg." and "Pendientes": published assessments already due.
create index assessments_due_idx
  on assessments (tenant_id, due_at)
  where status = 'published' and deleted_at is null;
create index assessments_component_idx on assessments (component_id) where deleted_at is null;
create index assessments_session_idx on assessments (session_id) where session_id is not null and deleted_at is null;

select app.enable_tenant_rls('assessments');
select app.attach_updated_at('assessments');
select app.attach_soft_delete_guard('assessments');

create table assessment_competencies (
  id             uuid primary key default gen_random_uuid(),
  tenant_id      uuid not null references tenants (id),
  assessment_id  uuid not null,
  competency_id  uuid not null,
  weight         numeric(9, 6) not null default 1 check (weight > 0),
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now(),
  deleted_at     timestamptz,
  constraint assessment_competencies_assessment_fk foreign key (tenant_id, assessment_id)
    references assessments (tenant_id, id),
  constraint assessment_competencies_competency_fk foreign key (tenant_id, competency_id)
    references competencies (tenant_id, id)
);

comment on table assessment_competencies is 'Which competencies an assessment evidences. The path from a raw score to competency-level reporting, which MINEDU requires even though the six screens do not show it yet.';

create unique index assessment_competencies_key
  on assessment_competencies (assessment_id, competency_id) where deleted_at is null;
create index assessment_competencies_competency_idx on assessment_competencies (competency_id);

select app.enable_tenant_rls('assessment_competencies');
select app.attach_updated_at('assessment_competencies');
select app.attach_soft_delete_guard('assessment_competencies');

-- ---------------------------------------------------------------------------
-- retake_authorizations
-- ---------------------------------------------------------------------------
create table retake_authorizations (
  id                     uuid primary key default gen_random_uuid(),
  tenant_id              uuid not null references tenants (id),
  assessment_id          uuid not null,
  student_id             uuid not null,
  kind                   text not null
                           check (kind in ('recuperacion', 'subsanacion', 'makeup', 'ampliacion')),
  reason                 text,
  window_starts_at       timestamptz,
  window_ends_at         timestamptz,
  max_normalized_cap     numeric(6, 5) check (max_normalized_cap between 0 and 1),
  status                 text not null default 'open'
                           check (status in ('open', 'used', 'expired', 'revoked')),
  authorized_by_id       uuid not null,
  authorized_at          timestamptz not null default now(),
  created_at             timestamptz not null default now(),
  updated_at             timestamptz not null default now(),
  deleted_at             timestamptz,
  constraint retake_authorizations_tenant_id_key unique (tenant_id, id),
  constraint retake_authorizations_assessment_fk foreign key (tenant_id, assessment_id)
    references assessments (tenant_id, id),
  constraint retake_authorizations_student_fk foreign key (tenant_id, student_id)
    references students (tenant_id, id),
  constraint retake_authorizations_authorized_by_fk foreign key (tenant_id, authorized_by_id)
    references teachers (tenant_id, id),
  constraint retake_authorizations_window_valid
    check (window_ends_at is null or window_starts_at is null or window_ends_at > window_starts_at)
);

comment on table retake_authorizations is 'MINORS'' PERSONAL DATA (academic). Who authorised a recuperación or subsanación, for which student, within which window, capped at what. Peruvian retake mechanisms are legally required, and the authorisation is as auditable as the resulting score.';
comment on column retake_authorizations.kind is 'Kept in Spanish deliberately. recuperación (re-sit within the term) and subsanación (clearing a failed course from a previous year) are distinct legal instruments, not two words for a retake.';
comment on column retake_authorizations.max_normalized_cap is 'Ceiling on the retake result, overriding the scheme version''s default cap. Commonly the passing threshold and no higher.';

create index retake_authorizations_student_idx
  on retake_authorizations (student_id, assessment_id) where deleted_at is null;

select app.enable_tenant_rls('retake_authorizations');
select app.attach_updated_at('retake_authorizations');
select app.attach_soft_delete_guard('retake_authorizations');

-- ---------------------------------------------------------------------------
-- scores
-- ---------------------------------------------------------------------------
create table scores (
  id                        uuid primary key default gen_random_uuid(),
  tenant_id                 uuid not null references tenants (id),
  assessment_id             uuid not null,
  student_id                uuid not null,
  class_id                  uuid not null,
  term_id                   uuid not null,
  attempt_number            smallint not null default 1 check (attempt_number >= 1),
  attempt_kind              text not null default 'original'
                              check (attempt_kind in ('original', 'recuperacion', 'subsanacion', 'makeup')),
  retake_authorization_id   uuid,
  status                    text not null default 'graded'
                              check (status in ('graded', 'excused', 'absent', 'not_submitted')),
  raw_value                 numeric(8, 4),
  max_value                 numeric(8, 4) not null check (max_value > 0),
  late_days                 smallint not null default 0 check (late_days >= 0),
  feedback                  text,
  source                    text not null default 'manual'
                              check (source in ('manual', 'bulk', 'import', 'voice', 'auto')),
  recorded_by_id            uuid not null,
  recorded_at               timestamptz not null default now(),
  supersedes_id             uuid,
  superseded_at             timestamptz,
  created_at                timestamptz not null default now(),
  updated_at                timestamptz not null default now(),
  deleted_at                timestamptz,
  constraint scores_tenant_id_key unique (tenant_id, id),
  constraint scores_assessment_fk foreign key (tenant_id, assessment_id)
    references assessments (tenant_id, id),
  constraint scores_student_fk foreign key (tenant_id, student_id)
    references students (tenant_id, id),
  constraint scores_class_fk foreign key (tenant_id, class_id)
    references classes (tenant_id, id),
  constraint scores_term_fk foreign key (tenant_id, term_id)
    references terms (tenant_id, id),
  constraint scores_recorded_by_fk foreign key (tenant_id, recorded_by_id)
    references teachers (tenant_id, id),
  constraint scores_retake_fk foreign key (tenant_id, retake_authorization_id)
    references retake_authorizations (tenant_id, id),
  constraint scores_supersedes_fk foreign key (tenant_id, supersedes_id)
    references scores (tenant_id, id),
  constraint scores_value_matches_status
    check ((status = 'graded') = (raw_value is not null)),
  constraint scores_value_in_range
    check (raw_value is null or (raw_value >= 0 and raw_value <= max_value)),
  constraint scores_attempt_kind_consistent
    check ((attempt_number = 1) = (attempt_kind = 'original'))
);

comment on table scores is
  'MINORS'' PERSONAL DATA (academic). Append-only. Holds the raw value and the assessment maximum and nothing derived — no percentage, no weighted contribution, no late penalty already deducted. Correcting a score inserts a new row that supersedes the old one; a retake inserts a new attempt alongside it. Nothing here is ever updated in place or hard-deleted.';

comment on column scores.attempt_number is 'Attempt 1 is the original sitting. A recuperación is attempt 2 against the same assessment, never an overwrite: the fact that a student needed a retake is one of the strongest risk signals in the schema and must survive.';
comment on column scores.attempt_kind is 'Which legal instrument produced this attempt. Constrained to agree with attempt_number so attempt 1 is always the original.';
comment on column scores.status is 'excused excludes the row from the denominator entirely; absent and not_submitted are scored per the scheme version''s absent_counts_as. This is why an excused score is a row and not a missing one — a missing row means the teacher has not graded yet ("Sin evaluar" on screen 04).';
comment on column scores.raw_value is 'The number the teacher wrote. Null unless status = graded.';
comment on column scores.max_value is 'Copied from the assessment at write time. Frozen here so that changing an assessment''s max later cannot reinterpret grades already entered.';
comment on column scores.late_days is 'Whole days past due_at. The penalty is applied at computation time from the scheme version''s policy, never baked into raw_value, so a corrected late policy re-grades correctly.';
comment on column scores.supersedes_id is 'The row this one replaces after a correction. The link points backwards only, deliberately: a forward superseded_by_id would have to be written at the same moment as superseded_at, but the replacement row cannot exist until the old one is closed, so the pair is unsatisfiable. Follow supersedes_id backwards for the full history of a single grade.';
comment on column scores.superseded_at is 'Set when a newer row replaces this one. A row with superseded_at null and deleted_at null is the live value. Written before the replacement is inserted — see scores_live_attempt_key.';
comment on column scores.class_id is 'Denormalised from the assessment. Maintained by trigger; lets per-class grading-coverage aggregates skip a join.';
comment on column scores.term_id is 'Denormalised from the assessment. Every grade aggregate in the product is term-scoped.';

-- Exactly one live row per (assessment, student, attempt). Correcting a score is
-- therefore ordered: close the old row (set superseded_at), then insert the
-- replacement. A partial index cannot be DEFERRABLE, so the two cannot overlap.
create unique index scores_live_attempt_key
  on scores (assessment_id, student_id, attempt_number)
  where superseded_at is null and deleted_at is null;
-- Screen 02 "Pendientes · 3 alumnos": who in this assessment has no live score.
create index scores_assessment_idx
  on scores (assessment_id) where superseded_at is null and deleted_at is null;
-- Screen 04: one student's live scores for a class and term.
create index scores_student_term_idx
  on scores (student_id, term_id) where superseded_at is null and deleted_at is null;
-- Screen 02 "Notas reg." coverage: live scores for a class in a term.
create index scores_class_term_idx
  on scores (class_id, term_id) where superseded_at is null and deleted_at is null;
-- Risk signal: students who have ever needed a retake.
create index scores_retake_idx
  on scores (tenant_id, student_id) where attempt_number > 1 and deleted_at is null;
create index scores_supersedes_idx on scores (supersedes_id) where supersedes_id is not null;

-- Denormalised columns are copied from the assessment, never supplied. The
-- closed-term and draft-assessment guards live in this same function on
-- purpose: they depend on term_id, which does not exist on the incoming row.
-- As separate BEFORE INSERT triggers they would fire in name order, and a guard
-- that ran before this one would silently read a null term and pass.
-- +goose StatementBegin
create or replace function app.sync_score_denormalised() returns trigger
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

    -- A closed term stops accepting grades. This is what makes a closed report
    -- card real rather than a convention.
    if v_term_status in ('closed', 'archived') then
      raise exception 'term % is closed; grades cannot be added or changed', new.term_id
        using errcode = 'restrict_violation',
              hint = 'Reopen the term explicitly, which is an audited action, or record the change as a subsanación in the current term.';
    end if;

    return new;
  end;
  $fn$;
-- +goose StatementEnd

create trigger sync_denormalised before insert on scores
  for each row execute function app.sync_score_denormalised();

-- Constraint 5: grades are temporal. A score is never updated in place.
-- +goose StatementBegin
create or replace function app.forbid_score_mutation() returns trigger
  language plpgsql
  as $fn$
  begin
    if new.assessment_id  is distinct from old.assessment_id
       or new.student_id  is distinct from old.student_id
       or new.attempt_number is distinct from old.attempt_number
       or new.attempt_kind   is distinct from old.attempt_kind
       or new.status         is distinct from old.status
       or new.raw_value      is distinct from old.raw_value
       or new.max_value      is distinct from old.max_value
       or new.late_days      is distinct from old.late_days
       or new.recorded_by_id is distinct from old.recorded_by_id
       or new.recorded_at    is distinct from old.recorded_at then
      raise exception 'scores are append-only (score %); insert a superseding row instead of updating', old.id
        using errcode = 'restrict_violation',
              hint = 'Stamp superseded_at on this row FIRST, then insert the replacement with supersedes_id set. scores_live_attempt_key is a partial unique index and cannot be deferred, so two live rows for one attempt never coexist, even briefly.';
    end if;
    return new;
  end;
  $fn$;
-- +goose StatementEnd

create trigger forbid_mutation before update on scores
  for each row execute function app.forbid_score_mutation();

select app.enable_tenant_rls('scores');
select app.attach_updated_at('scores');
select app.attach_soft_delete_guard('scores');

-- +goose Down

drop trigger if exists forbid_mutation on scores;
drop function if exists app.forbid_score_mutation();
drop trigger if exists sync_denormalised on scores;
drop function if exists app.sync_score_denormalised();
drop table if exists scores;
drop table if exists retake_authorizations;
drop table if exists assessment_competencies;
drop table if exists assessments;
drop table if exists assessment_template_competencies;
drop table if exists assessment_templates;
