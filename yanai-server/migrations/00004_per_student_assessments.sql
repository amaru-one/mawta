-- Evidencia for one student, not only for the whole class.
--
-- Under RVM 094-2020 (mod. RVM 048-2024) the evidence a teacher judges a
-- competencia against is not necessarily the same for every student: a
-- recovery task, a re-done project, an oral defence given to one student
-- because they missed the group presentation, all count as evidencia and all
-- belong in the register. `assessments` could not express any of that -- a row
-- was always a column for the entire class, so the only way to record
-- something for one student was `practice_scores`, which is explicitly
-- unofficial and never reaches the record.
--
-- This migration adds `assessments.student_id`:
--   null      -> evidence for the whole class (every row before this migration)
--   not null  -> evidence for that student only
--
-- Nothing else about an assessment changes: it still belongs to a class, a
-- term and a grading component, and it is still evidence rather than a share
-- of a grade. The per-student form simply narrows who it applies to.
--
-- Callers that fan an assessment out across the roster (dashboard counts,
-- pendientes, per-component progress) must now filter
-- `a.student_id is null or a.student_id = <the student>`; the grade recompute
-- path already joins `scores` per student and needs no change.

-- +goose Up

alter table assessments
  add column student_id uuid,
  add constraint assessments_student_fk foreign key (tenant_id, student_id)
    references students (tenant_id, id);

comment on column assessments.student_id is 'Null means the assessment applies to the whole class -- the original and still the common case. Set, it is evidencia for that one student only: a recovery task, a re-done project, an oral defence replacing a missed group presentation. Every query that fans assessments out over the roster must filter (student_id is null or student_id = the student), or one student''s personal evidence counts as missing for everyone else.';

-- Reading one student's evidence for a class+term is the hot path (screen 04).
create index assessments_student_idx
  on assessments (class_id, term_id, student_id)
  where student_id is not null and deleted_at is null;

-- +goose Down

drop index if exists assessments_student_idx;

alter table assessments
  drop constraint if exists assessments_student_fk,
  drop column if exists student_id;
