-- Complete schema, as a single migration.
--
-- Squashed twice. First on 2026-08-26, from the original incremental history
-- (00001_bootstrap through 00018_competency_levels); again on 2026-09-10, from
-- 00001..00009, after the local database was dropped and with no environment
-- depending on the intermediate steps either time. No behavioural change from
-- the last state of either chain: every table below is in its final form, and
-- anything the chain created and then dropped is simply absent.
--
-- What the second squash removed rather than replayed: the predictive
-- subsystem (risk_rules, risk_flags, risk_flag_evidence, notifications.risk_
-- flag_id, computed_grades' two projection columns), the per-session
-- observation subsystem (session_observations, session_observation_flags,
-- behavior_flag_types, app.sync_observation_denormalised) and
-- evaluation_criterion_scores with its two trigger functions — all created and
-- later dropped inside the chain. Written directly in final form rather than
-- created-then-altered: assessments (student_id, counts_toward_internal,
-- value_scale, nullable max_score), scores (scale_level_id, nullable
-- max_value, the relaxed value/status checks), tenants.uses_internal_grading
-- and app.forbid_score_mutation. See migrations/SPEC.md's Change Log for the
-- reasoning behind each.
--
-- The one deliberate behavioural change made by the second squash, not a
-- replay of anything in the chain: 'quiz' and 'rubrica' are gone from the
-- assessment kind vocabulary, in every table that carries it (assessments,
-- practice_scores).
--
-- 2026-09-11: a third pass, not a squash — a dead-schema cleanup, done against
-- the live Go and yanai-ui code rather than against migration history. Removed
-- outright, whole: assessment_templates + assessment_template_competencies
-- (the reusable-template feature — no Go or UI code path ever called it),
-- note_summaries + note_summary_sources (the AI note-summary feature; its
-- route was retired 2026-08-29 and nothing has written a row since —
-- reverses migrations/SPEC.md's 2026-08-29 "keep it" resolution on an
-- explicit decision to do so this time), deletion_requests and the whole
-- privacy.anonymize_student() function (the erasure/anonymisation path —
-- no caller ever existed), and term_grade_snapshots (the closed-term acta
-- snapshot — no caller ever existed). Also dropped: 27 individual columns
-- across 12 surviving tables that no Go or UI code reads or writes, along
-- with the constraints, indexes and comments built only around them —
-- tenants (country_code, locale, default_retention_years), users
-- (auth_subject, last_login_at), memberships (revoked_at), students
-- (photo_storage_key, guardian_contact_note, anonymized_at, purge_after,
-- deleted_by_id, retention_until — the rest of the privacy/anonymisation
-- columns, consistent with dropping the function that used them),
-- section_memberships (exit_reason), class_sessions (plan_note, cancelled_at,
-- cancellation_reason, rescheduled_from_session_id), grading_scheme_versions
-- and assessments (late_penalty_max_pct, on both), class_grading_policies
-- (assigned_by_id, assigned_at), assessments (template_id, allows_retake, its
-- own late_penalty_max_pct), computed_grades (computed_at — its two indexes
-- that ordered by it now order by created_at instead), notifications
-- (dedupe_key, expires_at), and voice_notes (storage_bucket,
-- transcription_job_id, transcript_language, transcript_confidence,
-- transcribed_at, embedding, embedding_model, embedded_at, purged_at — the
-- whole transcription/embedding pipeline; the pgvector extension is no longer
-- loaded, since nothing uses the vector type once embedding is gone).
-- students.status also lost its 'anonymized' value, the only one that meant
-- nothing once anonymized_at was gone; class_sessions.status keeps
-- 'cancelled'/'rescheduled' — those remain meaningful states on their own,
-- just without the auxiliary detail columns. Both prior migration-history
-- squashes are otherwise untouched by this pass: nothing here was ever
-- created and dropped within the chain, it simply never had a caller. See
-- migrations/SPEC.md's Change Log for the full accounting and what was
-- deliberately kept (retake_authorizations — a live join in
-- worker/handlers/recompute.go — and competency_year_snapshots /
-- year_final_situations, per the standing 2026-08-29 resolution).

-- +goose Up

create extension if not exists btree_gist;  -- uuid WITH = inside EXCLUDE constraints
create extension if not exists pg_trgm;     -- class/student search boxes (screens 01, 03)

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

-- Hard deletes are allowed while the project is in development; this helper is
-- kept as a no-op so downstream migrations that call it keep working.
-- +goose StatementBegin
create or replace function app.attach_soft_delete_guard(p_table regclass) returns void
  language plpgsql
  as $fn$
  begin
    -- no-op: hard DELETE is permitted during development
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
  timezone                 text not null default 'America/Lima',
  uses_internal_grading    boolean not null default true,
  status                   text not null default 'active' check (status in ('active', 'suspended', 'closed')),
  created_at               timestamptz not null default now(),
  updated_at               timestamptz not null default now(),
  deleted_at               timestamptz
);

comment on table tenants is 'One school (institución educativa). Root of every RLS policy: app.current_tenant_id() resolves to a row here.';
comment on column tenants.modular_code is 'MINEDU código modular of the institución educativa, where it has one. Null for private schools outside the registry.';
comment on column tenants.timezone is 'IANA timezone of the school. All timestamps are stored UTC; this is the only place a local calendar day is defined, so "HOY" on screen 01 is computed against it.';
comment on column tenants.uses_internal_grading is
  'Whether this school runs its own weighted numeric grading system alongside the official MINEDU record (D.S. 009-2006-ED art. 37.4.f permits one). True is the historical behaviour and stays the default. False means the school records only niveles de logro: the UI stops asking for a mark on each piece of evidence and hides computed_grades entirely. It never changes how the official record is produced, which is the teacher''s judgement of evidence against the criterios either way. No value of this column may cause a number to determine a nivel de logro: RVM 048-2024 Anexo II converts a level into a number, never the reverse.';

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
  status         text not null default 'active' check (status in ('invited', 'active', 'suspended', 'deactivated')),
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now(),
  deleted_at     timestamptz
);

comment on table users is 'PII (adult). Authentication principals: teachers, coordinators, directors, admins. Holds no minor data — students are not users in v1 and have no login.';
comment on column users.email is 'PII (adult): contact. Lowercased on write; uniqueness enforced on lower(email).';
comment on column users.phone is 'PII (adult): contact.';

create unique index users_email_key on users (lower(email)) where deleted_at is null;

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
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  deleted_at  timestamptz,
  constraint memberships_tenant_id_key unique (tenant_id, id)
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


-- ---------------------------------------------------------------------------
-- academic_years
-- ---------------------------------------------------------------------------
create table academic_years (
  id              uuid primary key default gen_random_uuid(),
  tenant_id       uuid not null references tenants (id),
  year            smallint not null check (year between 2000 and 2100),
  name            text not null,
  starts_on       date not null,
  ends_on         date not null,
  term_structure  text not null default 'bimestre'
                    check (term_structure in ('bimestre', 'trimestre', 'semestre')),
  status          text not null default 'planned'
                    check (status in ('planned', 'active', 'closed')),
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  deleted_at      timestamptz,
  constraint academic_years_tenant_id_key unique (tenant_id, id),
  constraint academic_years_range_valid check (ends_on > starts_on)
);

comment on table academic_years is 'One school year (año escolar) for one tenant. In Peru this runs roughly March to December, not January to December.';
comment on column academic_years.term_structure is 'How the year is subdivided. Most Peruvian schools use four bimestres; some use trimestres. Stored per year, not per tenant, because schools do change this between years.';

create unique index academic_years_tenant_year_key
  on academic_years (tenant_id, year) where deleted_at is null;
-- Only one year may be active at a time; screens 01 and 02 assume "the current year" with no selector.
create unique index academic_years_one_active_key
  on academic_years (tenant_id) where status = 'active' and deleted_at is null;

select app.enable_tenant_rls('academic_years');
select app.attach_updated_at('academic_years');
select app.attach_soft_delete_guard('academic_years');

-- ---------------------------------------------------------------------------
-- terms
-- ---------------------------------------------------------------------------
create table terms (
  id                uuid primary key default gen_random_uuid(),
  tenant_id         uuid not null references tenants (id),
  academic_year_id  uuid not null,
  sequence          smallint not null check (sequence between 1 and 6),
  name              text not null,
  short_name        text,
  starts_on         date not null,
  ends_on           date not null,
  status            text not null default 'planned'
                      check (status in ('planned', 'active', 'closed', 'archived')),
  grades_due_on     date,
  closed_at         timestamptz,
  closed_by_id      uuid references teachers (id),
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now(),
  deleted_at        timestamptz,
  constraint terms_tenant_id_key unique (tenant_id, id),
  constraint terms_year_fk foreign key (tenant_id, academic_year_id)
    references academic_years (tenant_id, id),
  constraint terms_range_valid check (ends_on > starts_on),
  constraint terms_closed_consistent
    check ((status in ('closed', 'archived')) = (closed_at is not null)),
  constraint terms_no_overlap
    exclude using gist (academic_year_id with =, daterange(starts_on, ends_on, '[]') with &&)
    where (deleted_at is null)
);

comment on table terms is 'A bimestre, trimestre or semestre. Screen 04 renders name ("Bimestre II"); screen 06 scopes its whole activity panel to one term.';
comment on column terms.sequence is 'Ordinal position within the year. Bimestre II is sequence 2. Bounded at 6 so a mis-typed value cannot create a phantom term.';
comment on column terms.grades_due_on is 'Deadline for submitting grades. Drives the "notas pendientes" reminders on screen 05.';
comment on column terms.closed_at is 'When the term was closed. A closed term rejects new scores, which is what keeps a grade already reported from changing after the fact.';
comment on constraint terms_no_overlap on terms is 'Two terms in the same year cannot cover the same date, so "the term containing this session" is always a single row.';

create unique index terms_year_sequence_key
  on terms (academic_year_id, sequence) where deleted_at is null;
-- Screens 02/04/06: nearly every aggregate is "for the current term", resolved by date.
create index terms_tenant_range_idx on terms (tenant_id, starts_on, ends_on) where deleted_at is null;

select app.enable_tenant_rls('terms');
select app.attach_updated_at('terms');
select app.attach_soft_delete_guard('terms');

-- ---------------------------------------------------------------------------
-- grade_levels
-- ---------------------------------------------------------------------------
-- A table, not an enum or a smallint: screen 06 groups classes under "1ER
-- GRADO".."5TO GRADO" (Peruvian secundaria), but "Math 8B" on screen 05 implies
-- a school numbering grades 1-11, and international schools use "Year 9".
create table grade_levels (
  id          uuid primary key default gen_random_uuid(),
  tenant_id   uuid not null references tenants (id),
  code        text not null,
  label       text not null,
  long_label  text not null,
  stage       text not null default 'secundaria'
                check (stage in ('inicial', 'primaria', 'secundaria', 'otro')),
  ordinal     smallint not null,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  deleted_at  timestamptz,
  constraint grade_levels_tenant_id_key unique (tenant_id, id)
);

comment on table grade_levels is 'Grade levels as the school names them. Modelled as rows so a school can use 1ro-5to secundaria, grades 1-11, or Year 7-11 without a schema change.';
comment on column grade_levels.label is 'Short form used inside a class name, e.g. "5to" in "Inglés 5to B".';
comment on column grade_levels.long_label is 'Section-header form on screen 06, e.g. "5TO GRADO".';
comment on column grade_levels.ordinal is 'Sort order for screen 06''s grouped class list. Distinct from code, which may not sort naturally.';

create unique index grade_levels_tenant_code_key
  on grade_levels (tenant_id, code) where deleted_at is null;
create unique index grade_levels_tenant_ordinal_key
  on grade_levels (tenant_id, ordinal) where deleted_at is null;

select app.enable_tenant_rls('grade_levels');
select app.attach_updated_at('grade_levels');
select app.attach_soft_delete_guard('grade_levels');


-- ---------------------------------------------------------------------------
-- subjects
-- ---------------------------------------------------------------------------
create table subjects (
  id              uuid primary key default gen_random_uuid(),
  tenant_id       uuid not null references tenants (id),
  code            text not null,
  name            text not null,
  area_curricular text,
  icon_key        text,
  is_tutoria      boolean not null default false,
  sort_order      smallint not null default 0,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  deleted_at      timestamptz,
  constraint subjects_tenant_id_key unique (tenant_id, id)
);

comment on table subjects is 'A school subject: Matemática, Comunicación, Inglés, Historia, Geografía, Tutoría.';
comment on column subjects.area_curricular is 'MINEDU área curricular the subject belongs to, e.g. "Ciencias Sociales" for Historia and Geografía. Kept in Spanish: it is a named artefact of the national curriculum, not a generic category.';
comment on column subjects.icon_key is 'Stable key for the glyph on screen 01''s class cards (calculator, book, bank, world). Stored rather than derived from the name, so renaming a subject does not change its icon.';
comment on column subjects.is_tutoria is 'Tutoría is timetabled like a subject but is not graded on the achievement scale. Screen 06 lists "Tutoría 5to A" among the classes; it must be excluded from achievement-distribution aggregates.';

create unique index subjects_tenant_code_key
  on subjects (tenant_id, code) where deleted_at is null;

select app.enable_tenant_rls('subjects');
select app.attach_updated_at('subjects');
select app.attach_soft_delete_guard('subjects');

-- ---------------------------------------------------------------------------
-- competencies
-- ---------------------------------------------------------------------------
-- competencies.kind (RVM 094-2020 num. 5.1.3 p.9-11: transversales never
-- count towards promotion; adicionales count only when organised into an
-- área) and the nullable subject_id it requires (transversales belong to no
-- área) are final-state here rather than replayed as a later ALTER — see
-- the historical note in migrations/SPEC.md.
create table competencies (
  id           uuid primary key default gen_random_uuid(),
  tenant_id    uuid not null references tenants (id),
  subject_id   uuid,
  code         text not null,
  name         text not null,
  description  text,
  kind         text not null default 'area'
                 check (kind in ('area', 'transversal', 'adicional_area', 'adicional_libre')),
  sort_order   smallint not null default 0,
  is_active    boolean not null default true,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now(),
  deleted_at   timestamptz,
  constraint competencies_tenant_id_key unique (tenant_id, id),
  constraint competencies_subject_fk foreign key (tenant_id, subject_id)
    references subjects (tenant_id, id),
  constraint competencies_transversal_has_no_subject
    check ((kind = 'transversal') = (subject_id is null))
);

comment on table competencies is 'A MINEDU competencia within a subject, e.g. "Se comunica oralmente en inglés como lengua extranjera". Assessments link here so achievement can later be reported per competency rather than only per component.';
comment on column competencies.code is 'National curriculum code where one exists, otherwise a school-local code. Not unique across tenants by design: two schools may code the same competency differently.';
comment on column competencies.kind is
  'What this competency counts as for promotion (RVM 094-2020 num. 5.1.3 p.9-11). ''area'': a CNEB competency of an área curricular or taller — counts. ''adicional_area'': a school-added competency organised into an área curricular — counts (5.1.3 p.11). ''adicional_libre'': a school-added competency not organised into an área — does not count (p.10). ''transversal'': one of the two CNEB cross-cutting competencies — never counts (p.9), and carries no subject_id.';
comment on column competencies.subject_id is
  'The área curricular or taller this competency belongs to. Null only for kind = ''transversal'': the two CNEB cross-cutting competencies are not adscribed to an área or to a single teacher (5.1.1.3 p.8), and each IE decides how their level is assigned.';

create unique index competencies_subject_code_key
  on competencies (tenant_id, subject_id, code) where deleted_at is null;
-- competencies_subject_code_key is partial on a nullable column, so it does
-- not constrain transversales; they need their own uniqueness.
create unique index competencies_transversal_code_key
  on competencies (tenant_id, code)
  where subject_id is null and deleted_at is null;

select app.enable_tenant_rls('competencies');
select app.attach_updated_at('competencies');
select app.attach_soft_delete_guard('competencies');

-- ---------------------------------------------------------------------------
-- courses
-- ---------------------------------------------------------------------------
-- subject x grade level x year. "Inglés 5to" as a curricular offering, before
-- it is split across sections A/B/C. Grading policy can be overridden here.
create table courses (
  id                uuid primary key default gen_random_uuid(),
  tenant_id         uuid not null references tenants (id),
  academic_year_id  uuid not null,
  subject_id        uuid not null,
  grade_level_id    uuid not null,
  name              text not null,
  code              text,
  weekly_hours      numeric(4, 2) check (weekly_hours >= 0),
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now(),
  deleted_at        timestamptz,
  constraint courses_tenant_id_key unique (tenant_id, id),
  constraint courses_year_fk foreign key (tenant_id, academic_year_id)
    references academic_years (tenant_id, id),
  constraint courses_subject_fk foreign key (tenant_id, subject_id)
    references subjects (tenant_id, id),
  constraint courses_grade_level_fk foreign key (tenant_id, grade_level_id)
    references grade_levels (tenant_id, id)
);

comment on table courses is 'A subject taught at a grade level in a given year. Sits between subjects and classes so curriculum (units, competencies) and grading policy are authored once per grade, not once per section.';
comment on column courses.weekly_hours is 'Nominal timetabled hours per week from the plan de estudios. The real figure comes from class_schedules; this is the plan to compare against.';

create unique index courses_natural_key
  on courses (tenant_id, academic_year_id, subject_id, grade_level_id) where deleted_at is null;

select app.enable_tenant_rls('courses');
select app.attach_updated_at('courses');
select app.attach_soft_delete_guard('courses');

-- ---------------------------------------------------------------------------
-- units
-- ---------------------------------------------------------------------------
create table units (
  id          uuid primary key default gen_random_uuid(),
  tenant_id   uuid not null references tenants (id),
  course_id   uuid not null,
  term_id     uuid,
  sequence    smallint not null,
  title       text not null,
  description text,
  starts_on   date,
  ends_on     date,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  deleted_at  timestamptz,
  constraint units_tenant_id_key unique (tenant_id, id),
  constraint units_course_fk foreign key (tenant_id, course_id)
    references courses (tenant_id, id),
  constraint units_term_fk foreign key (tenant_id, term_id)
    references terms (tenant_id, id),
  constraint units_range_valid check (ends_on is null or starts_on is null or ends_on >= starts_on)
);

comment on table units is 'A unidad didáctica within a course. Sessions and assessments point at a unit so "Present perfect tense" on screen 02 can be placed in the syllabus.';
comment on column units.term_id is 'Term the unit is planned for. Nullable: some schools plan units by date only and let them straddle a bimestre boundary.';

create unique index units_course_sequence_key
  on units (tenant_id, course_id, sequence) where deleted_at is null;

select app.enable_tenant_rls('units');
select app.attach_updated_at('units');
select app.attach_soft_delete_guard('units');

-- ---------------------------------------------------------------------------
-- unit_competencies
-- ---------------------------------------------------------------------------
create table unit_competencies (
  id             uuid primary key default gen_random_uuid(),
  tenant_id      uuid not null references tenants (id),
  unit_id        uuid not null,
  competency_id  uuid not null,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now(),
  deleted_at     timestamptz,
  constraint unit_competencies_unit_fk foreign key (tenant_id, unit_id)
    references units (tenant_id, id),
  constraint unit_competencies_competency_fk foreign key (tenant_id, competency_id)
    references competencies (tenant_id, id)
);

comment on table unit_competencies is 'Which competencies a unit develops. Lets an ungraded session still be attributed to a competency through its unit.';

create unique index unit_competencies_key
  on unit_competencies (unit_id, competency_id) where deleted_at is null;
create index unit_competencies_competency_idx on unit_competencies (competency_id);

select app.enable_tenant_rls('unit_competencies');
select app.attach_updated_at('unit_competencies');
select app.attach_soft_delete_guard('unit_competencies');


-- ---------------------------------------------------------------------------
-- capabilities
-- ---------------------------------------------------------------------------
-- The CNEB chain below a competencia is Competencia -> Capacidades (fixed,
-- national, 2-4 per competencia) -> Desempeños (national, per grado/ciclo) ->
-- the teacher's own criterios de evaluación (desempeños precisados, adapted to
-- a unit/rubric). The three tables here and assessment_criteria below are that
-- chain. competency_term_levels stays a teacher's judgement call and is never
-- computed from any of it.
create table capabilities (
  id            uuid primary key default gen_random_uuid(),
  tenant_id     uuid not null references tenants (id),
  competency_id uuid not null,
  code          text not null,
  name          text not null,
  description   text,
  sort_order    smallint not null default 0,
  is_active     boolean not null default true,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now(),
  deleted_at    timestamptz,
  constraint capabilities_tenant_id_key unique (tenant_id, id),
  constraint capabilities_competency_fk foreign key (tenant_id, competency_id)
    references competencies (tenant_id, id)
);

comment on table capabilities is 'A MINEDU capacidad: one of the 2-4 fixed sub-skills that make up a competencia (CNEB). Fixed and national in content, but authored per tenant like competencies: a school loads its own copy of the national list; there is no cross-tenant sharing in this version.';
comment on column capabilities.code is 'National curriculum code where one exists, otherwise a school-local code. Not unique across tenants, matching competencies.code.';

create unique index capabilities_competency_code_key
  on capabilities (tenant_id, competency_id, code) where deleted_at is null;

select app.enable_tenant_rls('capabilities');
select app.attach_updated_at('capabilities');
select app.attach_soft_delete_guard('capabilities');


-- ---------------------------------------------------------------------------
-- performance_standards
-- ---------------------------------------------------------------------------
-- A desempeño is defined per ciclo in the CNEB (e.g. ciclo VI = 1.-2. de
-- secundaria), which can span more than one grade_levels row. Rather than a
-- range, this models one row per grade_level it applies to: simpler FK, at
-- the cost of duplicating a ciclo-wide desempeño across its grades. Matches
-- how the schema already prefers explicit rows over ranges except where an
-- exclusion constraint needs one (class_schedules, terms).
create table performance_standards (
  id             uuid primary key default gen_random_uuid(),
  tenant_id      uuid not null references tenants (id),
  capability_id  uuid not null,
  grade_level_id uuid,
  code           text not null,
  description    text not null,
  sort_order     smallint not null default 0,
  is_active      boolean not null default true,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now(),
  deleted_at     timestamptz,
  constraint performance_standards_tenant_id_key unique (tenant_id, id),
  constraint performance_standards_capability_fk foreign key (tenant_id, capability_id)
    references capabilities (tenant_id, id),
  constraint performance_standards_grade_level_fk foreign key (tenant_id, grade_level_id)
    references grade_levels (tenant_id, id)
);

comment on table performance_standards is 'A MINEDU desempeño: the national description of expected performance for one capacidad at one grade level. Null grade_level_id is reserved for a desempeño not yet tied to a specific grade (e.g. authored ahead of the grade_levels catalog); a ciclo-wide desempeño is one row per grade it covers, not a range.';
comment on column performance_standards.description is 'The desempeño text itself, verbatim from the CNEB or the school''s adaptation of it.';

create unique index performance_standards_grade_key
  on performance_standards (tenant_id, capability_id, grade_level_id, code)
  where deleted_at is null and grade_level_id is not null;
-- performance_standards_grade_key is partial on a nullable column, so a
-- desempeño not yet tied to a grade needs its own uniqueness, mirroring
-- competencies_transversal_code_key.
create unique index performance_standards_ungraded_key
  on performance_standards (tenant_id, capability_id, code)
  where deleted_at is null and grade_level_id is null;

select app.enable_tenant_rls('performance_standards');
select app.attach_updated_at('performance_standards');
select app.attach_soft_delete_guard('performance_standards');


-- ---------------------------------------------------------------------------
-- evaluation_criteria
-- ---------------------------------------------------------------------------
-- What a teacher actually writes and loads: a desempeño precisado for a unit
-- or rubric. Known gap, deliberately not enforced here: nothing checks that
-- performance_standard_id's capacidad belongs to competency_id. Cross-table
-- consistency like this exists elsewhere only via trigger (see
-- app.sync_score_denormalised); adding one is a flagged follow-up, not an
-- oversight.
create table evaluation_criteria (
  id                       uuid primary key default gen_random_uuid(),
  tenant_id                uuid not null references tenants (id),
  competency_id            uuid not null,
  performance_standard_id  uuid,
  unit_id                  uuid,
  code                     text,
  description              text not null,
  sort_order               smallint not null default 0,
  is_active                boolean not null default true,
  created_at               timestamptz not null default now(),
  updated_at               timestamptz not null default now(),
  deleted_at               timestamptz,
  constraint evaluation_criteria_tenant_id_key unique (tenant_id, id),
  constraint evaluation_criteria_competency_fk foreign key (tenant_id, competency_id)
    references competencies (tenant_id, id),
  constraint evaluation_criteria_performance_standard_fk foreign key (tenant_id, performance_standard_id)
    references performance_standards (tenant_id, id),
  constraint evaluation_criteria_unit_fk foreign key (tenant_id, unit_id)
    references units (tenant_id, id)
);

comment on table evaluation_criteria is 'A criterio de evaluación: the teacher''s own precisado of a desempeño (or an ad hoc criterion with no desempeño linked yet), for a unit or rubric. This is the layer teachers load into the system to evaluate a competencia.';
comment on column evaluation_criteria.performance_standard_id is 'The national desempeño this criterio precises. Nullable: a teacher may write a criterio before linking it to the national catalog.';
comment on column evaluation_criteria.unit_id is 'The unidad didáctica this criterio was authored for. Nullable so a criterio can be authored ahead of a unit, or reused across units.';

create index evaluation_criteria_competency_idx
  on evaluation_criteria (tenant_id, competency_id) where deleted_at is null;
create index evaluation_criteria_unit_idx
  on evaluation_criteria (unit_id) where unit_id is not null and deleted_at is null;

select app.enable_tenant_rls('evaluation_criteria');
select app.attach_updated_at('evaluation_criteria');
select app.attach_soft_delete_guard('evaluation_criteria');


-- ---------------------------------------------------------------------------
-- sections
-- ---------------------------------------------------------------------------
create table sections (
  id                uuid primary key default gen_random_uuid(),
  tenant_id         uuid not null references tenants (id),
  academic_year_id  uuid not null,
  grade_level_id    uuid not null,
  label             text not null,
  name              text not null,
  tutor_teacher_id  uuid,
  shift             text not null default 'manana'
                      check (shift in ('manana', 'tarde', 'noche', 'completo')),
  capacity          smallint check (capacity > 0),
  status            text not null default 'active' check (status in ('active', 'archived')),
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now(),
  deleted_at        timestamptz,
  constraint sections_tenant_id_key unique (tenant_id, id),
  constraint sections_year_fk foreign key (tenant_id, academic_year_id)
    references academic_years (tenant_id, id),
  constraint sections_grade_level_fk foreign key (tenant_id, grade_level_id)
    references grade_levels (tenant_id, id),
  constraint sections_tutor_fk foreign key (tenant_id, tutor_teacher_id)
    references teachers (tenant_id, id)
);

comment on table sections is 'A cohort of students who move together through every subject, e.g. "5to B". The roster: a student belongs to a section, and thereby to every class taught to that section.';
comment on column sections.label is 'Section letter on its own, e.g. "B".';
comment on column sections.name is 'Display form combining grade and letter, e.g. "5to B". Stored rather than derived because schools use their own spacing and abbreviations.';
comment on column sections.tutor_teacher_id is 'Homeroom tutor. Distinct from the teacher of the Tutoría class, which is timetabled separately.';

create unique index sections_natural_key
  on sections (tenant_id, academic_year_id, grade_level_id, label) where deleted_at is null;
create index sections_tutor_idx on sections (tutor_teacher_id) where deleted_at is null;

select app.enable_tenant_rls('sections');
select app.attach_updated_at('sections');
select app.attach_soft_delete_guard('sections');

-- ---------------------------------------------------------------------------
-- students
-- ---------------------------------------------------------------------------
create table students (
  id               uuid primary key default gen_random_uuid(),
  tenant_id        uuid not null references tenants (id),
  student_code     text,
  given_name       text not null,
  paternal_surname text not null,
  maternal_surname text,
  preferred_name   text,
  birthdate        date,
  sex              text check (sex in ('F', 'M', 'X', 'unspecified')),
  document_type    text check (document_type in ('DNI', 'CE', 'PAS', 'PTP', 'otro')),
  document_number  text,
  enrolled_on      date,
  left_on          date,
  status           text not null default 'active'
                     check (status in ('active', 'withdrawn', 'transferred', 'graduated')),
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now(),
  deleted_at       timestamptz,
  constraint students_tenant_id_key unique (tenant_id, id),
  constraint students_document_pair check ((document_type is null) = (document_number is null)),
  constraint students_left_after_enrolled check (left_on is null or enrolled_on is null or left_on >= enrolled_on)
);

comment on table students is
  'MINORS'' PERSONAL DATA. Every row is a child. Holds: legal names, birthdate, sex and national identity document. Processed under Ley 29733 (Perú) with parental consent held by the school. Every read must be recorded in events (action=''student.read'').';

comment on column students.student_code is 'PII (minor): identifier. School-internal enrolment code (código de matrícula).';
comment on column students.given_name is 'PII (minor): name.';
comment on column students.paternal_surname is 'PII (minor): name. Peruvian convention keeps the two surnames separate; concatenating them loses information.';
comment on column students.maternal_surname is 'PII (minor): name.';
comment on column students.preferred_name is 'PII (minor): name. What the teacher actually calls the student.';
comment on column students.birthdate is 'PII (minor): sensitive. Present because age drives both curriculum placement and the consent regime; not needed for any of the six screens.';
comment on column students.sex is 'PII (minor): sensitive.';
comment on column students.document_number is 'PII (minor): government identifier. DNI or equivalent. The highest-risk column in the schema.';

create unique index students_tenant_code_key
  on students (tenant_id, student_code) where student_code is not null and deleted_at is null;
create unique index students_tenant_document_key
  on students (tenant_id, document_type, document_number) where document_number is not null and deleted_at is null;
-- Screen 03: "Buscar alumno..." over a roster, typed one character at a time.
create index students_name_trgm_idx on students
  using gin ((coalesce(given_name, '') || ' ' || coalesce(paternal_surname, '') || ' ' || coalesce(maternal_surname, '')) gin_trgm_ops);

select app.enable_tenant_rls('students');
select app.attach_updated_at('students');
select app.attach_soft_delete_guard('students');

-- ---------------------------------------------------------------------------
-- section_memberships
-- ---------------------------------------------------------------------------
create table section_memberships (
  id                uuid primary key default gen_random_uuid(),
  tenant_id         uuid not null references tenants (id),
  student_id        uuid not null,
  section_id        uuid not null,
  academic_year_id  uuid not null,
  joined_on         date not null,
  left_on           date,
  status            text not null default 'active'
                      check (status in ('active', 'withdrawn', 'transferred', 'promoted')),
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now(),
  deleted_at        timestamptz,
  constraint section_memberships_student_fk foreign key (tenant_id, student_id)
    references students (tenant_id, id),
  constraint section_memberships_section_fk foreign key (tenant_id, section_id)
    references sections (tenant_id, id),
  constraint section_memberships_year_fk foreign key (tenant_id, academic_year_id)
    references academic_years (tenant_id, id),
  constraint section_memberships_range_valid check (left_on is null or left_on >= joined_on),
  constraint section_memberships_active_consistent
    check ((status = 'active') = (left_on is null)),
  constraint section_memberships_one_at_a_time
    exclude using gist (
      student_id with =,
      academic_year_id with =,
      daterange(joined_on, left_on, '[)') with &&
    ) where (deleted_at is null)
);

comment on table section_memberships is
  'MINORS'' PERSONAL DATA (association). The temporal roster: which student sat in which section, over which dates. A class roster is derived from this, so attendance denominators are always evaluated as of the session date rather than as of today.';
comment on column section_memberships.left_on is 'Exclusive end date. Null while the student is still in the section. A student who leaves mid-bimestre keeps every prior attendance and score row.';
comment on constraint section_memberships_one_at_a_time on section_memberships is
  'A student cannot sit in two sections on the same date within one academic year. This is the invariant that makes "the roster of class X on date D" a single unambiguous set.';

-- Screen 02/03: the roster query. Section first, then date-filtered.
create index section_memberships_section_idx
  on section_memberships (section_id, joined_on, left_on) where deleted_at is null;
-- Screen 06: "542 Alumnos" -- distinct students across a teacher's sections.
create index section_memberships_student_idx
  on section_memberships (student_id) where deleted_at is null;

select app.enable_tenant_rls('section_memberships');
select app.attach_updated_at('section_memberships');
select app.attach_soft_delete_guard('section_memberships');


-- ---------------------------------------------------------------------------
-- classes
-- ---------------------------------------------------------------------------
create table classes (
  id                uuid primary key default gen_random_uuid(),
  tenant_id         uuid not null references tenants (id),
  academic_year_id  uuid not null,
  course_id         uuid not null,
  section_id        uuid not null,
  name              text not null,
  code              text,
  default_room      text,
  status            text not null default 'active'
                      check (status in ('active', 'archived', 'cancelled')),
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now(),
  deleted_at        timestamptz,
  constraint classes_tenant_id_key unique (tenant_id, id),
  constraint classes_year_fk foreign key (tenant_id, academic_year_id)
    references academic_years (tenant_id, id),
  constraint classes_course_fk foreign key (tenant_id, course_id)
    references courses (tenant_id, id),
  constraint classes_section_fk foreign key (tenant_id, section_id)
    references sections (tenant_id, id)
);

comment on table classes is 'One course taught to one section: "Inglés 5to B". The unit the teacher actually works in — every screen except 06 is scoped to a single class.';
comment on column classes.name is 'Display name shown on screens 01, 02, 03 and 06. Stored because it is the string teachers search on, and because "Historia 5to C" and "Math 8B" follow no single derivation rule.';

create unique index classes_course_section_key
  on classes (tenant_id, course_id, section_id) where deleted_at is null;
-- Screen 01: "Buscar por clase" -- substring search as the teacher types.
create index classes_name_trgm_idx on classes using gin (name gin_trgm_ops);
create index classes_section_idx on classes (section_id) where deleted_at is null;

select app.enable_tenant_rls('classes');
select app.attach_updated_at('classes');
select app.attach_soft_delete_guard('classes');

-- ---------------------------------------------------------------------------
-- class_teachers
-- ---------------------------------------------------------------------------
-- Dated, because a teacher going on leave mid-year must not rewrite who taught
-- (and who graded) the sessions before the handover.
create table class_teachers (
  id          uuid primary key default gen_random_uuid(),
  tenant_id   uuid not null references tenants (id),
  class_id    uuid not null,
  teacher_id  uuid not null,
  role        text not null default 'titular'
                check (role in ('titular', 'auxiliar', 'practicante', 'reemplazo')),
  starts_on   date not null,
  ends_on     date,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  deleted_at  timestamptz,
  constraint class_teachers_class_fk foreign key (tenant_id, class_id)
    references classes (tenant_id, id),
  constraint class_teachers_teacher_fk foreign key (tenant_id, teacher_id)
    references teachers (tenant_id, id),
  constraint class_teachers_range_valid check (ends_on is null or ends_on >= starts_on),
  constraint class_teachers_one_titular
    exclude using gist (
      class_id with =,
      daterange(starts_on, ends_on, '[)') with &&
    ) where (role = 'titular' and deleted_at is null)
);

comment on table class_teachers is 'Who teaches a class, in what capacity, over which dates. A class has exactly one titular at a time and any number of auxiliares.';
comment on constraint class_teachers_one_titular on class_teachers is 'Two titulares on the same date would make "my classes" on screens 01 and 06 double-count.';

-- Screens 01 and 06: "my classes today" and "MIS CLASES · 20" both start here.
create index class_teachers_teacher_idx
  on class_teachers (teacher_id, starts_on, ends_on) where deleted_at is null;
create unique index class_teachers_key
  on class_teachers (class_id, teacher_id, starts_on) where deleted_at is null;

select app.enable_tenant_rls('class_teachers');
select app.attach_updated_at('class_teachers');
select app.attach_soft_delete_guard('class_teachers');

-- ---------------------------------------------------------------------------
-- class_schedules
-- ---------------------------------------------------------------------------
-- The recurring weekly pattern, one row per weekly slot. Screen 01 renders
-- these directly for classes later in the week ("Lunes 11:30 – 12:30" /
-- "Martes 3:00 – 4:00 PM" on one card = two rows). Screens 02 and 06 count
-- them for "4 sesiones/semana" and "2/sem".
create table class_schedules (
  id              uuid primary key default gen_random_uuid(),
  tenant_id       uuid not null references tenants (id),
  class_id        uuid not null,
  weekday         smallint not null check (weekday between 1 and 7),
  starts_at       time not null,
  ends_at         time not null,
  room            text,
  effective_from  date not null,
  effective_to    date,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  deleted_at      timestamptz,
  constraint class_schedules_tenant_id_key unique (tenant_id, id),
  constraint class_schedules_class_fk foreign key (tenant_id, class_id)
    references classes (tenant_id, id),
  constraint class_schedules_time_valid check (ends_at > starts_at),
  constraint class_schedules_range_valid check (effective_to is null or effective_to > effective_from),
  constraint class_schedules_no_overlap
    exclude using gist (
      class_id with =,
      weekday with =,
      timerange(starts_at, ends_at, '[)') with &&,
      daterange(effective_from, effective_to, '[)') with &&
    ) where (deleted_at is null)
);

comment on table class_schedules is 'The recurring weekly pattern for a class: one row per weekly slot. Distinct from class_sessions, which are the concrete dated instances. A timetable change closes the old row with effective_to and opens a new one, so past sessions still explain themselves.';
comment on column class_schedules.weekday is 'ISO-8601 weekday, 1 = Monday .. 7 = Sunday. Matches extract(isodow), so the generator can join without arithmetic.';
comment on column class_schedules.starts_at is 'Local wall-clock time in the tenant timezone. Deliberately not timestamptz: "10:00 on Mondays" must survive a DST-style offset change, and the concrete UTC instant is materialised onto class_sessions.';
comment on constraint class_schedules_no_overlap on class_schedules is 'A class cannot occupy two overlapping slots on the same weekday while both are in effect. Does not attempt to detect a teacher double-booked across two classes — see the notes on cross-class timetable conflicts.';

-- Screen 01 "ESTA SEMANA": the teacher's weekly pattern, by weekday.
create index class_schedules_class_idx
  on class_schedules (class_id, weekday) where deleted_at is null;
-- Session generator: which slots are in effect for a date range.
create index class_schedules_effective_idx
  on class_schedules (tenant_id, effective_from, effective_to) where deleted_at is null;

select app.enable_tenant_rls('class_schedules');
select app.attach_updated_at('class_schedules');
select app.attach_soft_delete_guard('class_schedules');


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
  room                        text,
  started_by_id               uuid,
  attendance_taken_at         timestamptz,
  attendance_taken_by_id      uuid,
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
  constraint class_sessions_window_valid check (scheduled_end_at > scheduled_start_at),
  constraint class_sessions_actual_valid
    check (actual_end_at is null or actual_start_at is null or actual_end_at >= actual_start_at),
  constraint class_sessions_started_consistent
    check ((status in ('in_progress', 'completed')) <= (actual_start_at is not null)),
  constraint class_sessions_attendance_consistent
    check ((attendance_taken_at is null) = (attendance_taken_by_id is null))
);

comment on table class_sessions is 'One dated instance of a class. Lifecycle scheduled -> in_progress -> completed, with cancelled and rescheduled as terminal alternatives. Screen 02''s "HOY · SIN INICIAR" card is a scheduled row for today; the "Iniciar clase" button moves it to in_progress and stamps actual_start_at.';
comment on column class_sessions.schedule_id is 'The recurring slot this instance came from. Null for a one-off session added by hand, so an ad-hoc make-up class is representable without inventing a weekly rule.';
comment on column class_sessions.topic is 'What the session covers, e.g. "Present perfect tense". Rendered on screen 02 both for the next session and for past ones.';
comment on column class_sessions.attendance_taken_at is 'Null means attendance was never marked, which is exactly what screen 02''s "Asistencia sin marcar" and screen 05''s reminder key off. Distinct from a session where everyone was absent.';
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


-- ---------------------------------------------------------------------------
-- grade_scales
-- ---------------------------------------------------------------------------
create table grade_scales (
  id             uuid primary key default gen_random_uuid(),
  tenant_id      uuid not null references tenants (id),
  code           text not null,
  name           text not null,
  kind           text not null check (kind in ('ordinal', 'numeric', 'percentage')),
  min_value      numeric(8, 4) not null,
  max_value      numeric(8, 4) not null,
  passing_value  numeric(8, 4),
  decimals       smallint not null default 0 check (decimals between 0 and 4),
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now(),
  deleted_at     timestamptz,
  constraint grade_scales_tenant_id_key unique (tenant_id, id),
  constraint grade_scales_range_valid check (max_value > min_value),
  constraint grade_scales_passing_in_range
    check (passing_value is null or passing_value between min_value and max_value)
);

comment on table grade_scales is 'How a school expresses a grade. ordinal = MINEDU AD/A/B/C, numeric = 0-20 vigesimal, percentage = 0-100. Every scale maps onto the same 0-1 normalised axis, which is what lets one model train across tenants.';
comment on column grade_scales.kind is 'Drives display only. ordinal renders the level code, numeric renders the value, percentage renders a percent. All three normalise identically.';
comment on column grade_scales.min_value is 'Lowest value the scale can express: 0 for vigesimal, and for an ordinal scale the numeric floor of its lowest band.';
comment on column grade_scales.decimals is 'Display precision. Vigesimal is normally reported as a whole number even though raw scores are decimal.';
comment on column grade_scales.passing_value is
  'Cutoff for scales that genuinely have one. MUST be null for any scale used to report CNEB niveles de logro: "aprobado" is not a property of a level there (B suffices in 1.°/3.°/4.° and does not in 2.°/5.°), so no single value can express it. internal/promotion decides promotion from the cuadro of 5.1.3; nothing in the normative path may read this column.';

create unique index grade_scales_tenant_code_key
  on grade_scales (tenant_id, code) where deleted_at is null;

select app.enable_tenant_rls('grade_scales');
select app.attach_updated_at('grade_scales');
select app.attach_soft_delete_guard('grade_scales');

-- ---------------------------------------------------------------------------
-- grade_scale_levels
-- ---------------------------------------------------------------------------
create table grade_scale_levels (
  id              uuid primary key default gen_random_uuid(),
  tenant_id       uuid not null references tenants (id),
  scale_id        uuid not null,
  code            text not null,
  label           text not null,
  short_label     text,
  ordinal         smallint not null,
  min_normalized  numeric(6, 5) not null check (min_normalized >= 0 and min_normalized <= 1),
  max_normalized  numeric(6, 5) not null check (max_normalized >= 0 and max_normalized <= 1),
  is_passing      boolean not null default false,
  color_key       text,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  deleted_at      timestamptz,
  constraint grade_scale_levels_tenant_id_key unique (tenant_id, id),
  constraint grade_scale_levels_scale_fk foreign key (tenant_id, scale_id)
    references grade_scales (tenant_id, id),
  constraint grade_scale_levels_band_valid check (max_normalized > min_normalized),
  constraint grade_scale_levels_no_gap_overlap
    exclude using gist (
      scale_id with =,
      numrange(min_normalized, max_normalized, '[)') with &&
    ) where (deleted_at is null)
);

comment on table grade_scale_levels is 'The bands of a scale. For AD/A/B/C these are the reported grades; for a numeric scale they are the colour bands behind the number. Screen 02''s "Distribución de logros" groups by this table, screen 03''s "Logro esperado / A" reads label and code from one row.';
comment on column grade_scale_levels.code is 'What is printed in the chip: "AD", "A", "B", "C".';
comment on column grade_scale_levels.label is 'Full wording: "Logro destacado", "Logro esperado", "En proceso", "En inicio". Screen 03 shows the label and the code together.';
comment on column grade_scale_levels.min_normalized is 'Inclusive lower bound on the 0-1 axis. Bands are half-open [min, max), so a value falls in exactly one band.';
comment on column grade_scale_levels.max_normalized is 'Exclusive upper bound, except for the top band which the lookup treats as closed so a perfect score has a level.';
comment on column grade_scale_levels.is_passing is
  'Advisory only — a display hint for scales that have a cutoff. Never read by promotion logic, for the reason given on grade_scales.passing_value.';
comment on constraint grade_scale_levels_no_gap_overlap on grade_scale_levels is 'Two bands of one scale cannot overlap. Gaps are not prevented here — a gap is detectable but not always wrong during authoring, so it is checked when the scale is first used.';

create unique index grade_scale_levels_scale_code_key
  on grade_scale_levels (tenant_id, scale_id, code) where deleted_at is null;
-- Level lookup: given a normalised value, find its band. Runs once per computed grade.
create index grade_scale_levels_lookup_idx
  on grade_scale_levels (scale_id, min_normalized, max_normalized) where deleted_at is null;

select app.enable_tenant_rls('grade_scale_levels');
select app.attach_updated_at('grade_scale_levels');
select app.attach_soft_delete_guard('grade_scale_levels');

-- ---------------------------------------------------------------------------
-- grading_schemes
-- ---------------------------------------------------------------------------
create table grading_schemes (
  id          uuid primary key default gen_random_uuid(),
  tenant_id   uuid not null references tenants (id),
  scale_id    uuid not null,
  code        text not null,
  name        text not null,
  description text,
  is_active   boolean not null default true,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  deleted_at  timestamptz,
  constraint grading_schemes_tenant_id_key unique (tenant_id, id),
  constraint grading_schemes_scale_fk foreign key (tenant_id, scale_id)
    references grade_scales (tenant_id, id)
);

comment on table grading_schemes is 'A named grading policy, e.g. "Evaluación MINEDU secundaria" or "Bachillerato 0-20". Stable identity; the rules live in its versions.';

create unique index grading_schemes_tenant_code_key
  on grading_schemes (tenant_id, code) where deleted_at is null;

select app.enable_tenant_rls('grading_schemes');
select app.attach_updated_at('grading_schemes');
select app.attach_soft_delete_guard('grading_schemes');

-- ---------------------------------------------------------------------------
-- grading_components
-- ---------------------------------------------------------------------------
-- Deliberately hung off the scheme, not off the version. An assessment created
-- in April points at "Examen final"; when the school re-versions its weights in
-- June, that assessment must still resolve to the same component under the new
-- version. If components belonged to versions, every re-version would orphan
-- every existing assessment.
create table grading_components (
  id          uuid primary key default gen_random_uuid(),
  tenant_id   uuid not null references tenants (id),
  scheme_id   uuid not null,
  code        text not null,
  name        text not null,
  description text,
  sort_order  smallint not null default 0,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  deleted_at  timestamptz,
  constraint grading_components_tenant_id_key unique (tenant_id, id),
  constraint grading_components_scheme_component_key unique (tenant_id, scheme_id, id),
  constraint grading_components_scheme_fk foreign key (tenant_id, scheme_id)
    references grading_schemes (tenant_id, id)
);

comment on table grading_components is 'A weighted bucket within a scheme: Participación, Quiz, Examen final. Screen 04 lists one row per component with its weight and the student''s result in it.';
comment on column grading_components.code is 'Stable machine key. The name may be re-worded without breaking assessments or historical computed grades.';
comment on constraint grading_components_scheme_component_key on grading_components is 'Lets assessments carry a composite (tenant_id, scheme_id, component_id) foreign key, which makes it structurally impossible to file an assessment under a component from a different school''s scheme.';

create unique index grading_components_scheme_code_key
  on grading_components (tenant_id, scheme_id, code) where deleted_at is null;

select app.enable_tenant_rls('grading_components');
select app.attach_updated_at('grading_components');
select app.attach_soft_delete_guard('grading_components');

-- ---------------------------------------------------------------------------
-- grading_scheme_versions
-- ---------------------------------------------------------------------------
create table grading_scheme_versions (
  id                            uuid primary key default gen_random_uuid(),
  tenant_id                     uuid not null references tenants (id),
  scheme_id                     uuid not null,
  version                       integer not null check (version >= 1),
  effective_from                date not null,
  effective_to                  date,
  rounding_mode                 text not null default 'half_up'
                                  check (rounding_mode in ('half_up', 'half_even', 'floor', 'ceil', 'none')),
  rounding_decimals             smallint not null default 0 check (rounding_decimals between 0 and 4),
  absent_counts_as              text not null default 'zero'
                                  check (absent_counts_as in ('zero', 'excused')),
  late_penalty_pct_per_day      numeric(5, 4) not null default 0
                                  check (late_penalty_pct_per_day >= 0 and late_penalty_pct_per_day <= 1),
  retake_policy                 text not null default 'best'
                                  check (retake_policy in ('none', 'best', 'last', 'capped')),
  retake_cap_normalized         numeric(6, 5)
                                  check (retake_cap_normalized is null or (retake_cap_normalized >= 0 and retake_cap_normalized <= 1)),
  min_evaluated_weight_for_grade numeric(6, 5) not null default 0
                                  check (min_evaluated_weight_for_grade >= 0 and min_evaluated_weight_for_grade <= 1),
  notes                         text,
  published_at                  timestamptz,
  published_by_id               uuid,
  created_at                    timestamptz not null default now(),
  updated_at                    timestamptz not null default now(),
  deleted_at                    timestamptz,
  constraint grading_scheme_versions_tenant_id_key unique (tenant_id, id),
  constraint grading_scheme_versions_scheme_fk foreign key (tenant_id, scheme_id)
    references grading_schemes (tenant_id, id),
  constraint grading_scheme_versions_published_by_fk foreign key (tenant_id, published_by_id)
    references teachers (tenant_id, id),
  constraint grading_scheme_versions_range_valid
    check (effective_to is null or effective_to > effective_from),
  constraint grading_scheme_versions_capped_needs_cap
    check (retake_policy <> 'capped' or retake_cap_normalized is not null),
  constraint grading_scheme_versions_no_overlap
    exclude using gist (
      scheme_id with =,
      daterange(effective_from, effective_to, '[)') with &&
    ) where (published_at is not null and deleted_at is null)
);

comment on table grading_scheme_versions is 'An immutable snapshot of a scheme''s rules over a date range. Changing weights inserts a new version and closes the old one with effective_to; it never edits a published row. Every computed grade records the version that produced it, so a report card issued in April cannot silently change in June.';
comment on column grading_scheme_versions.absent_counts_as is 'What an unexcused absence on an assessment is worth. This is policy, not data: the score row records only that the student was absent, and this decides whether that becomes a zero or drops out of the denominator.';
comment on column grading_scheme_versions.late_penalty_pct_per_day is 'Fraction deducted per day late. Applied at computation time from scores.late_days — the raw score is never modified, so correcting this policy re-grades correctly.';
comment on column grading_scheme_versions.retake_policy is 'How multiple attempts on one assessment combine: best, last, or best-capped. Peruvian recuperación is normally capped. Never resolved by discarding the earlier attempt.';
comment on column grading_scheme_versions.min_evaluated_weight_for_grade is 'Minimum share of the term''s weight that must be evaluated before a partial grade is shown at all. Guards against screen 04 reporting "AD" off a single 5%-weight quiz.';
comment on column grading_scheme_versions.published_at is 'Null while the version is a draft. Publishing freezes it: after this, only effective_to may change.';
comment on constraint grading_scheme_versions_no_overlap on grading_scheme_versions is 'Two published versions of one scheme cannot both be in effect on a date, so "the policy applying to this assessment" is unambiguous. Drafts are excluded so a replacement can be authored while the current one is live.';

create unique index grading_scheme_versions_scheme_version_key
  on grading_scheme_versions (scheme_id, version) where deleted_at is null;

select app.enable_tenant_rls('grading_scheme_versions');
select app.attach_updated_at('grading_scheme_versions');
select app.attach_soft_delete_guard('grading_scheme_versions');

-- ---------------------------------------------------------------------------
-- grading_scheme_component_weights
-- ---------------------------------------------------------------------------
create table grading_scheme_component_weights (
  id                 uuid primary key default gen_random_uuid(),
  tenant_id          uuid not null references tenants (id),
  scheme_version_id  uuid not null,
  component_id       uuid not null,
  weight             numeric(9, 6) not null check (weight > 0 and weight <= 1),
  drop_lowest_n      smallint not null default 0 check (drop_lowest_n >= 0),
  aggregation        text not null default 'weighted_mean'
                       check (aggregation in ('mean', 'weighted_mean', 'best', 'last', 'sum')),
  is_required        boolean not null default true,
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now(),
  deleted_at         timestamptz,
  constraint gscw_version_fk foreign key (tenant_id, scheme_version_id)
    references grading_scheme_versions (tenant_id, id),
  constraint gscw_component_fk foreign key (tenant_id, component_id)
    references grading_components (tenant_id, id)
);

comment on table grading_scheme_component_weights is 'The weights themselves, one row per component per version. Screen 04 renders "Peso 20%" straight from weight. Weights within a version sum to exactly 1, enforced by a deferred constraint trigger.';
comment on column grading_scheme_component_weights.drop_lowest_n is 'Discard the N weakest scores in this component before aggregating. Which scores were dropped is recorded per student on computed_grade_components, so the teacher can explain the number.';
comment on column grading_scheme_component_weights.aggregation is 'How several assessments inside one component combine. weighted_mean uses assessments.weight_within_component; sum is for point-accumulation schemes where the component total is the denominator.';
comment on column grading_scheme_component_weights.is_required is 'If false, the component drops out of the denominator when it has no scores at all, instead of counting as unevaluated weight.';

create unique index gscw_version_component_key
  on grading_scheme_component_weights (scheme_version_id, component_id) where deleted_at is null;
create index gscw_component_idx on grading_scheme_component_weights (component_id);

-- Weights must sum to 1 per version. A row-level CHECK cannot see sibling rows,
-- so this is a deferred constraint trigger: it fires at COMMIT, which lets a
-- whole weight table be inserted or rebalanced in one transaction.
-- +goose StatementBegin
create or replace function app.check_component_weights_sum() returns trigger
  language plpgsql
  as $fn$
  declare
    v_version uuid;
    v_sum     numeric;
  begin
    -- NEW is unassigned on DELETE; referencing it there would raise.
    if tg_op = 'DELETE' then
      v_version := old.scheme_version_id;
    else
      v_version := new.scheme_version_id;
    end if;

    -- The version may have been removed in the same transaction; nothing to check.
    if not exists (select 1 from grading_scheme_versions v
                    where v.id = v_version and v.deleted_at is null) then
      return null;
    end if;

    select coalesce(sum(weight), 0) into v_sum
      from grading_scheme_component_weights
     where scheme_version_id = v_version and deleted_at is null;

    if v_sum <> 1 then
      raise exception 'component weights for grading scheme version % sum to %, must sum to exactly 1', v_version, v_sum
        using errcode = 'check_violation',
              hint = 'For thirds use 0.333333 / 0.333333 / 0.333334 -- weights are exact numerics, not floats.';
    end if;
    return null;
  end;
  $fn$;
-- +goose StatementEnd

create constraint trigger check_weights_sum
  after insert or update or delete on grading_scheme_component_weights
  deferrable initially deferred
  for each row execute function app.check_component_weights_sum();

-- A version with no weight rows at all would never fire the trigger above, so
-- publishing is also a checkpoint.
-- +goose StatementBegin
create or replace function app.check_version_publishable() returns trigger
  language plpgsql
  as $fn$
  declare
    v_sum numeric;
    v_cnt integer;
  begin
    if new.published_at is null then
      return new;
    end if;

    select count(*), coalesce(sum(weight), 0) into v_cnt, v_sum
      from grading_scheme_component_weights
     where scheme_version_id = new.id and deleted_at is null;

    if v_cnt = 0 then
      raise exception 'grading scheme version % has no components and cannot be published', new.id
        using errcode = 'check_violation';
    end if;
    if v_sum <> 1 then
      raise exception 'grading scheme version % has weights summing to %, must be exactly 1', new.id, v_sum
        using errcode = 'check_violation';
    end if;
    return new;
  end;
  $fn$;
-- +goose StatementEnd

create trigger check_publishable before insert or update of published_at on grading_scheme_versions
  for each row execute function app.check_version_publishable();

-- Published versions are immutable except for being closed off with effective_to.
-- +goose StatementBegin
create or replace function app.forbid_published_version_mutation() returns trigger
  language plpgsql
  as $fn$
  begin
    if old.published_at is null then
      return new;
    end if;
    if new.scheme_id            is distinct from old.scheme_id
       or new.version           is distinct from old.version
       or new.effective_from    is distinct from old.effective_from
       or new.rounding_mode     is distinct from old.rounding_mode
       or new.rounding_decimals is distinct from old.rounding_decimals
       or new.absent_counts_as  is distinct from old.absent_counts_as
       or new.late_penalty_pct_per_day is distinct from old.late_penalty_pct_per_day
       or new.retake_policy            is distinct from old.retake_policy
       or new.retake_cap_normalized    is distinct from old.retake_cap_normalized
       or new.min_evaluated_weight_for_grade is distinct from old.min_evaluated_weight_for_grade
       or new.published_at             is distinct from old.published_at then
      raise exception 'grading scheme version % is published and immutable; insert a new version instead', old.id
        using errcode = 'restrict_violation',
              hint = 'Only effective_to may change on a published version, to close it off.';
    end if;
    return new;
  end;
  $fn$;
-- +goose StatementEnd

create trigger forbid_published_mutation before update on grading_scheme_versions
  for each row execute function app.forbid_published_version_mutation();

-- +goose StatementBegin
create or replace function app.forbid_published_weight_mutation() returns trigger
  language plpgsql
  as $fn$
  declare
    v_version   uuid;
    v_published timestamptz;
  begin
    -- NEW is unset on DELETE, so the row being examined depends on the operation.
    if tg_op = 'DELETE' then
      -- A sanctioned erasure (tenant offboarding, seed rollback) may remove the
      -- rows outright; ordinary application code cannot.
      if coalesce(nullif(current_setting('app.allow_hard_delete', true), ''), 'off') = 'on' then
        return old;
      end if;
      v_version := old.scheme_version_id;
    else
      v_version := new.scheme_version_id;
    end if;

    select published_at into v_published
      from grading_scheme_versions where id = v_version;

    if v_published is not null then
      raise exception 'weights of published grading scheme version % cannot be changed; insert a new version', v_version
        using errcode = 'restrict_violation';
    end if;

    if tg_op = 'DELETE' then
      return old;
    end if;
    return new;
  end;
  $fn$;
-- +goose StatementEnd

create trigger forbid_published_weight_mutation
  before update or delete on grading_scheme_component_weights
  for each row execute function app.forbid_published_weight_mutation();

select app.enable_tenant_rls('grading_scheme_component_weights');
select app.attach_updated_at('grading_scheme_component_weights');

-- ---------------------------------------------------------------------------
-- Scheme resolution: tenant default -> course override -> class/term override
-- ---------------------------------------------------------------------------
alter table tenants add column default_grading_scheme_id uuid;
alter table tenants add constraint tenants_default_scheme_fk
  foreign key (id, default_grading_scheme_id) references grading_schemes (tenant_id, id);
comment on column tenants.default_grading_scheme_id is 'School-wide fallback grading scheme. Overridden per course, then per class and term.';

alter table courses add column grading_scheme_id uuid;
alter table courses add constraint courses_grading_scheme_fk
  foreign key (tenant_id, grading_scheme_id) references grading_schemes (tenant_id, id);
comment on column courses.grading_scheme_id is 'Optional per-course override, for a school where Matemática weights differently from Inglés. Null falls back to the tenant default.';

create table class_grading_policies (
  id                 uuid primary key default gen_random_uuid(),
  tenant_id          uuid not null references tenants (id),
  class_id           uuid not null,
  term_id            uuid not null,
  scheme_id          uuid not null,
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now(),
  deleted_at         timestamptz,
  constraint class_grading_policies_class_fk foreign key (tenant_id, class_id)
    references classes (tenant_id, id),
  constraint class_grading_policies_term_fk foreign key (tenant_id, term_id)
    references terms (tenant_id, id),
  constraint class_grading_policies_scheme_fk foreign key (tenant_id, scheme_id)
    references grading_schemes (tenant_id, id)
);

comment on table class_grading_policies is 'Narrowest override: this class, this term, this scheme. Scoped by term so a class can change policy between bimestres without rewriting the previous bimestre''s grades.';

create unique index class_grading_policies_key
  on class_grading_policies (class_id, term_id) where deleted_at is null;

select app.enable_tenant_rls('class_grading_policies');
select app.attach_updated_at('class_grading_policies');
select app.attach_soft_delete_guard('class_grading_policies');

-- The resolution order in one place, so no Go code re-implements it.
create view class_effective_grading_schemes as
select
  c.tenant_id,
  c.id                                            as class_id,
  t.id                                            as term_id,
  coalesce(p.scheme_id, co.grading_scheme_id, tn.default_grading_scheme_id) as scheme_id,
  case
    when p.scheme_id is not null              then 'class_term'
    when co.grading_scheme_id is not null     then 'course'
    when tn.default_grading_scheme_id is not null then 'tenant'
  end                                             as resolved_from,
  v.id                                            as scheme_version_id
from classes c
join tenants tn on tn.id = c.tenant_id
join courses co on co.id = c.course_id and co.tenant_id = c.tenant_id
join terms   t  on t.tenant_id = c.tenant_id and t.academic_year_id = c.academic_year_id
left join class_grading_policies p
  on p.class_id = c.id and p.term_id = t.id and p.deleted_at is null
left join lateral (
  select gv.id
    from grading_scheme_versions gv
   where gv.scheme_id = coalesce(p.scheme_id, co.grading_scheme_id, tn.default_grading_scheme_id)
     and gv.published_at is not null
     and gv.deleted_at is null
     and gv.effective_from <= t.starts_on
     and (gv.effective_to is null or gv.effective_to > t.starts_on)
   order by gv.effective_from desc
   limit 1
) v on true
where c.deleted_at is null;

comment on view class_effective_grading_schemes is 'Resolves which grading scheme, and which published version of it, governs a class in a term. Version is chosen by the term start date, so re-versioning mid-year does not retroactively change a term already under way.';


-- ---------------------------------------------------------------------------
-- assessments
-- ---------------------------------------------------------------------------
create table assessments (
  id                        uuid primary key default gen_random_uuid(),
  tenant_id                 uuid not null references tenants (id),
  class_id                  uuid not null,
  term_id                   uuid not null,
  scheme_id                 uuid not null,
  component_id              uuid not null,
  unit_id                   uuid,
  session_id                uuid,
  title                     text not null,
  description               text,
  student_id                uuid,
  kind                      text not null default 'otro'
                              check (kind in ('examen', 'practica', 'tarea', 'proyecto',
                                              'exposicion', 'participacion', 'otro')),
  value_scale               text not null default 'numeric'
                              check (value_scale in ('numeric', 'ordinal', 'none')),
  max_score                 numeric(8, 4),
  counts_toward_internal    boolean not null default true,
  weight_within_component   numeric(9, 6) not null default 1 check (weight_within_component > 0),
  due_at                    timestamptz,
  status                    text not null default 'draft'
                              check (status in ('draft', 'published', 'closed', 'cancelled')),
  published_at              timestamptz,
  closed_at                 timestamptz,
  late_penalty_pct_per_day  numeric(5, 4) check (late_penalty_pct_per_day between 0 and 1),
  created_by_id             uuid,
  created_at                timestamptz not null default now(),
  updated_at                timestamptz not null default now(),
  deleted_at                timestamptz,
  constraint assessments_tenant_id_key unique (tenant_id, id),
  constraint assessments_class_fk foreign key (tenant_id, class_id)
    references classes (tenant_id, id),
  constraint assessments_term_fk foreign key (tenant_id, term_id)
    references terms (tenant_id, id),
  constraint assessments_component_fk foreign key (tenant_id, scheme_id, component_id)
    references grading_components (tenant_id, scheme_id, id),
  constraint assessments_unit_fk foreign key (tenant_id, unit_id)
    references units (tenant_id, id),
  constraint assessments_session_fk foreign key (tenant_id, session_id)
    references class_sessions (tenant_id, id),
  constraint assessments_created_by_fk foreign key (tenant_id, created_by_id)
    references teachers (tenant_id, id),
  constraint assessments_student_fk foreign key (tenant_id, student_id)
    references students (tenant_id, id),
  constraint assessments_published_consistent
    check ((status in ('published', 'closed')) <= (published_at is not null)),
  constraint assessments_closed_consistent
    check ((status = 'closed') = (closed_at is not null)),
  -- max_score stops being universal once a piece of evidencia carries its own
  -- scale. The check pins it to the one scale that has a denominator, in both
  -- directions: a numeric evidence without a max is unmarkable, and a max on a
  -- letter-valued one is a number nobody will ever use that later readers
  -- would try to interpret.
  constraint assessments_max_score_positive
    check (max_score is null or max_score > 0),
  constraint assessments_max_score_matches_scale
    check ((value_scale = 'numeric') = (max_score is not null))
);

comment on table assessments is 'A graded item for one class: "Quiz 1", "Examen final", "Participación". Screen 04 lists these under EVALUACIONES with the component weight beside each. "Añadir evaluación" inserts here.';
comment on column assessments.scheme_id is 'Denormalised from the component so the composite FK can prove the component belongs to the intended scheme. Set from the class''s resolved grading policy at creation.';
comment on column assessments.student_id is 'Null means the assessment applies to the whole class, which is the original and still the common case. Set, it is evidencia for that one student only: a recovery task, a re-done project, an oral defence replacing a missed group presentation. Every query that fans assessments out over the roster must filter (student_id is null or student_id = the student), or one student''s personal evidence counts as missing for everyone else.';
comment on column assessments.value_scale is
  'How this piece of evidencia is valued. numeric: a mark on the school''s own vigesimal scale, with max_score as the denominator and the value in scores.raw_value. ordinal: a letter on the MINEDU AD/A/B/C scale, with the value in scores.scale_level_id and no denominator. none: registered and read but never valued, so it has no scores rows at all. A letter here is NOT a nivel de logro: the level of a competencia is asserted in competency_term_levels by a teacher who has read the whole period, and nothing may derive it from these values.';
comment on column assessments.max_score is
  'The denominator, present only when value_scale is numeric. Null for a literal or unvalued piece of evidencia, enforced by assessments_max_score_matches_scale.';
comment on column assessments.counts_toward_internal is
  'Whether this evidence feeds the school''s internal weighted average. It always feeds the official judgement: a criterio level recorded against it counts regardless, because the norm knows nothing about this flag. False exists for the recovery task given to one student (assessments.student_id set). That task is legitimate evidencia of the competencia, but letting it lift only that student''s internal average hands them an opportunity the rest of the class never had. Read by worker/handlers/recompute.go, which is the only consumer.';
comment on column assessments.weight_within_component is 'Relative weight against other assessments in the same component, used when the component aggregates by weighted_mean. Not a share of the final grade — that is the component''s weight.';
comment on column assessments.due_at is 'Deadline. Drives scores.late_days, and defines which assessments count in the "expected grades so far" denominator behind screen 02''s "Notas reg." tile.';
comment on column assessments.status is 'draft is invisible to grade computation. An assessment must be published before it contributes unevaluated weight to screen 04''s "falta 40%".';
comment on column assessments.late_penalty_pct_per_day is 'Per-assessment override of the scheme version''s late policy. Null inherits.';

-- Screen 04: this student's assessments for this class and term, in component order.
-- Deliberately no index for counts_toward_internal: this index stays
-- non-partial because the evidence list, the dashboard counts and the recompute
-- all read the same (class_id, term_id, status) rows, and only the last of the
-- three cares about the flag. Narrowing the shared index to the one caller
-- would push the other two off it to serve a filter that discards at most a
-- handful of rows per class.
create index assessments_class_term_idx
  on assessments (class_id, term_id, status) where deleted_at is null;
-- Reading one student's own evidence for a class+term is the hot path (screen 04).
create index assessments_student_idx
  on assessments (class_id, term_id, student_id)
  where student_id is not null and deleted_at is null;
-- Screen 02 "Notas reg." and "Pendientes": published assessments already due.
create index assessments_due_idx
  on assessments (tenant_id, due_at)
  where status = 'published' and deleted_at is null;
create index assessments_component_idx on assessments (component_id) where deleted_at is null;
create index assessments_session_idx on assessments (session_id) where session_id is not null and deleted_at is null;

select app.enable_tenant_rls('assessments');
select app.attach_updated_at('assessments');
select app.attach_soft_delete_guard('assessments');

create table assessment_competencies (
  id             uuid primary key default gen_random_uuid(),
  tenant_id      uuid not null references tenants (id),
  assessment_id  uuid not null,
  competency_id  uuid not null,
  weight         numeric(9, 6) not null default 1 check (weight > 0),
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now(),
  deleted_at     timestamptz,
  constraint assessment_competencies_assessment_fk foreign key (tenant_id, assessment_id)
    references assessments (tenant_id, id),
  constraint assessment_competencies_competency_fk foreign key (tenant_id, competency_id)
    references competencies (tenant_id, id)
);

comment on table assessment_competencies is 'Which competencies an assessment evidences. The path from a raw score to competency-level reporting, which MINEDU requires even though the six screens do not show it yet.';

create unique index assessment_competencies_key
  on assessment_competencies (assessment_id, competency_id) where deleted_at is null;
create index assessment_competencies_competency_idx on assessment_competencies (competency_id);

select app.enable_tenant_rls('assessment_competencies');
select app.attach_updated_at('assessment_competencies');
select app.attach_soft_delete_guard('assessment_competencies');

-- ---------------------------------------------------------------------------
-- assessment_criteria
-- ---------------------------------------------------------------------------
-- Sibling of assessment_competencies, at criterio granularity. Both tables are
-- kept: assessments not yet broken into criterios keep working through
-- assessment_competencies; a competency's coverage can also be derived by
-- joining assessment_criteria -> evaluation_criteria.competency_id once
-- criterios are in use. A criterio is a tag on a piece of evidencia and is
-- never itself graded -- there is no per-criterio score anywhere in this
-- schema, by design.
create table assessment_criteria (
  id             uuid primary key default gen_random_uuid(),
  tenant_id      uuid not null references tenants (id),
  assessment_id  uuid not null,
  criterion_id   uuid not null,
  weight         numeric(9, 6) not null default 1 check (weight > 0),
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now(),
  deleted_at     timestamptz,
  constraint assessment_criteria_assessment_fk foreign key (tenant_id, assessment_id)
    references assessments (tenant_id, id),
  constraint assessment_criteria_criterion_fk foreign key (tenant_id, criterion_id)
    references evaluation_criteria (tenant_id, id)
);

comment on table assessment_criteria is 'Which criterios de evaluación a piece of evidencia speaks to: the teacher''s note of what to look at in this work. It is a tag, not a score. No level is ever recorded per criterio: the one recorded judgement is the nivel de logro of the competencia, in competency_term_levels, asserted by the teacher after reading the period''s evidence. The weight column is vestigial and read by nothing.';

create unique index assessment_criteria_key
  on assessment_criteria (assessment_id, criterion_id) where deleted_at is null;
create index assessment_criteria_criterion_idx on assessment_criteria (criterion_id);

select app.enable_tenant_rls('assessment_criteria');
select app.attach_updated_at('assessment_criteria');
select app.attach_soft_delete_guard('assessment_criteria');

-- ---------------------------------------------------------------------------
-- retake_authorizations
-- ---------------------------------------------------------------------------
create table retake_authorizations (
  id                     uuid primary key default gen_random_uuid(),
  tenant_id              uuid not null references tenants (id),
  assessment_id          uuid not null,
  student_id             uuid not null,
  kind                   text not null
                           check (kind in ('recuperacion', 'subsanacion', 'makeup', 'ampliacion')),
  reason                 text,
  window_starts_at       timestamptz,
  window_ends_at         timestamptz,
  max_normalized_cap     numeric(6, 5) check (max_normalized_cap between 0 and 1),
  status                 text not null default 'open'
                           check (status in ('open', 'used', 'expired', 'revoked')),
  authorized_by_id       uuid not null,
  authorized_at          timestamptz not null default now(),
  created_at             timestamptz not null default now(),
  updated_at             timestamptz not null default now(),
  deleted_at             timestamptz,
  constraint retake_authorizations_tenant_id_key unique (tenant_id, id),
  constraint retake_authorizations_assessment_fk foreign key (tenant_id, assessment_id)
    references assessments (tenant_id, id),
  constraint retake_authorizations_student_fk foreign key (tenant_id, student_id)
    references students (tenant_id, id),
  constraint retake_authorizations_authorized_by_fk foreign key (tenant_id, authorized_by_id)
    references teachers (tenant_id, id),
  constraint retake_authorizations_window_valid
    check (window_ends_at is null or window_starts_at is null or window_ends_at > window_starts_at)
);

comment on table retake_authorizations is 'MINORS'' PERSONAL DATA (academic). Who authorised a recuperación or subsanación, for which student, within which window, capped at what. Peruvian retake mechanisms are legally required, and the authorisation is as auditable as the resulting score.';
comment on column retake_authorizations.kind is 'Kept in Spanish deliberately. recuperación (re-sit within the term) and subsanación (clearing a failed course from a previous year) are distinct legal instruments, not two words for a retake.';
comment on column retake_authorizations.max_normalized_cap is 'Ceiling on the retake result, overriding the scheme version''s default cap. Commonly the passing threshold and no higher.';

create index retake_authorizations_student_idx
  on retake_authorizations (student_id, assessment_id) where deleted_at is null;

select app.enable_tenant_rls('retake_authorizations');
select app.attach_updated_at('retake_authorizations');
select app.attach_soft_delete_guard('retake_authorizations');

-- ---------------------------------------------------------------------------
-- scores
-- ---------------------------------------------------------------------------
create table scores (
  id                        uuid primary key default gen_random_uuid(),
  tenant_id                 uuid not null references tenants (id),
  assessment_id             uuid not null,
  student_id                uuid not null,
  class_id                  uuid not null,
  term_id                   uuid not null,
  attempt_number            smallint not null default 1 check (attempt_number >= 1),
  attempt_kind              text not null default 'original'
                              check (attempt_kind in ('original', 'recuperacion', 'subsanacion', 'makeup')),
  retake_authorization_id   uuid,
  status                    text not null default 'graded'
                              check (status in ('graded', 'excused', 'absent', 'not_submitted')),
  raw_value                 numeric(8, 4),
  -- The literal value of one piece of work for one student. It points at the
  -- same grade_scale_levels rows competency_term_levels uses, because AD/A/B/C
  -- is one vocabulary; what differs is the standing of the row, not the letters.
  scale_level_id            uuid,
  max_value                 numeric(8, 4),
  late_days                 smallint not null default 0 check (late_days >= 0),
  feedback                  text,
  source                    text not null default 'manual'
                              check (source in ('manual', 'bulk', 'import', 'voice', 'auto')),
  recorded_by_id            uuid not null,
  recorded_at               timestamptz not null default now(),
  supersedes_id             uuid,
  superseded_at             timestamptz,
  created_at                timestamptz not null default now(),
  updated_at                timestamptz not null default now(),
  deleted_at                timestamptz,
  constraint scores_tenant_id_key unique (tenant_id, id),
  constraint scores_assessment_fk foreign key (tenant_id, assessment_id)
    references assessments (tenant_id, id),
  constraint scores_student_fk foreign key (tenant_id, student_id)
    references students (tenant_id, id),
  constraint scores_class_fk foreign key (tenant_id, class_id)
    references classes (tenant_id, id),
  constraint scores_term_fk foreign key (tenant_id, term_id)
    references terms (tenant_id, id),
  constraint scores_recorded_by_fk foreign key (tenant_id, recorded_by_id)
    references teachers (tenant_id, id),
  constraint scores_retake_fk foreign key (tenant_id, retake_authorization_id)
    references retake_authorizations (tenant_id, id),
  constraint scores_supersedes_fk foreign key (tenant_id, supersedes_id)
    references scores (tenant_id, id),
  constraint scores_scale_level_fk foreign key (tenant_id, scale_level_id)
    references grade_scale_levels (tenant_id, id),
  constraint scores_max_value_positive
    check (max_value is null or max_value > 0),
  -- A graded score carries a number or a letter, so both the null-value and the
  -- range check have to admit a row that has one and not the other.
  constraint scores_value_matches_status
    check ((status = 'graded') = (raw_value is not null or scale_level_id is not null)),
  constraint scores_value_in_range
    check (raw_value is null or (max_value is not null and raw_value >= 0 and raw_value <= max_value)),
  -- A row is one kind of value or the other, never both: two values for one
  -- piece of work would leave every reader to decide which one counts.
  constraint scores_one_value_kind
    check (raw_value is null or scale_level_id is null),
  constraint scores_attempt_kind_consistent
    check ((attempt_number = 1) = (attempt_kind = 'original'))
);

comment on table scores is
  'MINORS'' PERSONAL DATA (academic). Append-only. Holds the raw value and the assessment maximum and nothing derived — no percentage, no weighted contribution, no late penalty already deducted. Correcting a score inserts a new row that supersedes the old one; a retake inserts a new attempt alongside it. Nothing here is ever updated in place or hard-deleted.';

comment on column scores.attempt_number is 'Attempt 1 is the original sitting. A recuperación is attempt 2 against the same assessment, never an overwrite: the fact that a student needed a retake is one of the strongest risk signals in the schema and must survive.';
comment on column scores.attempt_kind is 'Which legal instrument produced this attempt. Constrained to agree with attempt_number so attempt 1 is always the original.';
comment on column scores.status is 'excused excludes the row from the denominator entirely; absent and not_submitted are scored per the scheme version''s absent_counts_as. This is why an excused score is a row and not a missing one — a missing row means the teacher has not graded yet ("Sin evaluar" on screen 04).';
comment on column scores.raw_value is 'The number the teacher wrote. Null unless status = graded.';
comment on column scores.scale_level_id is
  'The letter this piece of work earned, when its assessment has value_scale = ordinal. Null for a numeric score, where the value is raw_value over max_value. It is a value on a piece of evidence and carries no normative standing: only competency_term_levels holds a nivel de logro, and internal/grading never reads this column, since a letter has no place in a weighted average.';
comment on column scores.max_value is 'Copied from the assessment at write time and frozen, so changing an assessment''s max later cannot reinterpret grades already entered. Null when the score is a letter, which has no denominator.';
comment on column scores.late_days is 'Whole days past due_at. The penalty is applied at computation time from the scheme version''s policy, never baked into raw_value, so a corrected late policy re-grades correctly.';
comment on column scores.supersedes_id is 'The row this one replaces after a correction. The link points backwards only, deliberately: a forward superseded_by_id would have to be written at the same moment as superseded_at, but the replacement row cannot exist until the old one is closed, so the pair is unsatisfiable. Follow supersedes_id backwards for the full history of a single grade.';
comment on column scores.superseded_at is 'Set when a newer row replaces this one. A row with superseded_at null and deleted_at null is the live value. Written before the replacement is inserted — see scores_live_attempt_key.';
comment on column scores.class_id is 'Denormalised from the assessment. Maintained by trigger; lets per-class grading-coverage aggregates skip a join.';
comment on column scores.term_id is 'Denormalised from the assessment. Every grade aggregate in the product is term-scoped.';

-- Exactly one live row per (assessment, student, attempt). Correcting a score is
-- therefore ordered: close the old row (set superseded_at), then insert the
-- replacement. A partial index cannot be DEFERRABLE, so the two cannot overlap.
create unique index scores_live_attempt_key
  on scores (assessment_id, student_id, attempt_number)
  where superseded_at is null and deleted_at is null;
-- Screen 02 "Pendientes · 3 alumnos": who in this assessment has no live score.
create index scores_assessment_idx
  on scores (assessment_id) where superseded_at is null and deleted_at is null;
-- Screen 04: one student's live scores for a class and term.
create index scores_student_term_idx
  on scores (student_id, term_id) where superseded_at is null and deleted_at is null;
-- Screen 02 "Notas reg." coverage: live scores for a class in a term.
create index scores_class_term_idx
  on scores (class_id, term_id) where superseded_at is null and deleted_at is null;
-- Risk signal: students who have ever needed a retake.
create index scores_retake_idx
  on scores (tenant_id, student_id) where attempt_number > 1 and deleted_at is null;
create index scores_supersedes_idx on scores (supersedes_id) where supersedes_id is not null;

-- Denormalised columns are copied from the assessment, never supplied. The
-- closed-term and draft-assessment guards live in this same function on
-- purpose: they depend on term_id, which does not exist on the incoming row.
-- As separate BEFORE INSERT triggers they would fire in name order, and a guard
-- that ran before this one would silently read a null term and pass.
-- +goose StatementBegin
create or replace function app.sync_score_denormalised() returns trigger
  language plpgsql
  as $fn$
  declare
    v_assessment_status text;
    v_term_status       text;
  begin
    select a.class_id, a.term_id, a.status, t.status
      into new.class_id, new.term_id, v_assessment_status, v_term_status
      from assessments a
      join terms t on t.id = a.term_id
     where a.id = new.assessment_id
       and a.tenant_id = new.tenant_id;

    if not found then
      raise exception 'assessment % not found in tenant %', new.assessment_id, new.tenant_id
        using errcode = 'foreign_key_violation';
    end if;

    if v_assessment_status = 'draft' then
      raise exception 'assessment % is still a draft and cannot be scored', new.assessment_id
        using errcode = 'check_violation';
    end if;

    -- A closed term stops accepting grades. This is what makes a closed report
    -- card real rather than a convention.
    if v_term_status in ('closed', 'archived') then
      raise exception 'term % is closed; grades cannot be added or changed', new.term_id
        using errcode = 'restrict_violation',
              hint = 'Reopen the term explicitly, which is an audited action, or record the change as a subsanación in the current term.';
    end if;

    return new;
  end;
  $fn$;
-- +goose StatementEnd

create trigger sync_denormalised before insert on scores
  for each row execute function app.sync_score_denormalised();

-- Constraint 5: grades are temporal. A score is never updated in place.
-- scale_level_id is among the identity columns the guard protects: correcting a
-- letter inserts a superseding row, exactly as correcting a mark does.
-- +goose StatementBegin
create or replace function app.forbid_score_mutation() returns trigger
  language plpgsql
  as $fn$
  begin
    if new.assessment_id  is distinct from old.assessment_id
       or new.student_id  is distinct from old.student_id
       or new.attempt_number is distinct from old.attempt_number
       or new.attempt_kind   is distinct from old.attempt_kind
       or new.status         is distinct from old.status
       or new.raw_value      is distinct from old.raw_value
       or new.scale_level_id is distinct from old.scale_level_id
       or new.max_value      is distinct from old.max_value
       or new.late_days      is distinct from old.late_days
       or new.recorded_by_id is distinct from old.recorded_by_id
       or new.recorded_at    is distinct from old.recorded_at then
      raise exception 'scores are append-only (score %); insert a superseding row instead of updating', old.id
        using errcode = 'restrict_violation',
              hint = 'Stamp superseded_at on this row FIRST, then insert the replacement with supersedes_id set. scores_live_attempt_key is a partial unique index and cannot be deferred, so two live rows for one attempt never coexist, even briefly.';
    end if;
    return new;
  end;
  $fn$;
-- +goose StatementEnd

create trigger forbid_mutation before update on scores
  for each row execute function app.forbid_score_mutation();

select app.enable_tenant_rls('scores');
select app.attach_updated_at('scores');
select app.attach_soft_delete_guard('scores');


-- ---------------------------------------------------------------------------
-- computed_grades
-- ---------------------------------------------------------------------------
create table computed_grades (
  id                        uuid primary key default gen_random_uuid(),
  tenant_id                 uuid not null references tenants (id),
  student_id                uuid not null,
  class_id                  uuid not null,
  term_id                   uuid not null,
  scheme_version_id         uuid not null,
  scale_id                  uuid not null,
  scope                     text not null default 'term_partial'
                              check (scope in ('term_partial', 'term_final')),

  normalized_value          numeric(6, 5) not null check (normalized_value between 0 and 1),
  normalization_method      text not null
                              check (normalization_method in ('ratio_of_evaluated', 'linear_min_max',
                                                              'band_midpoint', 'identity')),
  scale_level_id            uuid,
  display_value             text,

  total_weight              numeric(9, 6) not null check (total_weight > 0),
  evaluated_weight          numeric(9, 6) not null check (evaluated_weight >= 0),

  previous_scale_level_id   uuid,
  previous_normalized_value numeric(6, 5) check (previous_normalized_value between 0 and 1),
  trend                     text check (trend in ('up', 'down', 'flat')),

  scores_counted            integer not null default 0 check (scores_counted >= 0),
  inputs_digest             text,
  computed_by_job_id        bigint,
  supersedes_id             uuid,
  superseded_at             timestamptz,
  created_at                timestamptz not null default now(),
  updated_at                timestamptz not null default now(),
  deleted_at                timestamptz,

  constraint computed_grades_tenant_id_key unique (tenant_id, id),
  constraint computed_grades_student_fk foreign key (tenant_id, student_id)
    references students (tenant_id, id),
  constraint computed_grades_class_fk foreign key (tenant_id, class_id)
    references classes (tenant_id, id),
  constraint computed_grades_term_fk foreign key (tenant_id, term_id)
    references terms (tenant_id, id),
  constraint computed_grades_version_fk foreign key (tenant_id, scheme_version_id)
    references grading_scheme_versions (tenant_id, id),
  constraint computed_grades_scale_fk foreign key (tenant_id, scale_id)
    references grade_scales (tenant_id, id),
  constraint computed_grades_level_fk foreign key (tenant_id, scale_level_id)
    references grade_scale_levels (tenant_id, id),
  constraint computed_grades_prev_level_fk foreign key (tenant_id, previous_scale_level_id)
    references grade_scale_levels (tenant_id, id),
  constraint computed_grades_supersedes_fk foreign key (tenant_id, supersedes_id)
    references computed_grades (tenant_id, id),
  constraint computed_grades_evaluated_within_total
    check (evaluated_weight <= total_weight),
  constraint computed_grades_trend_needs_previous
    check ((trend is null) or (previous_normalized_value is not null))
);

comment on table computed_grades is
  'MINORS'' PERSONAL DATA (academic, derived). NOT the official record. The school''s own internal weighted system (D.S. 009-2006-ED art. 37.4.f lets a private IE run one), kept for schools that want a numeric mark alongside the norm. RVM 094-2020 determines achievement per competencia from the teacher''s judgement against criterios (see competency_term_levels, which is the official record and is never derived from this table). One row per student per class per term, rewritten as a new row whenever the result changes.';

comment on column computed_grades.normalized_value is 'The grade on a 0-1 axis, comparable across every scale and every tenant. This is the column models train on with a plain SELECT. For a partial term it is achievement over the evaluated portion only: screen 04''s "83% de lo evaluado" is 0.83333.';
comment on column computed_grades.normalization_method is 'How the raw result became a 0-1 number. ratio_of_evaluated is the partial-term case; band_midpoint is the lossy path used when the source is an ordinal judgement with no underlying number. Stored because the method changes what the value means.';
comment on column computed_grades.scale_level_id is 'The band the normalised value falls in: the "A" on screens 03 and 04, and the group-by key behind screen 02''s "Distribución de logros". Null when evaluated_weight is below the version''s minimum for showing a grade.';
comment on column computed_grades.display_value is 'What to print: "A" for an ordinal scale, "15.4" for vigesimal. Rendered once here rather than in each client.';
comment on column computed_grades.total_weight is 'Sum of component weights in play for this term. Normally 1; less if an optional component was dropped for having no assessments.';
comment on column computed_grades.evaluated_weight is 'Share of total_weight already evaluated. Screen 04''s "60% del curso evaluado · falta 40%" is this over total_weight.';
comment on column computed_grades.previous_scale_level_id is
  'Level on the previous computation, for the school''s own internal weighted system. Kept so a change in standing can be shown without recomputing history. Read only by that system: the official nivel de logro is asserted by a teacher and never derived from these rows.';
comment on column computed_grades.trend is
  'Direction of the last change, for the school''s own internal weighted system. Derivable from previous_normalized_value, cached because a class dashboard reads it for a whole section at once.';
comment on column computed_grades.inputs_digest is 'Hash of the score rows that fed this computation. Lets the recompute job skip writing a new row when nothing material changed, which is what keeps this table from growing on every keystroke.';
comment on column computed_grades.superseded_at is 'Set when a newer computation replaces this row. Null means current. Written before the replacement is inserted, since computed_grades_current_key admits only one live row per student, class and term.';
comment on column computed_grades.supersedes_id is 'The computation this row replaces. Points backwards only, for the same reason as scores.supersedes_id: a forward pointer could never be written, because the successor does not exist at the moment the predecessor must be closed.';
comment on column computed_grades.computed_by_job_id is 'The jobs row that produced this computation, when it came from the queue rather than an interactive save. Intentionally not a foreign key: finished jobs are pruned, and a grade must not become unwritable because its job row aged out.';

-- One current row per student, class and term.
create unique index computed_grades_current_key
  on computed_grades (student_id, class_id, term_id)
  where superseded_at is null and deleted_at is null;
-- Screen 02 "Distribución de logros": count current grades per level for a class.
create index computed_grades_class_level_idx
  on computed_grades (class_id, term_id, scale_level_id)
  where superseded_at is null and deleted_at is null;
-- Screen 03: the roster with each student's current level and trend.
create index computed_grades_class_term_idx
  on computed_grades (class_id, term_id)
  where superseded_at is null and deleted_at is null;
-- Screen 04 and the student timeline: one student's grade history, newest first.
create index computed_grades_student_history_idx
  on computed_grades (student_id, class_id, created_at desc) where deleted_at is null;
-- Model training: pull normalised grades across all tenants for a period.
create index computed_grades_training_idx
  on computed_grades (created_at) where superseded_at is null and deleted_at is null;

select app.enable_tenant_rls('computed_grades');
select app.attach_updated_at('computed_grades');
select app.attach_soft_delete_guard('computed_grades');

-- ---------------------------------------------------------------------------
-- computed_grade_components
-- ---------------------------------------------------------------------------
create table computed_grade_components (
  id                  uuid primary key default gen_random_uuid(),
  tenant_id           uuid not null references tenants (id),
  computed_grade_id   uuid not null,
  component_id        uuid not null,
  weight_applied      numeric(9, 6) not null check (weight_applied >= 0),
  is_evaluated        boolean not null default false,
  normalized_value    numeric(6, 5) check (normalized_value between 0 and 1),
  display_value       text,
  assessments_counted integer not null default 0 check (assessments_counted >= 0),
  counted_score_ids   uuid[] not null default '{}',
  dropped_score_ids   uuid[] not null default '{}',
  excused_score_ids   uuid[] not null default '{}',
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now(),
  deleted_at          timestamptz,
  constraint cgc_grade_fk foreign key (tenant_id, computed_grade_id)
    references computed_grades (tenant_id, id) on delete cascade,
  constraint cgc_component_fk foreign key (tenant_id, component_id)
    references grading_components (tenant_id, id),
  constraint cgc_evaluated_has_value
    check (is_evaluated = (normalized_value is not null))
);

comment on table computed_grade_components is 'The per-component breakdown behind one computed grade. Screen 04''s EVALUACIONES list reads weight_applied and normalized_value from here, and the "Sin evaluar" row is a component with is_evaluated = false.';
comment on column computed_grade_components.counted_score_ids is 'Exactly which score rows fed this number. Makes a grade explainable to a parent without re-running the computation.';
comment on column computed_grade_components.dropped_score_ids is 'Scores removed by drop-lowest-N. Kept so the teacher can answer "why is my worst quiz not counting" precisely.';
comment on column computed_grade_components.excused_score_ids is 'Scores excluded from the denominator because they were excused. Distinct from dropped: excused was a decision about the student, dropped was a rule about the numbers.';

create unique index cgc_key on computed_grade_components (computed_grade_id, component_id)
  where deleted_at is null;
create index cgc_component_idx on computed_grade_components (component_id);

select app.enable_tenant_rls('computed_grade_components');
select app.attach_updated_at('computed_grade_components');

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
  storage_key           text,
  audio                 bytea,
  mime_type             text,
  byte_size             bigint check (byte_size >= 0),
  status                text not null default 'draft'
                          check (status in ('draft', 'saved', 'discarded')),
  transcription_status  text not null default 'pending'
                          check (transcription_status in ('pending', 'queued', 'processing', 'completed', 'failed', 'skipped')),
  transcript            text,
  retention_until       date,
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
    check ((transcription_status = 'completed') <= (transcript is not null))
);

comment on table voice_notes is
  'MINORS'' PERSONAL DATA (behavioural, via the transcript). A teacher''s spoken note about one student, recorded during a session. The audio is the teacher''s own voice; the transcript is unstructured speech about a minor, which is the highest-risk column in the schema after the students'' own identifying data. Retention is enforced per row, not per tenant.';

comment on column voice_notes.duration_ms is 'Length in milliseconds. Screen 03 renders it as "0:04" beside the play control.';
comment on column voice_notes.storage_key is
  'Legacy disk pointer, from before audio moved into this table. Left in place so pre-migration recordings on STORAGE_DIR remain playable; new rows leave it null.';
comment on column voice_notes.audio is
  'The recorded audio itself. Not PII of a minor: this is the teacher''s voice, recorded with their knowledge while narrating an observation — the sensitive part is the spoken content (see the transcript column), not the voiceprint. Superseded storage_key: writing here happens inside the same transaction as the row insert, so a note and its audio can never drift apart the way a DB row and a disk file could.';
comment on column voice_notes.status is 'draft is a recording the teacher has not kept yet — screen 03 shows it with save and trash controls. discarded is the trash tap: soft, so an accidental discard is recoverable and a deliberate one is auditable.';
comment on column voice_notes.transcript is 'PII (minor): free-text speech about a child. Nullable and separately purgeable from the audio, so a school can drop transcripts while keeping durations for analytics.';
comment on column voice_notes.retention_until is 'Date after which the audio and transcript must be purged. Deliberately shorter by default than the academic record: a grade has a legal retention period, a recording of a child does not.';

-- Screen 03: the notes for one session, and per student within it.
create index voice_notes_session_idx on voice_notes (session_id) where deleted_at is null;
-- Screen 04: all saved notes for one student, newest first -- the summary input.
create index voice_notes_student_idx
  on voice_notes (student_id, recorded_at desc) where status = 'saved' and deleted_at is null;
-- Transcription worker: the queue of notes still waiting.
create index voice_notes_transcription_idx
  on voice_notes (tenant_id, transcription_status)
  where transcription_status in ('pending', 'queued', 'failed') and deleted_at is null;
-- Screen 06: "Notas de voz 486" for one teacher over a term.
create index voice_notes_teacher_idx
  on voice_notes (teacher_id, recorded_at) where deleted_at is null;

select app.enable_tenant_rls('voice_notes');
select app.attach_updated_at('voice_notes');
select app.attach_soft_delete_guard('voice_notes');

-- ---------------------------------------------------------------------------
-- notifications
-- ---------------------------------------------------------------------------
create table notifications (
  id                   uuid primary key default gen_random_uuid(),
  tenant_id            uuid not null references tenants (id),
  recipient_teacher_id uuid not null,
  kind                 text not null check (kind in ('alert', 'reminder')),
  category             text not null,
  severity             text not null default 'info' check (severity in ('info', 'low', 'medium', 'high')),
  title                text not null,
  body                 text,
  payload              jsonb not null default '{}'::jsonb,
  student_id           uuid,
  class_id             uuid,
  session_id           uuid,
  assessment_id        uuid,
  source               text not null default 'system'
                         check (source in ('system', 'rule', 'model', 'teacher')),
  created_at           timestamptz not null default now(),
  read_at              timestamptz,
  dismissed_at         timestamptz,
  updated_at           timestamptz not null default now(),
  deleted_at           timestamptz,
  constraint notifications_recipient_fk foreign key (tenant_id, recipient_teacher_id)
    references teachers (tenant_id, id),
  constraint notifications_student_fk foreign key (tenant_id, student_id)
    references students (tenant_id, id),
  constraint notifications_class_fk foreign key (tenant_id, class_id)
    references classes (tenant_id, id),
  constraint notifications_session_fk foreign key (tenant_id, session_id)
    references class_sessions (tenant_id, id),
  constraint notifications_assessment_fk foreign key (tenant_id, assessment_id)
    references assessments (tenant_id, id)
);

comment on table notifications is 'MINORS'' PERSONAL DATA (derived). The feed on screen 05. Alert titles and bodies name individual students and state inferences about them, so a notification row is student data even though it is addressed to a teacher. kind drives the Alertas/Recordatorios filter pills; read_at drives the unread dot and the dimmed "Leído" state. Every row carries the entity that triggered it, so tapping through lands on the student or class rather than on a dead end.';

comment on column notifications.category is 'Machine-readable subtype within the kind: level_drop, consecutive_absences, attendance_unmarked, grades_pending, no_voice_notes. What the client groups and filters on; title and body are for humans.';

-- Screen 05: the feed, newest first, optionally filtered by kind.
create index notifications_feed_idx
  on notifications (recipient_teacher_id, created_at desc) where deleted_at is null;
-- The bell badge: does this teacher have anything unread?
create index notifications_unread_idx
  on notifications (recipient_teacher_id, kind)
  where read_at is null and dismissed_at is null and deleted_at is null;
create index notifications_student_idx on notifications (student_id) where student_id is not null;

select app.enable_tenant_rls('notifications');
select app.attach_updated_at('notifications');
select app.attach_soft_delete_guard('notifications');


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
comment on column events.action is 'Verb in entity.verb form: student.read, score.recorded, session.started, attendance.marked, voice_note.saved. The single most important column for model training, so it is a plain text taxonomy rather than a constrained enum that would need a migration per new verb.';
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

comment on table jobs is
  'The work queue, in Postgres. Grade recomputation and term-failure risk evaluation run through it. Claimed with SELECT ... FOR UPDATE SKIP LOCKED, which is the only reason a queue in the primary database is viable at this scale.';

comment on column jobs.tenant_id is 'Nullable: cross-tenant maintenance work (partition creation, retention sweeps) has no tenant. This is why jobs carries no RLS policy — a worker legitimately spans tenants and sets app.tenant_id per job.';
comment on column jobs.kind is
  'Which handler runs the job. Three kinds are live: ''grade.recompute'' (recomputes the suggested grade for a class/term), ''risk.term_failure'' (heuristic early warning that a suggestion is heading for band C), and ''risk.promotion_projection'' (projects PRO/PER/RR from asserted competency levels under the cuadro of RVM 094-2020 num. 5.1.3). Plain text with no CHECK: rows of retired kinds fail as ''unknown job kind'' rather than being rewritten.';
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

create table practice_scores (
  id             uuid primary key default gen_random_uuid(),
  tenant_id      uuid not null references tenants (id),
  student_id     uuid not null,
  class_id       uuid not null,
  term_id        uuid not null,
  title          text not null,
  kind           text not null default 'otro'
                   check (kind in ('examen', 'practica', 'tarea', 'proyecto',
                                    'exposicion', 'participacion', 'otro')),
  raw_value      numeric(8, 4) not null,
  max_value      numeric(8, 4) not null check (max_value > 0),
  note           text,
  recorded_by_id uuid not null,
  recorded_at    timestamptz not null default now(),
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now(),
  deleted_at     timestamptz,
  constraint practice_scores_tenant_id_key unique (tenant_id, id),
  constraint practice_scores_student_fk foreign key (tenant_id, student_id)
    references students (tenant_id, id),
  constraint practice_scores_class_fk foreign key (tenant_id, class_id)
    references classes (tenant_id, id),
  constraint practice_scores_term_fk foreign key (tenant_id, term_id)
    references terms (tenant_id, id),
  constraint practice_scores_recorded_by_fk foreign key (tenant_id, recorded_by_id)
    references teachers (tenant_id, id)
);

comment on table practice_scores is
  'A teacher''s personal, unofficial record of a score on the student grades screen — "Añadir evaluación". Explicitly not an assessment: it carries no component and no weight, is never read by internal/grading, and never reaches computed_grades. What it''s used for (a practice quiz, a reinforcement check, anything) is entirely up to the teacher.';
comment on column practice_scores.kind is 'Same vocabulary as assessments.kind, for label consistency with the official EVALUACIONES list — not a foreign key, since these are not tied to any grading scheme.';
comment on column practice_scores.note is 'Optional free text the teacher attaches to the score.';

-- Screen 04: one student's personal scores for one class/term, newest first.
create index practice_scores_student_idx
  on practice_scores (student_id, class_id, term_id, recorded_at desc) where deleted_at is null;

select app.enable_tenant_rls('practice_scores');
select app.attach_updated_at('practice_scores');
select app.attach_soft_delete_guard('practice_scores');


-- ---------------------------------------------------------------------------
-- Inclusive education.
--
-- 5.1.1.3 p.7 (048-2024 text): for students facing educational barriers the
-- conclusión descriptiva must record the apoyos educativos and ajustes
-- razonables provided *in every period*, whatever the level reached.
-- ---------------------------------------------------------------------------

alter table students
  add column inclusion_support boolean not null default false;

comment on column students.inclusion_support is
  'MINORS'' PERSONAL DATA (sensitive). True when the student faces educational barriers and receives apoyos educativos / ajustes razonables. Makes a conclusión descriptiva mandatory in every period regardless of the level reached, and that conclusion must state the supports given (RVM 048-2024, 5.1.1.3 p.7 final paragraph). Deliberately a flag, not a diagnosis: the schema records the obligation, not the condition.';

-- ---------------------------------------------------------------------------
-- The record itself.
-- ---------------------------------------------------------------------------

create table competency_term_levels (
  id                 uuid primary key default gen_random_uuid(),
  tenant_id          uuid not null references tenants (id),
  student_id         uuid not null,
  competency_id      uuid not null,
  term_id            uuid not null,
  class_id           uuid,
  scale_level_id     uuid not null,
  suggested_level_id uuid,
  computed_grade_id  uuid,
  asserted_by_id     uuid not null,
  asserted_at        timestamptz not null default now(),
  note               text,
  supersedes_id      uuid,
  superseded_at      timestamptz,
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now(),
  deleted_at         timestamptz,
  constraint ctl_tenant_id_key unique (tenant_id, id),
  constraint ctl_student_fk foreign key (tenant_id, student_id)
    references students (tenant_id, id),
  constraint ctl_competency_fk foreign key (tenant_id, competency_id)
    references competencies (tenant_id, id),
  constraint ctl_term_fk foreign key (tenant_id, term_id)
    references terms (tenant_id, id),
  constraint ctl_class_fk foreign key (tenant_id, class_id)
    references classes (tenant_id, id),
  constraint ctl_level_fk foreign key (tenant_id, scale_level_id)
    references grade_scale_levels (tenant_id, id),
  constraint ctl_suggested_level_fk foreign key (tenant_id, suggested_level_id)
    references grade_scale_levels (tenant_id, id),
  constraint ctl_computed_grade_fk foreign key (tenant_id, computed_grade_id)
    references computed_grades (tenant_id, id),
  constraint ctl_asserted_by_fk foreign key (tenant_id, asserted_by_id)
    references teachers (tenant_id, id),
  constraint ctl_supersedes_fk foreign key (tenant_id, supersedes_id)
    references competency_term_levels (tenant_id, id)
);

comment on table competency_term_levels is
  'MINORS'' PERSONAL DATA (academic, official). The nivel de logro of one competencia for one student in one periodo — the row that goes to SIAGIE and, at year end, decides the situación final. Written by a teacher''s judgement over the period''s evidence (5.1.1.3 p.2-3), never by a computation: internal/grading only fills suggested_level_id. A competency not developed and explicitly evaluated in the period simply has no row (5.1.2.2 p.1) — absence is meaningful and must not be read as C.';
comment on column competency_term_levels.scale_level_id is 'The asserted level, as a row of grade_scale_levels (AD/A/B/C on the MINEDU ordinal scale). The only value that is official.';
comment on column competency_term_levels.suggested_level_id is 'What Yanai proposed from the weighted scores before the teacher decided. Null when nothing was computed. Kept to measure how often the suggestion is overridden — it has no normative standing whatsoever.';
comment on column competency_term_levels.computed_grade_id is 'The computed_grades row the suggestion came from, for provenance. Null when the teacher asserted without any computed input.';
comment on column competency_term_levels.class_id is 'Which class the teacher asserted from, for provenance and permissions. Not part of the identity of the record: the norm knows competencies and periods, not classes, and one competency gets exactly one level per period.';
comment on column competency_term_levels.superseded_at is 'Set when a correction replaces this row. Null means current. Written before the replacement is inserted, since ctl_current_key admits only one live row per student, competency and term.';

create unique index ctl_current_key
  on competency_term_levels (student_id, competency_id, term_id)
  where superseded_at is null and deleted_at is null;

-- The year-end read: every live level for one student, newest term first.
create index ctl_student_idx
  on competency_term_levels (student_id, term_id)
  where superseded_at is null and deleted_at is null;

-- The registration screen: one class's assertions for a period.
create index ctl_class_term_idx
  on competency_term_levels (class_id, term_id)
  where superseded_at is null and deleted_at is null;

select app.enable_tenant_rls('competency_term_levels');
select app.attach_updated_at('competency_term_levels');
select app.attach_soft_delete_guard('competency_term_levels');

-- ---------------------------------------------------------------------------
-- Conclusiones descriptivas.
--
-- Secondary EBR (5.1.1.3 p.7.d, 5.1.2.1.b p.8, 5.1.2.2 p.6, all 048-2024
-- text): mandatory when the level is C, optional otherwise. Two further
-- mandatory cases: C in two or more consecutive periods, where the conclusion
-- must justify the lack of progress (5.1.1.3 p.3); and students with
-- inclusion_support, in every period (5.1.1.3 p.7).
-- ---------------------------------------------------------------------------

create table descriptive_conclusions (
  id                       uuid primary key default gen_random_uuid(),
  tenant_id                uuid not null references tenants (id),
  student_id               uuid not null,
  competency_id            uuid not null,
  term_id                  uuid not null,
  class_id                 uuid,
  body                     text not null,
  requirement              text not null default 'optional'
                             check (requirement in ('level_c', 'consecutive_c',
                                                     'inclusion_support', 'optional')),
  includes_recommendations boolean not null default false,
  status                   text not null default 'draft'
                             check (status in ('draft', 'final')),
  authored_by_id           uuid not null,
  authored_at              timestamptz not null default now(),
  supersedes_id            uuid,
  superseded_at            timestamptz,
  created_at               timestamptz not null default now(),
  updated_at               timestamptz not null default now(),
  deleted_at               timestamptz,
  constraint dc_tenant_id_key unique (tenant_id, id),
  constraint dc_student_fk foreign key (tenant_id, student_id)
    references students (tenant_id, id),
  constraint dc_competency_fk foreign key (tenant_id, competency_id)
    references competencies (tenant_id, id),
  constraint dc_term_fk foreign key (tenant_id, term_id)
    references terms (tenant_id, id),
  constraint dc_class_fk foreign key (tenant_id, class_id)
    references classes (tenant_id, id),
  constraint dc_authored_by_fk foreign key (tenant_id, authored_by_id)
    references teachers (tenant_id, id),
  constraint dc_supersedes_fk foreign key (tenant_id, supersedes_id)
    references descriptive_conclusions (tenant_id, id),
  constraint dc_body_not_blank check (btrim(body) <> ''),
  constraint dc_final_has_recommendations
    check (status <> 'final' or includes_recommendations)
);

comment on table descriptive_conclusions is
  'MINORS'' PERSONAL DATA (academic, official). The conclusión descriptiva for one competencia in one periodo: "juicio docente basado en evidencias […] Señala avances, dificultades y recomendaciones" (094-2020, glosario). Goes to SIAGIE alongside the level. Only a ''final'' row satisfies a mandatory requirement; a ''draft'' does not unblock closing the period.';
comment on column descriptive_conclusions.requirement is
  'Why this conclusion exists. ''level_c'': the competency is at C, so it is mandatory (5.1.1.3 p.7.d). ''consecutive_c'': C in two or more consecutive periods — mandatory *and* the text must justify why there is no progress (5.1.1.3 p.3). ''inclusion_support'': the student faces educational barriers, so it is mandatory every period and must state the supports and reasonable adjustments given (5.1.1.3 p.7). ''optional'': level B, A or AD, written because the teacher considered it convenient. Set by the server from the live level and the student, never trusted from the client.';
comment on column descriptive_conclusions.includes_recommendations is
  'Asserts the text carries the personalised recommendations the norm requires of every conclusion without exception ("En todos los casos, las conclusiones descriptivas deben incluir recomendaciones personalizadas orientadas al desarrollo de cada competencia", 5.1.1.3 p.7). Enforced for status = ''final'' by dc_final_has_recommendations.';

create unique index dc_current_key
  on descriptive_conclusions (student_id, competency_id, term_id)
  where superseded_at is null and deleted_at is null;

create index dc_term_idx
  on descriptive_conclusions (term_id, class_id)
  where superseded_at is null and deleted_at is null;

select app.enable_tenant_rls('descriptive_conclusions');
select app.attach_updated_at('descriptive_conclusions');
select app.attach_soft_delete_guard('descriptive_conclusions');

-- ---------------------------------------------------------------------------
-- Year close.
--
-- 5.1.2.2 p.3: "Al final del periodo lectivo se debe consignar el último
-- nivel de logro alcanzado en cada una de las competencias. Este nivel de
-- logro es el que se consignó a cada competencia en el último periodo
-- trabajado." The last level wins — not the mean, not the mode. A student who
-- was C in bimestre 1 and A in bimestre 4 closes the year at A.
-- ---------------------------------------------------------------------------

create table competency_year_snapshots (
  id                uuid primary key default gen_random_uuid(),
  tenant_id         uuid not null references tenants (id),
  student_id        uuid not null,
  competency_id     uuid not null,
  academic_year_id  uuid not null,
  scale_level_id    uuid not null,
  source_term_id    uuid not null,
  source_level_id   uuid not null,
  closed_at         timestamptz not null default now(),
  closed_by_id      uuid,
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now(),
  deleted_at        timestamptz,
  constraint cys_tenant_id_key unique (tenant_id, id),
  constraint cys_student_fk foreign key (tenant_id, student_id)
    references students (tenant_id, id),
  constraint cys_competency_fk foreign key (tenant_id, competency_id)
    references competencies (tenant_id, id),
  constraint cys_year_fk foreign key (tenant_id, academic_year_id)
    references academic_years (tenant_id, id),
  constraint cys_level_fk foreign key (tenant_id, scale_level_id)
    references grade_scale_levels (tenant_id, id),
  constraint cys_source_term_fk foreign key (tenant_id, source_term_id)
    references terms (tenant_id, id),
  constraint cys_source_level_fk foreign key (tenant_id, source_level_id)
    references competency_term_levels (tenant_id, id),
  constraint cys_closed_by_fk foreign key (tenant_id, closed_by_id)
    references teachers (tenant_id, id)
);

comment on table competency_year_snapshots is
  'MINORS'' PERSONAL DATA (academic, official). The frozen year-end level of one competencia, taken from the last period in which it was worked (5.1.2.2 p.3). Immutable once written: it is what the Acta Oficial and the Certificado de Estudios were issued from.';
comment on column competency_year_snapshots.source_term_id is 'The last period in which this competency was worked — the one the level was copied from. Recorded because "last" is a fact about the data at close time and must stay auditable afterwards.';
comment on column competency_year_snapshots.source_level_id is 'The exact competency_term_levels row copied, so the snapshot can be traced back to the teacher who asserted it.';

create unique index cys_key
  on competency_year_snapshots (student_id, competency_id, academic_year_id)
  where deleted_at is null;

-- ---------------------------------------------------------------------------
-- Situación final: PRO / PER / RR.
--
-- Determined by the cuadro of 5.1.3 literal A (048-2024 text) counting levels
-- per área — never by averaging, which the norm does not contemplate at all.
-- ---------------------------------------------------------------------------

create table year_final_situations (
  id                uuid primary key default gen_random_uuid(),
  tenant_id         uuid not null references tenants (id),
  student_id        uuid not null,
  academic_year_id  uuid not null,
  grade_level_id    uuid not null,
  situation         text not null check (situation in ('PRO', 'PER', 'RR')),
  stage             text not null default 'year_end'
                      check (stage in ('year_end', 'post_recuperacion')),
  breakdown         jsonb not null default '{}'::jsonb,
  closed_at         timestamptz not null default now(),
  closed_by_id      uuid,
  document_ref      text,
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now(),
  deleted_at        timestamptz,
  constraint yfs_tenant_id_key unique (tenant_id, id),
  constraint yfs_student_fk foreign key (tenant_id, student_id)
    references students (tenant_id, id),
  constraint yfs_year_fk foreign key (tenant_id, academic_year_id)
    references academic_years (tenant_id, id),
  constraint yfs_grade_level_fk foreign key (tenant_id, grade_level_id)
    references grade_levels (tenant_id, id),
  constraint yfs_closed_by_fk foreign key (tenant_id, closed_by_id)
    references teachers (tenant_id, id)
);

comment on table year_final_situations is
  'MINORS'' PERSONAL DATA (academic, official). The situación final the Acta Oficial carries: PRO (promovido), PER (permanece) or RR (requiere recuperación) — the siglas the norm names in 5.1.2.1.c p.5. Immutable once written.';
comment on column year_final_situations.grade_level_id is 'The grade the student was in, because the rule itself depends on it: 1.°, 3.° and 4.° promote on "B in half or more of each área", while 2.° and 5.° — the end-of-cycle grades — require "A or AD in half or more of each of three áreas and B in the rest" (cuadro 5.1.3.A, 048-2024).';
comment on column year_final_situations.stage is
  '''year_end'': the situation at the close of the periodo lectivo. ''post_recuperacion'': recomputed after the acompañamiento or evaluación de recuperación, which the norm treats as a separate determination producing its own acta (5.2.1.A p.4-6).';
comment on column year_final_situations.breakdown is
  'The per-área counts the decision was made from, captured as JSON: which competencies were considered, at which level, and which áreas met the condition. Denormalised on purpose — the reasoning must stay readable years later even if the curriculum is rewritten.';

create unique index yfs_key
  on year_final_situations (student_id, academic_year_id, stage)
  where deleted_at is null;

-- +goose StatementBegin
create or replace function app.forbid_year_close_mutation() returns trigger
  language plpgsql
  as $fn$
  begin
    if tg_table_name = 'competency_year_snapshots' then
      if new.scale_level_id is distinct from old.scale_level_id
         or new.student_id     is distinct from old.student_id
         or new.competency_id  is distinct from old.competency_id
         or new.academic_year_id is distinct from old.academic_year_id
         or new.source_term_id is distinct from old.source_term_id then
        raise exception 'competency year snapshot % is immutable', old.id
          using errcode = 'restrict_violation',
                hint = 'Reopening the year and re-closing it writes a new snapshot; it does not edit this one.';
      end if;
    else
      if new.situation is distinct from old.situation
         or new.student_id is distinct from old.student_id
         or new.academic_year_id is distinct from old.academic_year_id
         or new.stage is distinct from old.stage
         or new.breakdown is distinct from old.breakdown then
        raise exception 'year final situation % is immutable', old.id
          using errcode = 'restrict_violation',
                hint = 'The post-recuperacion determination is a separate row (stage), not an edit of the year-end one.';
      end if;
    end if;
    return new;
  end;
  $fn$;
-- +goose StatementEnd

create trigger forbid_mutation before update on competency_year_snapshots
  for each row execute function app.forbid_year_close_mutation();
create trigger forbid_mutation before update on year_final_situations
  for each row execute function app.forbid_year_close_mutation();

select app.enable_tenant_rls('competency_year_snapshots');
select app.attach_updated_at('competency_year_snapshots');
select app.attach_soft_delete_guard('competency_year_snapshots');

select app.enable_tenant_rls('year_final_situations');
select app.attach_updated_at('year_final_situations');
select app.attach_soft_delete_guard('year_final_situations');
-- +goose Down

drop view if exists class_effective_grading_schemes;

drop table if exists year_final_situations cascade;
drop table if exists competency_year_snapshots cascade;
drop table if exists descriptive_conclusions cascade;
drop table if exists competency_term_levels cascade;
drop table if exists practice_scores cascade;
drop table if exists jobs cascade;
drop table if exists events cascade;
drop table if exists notifications cascade;
drop table if exists voice_notes cascade;
drop table if exists computed_grade_components cascade;
drop table if exists computed_grades cascade;
drop table if exists scores cascade;
drop table if exists retake_authorizations cascade;
drop table if exists assessment_criteria cascade;
drop table if exists assessment_competencies cascade;
drop table if exists assessments cascade;
drop table if exists class_grading_policies cascade;
drop table if exists grading_scheme_component_weights cascade;
drop table if exists grading_scheme_versions cascade;
drop table if exists grading_components cascade;
drop table if exists grading_schemes cascade;
drop table if exists grade_scale_levels cascade;
drop table if exists grade_scales cascade;
drop table if exists attendance_records cascade;
drop table if exists class_sessions cascade;
drop table if exists class_schedules cascade;
drop table if exists class_teachers cascade;
drop table if exists classes cascade;
drop table if exists section_memberships cascade;
drop table if exists students cascade;
drop table if exists sections cascade;
drop table if exists evaluation_criteria cascade;
drop table if exists performance_standards cascade;
drop table if exists capabilities cascade;
drop table if exists unit_competencies cascade;
drop table if exists units cascade;
drop table if exists courses cascade;
drop table if exists competencies cascade;
drop table if exists subjects cascade;
drop table if exists grade_levels cascade;
drop table if exists terms cascade;
drop table if exists academic_years cascade;
drop table if exists teachers cascade;
drop table if exists memberships cascade;
drop table if exists users cascade;
drop table if exists tenants cascade;

-- Dropping the schemas with CASCADE removes every app.* and privacy.*
-- function/view in one step (trigger functions, DDL helpers, the
-- privacy.* views).
drop schema if exists privacy cascade;
drop schema if exists app cascade;

drop type if exists timerange cascade;

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
