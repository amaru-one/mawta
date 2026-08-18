-- Classes (course x section), their teachers, and the recurring weekly pattern.

-- +goose Up

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

-- +goose Down

drop table if exists class_schedules;
drop table if exists class_teachers;
drop table if exists classes;
