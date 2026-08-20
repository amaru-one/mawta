-- Move voice-note audio into Postgres so a note row and its audio are one
-- atomic, backed-up thing instead of a DB row plus a loose file on disk that
-- can silently drift out of sync.

-- +goose Up

alter table voice_notes add column audio bytea;
alter table voice_notes alter column storage_key drop not null;

comment on column voice_notes.audio is
  'The recorded audio itself. Not PII of a minor: this is the teacher''s voice, recorded with their knowledge while narrating an observation — the sensitive part is the spoken content (see the transcript column), not the voiceprint. Superseded storage_key: writing here happens inside the same transaction as the row insert, so a note and its audio can never drift apart the way a DB row and a disk file could.';

comment on column voice_notes.storage_key is
  'Legacy disk pointer, from before audio moved into this table. Left in place so pre-migration recordings on STORAGE_DIR remain playable; new rows leave it null.';

comment on table voice_notes is
  'MINORS'' PERSONAL DATA (behavioural, via the transcript). A teacher''s spoken note about one student, recorded during a session. The audio is the teacher''s own voice; the transcript is unstructured speech about a minor, which is the highest-risk column in the schema after the students'' own identifying data. Retention is enforced per row, not per tenant.';

-- +goose Down

-- storage_key is intentionally left nullable: rows created after the Up
-- migration may have no disk file at all, so restoring the NOT NULL
-- constraint here would fail (or silently corrupt data if forced).
alter table voice_notes drop column audio;
