-- CNEB evaluation-criteria layer.
--
-- 00001 models competencias (área-level, RVM 094-2020 5.1.3) and the official
-- nivel de logro per competencia per periodo (competency_term_levels, RVM
-- 048-2024). Nothing between them: the CNEB chain is Área curricular ->
-- Competencia -> Capacidades (fixed, national, 2-4 per competencia) ->
-- Desempeños (national, per grado/ciclo) -> the teacher's own criterios de
-- evaluación (desempeños precisados, adapted to a unit/rubric). That last
-- layer -- what a teacher actually writes and loads -- had no table. This
-- migration adds it: capabilities, performance_standards, evaluation_criteria,
-- assessment_criteria and evaluation_criterion_scores. Nothing in 00001 is
-- touched; competency_term_levels is still asserted by teacher judgement, not
-- computed from this.

-- +goose Up

-- ---------------------------------------------------------------------------
-- capabilities
-- ---------------------------------------------------------------------------
create table capabilities (
  id            uuid primary key default gen_random_uuid(),
  tenant_id     uuid not null references tenants (id),
  competency_id uuid not null,
  code          text not null,
  name          text not null,
  description   text,
  sort_order    smallint not null default 0,
  is_active     boolean not null default true,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now(),
  deleted_at    timestamptz,
  constraint capabilities_tenant_id_key unique (tenant_id, id),
  constraint capabilities_competency_fk foreign key (tenant_id, competency_id)
    references competencies (tenant_id, id)
);

comment on table capabilities is 'A MINEDU capacidad: one of the 2-4 fixed sub-skills that make up a competencia (CNEB). Fixed and national in content, but authored per tenant like competencies -- a school loads its own copy of the national list; there is no cross-tenant sharing in this version.';
comment on column capabilities.code is 'National curriculum code where one exists, otherwise a school-local code. Not unique across tenants, matching competencies.code.';

create unique index capabilities_competency_code_key
  on capabilities (tenant_id, competency_id, code) where deleted_at is null;

select app.enable_tenant_rls('capabilities');
select app.attach_updated_at('capabilities');
select app.attach_soft_delete_guard('capabilities');

-- ---------------------------------------------------------------------------
-- performance_standards
-- ---------------------------------------------------------------------------
-- A desempeño is defined per ciclo in the CNEB (e.g. ciclo VI = 1.-2. de
-- secundaria), which can span more than one grade_levels row. Rather than a
-- range, this models one row per grade_level it applies to: simpler FK, at
-- the cost of duplicating a ciclo-wide desempeño across its grades. Matches
-- how the schema already prefers explicit rows over ranges except where an
-- exclusion constraint needs one (class_schedules, terms).
create table performance_standards (
  id             uuid primary key default gen_random_uuid(),
  tenant_id      uuid not null references tenants (id),
  capability_id  uuid not null,
  grade_level_id uuid,
  code           text not null,
  description    text not null,
  sort_order     smallint not null default 0,
  is_active      boolean not null default true,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now(),
  deleted_at     timestamptz,
  constraint performance_standards_tenant_id_key unique (tenant_id, id),
  constraint performance_standards_capability_fk foreign key (tenant_id, capability_id)
    references capabilities (tenant_id, id),
  constraint performance_standards_grade_level_fk foreign key (tenant_id, grade_level_id)
    references grade_levels (tenant_id, id)
);

comment on table performance_standards is 'A MINEDU desempeño: the national description of expected performance for one capacidad at one grade level. Null grade_level_id is reserved for a desempeño not yet tied to a specific grade (e.g. authored ahead of the grade_levels catalog); a ciclo-wide desempeño is one row per grade it covers, not a range.';
comment on column performance_standards.description is 'The desempeño text itself, verbatim from the CNEB or the school''s adaptation of it.';

create unique index performance_standards_grade_key
  on performance_standards (tenant_id, capability_id, grade_level_id, code)
  where deleted_at is null and grade_level_id is not null;
-- performance_standards_grade_key is partial on a nullable column, so a
-- desempeño not yet tied to a grade needs its own uniqueness, mirroring
-- competencies_transversal_code_key.
create unique index performance_standards_ungraded_key
  on performance_standards (tenant_id, capability_id, code)
  where deleted_at is null and grade_level_id is null;

select app.enable_tenant_rls('performance_standards');
select app.attach_updated_at('performance_standards');
select app.attach_soft_delete_guard('performance_standards');

-- ---------------------------------------------------------------------------
-- evaluation_criteria
-- ---------------------------------------------------------------------------
-- What a teacher actually writes and loads: a desempeño precisado for a unit
-- or rubric. Known gap, deliberately not enforced here: nothing checks that
-- performance_standard_id's capacidad belongs to competency_id. Cross-table
-- consistency like this exists elsewhere only via trigger (see
-- app.sync_score_denormalised); adding one is a flagged follow-up, not an
-- oversight.
create table evaluation_criteria (
  id                       uuid primary key default gen_random_uuid(),
  tenant_id                uuid not null references tenants (id),
  competency_id            uuid not null,
  performance_standard_id  uuid,
  unit_id                  uuid,
  code                     text,
  description              text not null,
  sort_order               smallint not null default 0,
  is_active                boolean not null default true,
  created_at               timestamptz not null default now(),
  updated_at               timestamptz not null default now(),
  deleted_at               timestamptz,
  constraint evaluation_criteria_tenant_id_key unique (tenant_id, id),
  constraint evaluation_criteria_competency_fk foreign key (tenant_id, competency_id)
    references competencies (tenant_id, id),
  constraint evaluation_criteria_performance_standard_fk foreign key (tenant_id, performance_standard_id)
    references performance_standards (tenant_id, id),
  constraint evaluation_criteria_unit_fk foreign key (tenant_id, unit_id)
    references units (tenant_id, id)
);

comment on table evaluation_criteria is 'A criterio de evaluación: the teacher''s own precisado of a desempeño (or an ad hoc criterion with no desempeño linked yet), for a unit or rubric. This is the layer teachers load into the system to evaluate a competencia.';
comment on column evaluation_criteria.performance_standard_id is 'The national desempeño this criterio precises. Nullable: a teacher may write a criterio before linking it to the national catalog.';
comment on column evaluation_criteria.unit_id is 'The unidad didáctica this criterio was authored for. Nullable so a criterio can be authored ahead of a unit, or reused across units.';

create index evaluation_criteria_competency_idx
  on evaluation_criteria (tenant_id, competency_id) where deleted_at is null;
create index evaluation_criteria_unit_idx
  on evaluation_criteria (unit_id) where unit_id is not null and deleted_at is null;

select app.enable_tenant_rls('evaluation_criteria');
select app.attach_updated_at('evaluation_criteria');
select app.attach_soft_delete_guard('evaluation_criteria');

-- ---------------------------------------------------------------------------
-- assessment_criteria
-- ---------------------------------------------------------------------------
-- Sibling of assessment_competencies, at criterio granularity. Both tables are
-- kept: assessments not yet broken into criterios keep working through
-- assessment_competencies; a competency's coverage can also be derived by
-- joining assessment_criteria -> evaluation_criteria.competency_id once
-- criterios are in use.
create table assessment_criteria (
  id             uuid primary key default gen_random_uuid(),
  tenant_id      uuid not null references tenants (id),
  assessment_id  uuid not null,
  criterion_id   uuid not null,
  weight         numeric(9, 6) not null default 1 check (weight > 0),
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now(),
  deleted_at     timestamptz,
  constraint assessment_criteria_assessment_fk foreign key (tenant_id, assessment_id)
    references assessments (tenant_id, id),
  constraint assessment_criteria_criterion_fk foreign key (tenant_id, criterion_id)
    references evaluation_criteria (tenant_id, id)
);

comment on table assessment_criteria is 'Which criterios de evaluación an assessment evidences. Finer-grained sibling of assessment_competencies -- the path from a rubric cell to competency-level reporting.';

create unique index assessment_criteria_key
  on assessment_criteria (assessment_id, criterion_id) where deleted_at is null;
create index assessment_criteria_criterion_idx on assessment_criteria (criterion_id);

select app.enable_tenant_rls('assessment_criteria');
select app.attach_updated_at('assessment_criteria');
select app.attach_soft_delete_guard('assessment_criteria');

-- ---------------------------------------------------------------------------
-- evaluation_criterion_scores
-- ---------------------------------------------------------------------------
-- The per-student rubric cell: the actual per-criterio evaluation of a
-- competencia. Modelled like scores/competency_term_levels: append-only,
-- since it is evidence of record, not a draft. This table is explicitly
-- evidence, not automation -- competency_term_levels is still asserted by
-- teacher judgement, never computed, from this data.
create table evaluation_criterion_scores (
  id              uuid primary key default gen_random_uuid(),
  tenant_id       uuid not null references tenants (id),
  assessment_id   uuid not null,
  criterion_id    uuid not null,
  student_id      uuid not null,
  class_id        uuid,
  term_id         uuid,
  scale_level_id  uuid not null,
  note            text,
  source          text not null default 'manual'
                    check (source in ('manual', 'bulk', 'import', 'voice', 'auto')),
  recorded_by_id  uuid not null,
  recorded_at     timestamptz not null default now(),
  supersedes_id   uuid,
  superseded_at   timestamptz,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  deleted_at      timestamptz,
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
    references evaluation_criterion_scores (tenant_id, id)
);

comment on table evaluation_criterion_scores is
  'MINORS'' PERSONAL DATA (academic). Append-only. One student''s rubric-level result against one criterio de evaluación on one assessment, on the tenant''s existing AD/A/B/C scale (grade_scale_levels) -- the same scale competency_term_levels reports on. Evidence a teacher can lean on when asserting a nivel de logro; never itself the official record. Correcting a result inserts a new row that supersedes the old one, exactly like scores.';
comment on column evaluation_criterion_scores.scale_level_id is 'The achievement level for this criterio, reusing the tenant''s existing scale rather than a second rubric vocabulary -- matches competency_term_levels.scale_level_id.';
comment on column evaluation_criterion_scores.class_id is 'Denormalised from the assessment. Maintained by trigger.';
comment on column evaluation_criterion_scores.term_id is 'Denormalised from the assessment. Maintained by trigger.';
comment on column evaluation_criterion_scores.supersedes_id is 'The row this one replaces after a correction. Backwards-only link, for the same reason as scores.supersedes_id: the replacement cannot exist until the old row is closed.';
comment on column evaluation_criterion_scores.superseded_at is 'Set when a newer row replaces this one. A row with superseded_at null and deleted_at null is the live value.';

-- Exactly one live row per (assessment, criterion, student).
create unique index ecs_live_key
  on evaluation_criterion_scores (assessment_id, criterion_id, student_id)
  where superseded_at is null and deleted_at is null;
create index ecs_assessment_idx
  on evaluation_criterion_scores (assessment_id) where superseded_at is null and deleted_at is null;
create index ecs_student_term_idx
  on evaluation_criterion_scores (student_id, term_id) where superseded_at is null and deleted_at is null;
create index ecs_class_term_idx
  on evaluation_criterion_scores (class_id, term_id) where superseded_at is null and deleted_at is null;
create index ecs_supersedes_idx on evaluation_criterion_scores (supersedes_id) where supersedes_id is not null;

-- Denormalised columns are copied from the assessment, never supplied. The
-- closed-term and draft-assessment guards live in this same function, on
-- purpose, mirroring app.sync_score_denormalised: as separate BEFORE INSERT
-- triggers they would fire in name order, and a guard that ran before this
-- one would silently read a null term and pass.
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

create trigger sync_denormalised before insert on evaluation_criterion_scores
  for each row execute function app.sync_criterion_score_denormalised();

-- Append-only, mirroring app.forbid_score_mutation.
-- +goose StatementBegin
create or replace function app.forbid_criterion_score_mutation() returns trigger
  language plpgsql
  as $fn$
  begin
    if new.assessment_id  is distinct from old.assessment_id
       or new.criterion_id  is distinct from old.criterion_id
       or new.student_id    is distinct from old.student_id
       or new.scale_level_id is distinct from old.scale_level_id
       or new.recorded_by_id is distinct from old.recorded_by_id
       or new.recorded_at    is distinct from old.recorded_at then
      raise exception 'evaluation criterion scores are append-only (score %); insert a superseding row instead of updating', old.id
        using errcode = 'restrict_violation',
              hint = 'Stamp superseded_at on this row FIRST, then insert the replacement with supersedes_id set. ecs_live_key is a partial unique index and cannot be deferred, so two live rows for one (assessment, criterion, student) never coexist, even briefly.';
    end if;
    return new;
  end;
  $fn$;
-- +goose StatementEnd

create trigger forbid_mutation before update on evaluation_criterion_scores
  for each row execute function app.forbid_criterion_score_mutation();

select app.enable_tenant_rls('evaluation_criterion_scores');
select app.attach_updated_at('evaluation_criterion_scores');
select app.attach_soft_delete_guard('evaluation_criterion_scores');

-- +goose Down

drop table if exists evaluation_criterion_scores cascade;
drop table if exists assessment_criteria cascade;
drop table if exists evaluation_criteria cascade;
drop table if exists performance_standards cascade;
drop table if exists capabilities cascade;

drop function if exists app.forbid_criterion_score_mutation();
drop function if exists app.sync_criterion_score_denormalised();
