-- Minors' data: discovery, retention, and lawful erasure.
--
-- The brief asks that columns holding personal data of minors be findable
-- programmatically. Rather than maintain a hand-written register that drifts
-- from the schema within a month, the register is derived from the COMMENT ON
-- text that every such column already carries. A column documented as PII is,
-- by construction, a column that appears in the register.

-- +goose Up

-- ---------------------------------------------------------------------------
-- The derived personal-data register
-- ---------------------------------------------------------------------------
create view privacy.pii_columns as
select
  n.nspname                        as schema_name,
  c.relname                        as table_name,
  a.attname                        as column_name,
  format_type(a.atttypid, a.atttypmod) as data_type,
  case
    when d.description like 'PII (minor and adult)%' then 'minor_and_adult'
    when d.description like 'PII (minor)%'           then 'minor'
    when d.description like 'PII (adult)%'           then 'adult'
    else 'unclassified'
  end                              as subject,
  nullif(trim(substring(d.description from 'PII \([^)]*\):\s*([^.]*)')), '') as category,
  d.description                    as note
from pg_class c
join pg_namespace n  on n.oid = c.relnamespace
join pg_attribute a  on a.attrelid = c.oid and a.attnum > 0 and not a.attisdropped
join pg_description d on d.objoid = c.oid and d.objsubid = a.attnum
where n.nspname = 'public'
  and c.relkind in ('r', 'p')
  and d.description like 'PII %';

comment on view privacy.pii_columns is 'Every column documented as holding personal data, derived from COMMENT ON text. Answers "where does this database keep data about children" with a single SELECT, and cannot go stale relative to the comments it reads.';

create view privacy.minor_data_tables as
select
  n.nspname   as schema_name,
  c.relname   as table_name,
  d.description as note
from pg_class c
join pg_namespace n on n.oid = c.relnamespace
join pg_description d on d.objoid = c.oid and d.objsubid = 0
where n.nspname = 'public'
  and c.relkind in ('r', 'p')
  and d.description like '%MINORS'' PERSONAL DATA%';

comment on view privacy.minor_data_tables is 'Tables whose comment declares that they hold data about children. The unit a retention or erasure procedure operates on.';

-- A guard against the register silently falling behind the schema: any table
-- that references a student but does not declare itself as holding minors' data.
create view privacy.undeclared_student_references as
select
  c.relname as table_name,
  a.attname as column_name
from pg_class c
join pg_namespace n on n.oid = c.relnamespace
join pg_attribute a on a.attrelid = c.oid and a.attnum > 0 and not a.attisdropped
left join pg_description d on d.objoid = c.oid and d.objsubid = 0
where n.nspname = 'public'
  and c.relkind in ('r', 'p')
  and not c.relispartition
  and a.attname = 'student_id'
  and coalesce(d.description, '') not like '%MINORS'' PERSONAL DATA%'
  and c.relname <> 'events';

comment on view privacy.undeclared_student_references is 'Should return zero rows. Any table carrying a student_id without declaring itself in the register is a documentation gap; assert this is empty in CI so new tables cannot skip the declaration. Partitions are skipped because they inherit their parent''s declaration rather than carrying their own comment, and events is skipped by name: it references every entity type and lives under its own retention rules.';

-- ---------------------------------------------------------------------------
-- deletion_requests
-- ---------------------------------------------------------------------------
create table deletion_requests (
  id              uuid primary key default gen_random_uuid(),
  tenant_id       uuid not null references tenants (id),
  subject_type    text not null check (subject_type in ('student', 'teacher', 'user', 'voice_note')),
  subject_id      uuid not null,
  mode            text not null check (mode in ('anonymize', 'purge')),
  legal_basis     text not null
                    check (legal_basis in ('data_subject_request', 'retention_expiry',
                                           'contract_termination', 'consent_withdrawn', 'court_order')),
  reason          text,
  requested_by_id uuid,
  requested_at    timestamptz not null default now(),
  scheduled_for   date,
  status          text not null default 'pending'
                    check (status in ('pending', 'scheduled', 'executed', 'rejected', 'cancelled')),
  executed_at     timestamptz,
  executed_by     text,
  execution_note  text,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  constraint deletion_requests_requested_by_fk foreign key (tenant_id, requested_by_id)
    references teachers (tenant_id, id),
  constraint deletion_requests_executed_consistent
    check ((status = 'executed') = (executed_at is not null))
);

comment on table deletion_requests is 'A record of every erasure, why it was lawful, who asked, and what was actually done. Ley 29733 gives a data subject a right to erasure; a schema whose rule is that nothing is ever deleted needs one sanctioned, audited path through that rule, and this is it.';
comment on column deletion_requests.mode is 'anonymize overwrites identifying columns and keeps the row, so attendance rates and grade distributions do not shift retroactively. purge removes the row entirely, for the narrower cases where anonymisation is not sufficient.';
comment on column deletion_requests.legal_basis is 'Why the erasure is lawful. Required: an erasure with no recorded basis is indistinguishable from tampering.';
comment on column deletion_requests.scheduled_for is 'Erasures run on a delay so an accidental or coerced request can be withdrawn before it is irreversible.';

create index deletion_requests_pending_idx
  on deletion_requests (scheduled_for) where status in ('pending', 'scheduled');
create index deletion_requests_subject_idx on deletion_requests (subject_type, subject_id);

select app.enable_tenant_rls('deletion_requests');
select app.attach_updated_at('deletion_requests');

-- ---------------------------------------------------------------------------
-- Anonymisation
-- ---------------------------------------------------------------------------
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

    -- Free text written about the child goes with the identity.
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

comment on function privacy.anonymize_student(uuid, uuid) is
  'Overwrites a student''s identifying columns and every free-text or audio artefact about them, in place. Attendance rows, scores and computed grades survive without names attached, so historical aggregates stay correct. The object-store audio itself must be deleted separately — this only clears the pointer, and the caller is responsible for the storage side.';

-- +goose Down

drop function if exists privacy.anonymize_student(uuid, uuid);
drop table if exists deletion_requests;
drop view if exists privacy.undeclared_student_references;
drop view if exists privacy.minor_data_tables;
drop view if exists privacy.pii_columns;
