-- Per-session observations, voice notes, and AI summaries.
--
-- These are the qualitative record, kept strictly separate from graded
-- assessments: a participation dot on screen 03 is not a grade, and must never
-- silently become one.

-- +goose Up

-- ---------------------------------------------------------------------------
-- behavior_flag_types
-- ---------------------------------------------------------------------------
create table behavior_flag_types (
  id          uuid primary key default gen_random_uuid(),
  tenant_id   uuid not null references tenants (id),
  code        text not null,
  label       text not null,
  description text,
  severity    text not null default 'low' check (severity in ('info', 'low', 'medium', 'high')),
  is_positive boolean not null default false,
  sort_order  smallint not null default 0,
  is_active   boolean not null default true,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  deleted_at  timestamptz,
  constraint behavior_flag_types_tenant_id_key unique (tenant_id, id)
);

comment on table behavior_flag_types is 'The flags a school lets teachers raise on a student in a session, defined per tenant. Rows rather than an enum because what counts as a flag is a school policy question, and a fixed list would force every school into one disciplinary vocabulary.';
comment on column behavior_flag_types.is_positive is 'Not every flag is negative. Recognising sustained effort uses the same mechanism, and mixing the two into one count would make screen 04''s "2 marcas de comportamiento" misleading.';

create unique index behavior_flag_types_tenant_code_key
  on behavior_flag_types (tenant_id, code) where deleted_at is null;

select app.enable_tenant_rls('behavior_flag_types');
select app.attach_updated_at('behavior_flag_types');
select app.attach_soft_delete_guard('behavior_flag_types');

-- ---------------------------------------------------------------------------
-- session_observations
-- ---------------------------------------------------------------------------
create table session_observations (
  id                  uuid primary key default gen_random_uuid(),
  tenant_id           uuid not null references tenants (id),
  session_id          uuid not null,
  student_id          uuid not null,
  class_id            uuid not null,
  session_date        date not null,
  participation_level smallint check (participation_level between 0 and 3),
  note                text,
  recorded_by_id      uuid not null,
  recorded_at         timestamptz not null default now(),
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now(),
  deleted_at          timestamptz,
  constraint session_observations_tenant_id_key unique (tenant_id, id),
  constraint session_observations_session_fk foreign key (tenant_id, session_id)
    references class_sessions (tenant_id, id),
  constraint session_observations_student_fk foreign key (tenant_id, student_id)
    references students (tenant_id, id),
  constraint session_observations_class_fk foreign key (tenant_id, class_id)
    references classes (tenant_id, id),
  constraint session_observations_recorded_by_fk foreign key (tenant_id, recorded_by_id)
    references teachers (tenant_id, id)
);

comment on table session_observations is
  'MINORS'' PERSONAL DATA (behavioural). What a teacher observed about one student in one session: participation and a free-text note. Explicitly not an assessment — it carries no weight, no max and no scale, and never reaches computed_grades.';
comment on column session_observations.participation_level is 'The three-dot control on screen 03, as 0-3 filled dots. Nullable because "not observed" is the honest default for most students in most sessions, and is different from "observed as zero".';
comment on column session_observations.note is 'PII (minor): free text written by a teacher about a child. Highest-sensitivity free-text column after the voice-note transcript.';
comment on column session_observations.session_date is 'Denormalised from the session so a term''s observations for one student can be scanned in date order without a join.';

-- Denormalised columns come from the session, never from the caller.
-- +goose StatementBegin
create or replace function app.sync_observation_denormalised() returns trigger
  language plpgsql
  as $fn$
  begin
    select s.class_id, s.session_date
      into new.class_id, new.session_date
      from class_sessions s
     where s.id = new.session_id and s.tenant_id = new.tenant_id;

    if not found then
      raise exception 'session % not found in tenant %', new.session_id, new.tenant_id
        using errcode = 'foreign_key_violation';
    end if;
    return new;
  end;
  $fn$;
-- +goose StatementEnd

create trigger sync_denormalised before insert or update of session_id on session_observations
  for each row execute function app.sync_observation_denormalised();

create unique index session_observations_key
  on session_observations (session_id, student_id) where deleted_at is null;
-- Screen 03: the observation strip for every student in one session.
create index session_observations_session_idx
  on session_observations (session_id) where deleted_at is null;
-- Screen 04: one student's participation history over a term.
create index session_observations_student_date_idx
  on session_observations (student_id, session_date desc) where deleted_at is null;

select app.enable_tenant_rls('session_observations');
select app.attach_updated_at('session_observations');
select app.attach_soft_delete_guard('session_observations');

-- ---------------------------------------------------------------------------
-- session_observation_flags
-- ---------------------------------------------------------------------------
create table session_observation_flags (
  id             uuid primary key default gen_random_uuid(),
  tenant_id      uuid not null references tenants (id),
  observation_id uuid not null,
  flag_type_id   uuid not null,
  note           text,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now(),
  deleted_at     timestamptz,
  constraint sof_observation_fk foreign key (tenant_id, observation_id)
    references session_observations (tenant_id, id),
  constraint sof_flag_type_fk foreign key (tenant_id, flag_type_id)
    references behavior_flag_types (tenant_id, id)
);

comment on table session_observation_flags is
  'MINORS'' PERSONAL DATA (behavioural). Which flags were raised in one observation. The filled flag pill on screen 03 is the existence of a row here; screen 04''s "2 marcas de comportamiento este bimestre" counts them over a term.';

create unique index sof_key on session_observation_flags (observation_id, flag_type_id)
  where deleted_at is null;
create index sof_flag_type_idx on session_observation_flags (flag_type_id) where deleted_at is null;

select app.enable_tenant_rls('session_observation_flags');
select app.attach_updated_at('session_observation_flags');
select app.attach_soft_delete_guard('session_observation_flags');

-- ---------------------------------------------------------------------------
-- voice_notes
-- ---------------------------------------------------------------------------
create table voice_notes (
  id                    uuid primary key default gen_random_uuid(),
  tenant_id             uuid not null references tenants (id),
  session_id            uuid not null,
  student_id            uuid not null,
  class_id              uuid not null,
  teacher_id            uuid not null,
  recorded_at           timestamptz not null default now(),
  duration_ms           integer not null check (duration_ms >= 0),
  storage_bucket        text,
  storage_key           text not null,
  mime_type             text,
  byte_size             bigint check (byte_size >= 0),
  status                text not null default 'draft'
                          check (status in ('draft', 'saved', 'discarded')),
  transcription_status  text not null default 'pending'
                          check (transcription_status in ('pending', 'queued', 'processing', 'completed', 'failed', 'skipped')),
  transcription_job_id  bigint,
  transcript            text,
  transcript_language   text,
  transcript_confidence numeric(4, 3) check (transcript_confidence between 0 and 1),
  transcribed_at        timestamptz,
  embedding             vector(1536),
  embedding_model       text,
  embedded_at           timestamptz,
  retention_until       date,
  purged_at             timestamptz,
  created_at            timestamptz not null default now(),
  updated_at            timestamptz not null default now(),
  deleted_at            timestamptz,
  constraint voice_notes_tenant_id_key unique (tenant_id, id),
  constraint voice_notes_session_fk foreign key (tenant_id, session_id)
    references class_sessions (tenant_id, id),
  constraint voice_notes_student_fk foreign key (tenant_id, student_id)
    references students (tenant_id, id),
  constraint voice_notes_class_fk foreign key (tenant_id, class_id)
    references classes (tenant_id, id),
  constraint voice_notes_teacher_fk foreign key (tenant_id, teacher_id)
    references teachers (tenant_id, id),
  constraint voice_notes_transcript_consistent
    check ((transcription_status = 'completed') <= (transcript is not null)),
  constraint voice_notes_embedding_consistent
    check ((embedding is null) = (embedded_at is null))
);

comment on table voice_notes is
  'MINORS'' PERSONAL DATA (voice, sensitive). A teacher''s spoken note about one student, recorded during a session. Holds an object-store pointer to the child''s recorded audio and its transcript. The highest-risk table in the schema after students: audio is biometric-adjacent, and the transcript is unstructured speech about a minor. Retention is enforced per row, not per tenant.';

comment on column voice_notes.duration_ms is 'Length in milliseconds. Screen 03 renders it as "0:04" beside the play control.';
comment on column voice_notes.storage_key is 'PII (minor): pointer to audio in object storage. The audio never enters Postgres; deleting this row must be accompanied by deleting the object.';
comment on column voice_notes.status is 'draft is a recording the teacher has not kept yet — screen 03 shows it with save and trash controls. discarded is the trash tap: soft, so an accidental discard is recoverable and a deliberate one is auditable.';
comment on column voice_notes.transcript is 'PII (minor): free-text speech about a child. Nullable and separately purgeable from the audio, so a school can drop transcripts while keeping durations for analytics.';
comment on column voice_notes.embedding is 'Reserved for semantic search over notes. Left unindexed on purpose: an HNSW index on an empty column costs write throughput for nothing. Create it when embeddings start landing — CREATE INDEX CONCURRENTLY voice_notes_embedding_idx ON voice_notes USING hnsw (embedding vector_cosine_ops).';
comment on column voice_notes.retention_until is 'Date after which the audio and transcript must be purged. Deliberately shorter by default than the academic record: a grade has a legal retention period, a recording of a child does not.';
comment on column voice_notes.purged_at is 'When audio and transcript were removed. The row survives with its duration and timestamps so screen 06''s "Notas de voz 486" does not change retroactively.';

-- Screen 03: the notes for one session, and per student within it.
create index voice_notes_session_idx on voice_notes (session_id) where deleted_at is null;
-- Screen 04: all saved notes for one student, newest first -- the summary input.
create index voice_notes_student_idx
  on voice_notes (student_id, recorded_at desc) where status = 'saved' and deleted_at is null;
-- Transcription worker: the queue of notes still waiting.
create index voice_notes_transcription_idx
  on voice_notes (tenant_id, transcription_status)
  where transcription_status in ('pending', 'queued', 'failed') and deleted_at is null;
-- Retention sweep.
create index voice_notes_retention_idx
  on voice_notes (retention_until) where purged_at is null and retention_until is not null;
-- Screen 06: "Notas de voz 486" for one teacher over a term.
create index voice_notes_teacher_idx
  on voice_notes (teacher_id, recorded_at) where deleted_at is null;

select app.enable_tenant_rls('voice_notes');
select app.attach_updated_at('voice_notes');
select app.attach_soft_delete_guard('voice_notes');

-- ---------------------------------------------------------------------------
-- note_summaries
-- ---------------------------------------------------------------------------
create table note_summaries (
  id                uuid primary key default gen_random_uuid(),
  tenant_id         uuid not null references tenants (id),
  student_id        uuid not null,
  class_id          uuid,
  term_id           uuid,
  scope             text not null default 'student_term'
                      check (scope in ('student_term', 'student_class_term', 'student_range')),
  range_starts_on   date,
  range_ends_on     date,
  bullets           jsonb not null default '[]'::jsonb,
  summary_text      text,
  notes_count       integer not null default 0 check (notes_count >= 0),
  model             text,
  prompt_version    text,
  generated_by_job_id bigint,
  requested_by_id   uuid,
  status            text not null default 'pending'
                      check (status in ('pending', 'generating', 'ready', 'failed', 'stale')),
  error_detail      text,
  generated_at      timestamptz,
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now(),
  deleted_at        timestamptz,
  constraint note_summaries_tenant_id_key unique (tenant_id, id),
  constraint note_summaries_student_fk foreign key (tenant_id, student_id)
    references students (tenant_id, id),
  constraint note_summaries_class_fk foreign key (tenant_id, class_id)
    references classes (tenant_id, id),
  constraint note_summaries_term_fk foreign key (tenant_id, term_id)
    references terms (tenant_id, id),
  constraint note_summaries_requested_by_fk foreign key (tenant_id, requested_by_id)
    references teachers (tenant_id, id),
  constraint note_summaries_ready_consistent
    check ((status = 'ready') <= (generated_at is not null)),
  constraint note_summaries_bullets_is_array
    check (jsonb_typeof(bullets) = 'array')
);

comment on table note_summaries is
  'MINORS'' PERSONAL DATA (derived, AI-generated). The card at the bottom of screen 04: "Resumen de 6 notas de voz" and its bullets. A separate entity from the notes themselves because it is generated, versioned by model and prompt, and can go stale when new notes arrive.';
comment on column note_summaries.bullets is 'Ordered array of bullet strings as rendered. Stored as JSON rather than as rows because the bullets are one indivisible generated artefact and are never queried individually.';
comment on column note_summaries.notes_count is 'How many notes were summarised — the "6" in the heading. Denormalised from note_summary_sources so the heading does not need a count query.';
comment on column note_summaries.model is 'Model identifier that produced this summary. Without it, a summary written today and one written next quarter are indistinguishable artefacts of different systems.';
comment on column note_summaries.status is 'stale means new voice notes have landed since generation. The card stays readable while a fresh summary is requested, rather than blanking.';

create index note_summaries_student_idx
  on note_summaries (student_id, created_at desc) where deleted_at is null;
create unique index note_summaries_current_key
  on note_summaries (student_id, class_id, term_id)
  where status in ('ready', 'generating') and deleted_at is null;

select app.enable_tenant_rls('note_summaries');
select app.attach_updated_at('note_summaries');
select app.attach_soft_delete_guard('note_summaries');

create table note_summary_sources (
  id            uuid primary key default gen_random_uuid(),
  tenant_id     uuid not null references tenants (id),
  summary_id    uuid not null,
  voice_note_id uuid not null,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now(),
  constraint nss_summary_fk foreign key (tenant_id, summary_id)
    references note_summaries (tenant_id, id) on delete cascade,
  constraint nss_voice_note_fk foreign key (tenant_id, voice_note_id)
    references voice_notes (tenant_id, id)
);

comment on table note_summary_sources is 'The exact set of voice notes a summary was built from. Required for the summary to be defensible: a teacher acting on "dificultad recurrente con tiempos verbales compuestos" must be able to reach the six recordings that claim says so.';

create unique index nss_key on note_summary_sources (summary_id, voice_note_id);
create index nss_voice_note_idx on note_summary_sources (voice_note_id);

select app.enable_tenant_rls('note_summary_sources');
select app.attach_updated_at('note_summary_sources');

-- +goose Down

drop table if exists note_summary_sources;
drop table if exists note_summaries;
drop table if exists voice_notes;
drop table if exists session_observation_flags;
drop trigger if exists sync_denormalised on session_observations;
drop function if exists app.sync_observation_denormalised();
drop table if exists session_observations;
drop table if exists behavior_flag_types;
