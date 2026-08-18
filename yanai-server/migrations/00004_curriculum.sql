-- Curriculum: subject -> course -> unit -> competency.

-- +goose Up

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
create table competencies (
  id           uuid primary key default gen_random_uuid(),
  tenant_id    uuid not null references tenants (id),
  subject_id   uuid not null,
  code         text not null,
  name         text not null,
  description  text,
  sort_order   smallint not null default 0,
  is_active    boolean not null default true,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now(),
  deleted_at   timestamptz,
  constraint competencies_tenant_id_key unique (tenant_id, id),
  constraint competencies_subject_fk foreign key (tenant_id, subject_id)
    references subjects (tenant_id, id)
);

comment on table competencies is 'A MINEDU competencia within a subject, e.g. "Se comunica oralmente en inglés como lengua extranjera". Assessments link here so achievement can later be reported per competency rather than only per component.';
comment on column competencies.code is 'National curriculum code where one exists, otherwise a school-local code. Not unique across tenants by design: two schools may code the same competency differently.';

create unique index competencies_subject_code_key
  on competencies (tenant_id, subject_id, code) where deleted_at is null;

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

-- +goose Down

drop table if exists unit_competencies;
drop table if exists units;
drop table if exists courses;
drop table if exists competencies;
drop table if exists subjects;
