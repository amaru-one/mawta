-- Bootstrap: extensions, helper schemas, session context, shared trigger functions.
-- Everything downstream depends on this file.

-- +goose Up

create extension if not exists btree_gist;  -- uuid WITH = inside EXCLUDE constraints
create extension if not exists pg_trgm;     -- class/student search boxes (screens 01, 03)
create extension if not exists vector;      -- reserved: voice-note + observation embeddings

create schema if not exists app;
create schema if not exists privacy;

comment on schema app is 'Session context helpers and shared trigger functions. Holds no business data.';
comment on schema privacy is 'Views and helpers for discovering and auditing personal-data columns (Ley 29733 tooling).';

-- Postgres has no built-in range over `time`; class_schedules needs one to reject
-- overlapping weekly slots for the same class.
create type timerange as range (subtype = time);
comment on type timerange is 'Local wall-clock interval within a weekday. Used by class_schedules exclusion constraints.';

-- ---------------------------------------------------------------------------
-- Application role
-- ---------------------------------------------------------------------------
-- RLS is only real if the connection role is NOT the table owner: a table owner
-- bypasses policies unless FORCE ROW LEVEL SECURITY is set, and even then
-- BYPASSRLS roles ignore them. The Go service must connect as yanai_app.

-- +goose StatementBegin
do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'yanai_app') then
    create role yanai_app nologin;
  end if;
end
$$;
-- +goose StatementEnd

grant usage on schema public, app, privacy to yanai_app;
alter default privileges in schema public grant select, insert, update, delete on tables to yanai_app;
alter default privileges in schema public grant usage, select on sequences to yanai_app;
alter default privileges in schema privacy grant select on tables to yanai_app;

-- ---------------------------------------------------------------------------
-- Session context
-- ---------------------------------------------------------------------------

-- +goose StatementBegin
create or replace function app.current_tenant_id() returns uuid
  language sql stable
  as $fn$
    select nullif(current_setting('app.tenant_id', true), '')::uuid;
  $fn$;
-- +goose StatementEnd

comment on function app.current_tenant_id() is
  'Tenant of the current session, read from SET LOCAL app.tenant_id. Returns NULL when unset, so every RLS predicate evaluates to NULL (i.e. no rows) rather than raising — a query that forgets its tenant filter returns nothing.';

-- +goose StatementBegin
create or replace function app.current_actor_id() returns uuid
  language sql stable
  as $fn$
    select nullif(current_setting('app.actor_id', true), '')::uuid;
  $fn$;
-- +goose StatementEnd

comment on function app.current_actor_id() is
  'Authenticated user of the current session, from SET LOCAL app.actor_id. Used to default actor columns on audit and event rows.';

-- ---------------------------------------------------------------------------
-- Shared trigger functions
-- ---------------------------------------------------------------------------

-- +goose StatementBegin
create or replace function app.set_updated_at() returns trigger
  language plpgsql
  as $fn$
  begin
    new.updated_at := now();
    return new;
  end;
  $fn$;
-- +goose StatementEnd

-- +goose StatementBegin
create or replace function app.forbid_hard_delete() returns trigger
  language plpgsql
  as $fn$
  begin
    if coalesce(nullif(current_setting('app.allow_hard_delete', true), ''), 'off') <> 'on' then
      raise exception '% is soft-delete only; set app.allow_hard_delete to run an authorised erasure', tg_table_name
        using errcode = 'restrict_violation',
              hint = 'Set deleted_at instead. Lawful erasure runs through privacy.execute_deletion_request().';
    end if;
    return old;
  end;
  $fn$;
-- +goose StatementEnd

comment on function app.forbid_hard_delete() is
  'Blocks DELETE on tables that must be soft-deleted. The app.allow_hard_delete escape hatch exists so a Ley 29733 erasure request can still be honoured — see privacy.deletion_requests.';

-- ---------------------------------------------------------------------------
-- DDL helpers
-- ---------------------------------------------------------------------------

-- +goose StatementBegin
create or replace function app.attach_updated_at(p_table regclass) returns void
  language plpgsql
  as $fn$
  begin
    execute format(
      'create trigger set_updated_at before update on %s for each row execute function app.set_updated_at()',
      p_table);
  end;
  $fn$;
-- +goose StatementEnd

-- +goose StatementBegin
create or replace function app.attach_soft_delete_guard(p_table regclass) returns void
  language plpgsql
  as $fn$
  begin
    execute format(
      'create trigger forbid_hard_delete before delete on %s for each row execute function app.forbid_hard_delete()',
      p_table);
  end;
  $fn$;
-- +goose StatementEnd

-- +goose StatementBegin
create or replace function app.enable_tenant_rls(p_table regclass) returns void
  language plpgsql
  as $fn$
  begin
    execute format('alter table %s enable row level security', p_table);
    execute format('alter table %s force row level security', p_table);
    execute format(
      'create policy tenant_isolation on %s using (tenant_id = app.current_tenant_id()) with check (tenant_id = app.current_tenant_id())',
      p_table);
  end;
  $fn$;
-- +goose StatementEnd

comment on function app.enable_tenant_rls(regclass) is
  'Applies the standard shared-schema isolation policy to a tenant-scoped table. FORCE is deliberate: it makes the policy apply to the table owner too, so a migration or an ops session cannot accidentally read across tenants.';

-- +goose Down

-- Role cleanup runs first: DROP OWNED BY resolves the default-privilege
-- entries, which are recorded against schemas that the drops below remove.
-- +goose StatementBegin
do $$
begin
  if exists (select 1 from pg_roles where rolname = 'yanai_app') then
    execute 'drop owned by yanai_app';
    execute 'drop role yanai_app';
  end if;
end
$$;
-- +goose StatementEnd

drop function if exists app.enable_tenant_rls(regclass);
drop function if exists app.attach_soft_delete_guard(regclass);
drop function if exists app.attach_updated_at(regclass);
drop function if exists app.forbid_hard_delete();
drop function if exists app.set_updated_at();
drop function if exists app.current_actor_id();
drop function if exists app.current_tenant_id();

drop type if exists timerange;

drop schema if exists privacy cascade;
drop schema if exists app cascade;
