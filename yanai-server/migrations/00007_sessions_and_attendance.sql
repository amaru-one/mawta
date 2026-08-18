-- Concrete dated sessions and attendance.
--
-- A class_schedules row is a rule ("Mondays 10:00"). A class_sessions row is an
-- instance that actually happened, or will. Screen 02 needs both future
-- instances with topics ("12 AGO · Grammar review") and past ones with
-- outcomes, so sessions are materialised ahead of time, not generated on read.

-- +goose Up

-- ---------------------------------------------------------------------------
-- class_sessions
-- ---------------------------------------------------------------------------
create table class_sessions (
  id                          uuid primary key default gen_random_uuid(),
  tenant_id                   uuid not null references tenants (id),
  class_id                    uuid not null,
  schedule_id                 uuid,
  term_id                     uuid,
  unit_id                     uuid,
  session_date                date not null,
  scheduled_start_at          timestamptz not null,
  scheduled_end_at            timestamptz not null,
  actual_start_at             timestamptz,
  actual_end_at               timestamptz,
  status                      text not null default 'scheduled'
                                check (status in ('scheduled', 'in_progress', 'completed', 'cancelled', 'rescheduled')),
  topic                       text,
  plan_note                   text,
  room                        text,
  started_by_id               uuid,
  attendance_taken_at         timestamptz,
  attendance_taken_by_id      uuid,
  cancelled_at                timestamptz,
  cancellation_reason         text,
  rescheduled_from_session_id uuid,
  created_at                  timestamptz not null default now(),
  updated_at                  timestamptz not null default now(),
  deleted_at                  timestamptz,
  constraint class_sessions_tenant_id_key unique (tenant_id, id),
  constraint class_sessions_class_fk foreign key (tenant_id, class_id)
    references classes (tenant_id, id),
  constraint class_sessions_schedule_fk foreign key (tenant_id, schedule_id)
    references class_schedules (tenant_id, id),
  constraint class_sessions_term_fk foreign key (tenant_id, term_id)
    references terms (tenant_id, id),
  constraint class_sessions_unit_fk foreign key (tenant_id, unit_id)
    references units (tenant_id, id),
  constraint class_sessions_started_by_fk foreign key (tenant_id, started_by_id)
    references teachers (tenant_id, id),
  constraint class_sessions_attendance_by_fk foreign key (tenant_id, attendance_taken_by_id)
    references teachers (tenant_id, id),
  constraint class_sessions_reschedule_fk foreign key (tenant_id, rescheduled_from_session_id)
    references class_sessions (tenant_id, id),
  constraint class_sessions_window_valid check (scheduled_end_at > scheduled_start_at),
  constraint class_sessions_actual_valid
    check (actual_end_at is null or actual_start_at is null or actual_end_at >= actual_start_at),
  constraint class_sessions_started_consistent
    check ((status in ('in_progress', 'completed')) <= (actual_start_at is not null)),
  constraint class_sessions_cancelled_consistent
    check ((status = 'cancelled') = (cancelled_at is not null)),
  constraint class_sessions_attendance_consistent
    check ((attendance_taken_at is null) = (attendance_taken_by_id is null))
);

comment on table class_sessions is 'One dated instance of a class. Lifecycle scheduled -> in_progress -> completed, with cancelled and rescheduled as terminal alternatives. Screen 02''s "HOY · SIN INICIAR" card is a scheduled row for today; the "Iniciar clase" button moves it to in_progress and stamps actual_start_at.';
comment on column class_sessions.schedule_id is 'The recurring slot this instance came from. Null for a one-off session added by hand, so an ad-hoc make-up class is representable without inventing a weekly rule.';
comment on column class_sessions.topic is 'What the session covers, e.g. "Present perfect tense". Rendered on screen 02 both for the next session and for past ones.';
comment on column class_sessions.attendance_taken_at is 'Null means attendance was never marked, which is exactly what screen 02''s "Asistencia sin marcar" and screen 05''s reminder key off. Distinct from a session where everyone was absent.';
comment on column class_sessions.rescheduled_from_session_id is 'Points at the session this one replaces. The original keeps status = rescheduled rather than being deleted, so the fact that a class moved is auditable.';
comment on constraint class_sessions_started_consistent on class_sessions is 'Boolean implication: in_progress or completed requires actual_start_at. A session cannot be under way without having started.';

create unique index class_sessions_class_start_key
  on class_sessions (class_id, scheduled_start_at) where deleted_at is null;
-- Screen 01 "HOY": all of a tenant's sessions for one local date, joined to the
-- teacher through class_teachers. Leading tenant_id keeps it inside the tenant.
create index class_sessions_tenant_date_idx
  on class_sessions (tenant_id, session_date, status) where deleted_at is null;
-- Screen 02 "PRÓXIMAS CLASES" / "CLASES ANTERIORES": one class, ordered by date,
-- scanned in both directions from today.
create index class_sessions_class_date_idx
  on class_sessions (class_id, session_date desc) where deleted_at is null;
-- Screen 02 "Pendientes" and screen 05 reminders: completed sessions with no attendance.
create index class_sessions_attendance_pending_idx
  on class_sessions (tenant_id, session_date)
  where attendance_taken_at is null and status in ('in_progress', 'completed') and deleted_at is null;
-- Screen 06 "Clases dictadas 214": completed sessions per term.
create index class_sessions_term_idx
  on class_sessions (term_id, status) where deleted_at is null;

select app.enable_tenant_rls('class_sessions');
select app.attach_updated_at('class_sessions');
select app.attach_soft_delete_guard('class_sessions');

-- ---------------------------------------------------------------------------
-- attendance_records
-- ---------------------------------------------------------------------------
create table attendance_records (
  id             uuid primary key default gen_random_uuid(),
  tenant_id      uuid not null references tenants (id),
  session_id     uuid not null,
  student_id     uuid not null,
  class_id       uuid not null,
  session_date   date not null,
  status         text not null
                   check (status in ('present', 'late', 'absent', 'excused', 'justified')),
  minutes_late   smallint check (minutes_late >= 0),
  note           text,
  source         text not null default 'manual'
                   check (source in ('manual', 'bulk', 'import', 'auto')),
  recorded_by_id uuid not null,
  recorded_at    timestamptz not null default now(),
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now(),
  deleted_at     timestamptz,
  constraint attendance_records_session_fk foreign key (tenant_id, session_id)
    references class_sessions (tenant_id, id),
  constraint attendance_records_student_fk foreign key (tenant_id, student_id)
    references students (tenant_id, id),
  constraint attendance_records_class_fk foreign key (tenant_id, class_id)
    references classes (tenant_id, id),
  constraint attendance_records_recorded_by_fk foreign key (tenant_id, recorded_by_id)
    references teachers (tenant_id, id),
  constraint attendance_records_late_consistent
    check (minutes_late is null or status = 'late')
);

comment on table attendance_records is
  'MINORS'' PERSONAL DATA (behavioural). One row per student per session. Screen 03 writes these one tap at a time or in bulk via "Todos presentes"; screen 02''s "Asistencia 94%" and the "3 ausencias seguidas" risk rule both read them.';
comment on column attendance_records.status is 'excused and justified are distinct: excused means the school authorised the absence in advance, justified means a valid reason was accepted afterwards. Both are absences for the family, neither counts against the student.';
comment on column attendance_records.class_id is 'Denormalised from the session. Present so per-class attendance rates do not need a join, and maintained by trigger rather than by the application.';
comment on column attendance_records.session_date is 'Denormalised from the session. The consecutive-absence rule scans a student''s records in date order; without this the scan needs a join and a sort on every evaluation.';
comment on column attendance_records.source is 'How the row was created. bulk marks a "Todos presentes" tap, which is worth distinguishing from per-student taps when judging how reliable the data is.';

-- Keep the denormalised columns honest: they are copied from the session, never
-- supplied by the caller.
-- +goose StatementBegin
create or replace function app.sync_attendance_denormalised() returns trigger
  language plpgsql
  as $fn$
  begin
    select s.class_id, s.session_date
      into new.class_id, new.session_date
      from class_sessions s
     where s.id = new.session_id
       and s.tenant_id = new.tenant_id;

    if not found then
      raise exception 'session % not found in tenant %', new.session_id, new.tenant_id
        using errcode = 'foreign_key_violation';
    end if;
    return new;
  end;
  $fn$;
-- +goose StatementEnd

create trigger sync_denormalised before insert or update of session_id on attendance_records
  for each row execute function app.sync_attendance_denormalised();

create unique index attendance_records_session_student_key
  on attendance_records (session_id, student_id) where deleted_at is null;
-- Screen 03: the roll-call list for one session.
create index attendance_records_session_idx
  on attendance_records (session_id) where deleted_at is null;
-- Risk rule "3 ausencias seguidas": one student's history in date order.
create index attendance_records_student_date_idx
  on attendance_records (student_id, session_date desc) where deleted_at is null;
-- Screen 02 "Asistencia 94%": one class over a term.
create index attendance_records_class_date_idx
  on attendance_records (class_id, session_date) where deleted_at is null;

select app.enable_tenant_rls('attendance_records');
select app.attach_updated_at('attendance_records');
select app.attach_soft_delete_guard('attendance_records');

-- +goose Down

drop trigger if exists sync_denormalised on attendance_records;
drop function if exists app.sync_attendance_denormalised();
drop table if exists attendance_records;
drop table if exists class_sessions;
