-- Demo tenant, reproducing the six screens with real rows.
--
-- The point of this script is to prove two claims that are otherwise just
-- assertions in a design document:
--
--   1. One school can run an AD/A/B/C qualitative scheme and a 0-20 vigesimal
--      scheme side by side, as rows, with no schema difference between them.
--   2. Screen 04's arithmetic falls out of raw scores and component weights
--      alone. Participación 10/20 at weight 0.20 and Quiz 1 20/20 at weight
--      0.40 give (0.50*0.20 + 1.00*0.40) / 0.60 = 0.83333 -- the "83% de lo
--      evaluado" on the card -- with a floor of 0.50 and a ceiling of 0.90.
--
-- Because RLS is FORCEd on every tenant table, this script sets
-- app.tenant_id before writing anything. That is not a workaround: it is the
-- isolation working as designed, against the script itself.
--
-- Not a goose migration. Apply the schema migrations first
-- (migrations/00001-00014), then run this file directly:
--   psql "$DATABASE_URL" -f seed/seed_demo_tenant.sql
-- See seed/README.md for how to record a new school, section, teacher,
-- class, or grading scheme, using this file as the worked example.

do $seed$
declare
  v_tenant      uuid := '11111111-1111-4111-8111-111111111111';
  v_year        uuid;
  v_b1 uuid; v_b2 uuid; v_b3 uuid; v_b4 uuid;
  v_g5          uuid;
  v_user        uuid;
  v_membership  uuid;
  v_teacher     uuid;

  v_scale_ord   uuid;  -- AD / A / B / C
  v_scale_vig   uuid;  -- 0 - 20
  v_lvl_ad uuid; v_lvl_a uuid; v_lvl_b uuid; v_lvl_c uuid;
  v_vig_ad uuid; v_vig_a uuid; v_vig_b uuid; v_vig_c uuid;

  v_scheme_min  uuid;  v_ver_min_1 uuid; v_ver_min_2 uuid;
  v_scheme_vig  uuid;  v_ver_vig_1 uuid;
  v_cmp_part uuid; v_cmp_quiz uuid; v_cmp_exam uuid;
  v_cmp_prac uuid; v_cmp_exam_v uuid; v_cmp_act uuid;

  v_subj_ing uuid; v_subj_mat uuid; v_subj_com uuid;
  v_subj_his uuid; v_subj_geo uuid; v_subj_tut uuid;
  v_course_ing uuid; v_course_mat uuid;
  v_unit uuid;
  v_section uuid;
  v_class_ing uuid; v_class_mat uuid;
  v_sched_mon uuid;

  v_flag_conducta uuid;
  v_rule_absence uuid; v_rule_drop uuid;

  v_agustin uuid; v_alonso uuid; v_amanda uuid; v_ana uuid;
  v_sofia uuid; v_diego uuid;

  v_sess_0728 uuid; v_sess_0801 uuid; v_sess_0803 uuid;
  v_sess_0808 uuid; v_sess_0812 uuid; v_sess_0814 uuid;

  v_a_part uuid; v_a_quiz uuid; v_a_exam uuid; v_a_mat uuid;
  v_cg uuid; v_flag uuid;

  v_student uuid;
  v_given   text;
  v_norm    numeric;
  v_level   uuid;
  v_display text;
  i         integer;

  c_first text[] := array['Lucía','Mateo','Valentina','Sebastián','Camila','Thiago','Emilia',
                          'Joaquín','Antonella','Facundo','Renata','Bruno','Micaela','Rodrigo',
                          'Fernanda','Iván','Paula','Nicolás','Daniela','Gabriel','Isabela',
                          'Andrés','Carolina','Martín'];
  c_last  text[] := array['Huamán','Quispe','Mamani','Flores','Chávez','Rojas','Zapata',
                          'Ccahuana','Salazar','Paredes','Vargas','Ochoa','Espinoza','Cárdenas',
                          'Ríos','Cabrera','Núñez','Ayala','Bravo','Ferrer','Molina',
                          'Delgado','Palomino','Ibáñez'];
begin
  -- Every write below is checked against this. Without it, the inserts fail.
  perform set_config('app.tenant_id', v_tenant::text, true);

  -- =========================================================================
  -- Tenant, calendar, grade levels
  -- =========================================================================
  insert into tenants (id, name, legal_name, kind, city, region, timezone, modular_code)
  values (v_tenant, 'I.E. Cristo Rey', 'Institución Educativa Cristo Rey', 'parroquial',
          'Cusco', 'Cusco', 'America/Lima', '0123456');

  insert into academic_years (tenant_id, year, name, starts_on, ends_on, term_structure, status)
  values (v_tenant, 2026, 'Año escolar 2026', date '2026-03-02', date '2026-12-18', 'bimestre', 'active')
  returning id into v_year;

  -- Bimestre boundaries follow a realistic Peruvian secundaria calendar:
  -- Bimestre II closes before Fiestas Patrias (28-29 Jul) and Bimestre III
  -- opens the day before -- which is why the demo's session block (28 Jul,
  -- 1/3/8/12/14 Ago) and screen 04's numbers sit in Bimestre III, not II.
  -- Bimestre I and II are both already closed by the time this demo's
  -- "today" (mid-August) rolls around: status and closed_at are constrained
  -- to agree, so they are set in the same statement rather than patched
  -- afterwards.
  insert into terms (tenant_id, academic_year_id, sequence, name, short_name, starts_on, ends_on, status, grades_due_on, closed_at)
  values (v_tenant, v_year, 1, 'Bimestre I',   'B-I',   date '2026-03-02', date '2026-05-15', 'closed',  date '2026-05-22', timestamptz '2026-05-25 12:00:00-05'),
         (v_tenant, v_year, 2, 'Bimestre II',  'B-II',  date '2026-05-18', date '2026-07-24', 'closed',  date '2026-07-31', timestamptz '2026-08-03 12:00:00-05'),
         (v_tenant, v_year, 3, 'Bimestre III', 'B-III', date '2026-07-27', date '2026-10-30', 'active',  date '2026-11-06', null),
         (v_tenant, v_year, 4, 'Bimestre IV',  'B-IV',  date '2026-11-02', date '2026-12-18', 'planned', date '2026-12-23', null);

  select id into v_b1 from terms where tenant_id = v_tenant and sequence = 1;
  select id into v_b2 from terms where tenant_id = v_tenant and sequence = 2;
  select id into v_b3 from terms where tenant_id = v_tenant and sequence = 3;
  select id into v_b4 from terms where tenant_id = v_tenant and sequence = 4;

  insert into grade_levels (tenant_id, code, label, long_label, stage, ordinal)
  values (v_tenant, '1', '1ro', '1ER GRADO', 'secundaria', 1),
         (v_tenant, '2', '2do', '2DO GRADO', 'secundaria', 2),
         (v_tenant, '3', '3ro', '3ER GRADO', 'secundaria', 3),
         (v_tenant, '4', '4to', '4TO GRADO', 'secundaria', 4),
         (v_tenant, '5', '5to', '5TO GRADO', 'secundaria', 5);
  select id into v_g5 from grade_levels where tenant_id = v_tenant and code = '5';

  -- =========================================================================
  -- Teacher
  -- =========================================================================
  insert into users (email, given_name, family_name, display_name, status)
  values ('janice.quispe@cristorey.edu.pe', 'Janice', 'Quispe', 'Janice Q', 'active')
  returning id into v_user;

  insert into memberships (tenant_id, user_id, role, status, joined_at)
  values (v_tenant, v_user, 'teacher', 'active', timestamptz '2021-03-01 08:00:00-05')
  returning id into v_membership;

  insert into teachers (tenant_id, membership_id, employee_code, display_name, title, hired_on, weekly_hours_contracted)
  values (v_tenant, v_membership, 'DOC-0142', 'Janice Quispe', 'Docente de Secundaria', date '2021-03-01', 30)
  returning id into v_teacher;

  update terms set closed_by_id = v_teacher where id = v_b1;
  update terms set closed_by_id = v_teacher where id = v_b2;

  -- =========================================================================
  -- Grade scales
  --
  -- Both scales carry the same numeric envelope (0-20, passing at 11) and the
  -- same normalised band edges: 11/20 = 0.55, 14/20 = 0.70, 18/20 = 0.90. They
  -- differ only in `kind`, which decides whether a result is reported as a
  -- letter or as a number. That is the whole difference between a MINEDU
  -- school and a vigesimal school in this schema.
  -- =========================================================================
  insert into grade_scales (tenant_id, code, name, kind, min_value, max_value, passing_value, decimals)
  values (v_tenant, 'minedu_ad_a_b_c', 'Escala de logro MINEDU (AD/A/B/C)', 'ordinal', 0, 20, 11, 0)
  returning id into v_scale_ord;

  insert into grade_scales (tenant_id, code, name, kind, min_value, max_value, passing_value, decimals)
  values (v_tenant, 'vigesimal_0_20', 'Escala vigesimal 0-20', 'numeric', 0, 20, 11, 0)
  returning id into v_scale_vig;

  insert into grade_scale_levels (tenant_id, scale_id, code, label, short_label, ordinal, min_normalized, max_normalized, is_passing, color_key)
  values (v_tenant, v_scale_ord, 'C',  'En inicio',        'C',  1, 0.00000, 0.55000, false, 'tier-c'),
         (v_tenant, v_scale_ord, 'B',  'En proceso',       'B',  2, 0.55000, 0.70000, false, 'warning'),
         (v_tenant, v_scale_ord, 'A',  'Logro esperado',   'A',  3, 0.70000, 0.90000, true,  'success'),
         (v_tenant, v_scale_ord, 'AD', 'Logro destacado',  'AD', 4, 0.90000, 1.00000, true,  'accent');

  select id into v_lvl_c  from grade_scale_levels where scale_id = v_scale_ord and code = 'C';
  select id into v_lvl_b  from grade_scale_levels where scale_id = v_scale_ord and code = 'B';
  select id into v_lvl_a  from grade_scale_levels where scale_id = v_scale_ord and code = 'A';
  select id into v_lvl_ad from grade_scale_levels where scale_id = v_scale_ord and code = 'AD';

  insert into grade_scale_levels (tenant_id, scale_id, code, label, short_label, ordinal, min_normalized, max_normalized, is_passing, color_key)
  values (v_tenant, v_scale_vig, '00-10', 'Desaprobado',   'C',  1, 0.00000, 0.55000, false, 'tier-c'),
         (v_tenant, v_scale_vig, '11-13', 'En proceso',    'B',  2, 0.55000, 0.70000, true,  'warning'),
         (v_tenant, v_scale_vig, '14-17', 'Logro esperado','A',  3, 0.70000, 0.90000, true,  'success'),
         (v_tenant, v_scale_vig, '18-20', 'Logro destacado','AD',4, 0.90000, 1.00000, true,  'accent');

  select id into v_vig_c  from grade_scale_levels where scale_id = v_scale_vig and code = '00-10';
  select id into v_vig_b  from grade_scale_levels where scale_id = v_scale_vig and code = '11-13';
  select id into v_vig_a  from grade_scale_levels where scale_id = v_scale_vig and code = '14-17';
  select id into v_vig_ad from grade_scale_levels where scale_id = v_scale_vig and code = '18-20';

  -- =========================================================================
  -- Scheme 1: MINEDU qualitative. Weights match screen 04 exactly.
  -- =========================================================================
  insert into grading_schemes (tenant_id, scale_id, code, name, description)
  values (v_tenant, v_scale_ord, 'minedu_secundaria', 'Evaluación MINEDU secundaria',
          'Participación 20%, evaluaciones cortas 40%, examen final 40%.')
  returning id into v_scheme_min;

  insert into grading_components (tenant_id, scheme_id, code, name, sort_order)
  values (v_tenant, v_scheme_min, 'participacion', 'Participación', 1),
         (v_tenant, v_scheme_min, 'quiz',          'Quiz',          2),
         (v_tenant, v_scheme_min, 'examen_final',  'Examen final',  3);

  select id into v_cmp_part from grading_components where scheme_id = v_scheme_min and code = 'participacion';
  select id into v_cmp_quiz from grading_components where scheme_id = v_scheme_min and code = 'quiz';
  select id into v_cmp_exam from grading_components where scheme_id = v_scheme_min and code = 'examen_final';

  insert into grading_scheme_versions (tenant_id, scheme_id, version, effective_from,
                                       rounding_mode, absent_counts_as, retake_policy,
                                       retake_cap_normalized, min_evaluated_weight_for_grade, notes)
  values (v_tenant, v_scheme_min, 1, date '2026-03-02', 'half_up', 'zero', 'capped', 0.55000, 0.10000,
          'Versión inicial 2026. Recuperación limitada a la nota mínima aprobatoria.')
  returning id into v_ver_min_1;

  insert into grading_scheme_component_weights (tenant_id, scheme_version_id, component_id, weight, aggregation, drop_lowest_n)
  values (v_tenant, v_ver_min_1, v_cmp_part, 0.200000, 'mean',          0),
         (v_tenant, v_ver_min_1, v_cmp_quiz, 0.400000, 'weighted_mean', 1),
         (v_tenant, v_ver_min_1, v_cmp_exam, 0.400000, 'last',          0);

  update grading_scheme_versions
     set published_at = timestamptz '2026-02-20 09:00:00-05', published_by_id = v_teacher
   where id = v_ver_min_1;

  -- A second version, to demonstrate that re-weighting inserts rather than
  -- edits. It takes effect at Bimestre IV, so everything computed under
  -- Bimestre II and Bimestre III on version 1 stays computed under version 1
  -- forever.
  insert into grading_scheme_versions (tenant_id, scheme_id, version, effective_from,
                                       rounding_mode, absent_counts_as, retake_policy,
                                       retake_cap_normalized, min_evaluated_weight_for_grade, notes)
  values (v_tenant, v_scheme_min, 2, date '2026-11-02', 'half_up', 'zero', 'capped', 0.55000, 0.10000,
          'Dirección aumenta el peso de participación para el último bimestre.')
  returning id into v_ver_min_2;

  insert into grading_scheme_component_weights (tenant_id, scheme_version_id, component_id, weight, aggregation, drop_lowest_n)
  values (v_tenant, v_ver_min_2, v_cmp_part, 0.300000, 'mean',          0),
         (v_tenant, v_ver_min_2, v_cmp_quiz, 0.400000, 'weighted_mean', 1),
         (v_tenant, v_ver_min_2, v_cmp_exam, 0.300000, 'last',          0);

  -- Version 1 must be closed off before version 2 is published: two published
  -- versions of one scheme may not both be in effect on a date. Closing
  -- effective_to is the only edit a published version accepts.
  update grading_scheme_versions set effective_to = date '2026-11-02' where id = v_ver_min_1;

  update grading_scheme_versions
     set published_at = timestamptz '2026-10-20 09:00:00-05', published_by_id = v_teacher
   where id = v_ver_min_2;

  -- =========================================================================
  -- Scheme 2: 0-20 vigesimal. Same tables, different rows.
  -- =========================================================================
  insert into grading_schemes (tenant_id, scale_id, code, name, description)
  values (v_tenant, v_scale_vig, 'vigesimal_ciencias', 'Evaluación vigesimal 0-20',
          'Prácticas 30%, exámenes 50%, actitudinal 20%. Se elimina la práctica más baja.')
  returning id into v_scheme_vig;

  insert into grading_components (tenant_id, scheme_id, code, name, sort_order)
  values (v_tenant, v_scheme_vig, 'practicas',   'Prácticas calificadas', 1),
         (v_tenant, v_scheme_vig, 'examenes',    'Exámenes',              2),
         (v_tenant, v_scheme_vig, 'actitudinal', 'Actitudinal',           3);

  select id into v_cmp_prac   from grading_components where scheme_id = v_scheme_vig and code = 'practicas';
  select id into v_cmp_exam_v from grading_components where scheme_id = v_scheme_vig and code = 'examenes';
  select id into v_cmp_act    from grading_components where scheme_id = v_scheme_vig and code = 'actitudinal';

  insert into grading_scheme_versions (tenant_id, scheme_id, version, effective_from,
                                       rounding_mode, rounding_decimals, absent_counts_as,
                                       late_penalty_pct_per_day, late_penalty_max_pct,
                                       retake_policy, min_evaluated_weight_for_grade)
  values (v_tenant, v_scheme_vig, 1, date '2026-03-02', 'half_up', 0, 'zero', 0.0500, 0.2000, 'best', 0.10000)
  returning id into v_ver_vig_1;

  insert into grading_scheme_component_weights (tenant_id, scheme_version_id, component_id, weight, aggregation, drop_lowest_n)
  values (v_tenant, v_ver_vig_1, v_cmp_prac,   0.300000, 'mean',          1),
         (v_tenant, v_ver_vig_1, v_cmp_exam_v, 0.500000, 'weighted_mean', 0),
         (v_tenant, v_ver_vig_1, v_cmp_act,    0.200000, 'mean',          0);

  update grading_scheme_versions
     set published_at = timestamptz '2026-02-20 09:00:00-05', published_by_id = v_teacher
   where id = v_ver_vig_1;

  -- MINEDU is the school default; Matemática overrides to vigesimal below.
  update tenants set default_grading_scheme_id = v_scheme_min where id = v_tenant;

  -- =========================================================================
  -- Curriculum
  -- =========================================================================
  insert into subjects (tenant_id, code, name, area_curricular, icon_key, is_tutoria, sort_order)
  values (v_tenant, 'ING', 'Inglés',        'Inglés como lengua extranjera', 'book',       false, 1),
         (v_tenant, 'MAT', 'Matemática',    'Matemática',                    'calculator', false, 2),
         (v_tenant, 'COM', 'Comunicación',  'Comunicación',                  'book',       false, 3),
         (v_tenant, 'HIS', 'Historia',      'Ciencias Sociales',             'bank',       false, 4),
         (v_tenant, 'GEO', 'Geografía',     'Ciencias Sociales',             'world',      false, 5),
         (v_tenant, 'TUT', 'Tutoría',       'Tutoría y Orientación Educativa','checklist', true,  6);

  select id into v_subj_ing from subjects where tenant_id = v_tenant and code = 'ING';
  select id into v_subj_mat from subjects where tenant_id = v_tenant and code = 'MAT';
  select id into v_subj_com from subjects where tenant_id = v_tenant and code = 'COM';
  select id into v_subj_his from subjects where tenant_id = v_tenant and code = 'HIS';
  select id into v_subj_geo from subjects where tenant_id = v_tenant and code = 'GEO';
  select id into v_subj_tut from subjects where tenant_id = v_tenant and code = 'TUT';

  insert into competencies (tenant_id, subject_id, code, name, sort_order)
  values (v_tenant, v_subj_ing, 'ING-C1', 'Se comunica oralmente en inglés como lengua extranjera', 1),
         (v_tenant, v_subj_ing, 'ING-C2', 'Lee diversos tipos de textos escritos en inglés', 2),
         (v_tenant, v_subj_ing, 'ING-C3', 'Escribe diversos tipos de textos en inglés', 3);

  insert into courses (tenant_id, academic_year_id, subject_id, grade_level_id, name, code, weekly_hours)
  values (v_tenant, v_year, v_subj_ing, v_g5, 'Inglés 5to', 'ING-5', 4)
  returning id into v_course_ing;

  -- The course-level override: Matemática is graded on the vigesimal scheme
  -- while the rest of the school runs on MINEDU.
  insert into courses (tenant_id, academic_year_id, subject_id, grade_level_id, name, code, weekly_hours, grading_scheme_id)
  values (v_tenant, v_year, v_subj_mat, v_g5, 'Matemática 5to', 'MAT-5', 5, v_scheme_vig)
  returning id into v_course_mat;

  insert into units (tenant_id, course_id, term_id, sequence, title, starts_on, ends_on)
  values (v_tenant, v_course_ing, v_b3, 3, 'Perfect tenses and daily routines', date '2026-07-27', date '2026-08-28')
  returning id into v_unit;

  insert into unit_competencies (tenant_id, unit_id, competency_id)
  select v_tenant, v_unit, id from competencies where tenant_id = v_tenant and code in ('ING-C1', 'ING-C3');

  -- =========================================================================
  -- Section, classes, weekly pattern
  -- =========================================================================
  insert into sections (tenant_id, academic_year_id, grade_level_id, label, name, tutor_teacher_id, shift, capacity)
  values (v_tenant, v_year, v_g5, 'B', '5to B', v_teacher, 'manana', 32)
  returning id into v_section;

  insert into classes (tenant_id, academic_year_id, course_id, section_id, name, code, default_room)
  values (v_tenant, v_year, v_course_ing, v_section, 'Inglés 5to B', 'ING-5B', 'Aula 12')
  returning id into v_class_ing;

  insert into classes (tenant_id, academic_year_id, course_id, section_id, name, code, default_room)
  values (v_tenant, v_year, v_course_mat, v_section, 'Matemática 5to B', 'MAT-5B', 'Aula 12')
  returning id into v_class_mat;

  insert into class_teachers (tenant_id, class_id, teacher_id, role, starts_on)
  values (v_tenant, v_class_ing, v_teacher, 'titular', date '2026-03-02'),
         (v_tenant, v_class_mat, v_teacher, 'titular', date '2026-03-02');

  -- "4 sesiones/semana" on screen 02.
  insert into class_schedules (tenant_id, class_id, weekday, starts_at, ends_at, room, effective_from)
  values (v_tenant, v_class_ing, 1, time '10:00', time '11:00', 'Aula 12', date '2026-03-02'),
         (v_tenant, v_class_ing, 2, time '10:00', time '11:00', 'Aula 12', date '2026-03-02'),
         (v_tenant, v_class_ing, 3, time '10:00', time '11:00', 'Aula 12', date '2026-03-02'),
         (v_tenant, v_class_ing, 5, time '10:00', time '11:00', 'Aula 12', date '2026-03-02');

  select id into v_sched_mon from class_schedules where class_id = v_class_ing and weekday = 1;

  -- =========================================================================
  -- Students: 30 enrolled in the section; 2 transfer out on 5 August, purely
  -- to exercise section_memberships.left_on (a student who leaves mid-term
  -- keeps every prior attendance and score row). This is not modeling the
  -- mockup's "30 alumnos" / "28" pairing on purpose -- that discrepancy is
  -- mockup inconsistency, not a product rule; see ANALYSIS.md item 1.
  -- =========================================================================
  insert into students (tenant_id, student_code, given_name, paternal_surname, maternal_surname, birthdate, sex, document_type, document_number, enrolled_on)
  values (v_tenant, 'EST-2026-001', 'Agustín', 'Soto',    'Ramos',   date '2010-04-12', 'M', 'DNI', '70123001', date '2026-03-02'),
         (v_tenant, 'EST-2026-002', 'Alonso',  'Guzmán',  'Ríos',    date '2010-02-28', 'M', 'DNI', '70123002', date '2026-03-02'),
         (v_tenant, 'EST-2026-003', 'Amanda',  'Vidal',   'Loayza',  date '2010-07-03', 'F', 'DNI', '70123003', date '2026-03-02'),
         (v_tenant, 'EST-2026-004', 'Ana',     'Morales', 'Sierra',  date '2010-11-19', 'F', 'DNI', '70123004', date '2026-03-02'),
         (v_tenant, 'EST-2026-005', 'Sofía',   'Ramírez', 'Ponce',   date '2010-06-08', 'F', 'DNI', '70123005', date '2026-03-02'),
         (v_tenant, 'EST-2026-006', 'Diego',   'Torres',  'Aguilar', date '2010-09-25', 'M', 'DNI', '70123006', date '2026-03-02');

  select id into v_agustin from students where tenant_id = v_tenant and student_code = 'EST-2026-001';
  select id into v_alonso  from students where tenant_id = v_tenant and student_code = 'EST-2026-002';
  select id into v_amanda  from students where tenant_id = v_tenant and student_code = 'EST-2026-003';
  select id into v_ana     from students where tenant_id = v_tenant and student_code = 'EST-2026-004';
  select id into v_sofia   from students where tenant_id = v_tenant and student_code = 'EST-2026-005';
  select id into v_diego   from students where tenant_id = v_tenant and student_code = 'EST-2026-006';

  for i in 1..24 loop
    insert into students (tenant_id, student_code, given_name, paternal_surname, maternal_surname,
                          birthdate, sex, document_type, document_number, enrolled_on)
    values (v_tenant,
            format('EST-2026-%s', lpad((i + 6)::text, 3, '0')),
            c_first[i], c_last[i], c_last[((i + 7) % 24) + 1],
            date '2010-01-01' + (i * 11), case when i % 2 = 0 then 'F' else 'M' end,
            'DNI', format('701230%s', lpad((i + 6)::text, 2, '0')),
            date '2026-03-02');
  end loop;

  insert into section_memberships (tenant_id, student_id, section_id, academic_year_id, joined_on)
  select v_tenant, s.id, v_section, v_year, date '2026-03-02'
    from students s where s.tenant_id = v_tenant;

  -- Two students transfer out on 5 August.
  update section_memberships sm
     set left_on = date '2026-08-05', status = 'transferred', exit_reason = 'Traslado a otra institución'
    from students s
   where s.id = sm.student_id
     and s.student_code in ('EST-2026-029', 'EST-2026-030');

  update students set status = 'transferred', left_on = date '2026-08-05',
                      retention_until = date '2031-08-05'
   where tenant_id = v_tenant and student_code in ('EST-2026-029', 'EST-2026-030');

  -- =========================================================================
  -- Sessions. schedule_id is resolved by weekday; a date with no matching slot
  -- lands as an ad-hoc session with schedule_id null, which is a supported case.
  -- =========================================================================
  -- status and actual_start_at are constrained to agree, so a completed session
  -- is inserted complete rather than backfilled by a later UPDATE.
  insert into class_sessions (tenant_id, class_id, schedule_id, term_id, unit_id, session_date,
                              scheduled_start_at, scheduled_end_at, status, topic, room,
                              actual_start_at, actual_end_at, started_by_id,
                              attendance_taken_at, attendance_taken_by_id)
  select v_tenant, v_class_ing,
         (select cs.id from class_schedules cs
           where cs.class_id = v_class_ing and cs.weekday = extract(isodow from d.day)::smallint limit 1),
         v_b3, v_unit, d.day,
         (d.day + time '10:00') at time zone 'America/Lima',
         (d.day + time '11:00') at time zone 'America/Lima',
         d.status, d.topic, 'Aula 12',
         case when d.status = 'completed' then (d.day + time '10:00') at time zone 'America/Lima' end,
         case when d.status = 'completed' then (d.day + time '11:00') at time zone 'America/Lima' end,
         case when d.status = 'completed' then v_teacher end,
         -- 8 August was taught but never marked: that null is screen 02's
         -- "Asistencia sin marcar" and screen 05's reminder, in one column.
         case when d.status = 'completed' and d.day <> date '2026-08-08'
              then ((d.day + time '10:00') at time zone 'America/Lima') + interval '6 minutes' end,
         case when d.status = 'completed' and d.day <> date '2026-08-08' then v_teacher end
    from (values
            (date '2026-07-28', 'completed', 'Simple past — ejercicios'),
            (date '2026-08-01', 'completed', 'Listening: diálogos cortos'),
            (date '2026-08-03', 'completed', 'Vocabulario: rutinas diarias'),
            (date '2026-08-08', 'completed', 'Present perfect tense'),
            (date '2026-08-12', 'scheduled', 'Grammar review'),
            (date '2026-08-14', 'scheduled', 'Reading comprehension')
         ) as d(day, status, topic);

  select id into v_sess_0728 from class_sessions where class_id = v_class_ing and session_date = date '2026-07-28';
  select id into v_sess_0801 from class_sessions where class_id = v_class_ing and session_date = date '2026-08-01';
  select id into v_sess_0803 from class_sessions where class_id = v_class_ing and session_date = date '2026-08-03';
  select id into v_sess_0808 from class_sessions where class_id = v_class_ing and session_date = date '2026-08-08';
  select id into v_sess_0812 from class_sessions where class_id = v_class_ing and session_date = date '2026-08-12';
  select id into v_sess_0814 from class_sessions where class_id = v_class_ing and session_date = date '2026-08-14';

  -- =========================================================================
  -- Attendance. On 8 August the roster is 28: "28/28 asistencia completa".
  -- =========================================================================
  insert into attendance_records (tenant_id, session_id, student_id, status, source, recorded_by_id, recorded_at)
  select v_tenant, sess.id, sm.student_id,
         case
           when sess.session_date = date '2026-08-01' and sm.student_id = v_sofia then 'absent'
           else 'present'
         end,
         'bulk', v_teacher, sess.scheduled_start_at + interval '6 minutes'
    from class_sessions sess
    join section_memberships sm
      on sm.section_id = v_section
     and sm.joined_on <= sess.session_date
     and (sm.left_on is null or sm.left_on > sess.session_date)
   where sess.class_id = v_class_ing
     and sess.status = 'completed'
     and sess.id <> v_sess_0808;

  -- =========================================================================
  -- Observations and a voice note, as rendered on screen 03.
  -- =========================================================================
  insert into behavior_flag_types (tenant_id, code, label, severity, is_positive, sort_order)
  values (v_tenant, 'interrumpe',    'Interrumpe la clase',        'medium', false, 1),
         (v_tenant, 'no_trabaja',    'No trabaja en clase',        'medium', false, 2),
         (v_tenant, 'tardanza',      'Llega tarde reiteradamente', 'low',    false, 3),
         (v_tenant, 'destaca',       'Destaca por su esfuerzo',    'info',   true,  4);
  select id into v_flag_conducta from behavior_flag_types where tenant_id = v_tenant and code = 'interrumpe';

  insert into session_observations (tenant_id, session_id, student_id, participation_level, recorded_by_id)
  values (v_tenant, v_sess_0808, v_agustin, 3, v_teacher),
         (v_tenant, v_sess_0808, v_alonso,  2, v_teacher),
         (v_tenant, v_sess_0808, v_amanda,  1, v_teacher),
         (v_tenant, v_sess_0808, v_ana,     0, v_teacher);

  insert into session_observation_flags (tenant_id, observation_id, flag_type_id)
  select v_tenant, o.id, v_flag_conducta
    from session_observations o
   where o.session_id = v_sess_0808 and o.student_id = v_agustin;

  insert into voice_notes (tenant_id, session_id, student_id, class_id, teacher_id,
                           duration_ms, storage_bucket, storage_key, mime_type, byte_size,
                           status, transcription_status, retention_until)
  values (v_tenant, v_sess_0808, v_agustin, v_class_ing, v_teacher,
          4000, 'yanai-voice', format('%s/%s/%s.m4a', v_tenant, v_sess_0808, gen_random_uuid()),
          'audio/mp4', 41230, 'draft', 'pending', date '2027-08-08');

  -- =========================================================================
  -- Assessments and scores. These are the numbers on screen 04.
  -- =========================================================================
  insert into assessments (tenant_id, class_id, term_id, scheme_id, component_id, unit_id,
                           title, kind, max_score, due_at, status, published_at, created_by_id)
  values (v_tenant, v_class_ing, v_b3, v_scheme_min, v_cmp_part, v_unit,
          'Participación', 'participacion', 20, timestamptz '2026-08-28 23:59:00-05',
          'published', timestamptz '2026-07-27 08:00:00-05', v_teacher)
  returning id into v_a_part;

  insert into assessments (tenant_id, class_id, term_id, scheme_id, component_id, unit_id, session_id,
                           title, kind, max_score, due_at, status, published_at, created_by_id)
  values (v_tenant, v_class_ing, v_b3, v_scheme_min, v_cmp_quiz, v_unit, v_sess_0801,
          'Quiz 1', 'quiz', 20, timestamptz '2026-08-01 11:00:00-05',
          'published', timestamptz '2026-07-27 08:00:00-05', v_teacher)
  returning id into v_a_quiz;

  -- Published but not yet due: this is screen 04's dashed "Sin evaluar" card,
  -- and the 40% of "falta 40%". No score rows exist for it -- "Sin evaluar" is
  -- the absence of a row, never a row with a null value.
  insert into assessments (tenant_id, class_id, term_id, scheme_id, component_id, unit_id,
                           title, kind, max_score, due_at, status, published_at, created_by_id)
  values (v_tenant, v_class_ing, v_b3, v_scheme_min, v_cmp_exam, v_unit,
          'Examen final', 'examen', 20, timestamptz '2026-08-26 11:00:00-05',
          'published', timestamptz '2026-07-27 08:00:00-05', v_teacher)
  returning id into v_a_exam;

  insert into assessment_competencies (tenant_id, assessment_id, competency_id)
  select v_tenant, v_a_quiz, id from competencies where tenant_id = v_tenant and code = 'ING-C2';

  -- Agustín: 10/20 participación, 20/20 quiz. Raw values and the maximum only.
  insert into scores (tenant_id, assessment_id, student_id, status, raw_value, max_value, recorded_by_id, recorded_at)
  values (v_tenant, v_a_part, v_agustin, 'graded', 10, 20, v_teacher, timestamptz '2026-08-10 18:00:00-05'),
         (v_tenant, v_a_quiz, v_agustin, 'graded', 20, 20, v_teacher, timestamptz '2026-08-02 19:20:00-05');

  -- Diego fails the original sitting. His retake below is a second attempt
  -- against this same row, not a replacement for it.
  insert into scores (tenant_id, assessment_id, student_id, status, raw_value, max_value, recorded_by_id, recorded_at)
  values (v_tenant, v_a_quiz, v_diego, 'graded', 9, 20, v_teacher, timestamptz '2026-08-02 19:20:00-05');

  -- The rest of the roster on the quiz, minus three: screen 02's
  -- "Listening: diálogos cortos · 3 alumnos" pending.
  insert into scores (tenant_id, assessment_id, student_id, status, raw_value, max_value, recorded_by_id, recorded_at)
  select v_tenant, v_a_quiz, sm.student_id, 'graded',
         12 + ((row_number() over (order by sm.student_id)) % 9), 20,
         v_teacher, timestamptz '2026-08-02 19:20:00-05'
    from section_memberships sm
   where sm.section_id = v_section
     and sm.student_id not in (v_agustin, v_diego)
     and sm.left_on is null
   order by sm.student_id
   limit 23;

  -- Sofía missed the quiz and it was excused: excluded from her denominator
  -- entirely, which is a different fact from scoring zero.
  insert into scores (tenant_id, assessment_id, student_id, status, raw_value, max_value, recorded_by_id, feedback)
  values (v_tenant, v_a_part, v_sofia, 'excused', null, 20, v_teacher,
          'Ausencia justificada por motivos de salud durante el periodo evaluado.')
  on conflict do nothing;

  -- A retake, kept as a second attempt rather than replacing the first.
  insert into retake_authorizations (tenant_id, assessment_id, student_id, kind, reason,
                                     window_starts_at, window_ends_at, max_normalized_cap, authorized_by_id)
  values (v_tenant, v_a_quiz, v_diego, 'recuperacion', 'Nota desaprobatoria en la evaluación original.',
          timestamptz '2026-08-10 08:00:00-05', timestamptz '2026-08-17 18:00:00-05', 0.55000, v_teacher);

  insert into scores (tenant_id, assessment_id, student_id, status, raw_value, max_value,
                      attempt_number, attempt_kind, retake_authorization_id, recorded_by_id)
  select v_tenant, v_a_quiz, v_diego, 'graded', 14, 20, 2, 'recuperacion', r.id, v_teacher
    from retake_authorizations r
   where r.assessment_id = v_a_quiz and r.student_id = v_diego;

  -- =========================================================================
  -- Bimestre I is closed but the schema has no rule that a closed term must
  -- have a final grade on record -- it should. Without one, no student has a
  -- prior term to compare against, so screen 03's roster-chip trend (an
  -- "X -> Y" style indicator) would never have anything to compute from. Only
  -- Agustín's row is seeded here; the rest of the roster's Bimestre I history
  -- is out of scope for this demo. Trend query: latest term_final row from
  -- the prior term vs. the current term's latest row, for the same student --
  -- no new computed_grades.scope value needed.
  -- =========================================================================
  insert into computed_grades (
    tenant_id, student_id, class_id, term_id, scheme_version_id, scale_id, scope,
    normalized_value, normalization_method, scale_level_id, display_value,
    total_weight, evaluated_weight, projected_min_normalized, projected_max_normalized,
    scores_counted, computed_at)
  values (
    v_tenant, v_agustin, v_class_ing, v_b1, v_ver_min_1, v_scale_ord, 'term_final',
    0.92000, 'ratio_of_evaluated', v_lvl_ad, 'AD',
    1.000000, 1.000000, 0.92000, 0.92000, 3, timestamptz '2026-05-25 12:00:05-05');

  -- =========================================================================
  -- Computed grades. Distribution AD 4 / A 18 / B 6 / C 2, as on screen 02.
  -- =========================================================================
  i := 0;
  for v_student, v_given in
    select s.id, s.given_name from students s where s.tenant_id = v_tenant order by s.student_code
  loop
    i := i + 1;

    if v_student = v_agustin then
      -- The only row computed from real scores rather than assigned:
      -- (0.50 * 0.20 + 1.00 * 0.40) / 0.60 = 0.83333
      v_norm := 0.83333; v_level := v_lvl_a;  v_display := 'A';
    elsif v_student = v_alonso then
      v_norm := 0.93000; v_level := v_lvl_ad; v_display := 'AD';
    elsif v_student = v_amanda then
      v_norm := 0.78000; v_level := v_lvl_a;  v_display := 'A';
    elsif v_student = v_ana then
      v_norm := 0.75000; v_level := v_lvl_a;  v_display := 'A';
    elsif v_student = v_sofia then
      v_norm := 0.60000; v_level := v_lvl_b;  v_display := 'B';
    elsif v_student = v_diego then
      v_norm := 0.62000; v_level := v_lvl_b;  v_display := 'B';
    elsif i <= 9  then v_norm := 0.94000; v_level := v_lvl_ad; v_display := 'AD';
    elsif i <= 24 then v_norm := 0.79000; v_level := v_lvl_a;  v_display := 'A';
    elsif i <= 28 then v_norm := 0.63000; v_level := v_lvl_b;  v_display := 'B';
    else               v_norm := 0.42000; v_level := v_lvl_c;  v_display := 'C';
    end if;

    insert into computed_grades (
      tenant_id, student_id, class_id, term_id, scheme_version_id, scale_id, scope,
      normalized_value, normalization_method, scale_level_id, display_value,
      total_weight, evaluated_weight, projected_min_normalized, projected_max_normalized,
      previous_scale_level_id, previous_normalized_value, trend, scores_counted, computed_at)
    values (
      v_tenant, v_student, v_class_ing, v_b3, v_ver_min_1, v_scale_ord, 'term_partial',
      v_norm, 'ratio_of_evaluated', v_level, v_display,
      1.000000, 0.600000,
      round(v_norm * 0.6, 5), round(v_norm * 0.6 + 0.4, 5),
      case when v_student = v_alonso then v_lvl_a
           when v_student = v_diego  then v_lvl_a
           else v_level end,
      case when v_student = v_alonso then 0.88000
           when v_student = v_diego  then 0.72000
           else v_norm end,
      case when v_student = v_alonso then 'up'
           when v_student = v_diego  then 'down'
           else 'flat' end,
      2, timestamptz '2026-08-10 18:00:05-05')
    returning id into v_cg;

    insert into computed_grade_components (tenant_id, computed_grade_id, component_id,
                                           weight_applied, is_evaluated, normalized_value, display_value)
    values (v_tenant, v_cg, v_cmp_part, 0.200000, true,
            case when v_student = v_agustin then 0.50000 else v_norm end,
            null),
           (v_tenant, v_cg, v_cmp_quiz, 0.400000, true,
            case when v_student = v_agustin then 1.00000 else v_norm end,
            null),
           (v_tenant, v_cg, v_cmp_exam, 0.400000, false, null, null);
  end loop;

  -- The same student, on the vigesimal course. Identical machinery, different
  -- scale: 0.83333 normalised renders as 17 out of 20 instead of "A".
  insert into assessments (tenant_id, class_id, term_id, scheme_id, component_id,
                           title, kind, max_score, due_at, status, published_at, created_by_id)
  values (v_tenant, v_class_mat, v_b3, v_scheme_vig, v_cmp_prac,
          'Práctica calificada 3', 'practica', 20, timestamptz '2026-08-07 11:00:00-05',
          'published', timestamptz '2026-08-01 08:00:00-05', v_teacher)
  returning id into v_a_mat;

  insert into scores (tenant_id, assessment_id, student_id, status, raw_value, max_value, late_days, recorded_by_id)
  values (v_tenant, v_a_mat, v_agustin, 'graded', 17, 20, 2, v_teacher);

  insert into computed_grades (
    tenant_id, student_id, class_id, term_id, scheme_version_id, scale_id, scope,
    normalized_value, normalization_method, scale_level_id, display_value,
    total_weight, evaluated_weight, projected_min_normalized, projected_max_normalized,
    scores_counted, computed_at)
  values (
    v_tenant, v_agustin, v_class_mat, v_b3, v_ver_vig_1, v_scale_vig, 'term_partial',
    0.83333, 'ratio_of_evaluated', v_vig_a, '17',
    1.000000, 0.300000, 0.25000, 0.95000, 1, timestamptz '2026-08-10 18:00:05-05');

  -- =========================================================================
  -- Risk flags and notifications, as on screens 02 and 05.
  -- =========================================================================
  insert into risk_rules (tenant_id, code, name, description, kind, version, params, severity, window_days)
  values (v_tenant, 'consecutive_absences', 'Ausencias consecutivas',
          'Marca al alumno tras N inasistencias seguidas en la misma clase.',
          'rule', '1', '{"consecutive_absences": 3}'::jsonb, 'high', 30),
         (v_tenant, 'level_drop', 'Caída de nivel de logro',
          'Marca al alumno cuando su nivel baja en las últimas N sesiones evaluadas.',
          'rule', '1', '{"level_drop_sessions": 3, "min_drop": 1}'::jsonb, 'medium', 30);

  select id into v_rule_absence from risk_rules where tenant_id = v_tenant and code = 'consecutive_absences';
  select id into v_rule_drop    from risk_rules where tenant_id = v_tenant and code = 'level_drop';

  insert into risk_flags (tenant_id, student_id, class_id, rule_id, rule_version, severity,
                          reason_code, reason_text, opened_at)
  values (v_tenant, v_sofia, v_class_ing, v_rule_absence, '1', 'high',
          'consecutive_absences', '3 ausencias seguidas', timestamptz '2026-08-10 09:15:00-05')
  returning id into v_flag;

  insert into risk_flag_evidence (tenant_id, risk_flag_id, entity_type, entity_id, occurred_at, detail)
  select v_tenant, v_flag, 'attendance_record', ar.id, ar.recorded_at,
         jsonb_build_object('status', ar.status, 'session_date', ar.session_date)
    from attendance_records ar
   where ar.student_id = v_sofia and ar.status = 'absent';

  insert into risk_flags (tenant_id, student_id, class_id, rule_id, rule_version, severity,
                          reason_code, reason_text, opened_at)
  values (v_tenant, v_diego, v_class_ing, v_rule_drop, '1', 'medium',
          'level_drop', 'Bajó de A a B en 3 clases', timestamptz '2026-08-11 07:40:00-05')
  returning id into v_flag;

  insert into risk_flag_evidence (tenant_id, risk_flag_id, entity_type, entity_id, occurred_at, detail)
  select v_tenant, v_flag, 'computed_grade', cg.id, cg.computed_at,
         jsonb_build_object('from', 'A', 'to', 'B', 'normalized_value', cg.normalized_value)
    from computed_grades cg
   where cg.student_id = v_diego and cg.class_id = v_class_ing;

  insert into notifications (tenant_id, recipient_teacher_id, kind, category, severity,
                             title, body, student_id, class_id, risk_flag_id, source, dedupe_key, created_at)
  select v_tenant, v_teacher, 'alert', 'level_drop', 'high',
         'Diego Torres bajó de A a B en las últimas 3 clases',
         'Revisa su desempeño reciente en Inglés 5to B.',
         v_diego, v_class_ing, v_flag, 'rule',
         format('level_drop:%s:%s', v_diego, v_class_ing), timestamptz '2026-08-13 09:40:00-05';

  insert into notifications (tenant_id, recipient_teacher_id, kind, category, severity,
                             title, student_id, class_id, risk_flag_id, source, dedupe_key, created_at)
  select v_tenant, v_teacher, 'alert', 'consecutive_absences', 'high',
         'Sofía Ramírez acumula 3 ausencias seguidas',
         v_sofia, v_class_ing, rf.id, 'rule',
         format('consecutive_absences:%s:%s', v_sofia, v_class_ing), timestamptz '2026-08-13 08:00:00-05'
    from risk_flags rf where rf.student_id = v_sofia and rf.rule_id = v_rule_absence;

  insert into notifications (tenant_id, recipient_teacher_id, kind, category, severity,
                             title, class_id, session_id, source, dedupe_key, created_at, expires_at)
  values (v_tenant, v_teacher, 'reminder', 'attendance_unmarked', 'medium',
          'Asistencia sin marcar — Inglés 5to B', v_class_ing, v_sess_0808, 'system',
          format('attendance_unmarked:%s', v_sess_0808),
          timestamptz '2026-08-13 07:00:00-05', timestamptz '2026-08-20 07:00:00-05'),
         (v_tenant, v_teacher, 'reminder', 'grades_pending', 'medium',
          '3 notas pendientes — Inglés 5to B', v_class_ing, v_sess_0801, 'system',
          format('grades_pending:%s', v_sess_0801),
          timestamptz '2026-08-12 10:00:00-05', timestamptz '2026-09-04 23:59:00-05');

  update notifications
     set read_at = timestamptz '2026-08-12 20:00:00-05'
   where tenant_id = v_tenant and category = 'grades_pending';

  perform app.log_event('tenant.seeded', 'tenant', v_tenant,
                        jsonb_build_object('source', 'seed/seed_demo_tenant.sql'));
end
$seed$;
