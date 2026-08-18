-- Computed grades: the derived layer, and the frozen snapshot taken at term close.
--
-- Every number on screen 04's dark card is here, and every one of them is
-- derivable from scores + the scheme version alone. They are stored because the
-- teacher sees them on a roster of 30 students at a time, and because a grade
-- must be attributable to the exact policy version that produced it.

-- +goose Up

-- ---------------------------------------------------------------------------
-- computed_grades
-- ---------------------------------------------------------------------------
create table computed_grades (
  id                        uuid primary key default gen_random_uuid(),
  tenant_id                 uuid not null references tenants (id),
  student_id                uuid not null,
  class_id                  uuid not null,
  term_id                   uuid not null,
  scheme_version_id         uuid not null,
  scale_id                  uuid not null,
  scope                     text not null default 'term_partial'
                              check (scope in ('term_partial', 'term_final')),

  normalized_value          numeric(6, 5) not null check (normalized_value between 0 and 1),
  normalization_method      text not null
                              check (normalization_method in ('ratio_of_evaluated', 'linear_min_max',
                                                              'band_midpoint', 'identity')),
  scale_level_id            uuid,
  display_value             text,

  total_weight              numeric(9, 6) not null check (total_weight > 0),
  evaluated_weight          numeric(9, 6) not null check (evaluated_weight >= 0),
  projected_min_normalized  numeric(6, 5) check (projected_min_normalized between 0 and 1),
  projected_max_normalized  numeric(6, 5) check (projected_max_normalized between 0 and 1),

  previous_scale_level_id   uuid,
  previous_normalized_value numeric(6, 5) check (previous_normalized_value between 0 and 1),
  trend                     text check (trend in ('up', 'down', 'flat')),

  scores_counted            integer not null default 0 check (scores_counted >= 0),
  inputs_digest             text,
  computed_at               timestamptz not null default now(),
  computed_by_job_id        bigint,
  supersedes_id             uuid,
  superseded_at             timestamptz,
  created_at                timestamptz not null default now(),
  updated_at                timestamptz not null default now(),
  deleted_at                timestamptz,

  constraint computed_grades_tenant_id_key unique (tenant_id, id),
  constraint computed_grades_student_fk foreign key (tenant_id, student_id)
    references students (tenant_id, id),
  constraint computed_grades_class_fk foreign key (tenant_id, class_id)
    references classes (tenant_id, id),
  constraint computed_grades_term_fk foreign key (tenant_id, term_id)
    references terms (tenant_id, id),
  constraint computed_grades_version_fk foreign key (tenant_id, scheme_version_id)
    references grading_scheme_versions (tenant_id, id),
  constraint computed_grades_scale_fk foreign key (tenant_id, scale_id)
    references grade_scales (tenant_id, id),
  constraint computed_grades_level_fk foreign key (tenant_id, scale_level_id)
    references grade_scale_levels (tenant_id, id),
  constraint computed_grades_prev_level_fk foreign key (tenant_id, previous_scale_level_id)
    references grade_scale_levels (tenant_id, id),
  constraint computed_grades_supersedes_fk foreign key (tenant_id, supersedes_id)
    references computed_grades (tenant_id, id),
  constraint computed_grades_evaluated_within_total
    check (evaluated_weight <= total_weight),
  constraint computed_grades_projection_ordered
    check (projected_max_normalized is null or projected_min_normalized is null
           or projected_max_normalized >= projected_min_normalized),
  constraint computed_grades_trend_needs_previous
    check ((trend is null) or (previous_normalized_value is not null))
);

comment on table computed_grades is
  'MINORS'' PERSONAL DATA (academic, derived). One row per student per class per term, rewritten as a new row whenever the result changes. Records which grading scheme version produced it, so a grade can always be re-explained against the rules that were in force — not the rules in force today.';

comment on column computed_grades.normalized_value is 'The grade on a 0-1 axis, comparable across every scale and every tenant. This is the column models train on with a plain SELECT. For a partial term it is achievement over the evaluated portion only: screen 04''s "83% de lo evaluado" is 0.83333.';
comment on column computed_grades.normalization_method is 'How the raw result became a 0-1 number. ratio_of_evaluated is the partial-term case; band_midpoint is the lossy path used when the source is an ordinal judgement with no underlying number. Stored because the method changes what the value means.';
comment on column computed_grades.scale_level_id is 'The band the normalised value falls in: the "A" on screens 03 and 04, and the group-by key behind screen 02''s "Distribución de logros". Null when evaluated_weight is below the version''s minimum for showing a grade.';
comment on column computed_grades.display_value is 'What to print: "A" for an ordinal scale, "15.4" for vigesimal. Rendered once here rather than in each client.';
comment on column computed_grades.total_weight is 'Sum of component weights in play for this term. Normally 1; less if an optional component was dropped for having no assessments.';
comment on column computed_grades.evaluated_weight is 'Share of total_weight already evaluated. Screen 04''s "60% del curso evaluado · falta 40%" is this over total_weight.';
comment on column computed_grades.projected_min_normalized is 'Floor at term close, assuming zero on everything remaining. Screen 04''s "50%".';
comment on column computed_grades.projected_max_normalized is 'Ceiling at term close, assuming full marks on everything remaining. Screen 04''s "90%".';
comment on column computed_grades.previous_scale_level_id is 'Level on the previous computation. This is what screen 03''s unlabelled "A →" indicator next to the current level is reading — without it the arrow cannot be drawn without recomputing history.';
comment on column computed_grades.trend is 'Direction of the last change. Derivable from previous_normalized_value, cached because it is rendered for every student on a 30-row roster.';
comment on column computed_grades.inputs_digest is 'Hash of the score rows that fed this computation. Lets the recompute job skip writing a new row when nothing material changed, which is what keeps this table from growing on every keystroke.';
comment on column computed_grades.superseded_at is 'Set when a newer computation replaces this row. Null means current. Written before the replacement is inserted, since computed_grades_current_key admits only one live row per student, class and term.';
comment on column computed_grades.supersedes_id is 'The computation this row replaces. Points backwards only, for the same reason as scores.supersedes_id: a forward pointer could never be written, because the successor does not exist at the moment the predecessor must be closed.';
comment on column computed_grades.computed_by_job_id is 'The jobs row that produced this computation, when it came from the queue rather than an interactive save. Intentionally not a foreign key: finished jobs are pruned, and a grade must not become unwritable because its job row aged out.';

-- One current row per student, class and term.
create unique index computed_grades_current_key
  on computed_grades (student_id, class_id, term_id)
  where superseded_at is null and deleted_at is null;
-- Screen 02 "Distribución de logros": count current grades per level for a class.
create index computed_grades_class_level_idx
  on computed_grades (class_id, term_id, scale_level_id)
  where superseded_at is null and deleted_at is null;
-- Screen 03: the roster with each student's current level and trend.
create index computed_grades_class_term_idx
  on computed_grades (class_id, term_id)
  where superseded_at is null and deleted_at is null;
-- Screen 04 and the student timeline: one student's grade history, newest first.
create index computed_grades_student_history_idx
  on computed_grades (student_id, class_id, computed_at desc) where deleted_at is null;
-- Model training: pull normalised grades across all tenants for a period.
create index computed_grades_training_idx
  on computed_grades (computed_at) where superseded_at is null and deleted_at is null;

select app.enable_tenant_rls('computed_grades');
select app.attach_updated_at('computed_grades');
select app.attach_soft_delete_guard('computed_grades');

-- ---------------------------------------------------------------------------
-- computed_grade_components
-- ---------------------------------------------------------------------------
create table computed_grade_components (
  id                  uuid primary key default gen_random_uuid(),
  tenant_id           uuid not null references tenants (id),
  computed_grade_id   uuid not null,
  component_id        uuid not null,
  weight_applied      numeric(9, 6) not null check (weight_applied >= 0),
  is_evaluated        boolean not null default false,
  normalized_value    numeric(6, 5) check (normalized_value between 0 and 1),
  display_value       text,
  assessments_counted integer not null default 0 check (assessments_counted >= 0),
  counted_score_ids   uuid[] not null default '{}',
  dropped_score_ids   uuid[] not null default '{}',
  excused_score_ids   uuid[] not null default '{}',
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now(),
  deleted_at          timestamptz,
  constraint cgc_grade_fk foreign key (tenant_id, computed_grade_id)
    references computed_grades (tenant_id, id) on delete cascade,
  constraint cgc_component_fk foreign key (tenant_id, component_id)
    references grading_components (tenant_id, id),
  constraint cgc_evaluated_has_value
    check (is_evaluated = (normalized_value is not null))
);

comment on table computed_grade_components is 'The per-component breakdown behind one computed grade. Screen 04''s EVALUACIONES list reads weight_applied and normalized_value from here, and the "Sin evaluar" row is a component with is_evaluated = false.';
comment on column computed_grade_components.counted_score_ids is 'Exactly which score rows fed this number. Makes a grade explainable to a parent without re-running the computation.';
comment on column computed_grade_components.dropped_score_ids is 'Scores removed by drop-lowest-N. Kept so the teacher can answer "why is my worst quiz not counting" precisely.';
comment on column computed_grade_components.excused_score_ids is 'Scores excluded from the denominator because they were excused. Distinct from dropped: excused was a decision about the student, dropped was a rule about the numbers.';

create unique index cgc_key on computed_grade_components (computed_grade_id, component_id)
  where deleted_at is null;
create index cgc_component_idx on computed_grade_components (component_id);

select app.enable_tenant_rls('computed_grade_components');
select app.attach_updated_at('computed_grade_components');

-- ---------------------------------------------------------------------------
-- term_grade_snapshots
-- ---------------------------------------------------------------------------
create table term_grade_snapshots (
  id                  uuid primary key default gen_random_uuid(),
  tenant_id           uuid not null references tenants (id),
  student_id          uuid not null,
  class_id            uuid not null,
  term_id             uuid not null,
  scheme_version_id   uuid not null,
  scale_id            uuid not null,
  computed_grade_id   uuid,
  normalized_value    numeric(6, 5) not null check (normalized_value between 0 and 1),
  scale_level_id      uuid,
  display_value       text not null,
  breakdown           jsonb not null default '{}'::jsonb,
  closed_at           timestamptz not null default now(),
  closed_by_id        uuid,
  published_at        timestamptz,
  document_ref        text,
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now(),
  deleted_at          timestamptz,
  constraint tgs_student_fk foreign key (tenant_id, student_id)
    references students (tenant_id, id),
  constraint tgs_class_fk foreign key (tenant_id, class_id)
    references classes (tenant_id, id),
  constraint tgs_term_fk foreign key (tenant_id, term_id)
    references terms (tenant_id, id),
  constraint tgs_version_fk foreign key (tenant_id, scheme_version_id)
    references grading_scheme_versions (tenant_id, id),
  constraint tgs_scale_fk foreign key (tenant_id, scale_id)
    references grade_scales (tenant_id, id),
  constraint tgs_level_fk foreign key (tenant_id, scale_level_id)
    references grade_scale_levels (tenant_id, id),
  constraint tgs_computed_fk foreign key (tenant_id, computed_grade_id)
    references computed_grades (tenant_id, id)
);

comment on table term_grade_snapshots is
  'MINORS'' PERSONAL DATA (academic, official). The frozen record issued when a term closes: the report-card row. Immutable once written. Everything above it is recomputable; this is not, which is what keeps a report card issued in April from changing in June.';
comment on column term_grade_snapshots.breakdown is 'Full component breakdown captured as JSON at close time, including the weights and the scheme version in force. Denormalised on purpose: the snapshot must stay readable even if the scheme, its components or the class are later archived.';
comment on column term_grade_snapshots.document_ref is 'Reference to the issued document (acta, libreta) if one was generated, so the stored grade and the printed grade can be reconciled.';

create unique index tgs_key on term_grade_snapshots (student_id, class_id, term_id)
  where deleted_at is null;
create index tgs_term_idx on term_grade_snapshots (term_id, class_id) where deleted_at is null;

-- +goose StatementBegin
create or replace function app.forbid_snapshot_mutation() returns trigger
  language plpgsql
  as $fn$
  begin
    if new.normalized_value  is distinct from old.normalized_value
       or new.scale_level_id is distinct from old.scale_level_id
       or new.display_value  is distinct from old.display_value
       or new.breakdown      is distinct from old.breakdown
       or new.scheme_version_id is distinct from old.scheme_version_id
       or new.student_id     is distinct from old.student_id
       or new.class_id       is distinct from old.class_id
       or new.term_id        is distinct from old.term_id then
      raise exception 'term grade snapshot % is immutable', old.id
        using errcode = 'restrict_violation',
              hint = 'Reopening a term and re-closing it writes a new snapshot; it does not edit this one.';
    end if;
    return new;
  end;
  $fn$;
-- +goose StatementEnd

create trigger forbid_mutation before update on term_grade_snapshots
  for each row execute function app.forbid_snapshot_mutation();

select app.enable_tenant_rls('term_grade_snapshots');
select app.attach_updated_at('term_grade_snapshots');
select app.attach_soft_delete_guard('term_grade_snapshots');

-- +goose Down

drop trigger if exists forbid_mutation on term_grade_snapshots;
drop function if exists app.forbid_snapshot_mutation();
drop table if exists term_grade_snapshots;
drop table if exists computed_grade_components;
drop table if exists computed_grades;
