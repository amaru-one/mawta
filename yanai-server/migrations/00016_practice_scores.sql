-- Unofficial, unweighted scores a teacher jots down on the student grades
-- screen — a practice quiz, a reinforcement check, anything they want to
-- track that isn't part of the graded scheme. Modelled on
-- session_observations (00011): deliberately outside the assessments/scores/
-- grading_components chain, so it can never touch computed_grades.

-- +goose Up

create table practice_scores (
  id             uuid primary key default gen_random_uuid(),
  tenant_id      uuid not null references tenants (id),
  student_id     uuid not null,
  class_id       uuid not null,
  term_id        uuid not null,
  title          text not null,
  kind           text not null default 'otro'
                   check (kind in ('quiz', 'examen', 'practica', 'tarea', 'proyecto',
                                    'exposicion', 'participacion', 'rubrica', 'otro')),
  raw_value      numeric(8, 4) not null,
  max_value      numeric(8, 4) not null check (max_value > 0),
  note           text,
  recorded_by_id uuid not null,
  recorded_at    timestamptz not null default now(),
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now(),
  deleted_at     timestamptz,
  constraint practice_scores_tenant_id_key unique (tenant_id, id),
  constraint practice_scores_student_fk foreign key (tenant_id, student_id)
    references students (tenant_id, id),
  constraint practice_scores_class_fk foreign key (tenant_id, class_id)
    references classes (tenant_id, id),
  constraint practice_scores_term_fk foreign key (tenant_id, term_id)
    references terms (tenant_id, id),
  constraint practice_scores_recorded_by_fk foreign key (tenant_id, recorded_by_id)
    references teachers (tenant_id, id)
);

comment on table practice_scores is
  'A teacher''s personal, unofficial record of a score on the student grades screen — "Añadir evaluación". Explicitly not an assessment: it carries no component and no weight, is never read by internal/grading, and never reaches computed_grades. What it''s used for (a practice quiz, a reinforcement check, anything) is entirely up to the teacher.';
comment on column practice_scores.kind is 'Same vocabulary as assessments.kind, for label consistency with the official EVALUACIONES list — not a foreign key, since these are not tied to any grading scheme.';
comment on column practice_scores.note is 'Optional free text the teacher attaches to the score.';

-- Screen 04: one student's personal scores for one class/term, newest first.
create index practice_scores_student_idx
  on practice_scores (student_id, class_id, term_id, recorded_at desc) where deleted_at is null;

select app.enable_tenant_rls('practice_scores');
select app.attach_updated_at('practice_scores');
select app.attach_soft_delete_guard('practice_scores');

-- +goose Down

drop table if exists practice_scores;
