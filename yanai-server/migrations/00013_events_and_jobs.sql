-- The append-only event log, and the Postgres-backed job queue.

-- +goose Up

-- ---------------------------------------------------------------------------
-- events
-- ---------------------------------------------------------------------------
-- Partitioned by month from day one. This table is designed to be read as a
-- time series -- "every action on this student, in order", "every grade edit
-- this bimestre" -- not only as an audit trail, and it will outgrow every other
-- table in the schema. Retiring old data must be a DETACH, not a DELETE.
create table events (
  id             uuid not null default gen_random_uuid(),
  tenant_id      uuid not null,
  occurred_at    timestamptz not null default now(),
  actor_type     text not null default 'user'
                   check (actor_type in ('user', 'system', 'job', 'model', 'import')),
  actor_id       uuid,
  actor_teacher_id uuid,
  action         text not null,
  entity_type    text not null,
  entity_id      uuid,
  student_id     uuid,
  class_id       uuid,
  session_id     uuid,
  term_id        uuid,
  request_id     text,
  payload        jsonb not null default '{}'::jsonb,
  primary key (id, occurred_at)
) partition by range (occurred_at);

comment on table events is
  'Append-only log of every meaningful action, including every read of a student record. Partitioned monthly and indexed for time-series access because it is the training corpus for risk detection and grade forecasting, not merely an audit trail. Never updated, never deleted — old months are detached.';

comment on column events.occurred_at is 'When the action happened, UTC. Also the partition key, so it is part of the primary key.';
comment on column events.tenant_id is 'Scopes the RLS policy. Deliberately not a foreign key to tenants: the log must survive the erasure of everything it describes, and a foreign key on a partitioned table this large would make every tenant-level operation take locks across every partition.';
comment on column events.actor_id is 'The users row that acted. Null for system and job actors. Not a foreign key: events outlive the rows they refer to, and an event must never be blocked or cascaded by a change to the actor.';
comment on column events.action is 'Verb in entity.verb form: student.read, score.recorded, session.started, attendance.marked, risk_flag.dismissed. The single most important column for model training, so it is a plain text taxonomy rather than a constrained enum that would need a migration per new verb.';
comment on column events.student_id is 'Denormalised subject of the action. Present so "everything that happened to this student" is one index scan rather than a jsonb search, and so a Ley 29733 subject-access request can be answered directly.';
comment on column events.class_id is 'Denormalised class context, for per-class activity series without unpacking payload.';
comment on column events.request_id is 'Correlates events written during one API request, which is what turns a list of rows into a causal sequence.';
comment on column events.payload is 'Action-specific detail. Deliberately schemaless: constraining it would make adding an action a migration.';

-- Screen-independent, but every retention and subject-access query needs it.
create index events_tenant_time_idx on events (tenant_id, occurred_at desc);
-- "Everything that happened to this student", including reads.
create index events_student_time_idx on events (student_id, occurred_at desc);
-- Audit of one entity's history: which grade was changed when, and by whom.
create index events_entity_idx on events (entity_type, entity_id, occurred_at desc);
-- Time-series feature extraction: one action type across a period.
create index events_action_time_idx on events (action, occurred_at desc);
create index events_class_time_idx on events (class_id, occurred_at desc);

-- Monthly partitions. The DEFAULT partition is a safety net so a late-arriving
-- or clock-skewed row is never rejected; the monthly job that pre-creates
-- partitions should keep it empty.
-- +goose StatementBegin
do $$
declare
  m date := date '2026-01-01';
begin
  while m < date '2028-01-01' loop
    execute format(
      'create table events_%s partition of events for values from (%L) to (%L)',
      to_char(m, 'YYYY_MM'), m, (m + interval '1 month')::date);
    m := (m + interval '1 month')::date;
  end loop;
end
$$;
-- +goose StatementEnd

create table events_default partition of events default;

comment on table events_default is 'Catch-all partition. Should stay empty: rows landing here mean the partition-creation job has fallen behind.';

-- +goose StatementBegin
create or replace function app.ensure_events_partition(p_month date) returns void
  language plpgsql
  as $fn$
  declare
    v_start date := date_trunc('month', p_month)::date;
    v_name  text := format('events_%s', to_char(v_start, 'YYYY_MM'));
  begin
    if to_regclass(v_name) is null then
      execute format(
        'create table %I partition of events for values from (%L) to (%L)',
        v_name, v_start, (v_start + interval '1 month')::date);
    end if;
  end;
  $fn$;
-- +goose StatementEnd

comment on function app.ensure_events_partition(date) is 'Idempotent partition creation, called by a scheduled job a few months ahead of time.';

-- Append-only, enforced rather than assumed.
-- +goose StatementBegin
create or replace function app.forbid_event_mutation() returns trigger
  language plpgsql
  as $fn$
  begin
    raise exception 'events is append-only (attempted % on %)', tg_op, tg_table_name
      using errcode = 'restrict_violation';
  end;
  $fn$;
-- +goose StatementEnd

create trigger forbid_mutation before update or delete on events
  for each row execute function app.forbid_event_mutation();

alter table events enable row level security;
alter table events force row level security;
create policy tenant_isolation on events
  using (tenant_id = app.current_tenant_id())
  with check (tenant_id = app.current_tenant_id());

-- +goose StatementBegin
create or replace function app.log_event(
  p_action      text,
  p_entity_type text,
  p_entity_id   uuid default null,
  p_payload     jsonb default '{}'::jsonb,
  p_student_id  uuid default null,
  p_class_id    uuid default null,
  p_session_id  uuid default null
) returns uuid
  language plpgsql
  as $fn$
  declare
    v_id uuid;
  begin
    insert into events (tenant_id, actor_id, action, entity_type, entity_id,
                        student_id, class_id, session_id, payload,
                        request_id)
    values (app.current_tenant_id(), app.current_actor_id(), p_action, p_entity_type, p_entity_id,
            p_student_id, p_class_id, p_session_id, p_payload,
            nullif(current_setting('app.request_id', true), ''))
    returning id into v_id;
    return v_id;
  end;
  $fn$;
-- +goose StatementEnd

comment on function app.log_event(text, text, uuid, jsonb, uuid, uuid, uuid) is
  'Convenience writer that fills tenant, actor and request from the session. Reads of student records are logged through this from the data-access layer — Postgres cannot trigger on SELECT, so the guarantee is enforced in Go and backstopped by pgaudit.';

-- ---------------------------------------------------------------------------
-- jobs
-- ---------------------------------------------------------------------------
create table jobs (
  id            bigint generated always as identity primary key,
  tenant_id     uuid references tenants (id),
  kind          text not null,
  queue         text not null default 'default',
  priority      smallint not null default 1 check (priority between 1 and 4),
  payload       jsonb not null default '{}'::jsonb,
  status        text not null default 'available'
                  check (status in ('available', 'running', 'retryable', 'scheduled',
                                    'completed', 'cancelled', 'discarded')),
  attempts      smallint not null default 0 check (attempts >= 0),
  max_attempts  smallint not null default 20 check (max_attempts > 0),
  run_after     timestamptz not null default now(),
  attempted_at  timestamptz,
  attempted_by  text,
  finalized_at  timestamptz,
  errors        jsonb not null default '[]'::jsonb,
  tags          text[] not null default '{}',
  unique_key    text,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now(),
  constraint jobs_finalized_consistent
    check ((status in ('completed', 'cancelled', 'discarded')) = (finalized_at is not null)),
  constraint jobs_errors_is_array check (jsonb_typeof(errors) = 'array')
);

comment on table jobs is 'The work queue, in Postgres. Voice-note transcription, summary generation, grade recomputation, risk detection and the retention sweep all run through it. Claimed with SELECT ... FOR UPDATE SKIP LOCKED, which is the only reason a queue in the primary database is viable at this scale.';

comment on column jobs.tenant_id is 'Nullable: cross-tenant maintenance work (partition creation, retention sweeps) has no tenant. This is why jobs carries no RLS policy — a worker legitimately spans tenants and sets app.tenant_id per job.';
comment on column jobs.kind is 'Worker selector: voice_note.transcribe, note_summary.generate, grade.recompute, risk.detect, notification.sweep, retention.sweep.';
comment on column jobs.priority is 'Lower runs first. Transcription of a note the teacher is watching outranks a nightly recompute.';
comment on column jobs.run_after is 'Earliest time this job may be claimed. Carries both scheduling and exponential backoff.';
comment on column jobs.attempted_by is 'Worker identity holding the current lease, for diagnosing a stuck job.';
comment on column jobs.errors is 'Append-only array of failure records, one per attempt. Kept whole because a job that eventually succeeded after three transcription failures is itself a signal about audio quality.';
comment on column jobs.unique_key is 'Deduplication key. Stops a burst of score edits from queueing forty identical grade recomputations for the same student.';

-- The claim query: one partial index doing all the work.
create index jobs_claim_idx
  on jobs (queue, priority, run_after, id)
  where status in ('available', 'retryable', 'scheduled');
create unique index jobs_unique_key_idx
  on jobs (kind, unique_key)
  where unique_key is not null and status in ('available', 'retryable', 'scheduled', 'running');
create index jobs_tenant_kind_idx on jobs (tenant_id, kind, created_at desc);
-- Pruning finished work.
create index jobs_finalized_idx on jobs (finalized_at) where finalized_at is not null;

select app.attach_updated_at('jobs');

-- +goose Down

drop table if exists jobs;
drop function if exists app.log_event(text, text, uuid, jsonb, uuid, uuid, uuid);
drop trigger if exists forbid_mutation on events;
drop function if exists app.forbid_event_mutation();
drop function if exists app.ensure_events_partition(date);
drop table if exists events;
