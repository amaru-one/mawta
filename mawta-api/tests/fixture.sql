-- Deterministic fixture for the database-backed tests. Applied once, by the
-- admin (superuser) pool, immediately after the migration. Ported from the
-- demo seed deleted in a1f3320 (mawta-server/seed/seed_demo_tenant.sql):
-- trimmed to what tests need, and extended to two tenants.
--
-- The scenario, in one paragraph. Two schools. In I.E. Cristo Rey, Quispe
-- teaches Matemática to 5to B; Rojas is an active teacher of that same school
-- who teaches nothing — Rojas exists to be the colleague who must not reach
-- Quispe's class. I.E. San Martín is a separate school entirely, so tenant
-- isolation has something to isolate. Bimestre II is live; Bimestre I sits
-- closed behind it, so "the immediately preceding period" is a real thing a
-- test can assert against.
--
-- Ids are fixed and mirrored in tests/conftest.py (Fixture). The trailing segment says what the
-- row is, so a failing test names something recognisable.
--
-- Constraint notes, each learned the hard way:
--   * memberships_one_school_per_user is on (user_id) ALONE, so the two
--     tenants cannot share a users row.
--   * classes carries 4-column composite FKs to both courses and sections:
--     the class's grade_level_id must equal BOTH of theirs.
--   * terms_no_overlap uses an INCLUSIVE '[]' daterange, so consecutive terms
--     must not share a boundary date.
--   * scores.class_id/term_id are filled by a BEFORE INSERT trigger and must
--     not be supplied.
--   * an assessment must be 'published' before any score row can exist.

-- ---------------------------------------------------------------- tenant A --

insert into tenants (id, name, modular_code, timezone) values
  ('a0000000-0000-4000-8000-000000000001', 'I.E. Cristo Rey', '0400001', 'America/Lima');

insert into users (id, email, given_name, family_name, username, password_hash, status) values
  ('a0000000-0000-4000-8000-000000000010', 'janice.quispe@cristorey.edu.pe', 'Janice', 'Quispe', 'jquispe',
   '$2a$04$abcdefghijklmnopqrstuvREPLACEDBYTESTSxxxxxxxxxxxxxxxxxxxx', 'active'),
  ('a0000000-0000-4000-8000-000000000020', 'marco.rojas@cristorey.edu.pe', 'Marco', 'Rojas', 'mrojas',
   '$2a$04$abcdefghijklmnopqrstuvREPLACEDBYTESTSxxxxxxxxxxxxxxxxxxxx', 'active');

insert into memberships (id, tenant_id, user_id, role, status) values
  ('a0000000-0000-4000-8000-000000000012', 'a0000000-0000-4000-8000-000000000001', 'a0000000-0000-4000-8000-000000000010', 'teacher', 'active'),
  ('a0000000-0000-4000-8000-000000000022', 'a0000000-0000-4000-8000-000000000001', 'a0000000-0000-4000-8000-000000000020', 'teacher', 'active');

insert into teachers (id, tenant_id, membership_id, display_name, status) values
  ('a0000000-0000-4000-8000-000000000011', 'a0000000-0000-4000-8000-000000000001', 'a0000000-0000-4000-8000-000000000012', 'Janice Quispe', 'active'),
  ('a0000000-0000-4000-8000-000000000021', 'a0000000-0000-4000-8000-000000000001', 'a0000000-0000-4000-8000-000000000022', 'Marco Rojas', 'active');

insert into academic_years (id, tenant_id, year, name, starts_on, ends_on, term_structure, status) values
  ('a0000000-0000-4000-8000-000000000030', 'a0000000-0000-4000-8000-000000000001', 2026, '2026', '2026-03-01', '2026-12-18', 'bimestre', 'active');

-- Bimestre I is closed and ends the day before II begins: terms_no_overlap
-- uses an inclusive range, so they must not share a boundary date.
insert into terms (id, tenant_id, academic_year_id, sequence, name, starts_on, ends_on, status, closed_at) values
  ('a0000000-0000-4000-8000-000000000031', 'a0000000-0000-4000-8000-000000000001', 'a0000000-0000-4000-8000-000000000030',
   1, 'Bimestre I', '2026-03-01', '2026-05-15', 'closed', '2026-05-16T00:00:00Z'),
  ('a0000000-0000-4000-8000-000000000032', 'a0000000-0000-4000-8000-000000000001', 'a0000000-0000-4000-8000-000000000030',
   2, 'Bimestre II', '2026-05-16', '2026-07-31', 'active', null);

insert into grade_levels (id, tenant_id, code, label, long_label, ordinal, stage) values
  ('a0000000-0000-4000-8000-000000000040', 'a0000000-0000-4000-8000-000000000001', '5S', '5to', 'Quinto de secundaria', 11, 'secundaria');

insert into sections (id, tenant_id, academic_year_id, grade_level_id, label, name, shift, status) values
  ('a0000000-0000-4000-8000-000000000041', 'a0000000-0000-4000-8000-000000000001', 'a0000000-0000-4000-8000-000000000030',
   'a0000000-0000-4000-8000-000000000040', 'B', '5to B', 'manana', 'active');

insert into subjects (id, tenant_id, code, name) values
  ('a0000000-0000-4000-8000-000000000050', 'a0000000-0000-4000-8000-000000000001', 'MAT', 'Matemática');

-- C1 has no criterios on purpose: the criterios screen shows it as an explicit
-- gap, and a test can assert that an unasserted competencia reads as null.
insert into competencies (id, tenant_id, subject_id, code, name, kind) values
  ('a0000000-0000-4000-8000-000000000060', 'a0000000-0000-4000-8000-000000000001', 'a0000000-0000-4000-8000-000000000050',
   'MAT-C1', 'Resuelve problemas de cantidad', 'area'),
  ('a0000000-0000-4000-8000-000000000061', 'a0000000-0000-4000-8000-000000000001', 'a0000000-0000-4000-8000-000000000050',
   'MAT-C2', 'Resuelve problemas de regularidad, equivalencia y cambio', 'area');

insert into capabilities (id, tenant_id, competency_id, code, name) values
  ('a0000000-0000-4000-8000-000000000062', 'a0000000-0000-4000-8000-000000000001', 'a0000000-0000-4000-8000-000000000061',
   'MAT-C2-CAP1', 'Traduce datos y condiciones a expresiones algebraicas');

insert into evaluation_criteria (id, tenant_id, competency_id, capability_id, code, description, sort_order) values
  ('a0000000-0000-4000-8000-000000000063', 'a0000000-0000-4000-8000-000000000001', 'a0000000-0000-4000-8000-000000000061',
   'a0000000-0000-4000-8000-000000000062', 'CR1', 'Plantea la ecuación que modela la situación', 1),
  ('a0000000-0000-4000-8000-000000000064', 'a0000000-0000-4000-8000-000000000001', 'a0000000-0000-4000-8000-000000000061',
   'a0000000-0000-4000-8000-000000000062', 'CR2', 'Justifica el procedimiento empleado', 2);

insert into students (id, tenant_id, student_code, given_name, paternal_surname, maternal_surname, sex, status) values
  ('a0000000-0000-4000-8000-000000000101', 'a0000000-0000-4000-8000-000000000001', 'EST-2026-001', 'Ana',   'Alvarez', 'Ruiz',   'F', 'active'),
  ('a0000000-0000-4000-8000-000000000102', 'a0000000-0000-4000-8000-000000000001', 'EST-2026-002', 'Bruno', 'Bravo',   'Soto',   'M', 'active'),
  ('a0000000-0000-4000-8000-000000000103', 'a0000000-0000-4000-8000-000000000001', 'EST-2026-003', 'Carla', 'Cordova', 'Ttito',  'F', 'active'),
  ('a0000000-0000-4000-8000-000000000104', 'a0000000-0000-4000-8000-000000000001', 'EST-2026-004', 'Diego', 'Diaz',    'Uscamayta','M', 'active'),
  ('a0000000-0000-4000-8000-000000000105', 'a0000000-0000-4000-8000-000000000001', 'EST-2026-005', 'Elena', 'Espinoza','Vilca',  'F', 'active');

insert into section_memberships (tenant_id, student_id, section_id, academic_year_id, joined_on, status) values
  ('a0000000-0000-4000-8000-000000000001', 'a0000000-0000-4000-8000-000000000101', 'a0000000-0000-4000-8000-000000000041', 'a0000000-0000-4000-8000-000000000030', '2026-03-01', 'active'),
  ('a0000000-0000-4000-8000-000000000001', 'a0000000-0000-4000-8000-000000000102', 'a0000000-0000-4000-8000-000000000041', 'a0000000-0000-4000-8000-000000000030', '2026-03-01', 'active'),
  ('a0000000-0000-4000-8000-000000000001', 'a0000000-0000-4000-8000-000000000103', 'a0000000-0000-4000-8000-000000000041', 'a0000000-0000-4000-8000-000000000030', '2026-03-01', 'active'),
  ('a0000000-0000-4000-8000-000000000001', 'a0000000-0000-4000-8000-000000000104', 'a0000000-0000-4000-8000-000000000041', 'a0000000-0000-4000-8000-000000000030', '2026-03-01', 'active'),
  ('a0000000-0000-4000-8000-000000000001', 'a0000000-0000-4000-8000-000000000105', 'a0000000-0000-4000-8000-000000000041', 'a0000000-0000-4000-8000-000000000030', '2026-03-01', 'active');

-- One scale: minedu_ad_a_b_c, the official ordinal ladder.
insert into grade_scales (id, tenant_id, code, name, kind, min_value, max_value, decimals) values
  ('a0000000-0000-4000-8000-000000000070', 'a0000000-0000-4000-8000-000000000001', 'minedu_ad_a_b_c', 'Escala MINEDU AD/A/B/C', 'ordinal', 1, 4, 0);

-- No passing_value on the scale and no is_passing on its levels: neither
-- column exists. "Aprobado" is not a property of a nivel de logro — AD/A/B/C
-- carry no mark at all (RVM 094-2020; see migrations/SPEC.md).
insert into grade_scale_levels (id, tenant_id, scale_id, code, label, ordinal, min_normalized, max_normalized) values
  ('a0000000-0000-4000-8000-000000000074', 'a0000000-0000-4000-8000-000000000001', 'a0000000-0000-4000-8000-000000000070', 'C',  'En inicio',   1, 0.00, 0.55),
  ('a0000000-0000-4000-8000-000000000073', 'a0000000-0000-4000-8000-000000000001', 'a0000000-0000-4000-8000-000000000070', 'B',  'En proceso',  2, 0.55, 0.70),
  ('a0000000-0000-4000-8000-000000000072', 'a0000000-0000-4000-8000-000000000001', 'a0000000-0000-4000-8000-000000000070', 'A',  'Esperado',    3, 0.70, 0.85),
  ('a0000000-0000-4000-8000-000000000071', 'a0000000-0000-4000-8000-000000000001', 'a0000000-0000-4000-8000-000000000070', 'AD', 'Destacado',   4, 0.85, 1.00);

insert into courses (id, tenant_id, academic_year_id, subject_id, grade_level_id, name) values
  ('a0000000-0000-4000-8000-000000000051', 'a0000000-0000-4000-8000-000000000001', 'a0000000-0000-4000-8000-000000000030',
   'a0000000-0000-4000-8000-000000000050', 'a0000000-0000-4000-8000-000000000040', 'Matemática 5to');

insert into classes (id, tenant_id, academic_year_id, grade_level_id, course_id, section_id, code, name, status) values
  ('a0000000-0000-4000-8000-000000000052', 'a0000000-0000-4000-8000-000000000001', 'a0000000-0000-4000-8000-000000000030',
   'a0000000-0000-4000-8000-000000000040', 'a0000000-0000-4000-8000-000000000051', 'a0000000-0000-4000-8000-000000000041',
   'MAT-5B', 'Matemática 5to B', 'active');

-- Quispe teaches it. Rojas deliberately has no row here: that absence is what
-- the authorization tests are about.
insert into class_teachers (tenant_id, class_id, teacher_id, role, starts_on) values
  ('a0000000-0000-4000-8000-000000000001', 'a0000000-0000-4000-8000-000000000052', 'a0000000-0000-4000-8000-000000000011', 'titular', '2026-03-01');

insert into class_sessions (id, tenant_id, academic_year_id, class_id, term_id, session_date, scheduled_start_at, scheduled_end_at, status, actual_start_at, started_by_id) values
  ('a0000000-0000-4000-8000-000000000110', 'a0000000-0000-4000-8000-000000000001', 'a0000000-0000-4000-8000-000000000030',
   'a0000000-0000-4000-8000-000000000052', 'a0000000-0000-4000-8000-000000000032', '2026-05-18',
   '2026-05-18T13:00:00Z', '2026-05-18T14:30:00Z', 'completed', '2026-05-18T13:02:00Z', 'a0000000-0000-4000-8000-000000000011');

-- A numeric assessment (carries max_score, valued with a raw mark) and an
-- ordinal one (no max_score, valued with an AD/A/B/C level). Both shapes have
-- to exist: the two value kinds follow different paths through `scores`. Every
-- evidence is tagged with at least one criterio.
insert into assessments (id, tenant_id, class_id, term_id, session_id, title, kind, value_scale, max_score, status, published_at, created_by_id) values
  ('a0000000-0000-4000-8000-000000000120', 'a0000000-0000-4000-8000-000000000001', 'a0000000-0000-4000-8000-000000000052',
   'a0000000-0000-4000-8000-000000000032',
   'a0000000-0000-4000-8000-000000000110', 'Práctica 1', 'produccion', 'numeric', 20, 'published', '2026-05-18T13:00:00Z',
   'a0000000-0000-4000-8000-000000000011'),
  ('a0000000-0000-4000-8000-000000000121', 'a0000000-0000-4000-8000-000000000001', 'a0000000-0000-4000-8000-000000000052',
   'a0000000-0000-4000-8000-000000000032',
   null, 'Proyecto de modelación', 'produccion', 'ordinal', null, 'published', '2026-05-18T13:00:00Z',
   'a0000000-0000-4000-8000-000000000011');

insert into assessment_criteria (tenant_id, assessment_id, criterion_id) values
  ('a0000000-0000-4000-8000-000000000001', 'a0000000-0000-4000-8000-000000000120', 'a0000000-0000-4000-8000-000000000063'),
  ('a0000000-0000-4000-8000-000000000001', 'a0000000-0000-4000-8000-000000000121', 'a0000000-0000-4000-8000-000000000063'),
  ('a0000000-0000-4000-8000-000000000001', 'a0000000-0000-4000-8000-000000000121', 'a0000000-0000-4000-8000-000000000064');

-- class_id and term_id are omitted on purpose: a BEFORE INSERT trigger copies
-- them from the assessment and raises if they are inconsistent.
insert into scores (id, tenant_id, assessment_id, student_id, status, raw_value, max_value, recorded_by_id) values
  ('a0000000-0000-4000-8000-000000000122', 'a0000000-0000-4000-8000-000000000001', 'a0000000-0000-4000-8000-000000000120',
   'a0000000-0000-4000-8000-000000000101', 'graded', 16, 20, 'a0000000-0000-4000-8000-000000000011');

-- ---------------------------------------------------------------- tenant B --
-- A second school, so tenant isolation has something to isolate. Kept minimal:
-- everything a cross-tenant read could reach, and nothing more.

insert into tenants (id, name, modular_code, timezone) values
  ('b0000000-0000-4000-8000-000000000001', 'I.E. San Martín', '0400002', 'America/Lima');

-- A separate users row is mandatory, not tidiness: memberships_one_school_per_user
-- is on (user_id) alone, so one person cannot belong to both schools.
insert into users (id, email, given_name, family_name, username, password_hash, status) values
  ('b0000000-0000-4000-8000-000000000010', 'lucia.flores@sanmartin.edu.pe', 'Lucía', 'Flores', 'lflores',
   '$2a$04$abcdefghijklmnopqrstuvREPLACEDBYTESTSxxxxxxxxxxxxxxxxxxxx', 'active');

insert into memberships (id, tenant_id, user_id, role, status) values
  ('b0000000-0000-4000-8000-000000000012', 'b0000000-0000-4000-8000-000000000001', 'b0000000-0000-4000-8000-000000000010', 'teacher', 'active');

insert into teachers (id, tenant_id, membership_id, display_name, status) values
  ('b0000000-0000-4000-8000-000000000011', 'b0000000-0000-4000-8000-000000000001', 'b0000000-0000-4000-8000-000000000012', 'Lucía Flores', 'active');

insert into academic_years (id, tenant_id, year, name, starts_on, ends_on, term_structure, status) values
  ('b0000000-0000-4000-8000-000000000030', 'b0000000-0000-4000-8000-000000000001', 2026, '2026', '2026-03-01', '2026-12-18', 'bimestre', 'active');

insert into terms (id, tenant_id, academic_year_id, sequence, name, starts_on, ends_on, status) values
  ('b0000000-0000-4000-8000-000000000032', 'b0000000-0000-4000-8000-000000000001', 'b0000000-0000-4000-8000-000000000030',
   2, 'Bimestre II', '2026-05-16', '2026-07-31', 'active');

insert into grade_levels (id, tenant_id, code, label, long_label, ordinal, stage) values
  ('b0000000-0000-4000-8000-000000000040', 'b0000000-0000-4000-8000-000000000001', '5S', '5to', 'Quinto de secundaria', 11, 'secundaria');

insert into sections (id, tenant_id, academic_year_id, grade_level_id, label, name, shift, status) values
  ('b0000000-0000-4000-8000-000000000041', 'b0000000-0000-4000-8000-000000000001', 'b0000000-0000-4000-8000-000000000030',
   'b0000000-0000-4000-8000-000000000040', 'A', '5to A', 'manana', 'active');

insert into subjects (id, tenant_id, code, name) values
  ('b0000000-0000-4000-8000-000000000050', 'b0000000-0000-4000-8000-000000000001', 'MAT', 'Matemática');

insert into competencies (id, tenant_id, subject_id, code, name, kind) values
  ('b0000000-0000-4000-8000-000000000060', 'b0000000-0000-4000-8000-000000000001', 'b0000000-0000-4000-8000-000000000050',
   'MAT-C1', 'Resuelve problemas de cantidad', 'area');

-- Tenant B needs its own ordinal scale: AssertCompetencyLevel resolves the
-- level code with `where kind = 'ordinal' limit 1` and no tenant predicate,
-- leaning entirely on RLS to pick the right one.
insert into grade_scales (id, tenant_id, code, name, kind, min_value, max_value, decimals) values
  ('b0000000-0000-4000-8000-000000000070', 'b0000000-0000-4000-8000-000000000001', 'minedu_ad_a_b_c', 'Escala MINEDU AD/A/B/C', 'ordinal', 1, 4, 0);

insert into grade_scale_levels (id, tenant_id, scale_id, code, label, ordinal, min_normalized, max_normalized) values
  ('b0000000-0000-4000-8000-000000000074', 'b0000000-0000-4000-8000-000000000001', 'b0000000-0000-4000-8000-000000000070', 'C',  'En inicio',  1, 0.00, 0.55),
  ('b0000000-0000-4000-8000-000000000073', 'b0000000-0000-4000-8000-000000000001', 'b0000000-0000-4000-8000-000000000070', 'B',  'En proceso', 2, 0.55, 0.70),
  ('b0000000-0000-4000-8000-000000000072', 'b0000000-0000-4000-8000-000000000001', 'b0000000-0000-4000-8000-000000000070', 'A',  'Esperado',   3, 0.70, 0.85),
  ('b0000000-0000-4000-8000-000000000071', 'b0000000-0000-4000-8000-000000000001', 'b0000000-0000-4000-8000-000000000070', 'AD', 'Destacado',  4, 0.85, 1.00);

insert into students (id, tenant_id, student_code, given_name, paternal_surname, status) values
  ('b0000000-0000-4000-8000-000000000101', 'b0000000-0000-4000-8000-000000000001', 'EST-2026-501', 'Nadia', 'Nolasco', 'active');

insert into section_memberships (tenant_id, student_id, section_id, academic_year_id, joined_on, status) values
  ('b0000000-0000-4000-8000-000000000001', 'b0000000-0000-4000-8000-000000000101', 'b0000000-0000-4000-8000-000000000041', 'b0000000-0000-4000-8000-000000000030', '2026-03-01', 'active');

insert into courses (id, tenant_id, academic_year_id, subject_id, grade_level_id, name) values
  ('b0000000-0000-4000-8000-000000000051', 'b0000000-0000-4000-8000-000000000001', 'b0000000-0000-4000-8000-000000000030',
   'b0000000-0000-4000-8000-000000000050', 'b0000000-0000-4000-8000-000000000040', 'Matemática 5to');

insert into classes (id, tenant_id, academic_year_id, grade_level_id, course_id, section_id, code, name, status) values
  ('b0000000-0000-4000-8000-000000000052', 'b0000000-0000-4000-8000-000000000001', 'b0000000-0000-4000-8000-000000000030',
   'b0000000-0000-4000-8000-000000000040', 'b0000000-0000-4000-8000-000000000051', 'b0000000-0000-4000-8000-000000000041',
   'MAT-5A', 'Matemática 5to A', 'active');

insert into class_teachers (tenant_id, class_id, teacher_id, role, starts_on) values
  ('b0000000-0000-4000-8000-000000000001', 'b0000000-0000-4000-8000-000000000052', 'b0000000-0000-4000-8000-000000000011', 'titular', '2026-03-01');
