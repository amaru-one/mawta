-- A piece of evidencia gets to say how it is valued, and "not at all" is one of
-- the answers.
--
-- Until now every assessment carried a numeric max_score (not null, > 0) and
-- every value lived in scores.raw_value on a vigesimal axis. That encoded one
-- school's arrangement as a property of the schema. Three arrangements are
-- real, and a teacher meets all three inside one IE:
--
--   vigesimal  a prueba calificada out of 20, the school's own internal system
--              (D.S. 009-2006-ED art. 37.4.f)
--   literal    a piece of work valued AD / A / B / C, which many IE do directly
--   none       a debate, an exposición: registered, read, never given a value
--
-- 00005 gave the *school* an opt-out (tenants.uses_internal_grading). This
-- gives the *evidence* one, which is the finer and more useful grain: the same
-- teacher runs a numeric practice and an unvalued exposición in the same week.
--
-- What this migration does NOT do, and what nothing built on it may do:
-- convert between the two. A letter on a piece of evidence is not a nivel de
-- logro. The nivel de logro of a competencia is asserted by a teacher in
-- competency_term_levels after reading the period's evidence (RVM 094-2020,
-- 5.1.1.3 p.2-3); two AD and one B on three pieces of work are not an A, and no
-- column added here is allowed to become the arithmetic that says otherwise.
-- The direction of travel MINEDU itself defines is level to number, for the
-- certificate in Anexo II of RVM 048-2024, and never the reverse.
--
-- 1. assessments.value_scale  -- which of the three this evidence uses.
-- 2. assessments.max_score    -- now null unless value_scale = 'numeric'.
-- 3. scores.scale_level_id    -- where a literal value goes.
--
-- One table for all three values rather than a second table beside scores: the
-- supersede protocol, the closed-term guard, the append-only trigger and the
-- live-attempt key are all already here and all apply identically to a letter.
-- A parallel table would be evaluation_criterion_scores again, which 00009
-- drops for being exactly that.

-- Note for whoever edits the comment strings below: goose strips everything
-- after a `- -` (no space) when deciding whether a line ends a statement, even
-- inside a quoted literal, so a comment string containing one swallows the
-- statements that follow it. Punctuate with colons and commas instead.

-- +goose Up

alter table assessments
  add column value_scale text not null default 'numeric'
    check (value_scale in ('numeric', 'ordinal', 'none'));

comment on column assessments.value_scale is
  'How this piece of evidencia is valued. numeric: a mark on the school''s own vigesimal scale, with max_score as the denominator and the value in scores.raw_value. ordinal: a letter on the MINEDU AD/A/B/C scale, with the value in scores.scale_level_id and no denominator. none: registered and read but never valued, so it has no scores rows at all. The default is numeric because every row that existed before this column had a max_score. A letter here is NOT a nivel de logro: the level of a competencia is asserted in competency_term_levels by a teacher who has read the whole period, and nothing may derive it from these values.';

-- max_score stops being universal. The check pins it to the one scale that has
-- a denominator, in both directions: a numeric evidence without a max is
-- unmarkable, and a max on a letter-valued one is a number nobody will ever use
-- that later readers would try to interpret.
alter table assessments
  alter column max_score drop not null;

alter table assessments
  drop constraint if exists assessments_max_score_check;

alter table assessments
  add constraint assessments_max_score_positive
    check (max_score is null or max_score > 0),
  add constraint assessments_max_score_matches_scale
    check ((value_scale = 'numeric') = (max_score is not null));

comment on column assessments.max_score is
  'The denominator, present only when value_scale is numeric. Null for a literal or unvalued piece of evidencia, enforced by assessments_max_score_matches_scale.';

-- The literal value of one piece of work for one student. It points at the same
-- grade_scale_levels rows competency_term_levels uses, because AD/A/B/C is one
-- vocabulary; what differs is the standing of the row, not the letters.
alter table scores
  add column scale_level_id uuid,
  add constraint scores_scale_level_fk foreign key (tenant_id, scale_level_id)
    references grade_scale_levels (tenant_id, id);

comment on column scores.scale_level_id is
  'The letter this piece of work earned, when its assessment has value_scale = ordinal. Null for a numeric score, where the value is raw_value over max_value. It is a value on a piece of evidence and carries no normative standing: only competency_term_levels holds a nivel de logro, and internal/grading never reads this column, since a letter has no place in a weighted average.';

-- A graded score now carries a number or a letter, so both the null-value and
-- the range checks have to admit a row that has one and not the other.
alter table scores
  alter column max_value drop not null;

alter table scores
  drop constraint scores_value_matches_status,
  drop constraint scores_value_in_range,
  drop constraint if exists scores_max_value_check;

alter table scores
  add constraint scores_max_value_positive
    check (max_value is null or max_value > 0),
  add constraint scores_value_matches_status
    check ((status = 'graded') = (raw_value is not null or scale_level_id is not null)),
  add constraint scores_value_in_range
    check (raw_value is null or (max_value is not null and raw_value >= 0 and raw_value <= max_value)),
  -- A row is one kind of value or the other, never both: two values for one
  -- piece of work would leave every reader to decide which one counts.
  add constraint scores_one_value_kind
    check (raw_value is null or scale_level_id is null);

comment on column scores.max_value is
  'Copied from the assessment at write time and frozen, so changing an assessment''s max later cannot reinterpret grades already entered. Null when the score is a letter, which has no denominator.';

-- scale_level_id joins the identity columns the append-only guard protects:
-- correcting a letter inserts a superseding row, exactly as correcting a mark
-- does.
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
       or new.scale_level_id is distinct from old.scale_level_id
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

-- +goose Down

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
        using errcode = 'restrict_violation';
    end if;
    return new;
  end;
  $fn$;
-- +goose StatementEnd

-- Letters cannot be represented once the column is gone, so they go with it.
delete from scores where scale_level_id is not null;
delete from scores where assessment_id in (select id from assessments where value_scale <> 'numeric');
delete from assessments where value_scale <> 'numeric';

alter table scores
  drop constraint scores_one_value_kind,
  drop constraint scores_value_in_range,
  drop constraint scores_value_matches_status,
  drop constraint scores_max_value_positive,
  drop constraint scores_scale_level_fk,
  drop column scale_level_id;

alter table scores
  add constraint scores_value_matches_status
    check ((status = 'graded') = (raw_value is not null)),
  add constraint scores_value_in_range
    check (raw_value is null or (raw_value >= 0 and raw_value <= max_value));

alter table scores alter column max_value set not null;

alter table assessments
  drop constraint assessments_max_score_matches_scale,
  drop constraint assessments_max_score_positive,
  drop column value_scale;

alter table assessments
  add constraint assessments_max_score_check check (max_score > 0);

alter table assessments alter column max_score set not null;
