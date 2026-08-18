-- Tenancy and identity: the RLS root, auth principals, and teacher profiles.

-- +goose Up

-- ---------------------------------------------------------------------------
-- tenants
-- ---------------------------------------------------------------------------
create table tenants (
  id                       uuid primary key default gen_random_uuid(),
  name                     text not null,
  legal_name               text,
  modular_code             text,
  kind                     text not null default 'publica'
                             check (kind in ('publica', 'privada', 'parroquial', 'internacional')),
  city                     text,
  region                   text,
  country_code             text not null default 'PE' check (country_code ~ '^[A-Z]{2}$'),
  timezone                 text not null default 'America/Lima',
  locale                   text not null default 'es-PE',
  default_retention_years  smallint not null default 5 check (default_retention_years between 1 and 30),
  status                   text not null default 'active' check (status in ('active', 'suspended', 'closed')),
  created_at               timestamptz not null default now(),
  updated_at               timestamptz not null default now(),
  deleted_at               timestamptz
);

comment on table tenants is 'One school (institución educativa). Root of every RLS policy: app.current_tenant_id() resolves to a row here.';
comment on column tenants.modular_code is 'MINEDU código modular of the institución educativa, where it has one. Null for private schools outside the registry.';
comment on column tenants.timezone is 'IANA timezone of the school. All timestamps are stored UTC; this is the only place a local calendar day is defined, so "HOY" on screen 01 is computed against it.';
comment on column tenants.default_retention_years is 'Default years to retain a student record after the student leaves, before anonymisation. Overridable per student via students.retention_until.';

create unique index tenants_modular_code_key
  on tenants (modular_code) where modular_code is not null and deleted_at is null;

-- A bad IANA name silently breaks every "today" query, so reject it at write time.
-- This is a trigger rather than a CHECK because validation needs a lookup in
-- pg_timezone_names, and CHECK expressions cannot contain subqueries.
-- +goose StatementBegin
create or replace function app.validate_tenant_timezone() returns trigger
  language plpgsql
  as $fn$
  begin
    if not exists (select 1 from pg_timezone_names where name = new.timezone) then
      raise exception 'unknown IANA timezone %', new.timezone using errcode = 'check_violation';
    end if;
    return new;
  end;
  $fn$;
-- +goose StatementEnd

create trigger validate_timezone before insert or update of timezone on tenants
  for each row execute function app.validate_tenant_timezone();

alter table tenants enable row level security;
alter table tenants force row level security;
create policy tenant_isolation on tenants
  using (id = app.current_tenant_id())
  with check (id = app.current_tenant_id());

select app.attach_updated_at('tenants');
select app.attach_soft_delete_guard('tenants');

-- ---------------------------------------------------------------------------
-- users
-- ---------------------------------------------------------------------------
-- Deliberately NOT tenant-scoped: one person may teach at two schools and must
-- keep a single credential. Isolation runs through memberships instead.
create table users (
  id             uuid primary key default gen_random_uuid(),
  email          text not null,
  given_name     text not null,
  family_name    text not null,
  display_name   text,
  phone          text,
  auth_subject   text,
  status         text not null default 'active' check (status in ('invited', 'active', 'suspended', 'deactivated')),
  last_login_at  timestamptz,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now(),
  deleted_at     timestamptz
);

comment on table users is 'PII (adult). Authentication principals: teachers, coordinators, directors, admins. Holds no minor data — students are not users in v1 and have no login.';
comment on column users.email is 'PII (adult): contact. Lowercased on write; uniqueness enforced on lower(email).';
comment on column users.phone is 'PII (adult): contact.';
comment on column users.auth_subject is 'Opaque subject claim from the identity provider. Null until the invite is accepted.';

create unique index users_email_key on users (lower(email)) where deleted_at is null;
create unique index users_auth_subject_key on users (auth_subject) where auth_subject is not null;

select app.attach_updated_at('users');
select app.attach_soft_delete_guard('users');

-- ---------------------------------------------------------------------------
-- memberships
-- ---------------------------------------------------------------------------
create table memberships (
  id          uuid primary key default gen_random_uuid(),
  tenant_id   uuid not null references tenants (id),
  user_id     uuid not null references users (id),
  role        text not null check (role in ('teacher', 'coordinator', 'director', 'admin', 'support')),
  status      text not null default 'active' check (status in ('invited', 'active', 'suspended', 'revoked')),
  joined_at   timestamptz not null default now(),
  revoked_at  timestamptz,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  deleted_at  timestamptz,
  constraint memberships_tenant_id_key unique (tenant_id, id),
  constraint memberships_revoked_consistent
    check ((status = 'revoked') = (revoked_at is not null))
);

comment on table memberships is 'Which user acts in which school, and in what role. The join that makes a users row visible under RLS.';
comment on constraint memberships_tenant_id_key on memberships is 'Redundant against the PK, but required so child tables can carry a composite (tenant_id, membership_id) FK — that is what makes a cross-tenant reference structurally impossible rather than merely unlikely.';

create unique index memberships_tenant_user_key
  on memberships (tenant_id, user_id) where deleted_at is null;
-- Screens 05/06: every request resolves the acting membership from the session user.
create index memberships_user_idx on memberships (user_id) where deleted_at is null;

select app.enable_tenant_rls('memberships');
select app.attach_updated_at('memberships');
select app.attach_soft_delete_guard('memberships');

-- users RLS depends on memberships existing, so the policy is created here.
alter table users enable row level security;
alter table users force row level security;
create policy tenant_isolation on users
  using (exists (select 1 from memberships m
                  where m.user_id = users.id
                    and m.tenant_id = app.current_tenant_id()
                    and m.deleted_at is null))
  with check (exists (select 1 from memberships m
                       where m.user_id = users.id
                         and m.tenant_id = app.current_tenant_id()
                         and m.deleted_at is null));

comment on policy tenant_isolation on users is
  'A user row is visible to a tenant only while an undeleted membership links them, which prevents cross-tenant enumeration of teacher emails. Note the ordering consequence: the membership must be inserted before the user row can be read back.';

-- ---------------------------------------------------------------------------
-- teachers
-- ---------------------------------------------------------------------------
-- Keyed on membership, not on user: the profile ("Docente de Secundaria",
-- hired_on) is per-school, and going through membership means there is exactly
-- one path from a teacher to a tenant.
create table teachers (
  id                       uuid primary key default gen_random_uuid(),
  tenant_id                uuid not null references tenants (id),
  membership_id            uuid not null,
  employee_code            text,
  display_name             text not null,
  title                    text,
  hired_on                 date,
  weekly_hours_contracted  numeric(5, 2) check (weekly_hours_contracted >= 0),
  status                   text not null default 'active' check (status in ('active', 'on_leave', 'inactive')),
  created_at               timestamptz not null default now(),
  updated_at               timestamptz not null default now(),
  deleted_at               timestamptz,
  constraint teachers_tenant_id_key unique (tenant_id, id),
  constraint teachers_membership_fk foreign key (tenant_id, membership_id)
    references memberships (tenant_id, id)
);

comment on table teachers is 'PII (adult). Per-school teaching profile. Screen 06 renders display_name, title and hired_on directly; email and login live on the linked users row.';
comment on column teachers.title is 'Role label as shown on screen 06, e.g. "Docente de Secundaria". Free text: schools word this inconsistently and it is display-only.';
comment on column teachers.hired_on is 'Start date at this school. Screen 06 renders "Desde marzo 2021 · 5 años" from it.';
comment on column teachers.weekly_hours_contracted is 'Contracted weekly hours. Screen 06''s "30h Semanales" is computed from class_schedules instead; this is the contract figure to reconcile against.';

create unique index teachers_membership_key on teachers (membership_id) where deleted_at is null;
create unique index teachers_employee_code_key
  on teachers (tenant_id, employee_code) where employee_code is not null and deleted_at is null;

select app.enable_tenant_rls('teachers');
select app.attach_updated_at('teachers');
select app.attach_soft_delete_guard('teachers');

-- +goose Down

drop table if exists teachers;
drop policy if exists tenant_isolation on users;
drop table if exists memberships;
drop table if exists users;
drop trigger if exists validate_timezone on tenants;
drop function if exists app.validate_tenant_timezone();
drop table if exists tenants;
