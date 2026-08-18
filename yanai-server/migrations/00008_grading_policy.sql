-- Grading policy as data: scales, levels, schemes, immutable versions, weights.
--
-- Nothing in this file is specific to AD/A/B/C. A school on the 0-20 vigesimal
-- scale, a school on percentages and a school on the MINEDU qualitative scale
-- are three sets of rows, not three schemas. The seed migration proves it.

-- +goose Up

-- ---------------------------------------------------------------------------
-- grade_scales
-- ---------------------------------------------------------------------------
create table grade_scales (
  id             uuid primary key default gen_random_uuid(),
  tenant_id      uuid not null references tenants (id),
  code           text not null,
  name           text not null,
  kind           text not null check (kind in ('ordinal', 'numeric', 'percentage')),
  min_value      numeric(8, 4) not null,
  max_value      numeric(8, 4) not null,
  passing_value  numeric(8, 4),
  decimals       smallint not null default 0 check (decimals between 0 and 4),
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now(),
  deleted_at     timestamptz,
  constraint grade_scales_tenant_id_key unique (tenant_id, id),
  constraint grade_scales_range_valid check (max_value > min_value),
  constraint grade_scales_passing_in_range
    check (passing_value is null or passing_value between min_value and max_value)
);

comment on table grade_scales is 'How a school expresses a grade. ordinal = MINEDU AD/A/B/C, numeric = 0-20 vigesimal, percentage = 0-100. Every scale maps onto the same 0-1 normalised axis, which is what lets one model train across tenants.';
comment on column grade_scales.kind is 'Drives display only. ordinal renders the level code, numeric renders the value, percentage renders a percent. All three normalise identically.';
comment on column grade_scales.min_value is 'Lowest value the scale can express: 0 for vigesimal, and for an ordinal scale the numeric floor of its lowest band.';
comment on column grade_scales.decimals is 'Display precision. Vigesimal is normally reported as a whole number even though raw scores are decimal.';

create unique index grade_scales_tenant_code_key
  on grade_scales (tenant_id, code) where deleted_at is null;

select app.enable_tenant_rls('grade_scales');
select app.attach_updated_at('grade_scales');
select app.attach_soft_delete_guard('grade_scales');

-- ---------------------------------------------------------------------------
-- grade_scale_levels
-- ---------------------------------------------------------------------------
create table grade_scale_levels (
  id              uuid primary key default gen_random_uuid(),
  tenant_id       uuid not null references tenants (id),
  scale_id        uuid not null,
  code            text not null,
  label           text not null,
  short_label     text,
  ordinal         smallint not null,
  min_normalized  numeric(6, 5) not null check (min_normalized >= 0 and min_normalized <= 1),
  max_normalized  numeric(6, 5) not null check (max_normalized >= 0 and max_normalized <= 1),
  is_passing      boolean not null default false,
  color_key       text,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  deleted_at      timestamptz,
  constraint grade_scale_levels_tenant_id_key unique (tenant_id, id),
  constraint grade_scale_levels_scale_fk foreign key (tenant_id, scale_id)
    references grade_scales (tenant_id, id),
  constraint grade_scale_levels_band_valid check (max_normalized > min_normalized),
  constraint grade_scale_levels_no_gap_overlap
    exclude using gist (
      scale_id with =,
      numrange(min_normalized, max_normalized, '[)') with &&
    ) where (deleted_at is null)
);

comment on table grade_scale_levels is 'The bands of a scale. For AD/A/B/C these are the reported grades; for a numeric scale they are the colour bands behind the number. Screen 02''s "Distribución de logros" groups by this table, screen 03''s "Logro esperado / A" reads label and code from one row.';
comment on column grade_scale_levels.code is 'What is printed in the chip: "AD", "A", "B", "C".';
comment on column grade_scale_levels.label is 'Full wording: "Logro destacado", "Logro esperado", "En proceso", "En inicio". Screen 03 shows the label and the code together.';
comment on column grade_scale_levels.min_normalized is 'Inclusive lower bound on the 0-1 axis. Bands are half-open [min, max), so a value falls in exactly one band.';
comment on column grade_scale_levels.max_normalized is 'Exclusive upper bound, except for the top band which the lookup treats as closed so a perfect score has a level.';
comment on constraint grade_scale_levels_no_gap_overlap on grade_scale_levels is 'Two bands of one scale cannot overlap. Gaps are not prevented here — a gap is detectable but not always wrong during authoring, so it is checked when the scale is first used.';

create unique index grade_scale_levels_scale_code_key
  on grade_scale_levels (tenant_id, scale_id, code) where deleted_at is null;
-- Level lookup: given a normalised value, find its band. Runs once per computed grade.
create index grade_scale_levels_lookup_idx
  on grade_scale_levels (scale_id, min_normalized, max_normalized) where deleted_at is null;

select app.enable_tenant_rls('grade_scale_levels');
select app.attach_updated_at('grade_scale_levels');
select app.attach_soft_delete_guard('grade_scale_levels');

-- ---------------------------------------------------------------------------
-- grading_schemes
-- ---------------------------------------------------------------------------
create table grading_schemes (
  id          uuid primary key default gen_random_uuid(),
  tenant_id   uuid not null references tenants (id),
  scale_id    uuid not null,
  code        text not null,
  name        text not null,
  description text,
  is_active   boolean not null default true,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  deleted_at  timestamptz,
  constraint grading_schemes_tenant_id_key unique (tenant_id, id),
  constraint grading_schemes_scale_fk foreign key (tenant_id, scale_id)
    references grade_scales (tenant_id, id)
);

comment on table grading_schemes is 'A named grading policy, e.g. "Evaluación MINEDU secundaria" or "Bachillerato 0-20". Stable identity; the rules live in its versions.';

create unique index grading_schemes_tenant_code_key
  on grading_schemes (tenant_id, code) where deleted_at is null;

select app.enable_tenant_rls('grading_schemes');
select app.attach_updated_at('grading_schemes');
select app.attach_soft_delete_guard('grading_schemes');

-- ---------------------------------------------------------------------------
-- grading_components
-- ---------------------------------------------------------------------------
-- Deliberately hung off the scheme, not off the version. An assessment created
-- in April points at "Examen final"; when the school re-versions its weights in
-- June, that assessment must still resolve to the same component under the new
-- version. If components belonged to versions, every re-version would orphan
-- every existing assessment.
create table grading_components (
  id          uuid primary key default gen_random_uuid(),
  tenant_id   uuid not null references tenants (id),
  scheme_id   uuid not null,
  code        text not null,
  name        text not null,
  description text,
  sort_order  smallint not null default 0,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  deleted_at  timestamptz,
  constraint grading_components_tenant_id_key unique (tenant_id, id),
  constraint grading_components_scheme_component_key unique (tenant_id, scheme_id, id),
  constraint grading_components_scheme_fk foreign key (tenant_id, scheme_id)
    references grading_schemes (tenant_id, id)
);

comment on table grading_components is 'A weighted bucket within a scheme: Participación, Quiz, Examen final. Screen 04 lists one row per component with its weight and the student''s result in it.';
comment on column grading_components.code is 'Stable machine key. The name may be re-worded without breaking assessments or historical computed grades.';
comment on constraint grading_components_scheme_component_key on grading_components is 'Lets assessments carry a composite (tenant_id, scheme_id, component_id) foreign key, which makes it structurally impossible to file an assessment under a component from a different school''s scheme.';

create unique index grading_components_scheme_code_key
  on grading_components (tenant_id, scheme_id, code) where deleted_at is null;

select app.enable_tenant_rls('grading_components');
select app.attach_updated_at('grading_components');
select app.attach_soft_delete_guard('grading_components');

-- ---------------------------------------------------------------------------
-- grading_scheme_versions
-- ---------------------------------------------------------------------------
create table grading_scheme_versions (
  id                            uuid primary key default gen_random_uuid(),
  tenant_id                     uuid not null references tenants (id),
  scheme_id                     uuid not null,
  version                       integer not null check (version >= 1),
  effective_from                date not null,
  effective_to                  date,
  rounding_mode                 text not null default 'half_up'
                                  check (rounding_mode in ('half_up', 'half_even', 'floor', 'ceil', 'none')),
  rounding_decimals             smallint not null default 0 check (rounding_decimals between 0 and 4),
  absent_counts_as              text not null default 'zero'
                                  check (absent_counts_as in ('zero', 'excused')),
  late_penalty_pct_per_day      numeric(5, 4) not null default 0
                                  check (late_penalty_pct_per_day >= 0 and late_penalty_pct_per_day <= 1),
  late_penalty_max_pct          numeric(5, 4) not null default 0
                                  check (late_penalty_max_pct >= 0 and late_penalty_max_pct <= 1),
  retake_policy                 text not null default 'best'
                                  check (retake_policy in ('none', 'best', 'last', 'capped')),
  retake_cap_normalized         numeric(6, 5)
                                  check (retake_cap_normalized is null or (retake_cap_normalized >= 0 and retake_cap_normalized <= 1)),
  min_evaluated_weight_for_grade numeric(6, 5) not null default 0
                                  check (min_evaluated_weight_for_grade >= 0 and min_evaluated_weight_for_grade <= 1),
  notes                         text,
  published_at                  timestamptz,
  published_by_id               uuid,
  created_at                    timestamptz not null default now(),
  updated_at                    timestamptz not null default now(),
  deleted_at                    timestamptz,
  constraint grading_scheme_versions_tenant_id_key unique (tenant_id, id),
  constraint grading_scheme_versions_scheme_fk foreign key (tenant_id, scheme_id)
    references grading_schemes (tenant_id, id),
  constraint grading_scheme_versions_published_by_fk foreign key (tenant_id, published_by_id)
    references teachers (tenant_id, id),
  constraint grading_scheme_versions_range_valid
    check (effective_to is null or effective_to > effective_from),
  constraint grading_scheme_versions_capped_needs_cap
    check (retake_policy <> 'capped' or retake_cap_normalized is not null),
  constraint grading_scheme_versions_no_overlap
    exclude using gist (
      scheme_id with =,
      daterange(effective_from, effective_to, '[)') with &&
    ) where (published_at is not null and deleted_at is null)
);

comment on table grading_scheme_versions is 'An immutable snapshot of a scheme''s rules over a date range. Changing weights inserts a new version and closes the old one with effective_to; it never edits a published row. Every computed grade records the version that produced it, so a report card issued in April cannot silently change in June.';
comment on column grading_scheme_versions.absent_counts_as is 'What an unexcused absence on an assessment is worth. This is policy, not data: the score row records only that the student was absent, and this decides whether that becomes a zero or drops out of the denominator.';
comment on column grading_scheme_versions.late_penalty_pct_per_day is 'Fraction deducted per day late. Applied at computation time from scores.late_days — the raw score is never modified, so correcting this policy re-grades correctly.';
comment on column grading_scheme_versions.retake_policy is 'How multiple attempts on one assessment combine: best, last, or best-capped. Peruvian recuperación is normally capped. Never resolved by discarding the earlier attempt.';
comment on column grading_scheme_versions.min_evaluated_weight_for_grade is 'Minimum share of the term''s weight that must be evaluated before a partial grade is shown at all. Guards against screen 04 reporting "AD" off a single 5%-weight quiz.';
comment on column grading_scheme_versions.published_at is 'Null while the version is a draft. Publishing freezes it: after this, only effective_to may change.';
comment on constraint grading_scheme_versions_no_overlap on grading_scheme_versions is 'Two published versions of one scheme cannot both be in effect on a date, so "the policy applying to this assessment" is unambiguous. Drafts are excluded so a replacement can be authored while the current one is live.';

create unique index grading_scheme_versions_scheme_version_key
  on grading_scheme_versions (scheme_id, version) where deleted_at is null;

select app.enable_tenant_rls('grading_scheme_versions');
select app.attach_updated_at('grading_scheme_versions');
select app.attach_soft_delete_guard('grading_scheme_versions');

-- ---------------------------------------------------------------------------
-- grading_scheme_component_weights
-- ---------------------------------------------------------------------------
create table grading_scheme_component_weights (
  id                 uuid primary key default gen_random_uuid(),
  tenant_id          uuid not null references tenants (id),
  scheme_version_id  uuid not null,
  component_id       uuid not null,
  weight             numeric(9, 6) not null check (weight > 0 and weight <= 1),
  drop_lowest_n      smallint not null default 0 check (drop_lowest_n >= 0),
  aggregation        text not null default 'weighted_mean'
                       check (aggregation in ('mean', 'weighted_mean', 'best', 'last', 'sum')),
  is_required        boolean not null default true,
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now(),
  deleted_at         timestamptz,
  constraint gscw_version_fk foreign key (tenant_id, scheme_version_id)
    references grading_scheme_versions (tenant_id, id),
  constraint gscw_component_fk foreign key (tenant_id, component_id)
    references grading_components (tenant_id, id)
);

comment on table grading_scheme_component_weights is 'The weights themselves, one row per component per version. Screen 04 renders "Peso 20%" straight from weight. Weights within a version sum to exactly 1, enforced by a deferred constraint trigger.';
comment on column grading_scheme_component_weights.drop_lowest_n is 'Discard the N weakest scores in this component before aggregating. Which scores were dropped is recorded per student on computed_grade_components, so the teacher can explain the number.';
comment on column grading_scheme_component_weights.aggregation is 'How several assessments inside one component combine. weighted_mean uses assessments.weight_within_component; sum is for point-accumulation schemes where the component total is the denominator.';
comment on column grading_scheme_component_weights.is_required is 'If false, the component drops out of the denominator when it has no scores at all, instead of counting as unevaluated weight.';

create unique index gscw_version_component_key
  on grading_scheme_component_weights (scheme_version_id, component_id) where deleted_at is null;
create index gscw_component_idx on grading_scheme_component_weights (component_id);

-- Weights must sum to 1 per version. A row-level CHECK cannot see sibling rows,
-- so this is a deferred constraint trigger: it fires at COMMIT, which lets a
-- whole weight table be inserted or rebalanced in one transaction.
-- +goose StatementBegin
create or replace function app.check_component_weights_sum() returns trigger
  language plpgsql
  as $fn$
  declare
    v_version uuid;
    v_sum     numeric;
  begin
    -- NEW is unassigned on DELETE; referencing it there would raise.
    if tg_op = 'DELETE' then
      v_version := old.scheme_version_id;
    else
      v_version := new.scheme_version_id;
    end if;

    -- The version may have been removed in the same transaction; nothing to check.
    if not exists (select 1 from grading_scheme_versions v
                    where v.id = v_version and v.deleted_at is null) then
      return null;
    end if;

    select coalesce(sum(weight), 0) into v_sum
      from grading_scheme_component_weights
     where scheme_version_id = v_version and deleted_at is null;

    if v_sum <> 1 then
      raise exception 'component weights for grading scheme version % sum to %, must sum to exactly 1', v_version, v_sum
        using errcode = 'check_violation',
              hint = 'For thirds use 0.333333 / 0.333333 / 0.333334 -- weights are exact numerics, not floats.';
    end if;
    return null;
  end;
  $fn$;
-- +goose StatementEnd

create constraint trigger check_weights_sum
  after insert or update or delete on grading_scheme_component_weights
  deferrable initially deferred
  for each row execute function app.check_component_weights_sum();

-- A version with no weight rows at all would never fire the trigger above, so
-- publishing is also a checkpoint.
-- +goose StatementBegin
create or replace function app.check_version_publishable() returns trigger
  language plpgsql
  as $fn$
  declare
    v_sum numeric;
    v_cnt integer;
  begin
    if new.published_at is null then
      return new;
    end if;

    select count(*), coalesce(sum(weight), 0) into v_cnt, v_sum
      from grading_scheme_component_weights
     where scheme_version_id = new.id and deleted_at is null;

    if v_cnt = 0 then
      raise exception 'grading scheme version % has no components and cannot be published', new.id
        using errcode = 'check_violation';
    end if;
    if v_sum <> 1 then
      raise exception 'grading scheme version % has weights summing to %, must be exactly 1', new.id, v_sum
        using errcode = 'check_violation';
    end if;
    return new;
  end;
  $fn$;
-- +goose StatementEnd

create trigger check_publishable before insert or update of published_at on grading_scheme_versions
  for each row execute function app.check_version_publishable();

-- Published versions are immutable except for being closed off with effective_to.
-- +goose StatementBegin
create or replace function app.forbid_published_version_mutation() returns trigger
  language plpgsql
  as $fn$
  begin
    if old.published_at is null then
      return new;
    end if;
    if new.scheme_id            is distinct from old.scheme_id
       or new.version           is distinct from old.version
       or new.effective_from    is distinct from old.effective_from
       or new.rounding_mode     is distinct from old.rounding_mode
       or new.rounding_decimals is distinct from old.rounding_decimals
       or new.absent_counts_as  is distinct from old.absent_counts_as
       or new.late_penalty_pct_per_day is distinct from old.late_penalty_pct_per_day
       or new.late_penalty_max_pct     is distinct from old.late_penalty_max_pct
       or new.retake_policy            is distinct from old.retake_policy
       or new.retake_cap_normalized    is distinct from old.retake_cap_normalized
       or new.min_evaluated_weight_for_grade is distinct from old.min_evaluated_weight_for_grade
       or new.published_at             is distinct from old.published_at then
      raise exception 'grading scheme version % is published and immutable; insert a new version instead', old.id
        using errcode = 'restrict_violation',
              hint = 'Only effective_to may change on a published version, to close it off.';
    end if;
    return new;
  end;
  $fn$;
-- +goose StatementEnd

create trigger forbid_published_mutation before update on grading_scheme_versions
  for each row execute function app.forbid_published_version_mutation();

-- +goose StatementBegin
create or replace function app.forbid_published_weight_mutation() returns trigger
  language plpgsql
  as $fn$
  declare
    v_version   uuid;
    v_published timestamptz;
  begin
    -- NEW is unset on DELETE, so the row being examined depends on the operation.
    if tg_op = 'DELETE' then
      -- A sanctioned erasure (tenant offboarding, seed rollback) may remove the
      -- rows outright; ordinary application code cannot.
      if coalesce(nullif(current_setting('app.allow_hard_delete', true), ''), 'off') = 'on' then
        return old;
      end if;
      v_version := old.scheme_version_id;
    else
      v_version := new.scheme_version_id;
    end if;

    select published_at into v_published
      from grading_scheme_versions where id = v_version;

    if v_published is not null then
      raise exception 'weights of published grading scheme version % cannot be changed; insert a new version', v_version
        using errcode = 'restrict_violation';
    end if;

    if tg_op = 'DELETE' then
      return old;
    end if;
    return new;
  end;
  $fn$;
-- +goose StatementEnd

create trigger forbid_published_weight_mutation
  before update or delete on grading_scheme_component_weights
  for each row execute function app.forbid_published_weight_mutation();

select app.enable_tenant_rls('grading_scheme_component_weights');
select app.attach_updated_at('grading_scheme_component_weights');

-- ---------------------------------------------------------------------------
-- Scheme resolution: tenant default -> course override -> class/term override
-- ---------------------------------------------------------------------------
alter table tenants add column default_grading_scheme_id uuid;
alter table tenants add constraint tenants_default_scheme_fk
  foreign key (id, default_grading_scheme_id) references grading_schemes (tenant_id, id);
comment on column tenants.default_grading_scheme_id is 'School-wide fallback grading scheme. Overridden per course, then per class and term.';

alter table courses add column grading_scheme_id uuid;
alter table courses add constraint courses_grading_scheme_fk
  foreign key (tenant_id, grading_scheme_id) references grading_schemes (tenant_id, id);
comment on column courses.grading_scheme_id is 'Optional per-course override, for a school where Matemática weights differently from Inglés. Null falls back to the tenant default.';

create table class_grading_policies (
  id                 uuid primary key default gen_random_uuid(),
  tenant_id          uuid not null references tenants (id),
  class_id           uuid not null,
  term_id            uuid not null,
  scheme_id          uuid not null,
  assigned_by_id     uuid,
  assigned_at        timestamptz not null default now(),
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now(),
  deleted_at         timestamptz,
  constraint class_grading_policies_class_fk foreign key (tenant_id, class_id)
    references classes (tenant_id, id),
  constraint class_grading_policies_term_fk foreign key (tenant_id, term_id)
    references terms (tenant_id, id),
  constraint class_grading_policies_scheme_fk foreign key (tenant_id, scheme_id)
    references grading_schemes (tenant_id, id),
  constraint class_grading_policies_assigned_by_fk foreign key (tenant_id, assigned_by_id)
    references teachers (tenant_id, id)
);

comment on table class_grading_policies is 'Narrowest override: this class, this term, this scheme. Scoped by term so a class can change policy between bimestres without rewriting the previous bimestre''s grades.';

create unique index class_grading_policies_key
  on class_grading_policies (class_id, term_id) where deleted_at is null;

select app.enable_tenant_rls('class_grading_policies');
select app.attach_updated_at('class_grading_policies');
select app.attach_soft_delete_guard('class_grading_policies');

-- The resolution order in one place, so no Go code re-implements it.
create view class_effective_grading_schemes as
select
  c.tenant_id,
  c.id                                            as class_id,
  t.id                                            as term_id,
  coalesce(p.scheme_id, co.grading_scheme_id, tn.default_grading_scheme_id) as scheme_id,
  case
    when p.scheme_id is not null              then 'class_term'
    when co.grading_scheme_id is not null     then 'course'
    when tn.default_grading_scheme_id is not null then 'tenant'
  end                                             as resolved_from,
  v.id                                            as scheme_version_id
from classes c
join tenants tn on tn.id = c.tenant_id
join courses co on co.id = c.course_id and co.tenant_id = c.tenant_id
join terms   t  on t.tenant_id = c.tenant_id and t.academic_year_id = c.academic_year_id
left join class_grading_policies p
  on p.class_id = c.id and p.term_id = t.id and p.deleted_at is null
left join lateral (
  select gv.id
    from grading_scheme_versions gv
   where gv.scheme_id = coalesce(p.scheme_id, co.grading_scheme_id, tn.default_grading_scheme_id)
     and gv.published_at is not null
     and gv.deleted_at is null
     and gv.effective_from <= t.starts_on
     and (gv.effective_to is null or gv.effective_to > t.starts_on)
   order by gv.effective_from desc
   limit 1
) v on true
where c.deleted_at is null;

comment on view class_effective_grading_schemes is 'Resolves which grading scheme, and which published version of it, governs a class in a term. Version is chosen by the term start date, so re-versioning mid-year does not retroactively change a term already under way.';

-- +goose Down

drop view if exists class_effective_grading_schemes;
drop table if exists class_grading_policies;
alter table courses drop constraint if exists courses_grading_scheme_fk;
alter table courses drop column if exists grading_scheme_id;
alter table tenants drop constraint if exists tenants_default_scheme_fk;
alter table tenants drop column if exists default_grading_scheme_id;
drop trigger if exists forbid_published_weight_mutation on grading_scheme_component_weights;
drop function if exists app.forbid_published_weight_mutation();
drop trigger if exists forbid_published_mutation on grading_scheme_versions;
drop function if exists app.forbid_published_version_mutation();
drop trigger if exists check_publishable on grading_scheme_versions;
drop function if exists app.check_version_publishable();
drop trigger if exists check_weights_sum on grading_scheme_component_weights;
drop function if exists app.check_component_weights_sum();
drop table if exists grading_scheme_component_weights;
drop table if exists grading_scheme_versions;
drop table if exists grading_components;
drop table if exists grading_schemes;
drop table if exists grade_scale_levels;
drop table if exists grade_scales;
