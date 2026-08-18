-- Academic calendar: years, terms (bimestre/trimestre), and grade levels.

-- +goose Up

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
comment on column terms.closed_at is 'When the term was closed and term_grade_snapshots were frozen. A closed term rejects new scores, which is what keeps an April report card from changing in June.';
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

-- +goose Down

drop table if exists grade_levels;
drop table if exists terms;
drop table if exists academic_years;
