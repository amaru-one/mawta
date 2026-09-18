-- Drops voice_notes.status and voice_notes.retention_until.
--
-- status modeled a draft -> save -> discard cycle that no longer exists on the
-- client: there is no "guardar" control any more (recording already creates the
-- note; POST .../save is a silent background confirmation with no UI of its
-- own), and the discard confirm dialog already tells the teacher it is final.
-- POST /voice-notes/{voiceNoteID}/discard now actually enforces that: it sets
-- deleted_at instead of status = 'discarded', matching every other soft-delete
-- in this schema (see repo/SPEC.md: "Soft deletes (deleted_at) everywhere").
--
-- retention_until was set on every insert (current_date + 1 year) but nothing
-- ever read it -- there is no purge job, and none is added here.

-- +goose Up

-- Preserve today's discarded notes before the column that marked them is
-- dropped. 'draft' rows are left live: they carry real audio and were never
-- explicitly discarded, and 'draft' is not a concept in the new model either.
update voice_notes
   set deleted_at = now()
 where status = 'discarded'
   and deleted_at is null;

drop index voice_notes_student_idx;

alter table voice_notes
  drop column status,
  drop column retention_until;

-- Screen 04: all voice notes for one student, newest first.
create index voice_notes_student_idx
  on voice_notes (student_id, recorded_at desc)
  where deleted_at is null;

comment on table voice_notes is
  'MINORS'' PERSONAL DATA (behavioural, via the transcript). A teacher''s spoken note about one student, recorded during a session. The audio is the teacher''s own voice; the transcript is unstructured speech about a minor, which is the highest-risk column in the schema after the students'' own identifying data.';

-- +goose Down

alter table voice_notes
  add column status text not null default 'draft'
    check (status in ('draft', 'saved', 'discarded')),
  add column retention_until date;

-- Lossy: a discarded row cannot be told apart from one that was simply never
-- resolved past 'draft' before this migration first ran. Anything soft-deleted
-- maps back to 'discarded'; every other live row maps to 'saved', since by the
-- time this ships every note the teacher still sees has already gone through
-- the automatic post-create save call.
update voice_notes
   set status = case when deleted_at is not null then 'discarded' else 'saved' end,
       retention_until = created_at::date + interval '1 year';

drop index voice_notes_student_idx;

create index voice_notes_student_idx
  on voice_notes (student_id, recorded_at desc)
  where status = 'saved' and deleted_at is null;

comment on table voice_notes is
  'MINORS'' PERSONAL DATA (behavioural, via the transcript). A teacher''s spoken note about one student, recorded during a session. The audio is the teacher''s own voice; the transcript is unstructured speech about a minor, which is the highest-risk column in the schema after the students'' own identifying data. Retention is enforced per row, not per tenant.';
