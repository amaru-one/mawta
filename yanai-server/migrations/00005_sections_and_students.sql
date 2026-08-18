-- Sections, students, and the temporal roster.
--
-- Per the agreed model, the roster IS the section: there is no per-class
-- enrollment table. A class's roster on a given date is the set of students
-- whose section_memberships row covers that date. This is why the roster is
-- temporal rather than a plain join table -- screen 02 shows "30 alumnos"
-- while screen 03 counts attendance out of 28, which is two students having
-- left between the two dates.

-- +goose Up

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
  photo_storage_key text,
  guardian_contact_note text,
  enrolled_on      date,
  left_on          date,
  status           text not null default 'active'
                     check (status in ('active', 'withdrawn', 'transferred', 'graduated', 'anonymized')),
  retention_until  date,
  anonymized_at    timestamptz,
  purge_after      date,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now(),
  deleted_at       timestamptz,
  deleted_by_id    uuid references teachers (id),
  constraint students_tenant_id_key unique (tenant_id, id),
  constraint students_document_pair check ((document_type is null) = (document_number is null)),
  constraint students_left_after_enrolled check (left_on is null or enrolled_on is null or left_on >= enrolled_on),
  constraint students_anonymized_consistent
    check ((status = 'anonymized') = (anonymized_at is not null))
);

comment on table students is
  'MINORS'' PERSONAL DATA. Every row is a child. Holds: legal names, birthdate, sex, national identity document, an optional photo key and a free-text guardian contact note. Processed under Ley 29733 (Perú) with parental consent held by the school. Never hard-deleted by the application: erasure runs through privacy.deletion_requests, which anonymises in place so attendance and grade history stay statistically intact. Every read must be recorded in events (action=''student.read'').';

comment on column students.student_code is 'PII (minor): identifier. School-internal enrolment code (código de matrícula).';
comment on column students.given_name is 'PII (minor): name.';
comment on column students.paternal_surname is 'PII (minor): name. Peruvian convention keeps the two surnames separate; concatenating them loses information.';
comment on column students.maternal_surname is 'PII (minor): name.';
comment on column students.preferred_name is 'PII (minor): name. What the teacher actually calls the student.';
comment on column students.birthdate is 'PII (minor): sensitive. Present because age drives both curriculum placement and the consent regime; not needed for any of the six screens.';
comment on column students.sex is 'PII (minor): sensitive.';
comment on column students.document_number is 'PII (minor): government identifier. DNI or equivalent. The highest-risk column in the schema.';
comment on column students.photo_storage_key is 'PII (minor): biometric-adjacent. Object-store key for the roster photo; the image itself never enters Postgres.';
comment on column students.guardian_contact_note is 'PII (minor and adult): free text a teacher may use to record how to reach an apoderado. Free text is a leak risk, so it is retained and purged with the rest of the record.';
comment on column students.retention_until is 'Date after which this record must be anonymised. Defaulted from tenants.default_retention_years when the student leaves.';
comment on column students.anonymized_at is 'When identifying columns were overwritten. The row survives so historical aggregates do not silently change.';
comment on column students.purge_after is 'Date after which even the anonymised row may be removed, if the tenant contract requires full erasure rather than anonymisation.';

create unique index students_tenant_code_key
  on students (tenant_id, student_code) where student_code is not null and deleted_at is null;
create unique index students_tenant_document_key
  on students (tenant_id, document_type, document_number) where document_number is not null and deleted_at is null;
-- Screen 03: "Buscar alumno..." over a roster, typed one character at a time.
create index students_name_trgm_idx on students
  using gin ((coalesce(given_name, '') || ' ' || coalesce(paternal_surname, '') || ' ' || coalesce(maternal_surname, '')) gin_trgm_ops);
-- Retention sweep: find records due for anonymisation without scanning every tenant.
create index students_retention_idx on students (retention_until)
  where retention_until is not null and anonymized_at is null and deleted_at is null;

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
  exit_reason       text,
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

-- +goose Down

drop table if exists section_memberships;
drop table if exists students;
drop table if exists sections;
