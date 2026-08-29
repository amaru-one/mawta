-- The three-dot participation control is removed from the lesson screen, and
-- with it the column behind it.
--
-- session_observations.participation_level held a 0-3 rating a teacher tapped
-- on each roster row. It was a leftover of a pre-CNEB reading of the lesson
-- screen: under RVM 094-2020 (mod. RVM 048-2024) achievement is the teacher's
-- judgement of evidence against the criterios de evaluación, and a per-session
-- score for "participation" is neither evidencia nor criterio. Nothing ever
-- read it back: no query aggregated it, no computed grade consumed it, and the
-- number never reached the record. It was a daily tax on the teacher for a
-- datum the app then dropped on the floor.
--
-- Two comment strings elsewhere named UI that no longer exists and are
-- rewritten here rather than left to rot. The columns they describe stay:
-- computed_grades.previous_scale_level_id still feeds the school's own
-- internal weighted system through worker/handlers/recompute.go, even though
-- the roster row that used to draw the "A ->" arrow from it is gone.
--
-- This migration is destructive by design: the down path restores the column
-- and its CHECK, not the ratings that were in it.
--
-- Note for whoever edits the comment strings below: goose strips everything
-- after a `- -` (no space) when deciding whether a line ends a statement, even
-- inside a quoted literal, so a comment string containing one swallows the
-- statements that follow it. Punctuate with colons and commas instead.

-- +goose Up

alter table session_observations drop column participation_level;

comment on table session_observations is
  'MINORS'' PERSONAL DATA (behavioural). What a teacher observed about one student in one session: the behaviour flags and a free-text note. Explicitly not an assessment: it carries no weight, no max and no scale, and never reaches computed_grades.';

comment on column computed_grades.previous_scale_level_id is
  'Level on the previous computation, for the school''s own internal weighted system. Kept so a change in standing can be shown without recomputing history. Read only by that system: the official nivel de logro is asserted by a teacher and never derived from these rows.';

comment on column computed_grades.trend is
  'Direction of the last change, for the school''s own internal weighted system. Derivable from previous_normalized_value, cached because a class dashboard reads it for a whole section at once.';

-- +goose Down

alter table session_observations
  add column participation_level smallint check (participation_level between 0 and 3);

comment on column session_observations.participation_level is
  'A 0-3 participation rating tapped on each roster row of the lesson screen. Nullable because "not observed" is the honest default for most students in most sessions, and is different from "observed as zero".';

comment on table session_observations is
  'MINORS'' PERSONAL DATA (behavioural). What a teacher observed about one student in one session: participation and a free-text note. Explicitly not an assessment: it carries no weight, no max and no scale, and never reaches computed_grades.';

comment on column computed_grades.previous_scale_level_id is
  'Level on the previous computation. This is what screen 03''s unlabelled "A ->" indicator next to the current level is reading: without it the arrow cannot be drawn without recomputing history.';

comment on column computed_grades.trend is
  'Direction of the last change. Derivable from previous_normalized_value, cached because it is rendered for every student on a 30-row roster.';
