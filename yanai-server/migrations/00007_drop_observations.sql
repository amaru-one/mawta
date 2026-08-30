-- The lesson roster's flag and free-text note are both gone from the app, and
-- with them the entire per-session observation subsystem.
--
-- `session_observations.participation_level` was already dropped in `00006`.
-- That left the table with exactly one payload column, `note` — and nothing
-- in the UI ever wrote it: the schema-generation prompt asked only for
-- "participation level and behavior flags", the lesson screen never had a
-- text field, and the client's only use of the column was reading it back
-- and echoing it on every PUT so its own autoritative write would not clear
-- it. The behavior flag, meanwhile, could never be raised in the first
-- place: `behavior_flag_types` is a per-tenant catalog, and nothing —  no
-- migration, no seed script, no admin route — has ever inserted a row into
-- it, so `GET /flag-types` always answered empty and the flag button always
-- failed with a save error.
--
-- With both gone, `session_observations` has no column of substance left:
-- a bare (tenant, session, student, class, date, recorded_by, recorded_at)
-- tuple that `events` already records, more richly and append-only, via the
-- `observation.recorded` action. So this migration removes the whole
-- subsystem — `session_observations`, `session_observation_flags`,
-- `behavior_flag_types` — rather than leaving an empty shell standing.
--
-- `privacy.anonymize_student()` is redefined first, before any table is
-- dropped: plpgsql resolves table names at execution time, so leaving its
-- `update session_observations set note = null` statement in place would
-- make every future anonymisation fail once the table is gone.
--
-- Destructive by design: the down path restores the structure, not the
-- historical rows.
--
-- Note for whoever edits the comment strings below: goose strips everything
-- after a `- -` (no space) when deciding whether a line ends a statement, even
-- inside a quoted literal, so a comment string containing one swallows the
-- statements that follow it. Punctuate with colons and commas instead.

-- +goose Up

-- +goose StatementBegin
create or replace function privacy.anonymize_student(p_student_id uuid, p_request_id uuid default null)
  returns void
  language plpgsql
  as $fn$
  declare
    v_tenant uuid := app.current_tenant_id();
  begin
    if v_tenant is null then
      raise exception 'app.tenant_id must be set before anonymising a student'
        using errcode = 'insufficient_privilege';
    end if;

    update students
       set given_name            = 'Alumno',
           paternal_surname      = 'Anonimizado',
           maternal_surname      = null,
           preferred_name        = null,
           birthdate             = null,
           sex                   = null,
           document_type         = null,
           document_number       = null,
           photo_storage_key     = null,
           guardian_contact_note = null,
           student_code          = null,
           status                = 'anonymized',
           anonymized_at         = now()
     where id = p_student_id
       and tenant_id = v_tenant
       and anonymized_at is null;

    if not found then
      raise exception 'student % not found in tenant %, or already anonymised', p_student_id, v_tenant;
    end if;

    update voice_notes
       set transcript = null,
           embedding  = null,
           embedded_at = null,
           purged_at  = now()
     where student_id = p_student_id and tenant_id = v_tenant and purged_at is null;

    update note_summaries
       set bullets = '[]'::jsonb, summary_text = null, status = 'stale'
     where student_id = p_student_id and tenant_id = v_tenant;

    perform app.log_event('student.anonymized', 'student', p_student_id,
                          jsonb_build_object('deletion_request_id', p_request_id),
                          p_student_id);
  end;
  $fn$;
-- +goose StatementEnd

drop table session_observation_flags;

drop table session_observations;

drop function app.sync_observation_denormalised();

drop table behavior_flag_types;

-- +goose Down

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
comment on column behavior_flag_types.is_positive is 'Not every flag is negative. Recognising sustained effort uses the same mechanism, and mixing the two into one count would make a behaviour tally misleading.';

create unique index behavior_flag_types_tenant_code_key
  on behavior_flag_types (tenant_id, code) where deleted_at is null;

select app.enable_tenant_rls('behavior_flag_types');
select app.attach_updated_at('behavior_flag_types');
select app.attach_soft_delete_guard('behavior_flag_types');

create table session_observations (
  id             uuid primary key default gen_random_uuid(),
  tenant_id      uuid not null references tenants (id),
  session_id     uuid not null,
  student_id     uuid not null,
  class_id       uuid not null,
  session_date   date not null,
  note           text,
  recorded_by_id uuid not null,
  recorded_at    timestamptz not null default now(),
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now(),
  deleted_at     timestamptz,
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
  'MINORS'' PERSONAL DATA (behavioural). What a teacher observed about one student in one session: the behaviour flags and a free-text note. Explicitly not an assessment: it carries no weight, no max and no scale, and never reaches computed_grades.';
comment on column session_observations.note is 'PII (minor): free text written by a teacher about a child. Highest-sensitivity free-text column after the voice-note transcript.';
comment on column session_observations.session_date is 'Denormalised from the session so a term''s observations for one student can be scanned in date order without a join.';

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
create index session_observations_session_idx
  on session_observations (session_id) where deleted_at is null;
create index session_observations_student_date_idx
  on session_observations (student_id, session_date desc) where deleted_at is null;

select app.enable_tenant_rls('session_observations');
select app.attach_updated_at('session_observations');
select app.attach_soft_delete_guard('session_observations');

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
  'MINORS'' PERSONAL DATA (behavioural). Which flags were raised in one observation. The filled flag pill is the existence of a row here.';

create unique index sof_key on session_observation_flags (observation_id, flag_type_id)
  where deleted_at is null;
create index sof_flag_type_idx on session_observation_flags (flag_type_id) where deleted_at is null;

select app.enable_tenant_rls('session_observation_flags');
select app.attach_updated_at('session_observation_flags');
select app.attach_soft_delete_guard('session_observation_flags');

-- +goose StatementBegin
create or replace function privacy.anonymize_student(p_student_id uuid, p_request_id uuid default null)
  returns void
  language plpgsql
  as $fn$
  declare
    v_tenant uuid := app.current_tenant_id();
  begin
    if v_tenant is null then
      raise exception 'app.tenant_id must be set before anonymising a student'
        using errcode = 'insufficient_privilege';
    end if;

    update students
       set given_name            = 'Alumno',
           paternal_surname      = 'Anonimizado',
           maternal_surname      = null,
           preferred_name        = null,
           birthdate             = null,
           sex                   = null,
           document_type         = null,
           document_number       = null,
           photo_storage_key     = null,
           guardian_contact_note = null,
           student_code          = null,
           status                = 'anonymized',
           anonymized_at         = now()
     where id = p_student_id
       and tenant_id = v_tenant
       and anonymized_at is null;

    if not found then
      raise exception 'student % not found in tenant %, or already anonymised', p_student_id, v_tenant;
    end if;

    update session_observations set note = null
     where student_id = p_student_id and tenant_id = v_tenant and note is not null;

    update voice_notes
       set transcript = null,
           embedding  = null,
           embedded_at = null,
           purged_at  = now()
     where student_id = p_student_id and tenant_id = v_tenant and purged_at is null;

    update note_summaries
       set bullets = '[]'::jsonb, summary_text = null, status = 'stale'
     where student_id = p_student_id and tenant_id = v_tenant;

    perform app.log_event('student.anonymized', 'student', p_student_id,
                          jsonb_build_object('deletion_request_id', p_request_id),
                          p_student_id);
  end;
  $fn$;
-- +goose StatementEnd
