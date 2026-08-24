-- Demo tenant: one section (5to B) with two classes and their grading setups.
--
--   * Inglés 5to B    — MINEDU qualitative scheme, four skill components at
--                       25% each (Listening, Reading, Writing, Speaking) with
--                       4 / 2 / 2 / 1 published assessments respectively.
--   * Matemática 5to B — vigesimal 0-20 scheme: quizzes 40%, homework 20%,
--                       final exam 40%, with 4 / 2 / 1 published assessments.
--
-- Each class meets twice a week. Sessions are seeded around a "today" of
-- 2026-08-24 (Monday): one week of completed past sessions and three weeks
-- of upcoming scheduled ones (8 sessions per class). No attendance, scores
-- or computed grades are seeded — the dataset is a clean starting point.
--
-- Because RLS is FORCEd on every tenant table, this script sets
-- app.tenant_id before writing anything. That is not a workaround: it is the
-- isolation working as designed, against the script itself.
--
-- Not a goose migration. Apply the schema migrations first, then run this
-- file directly:
--   psql "$DATABASE_URL" -f seed/seed_demo_tenant.sql
-- See seed/README.md for how to record a new school, section, teacher,
-- class, or grading scheme, using this file as the worked example.

do $seed$
declare
  -- Fixed ids so PUBLIC_TENANT_ID / PUBLIC_ACTOR_ID in yanai-ui/.env.local
  -- survive a reseed.
  v_tenant      uuid := '11111111-1111-4111-8111-111111111111';
  v_user        uuid := '22222222-2222-4222-8222-222222222222';

  v_year        uuid;
  v_b1 uuid; v_b2 uuid; v_b3 uuid; v_b4 uuid;
  v_g5          uuid;
  v_membership  uuid;
  v_teacher     uuid;

  v_scale_ord   uuid;  -- AD / A / B / C
  v_scale_vig   uuid;  -- 0 - 20

  v_scheme_eng  uuid;  v_ver_eng_1 uuid;
  v_scheme_mat  uuid;  v_ver_mat_1 uuid;
  v_cmp_listening uuid; v_cmp_reading uuid; v_cmp_writing uuid; v_cmp_speaking uuid;
  v_cmp_quiz uuid; v_cmp_hw uuid; v_cmp_final uuid;

  v_subj_ing uuid; v_subj_mat uuid;
  v_course_ing uuid; v_course_mat uuid;
  v_section uuid;
  v_class_ing uuid; v_class_mat uuid;
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

  -- Bimestre III (27 Jul - 30 Oct) is active and holds every seeded session
  -- and assessment. Bimestre I and II are already closed: status and
  -- closed_at are constrained to agree, so they are set in one statement.
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
  insert into users (id, email, given_name, family_name, display_name, status)
  values (v_user, 'janice.quispe@cristorey.edu.pe', 'Janice', 'Quispe', 'Janice Q', 'active');

  insert into memberships (tenant_id, user_id, role, status, joined_at)
  values (v_tenant, v_user, 'teacher', 'active', timestamptz '2021-03-01 08:00:00-05')
  returning id into v_membership;

  insert into teachers (tenant_id, membership_id, employee_code, display_name, title, hired_on, weekly_hours_contracted)
  values (v_tenant, v_membership, 'DOC-0142', 'Janice Quispe', 'Docente de Secundaria', date '2021-03-01', 30)
  returning id into v_teacher;

  update terms set closed_by_id = v_teacher where id in (v_b1, v_b2);

  -- =========================================================================
  -- Grade scales
  --
  -- Both scales carry the same numeric envelope (0-20, passing at 11) and the
  -- same normalised band edges: 11/20 = 0.55, 14/20 = 0.70, 18/20 = 0.90. They
  -- differ only in `kind`, which decides whether a result is reported as a
  -- letter or as a number.
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

  insert into grade_scale_levels (tenant_id, scale_id, code, label, short_label, ordinal, min_normalized, max_normalized, is_passing, color_key)
  values (v_tenant, v_scale_vig, '00-10', 'Desaprobado',   'C',  1, 0.00000, 0.55000, false, 'tier-c'),
         (v_tenant, v_scale_vig, '11-13', 'En proceso',    'B',  2, 0.55000, 0.70000, true,  'warning'),
         (v_tenant, v_scale_vig, '14-17', 'Logro esperado','A',  3, 0.70000, 0.90000, true,  'success'),
         (v_tenant, v_scale_vig, '18-20', 'Logro destacado','AD',4, 0.90000, 1.00000, true,  'accent');

  -- =========================================================================
  -- Scheme 1: English, four skill modules at 25% each. Each skill is a
  -- component whose grade is the mean of its assessments.
  -- =========================================================================
  insert into grading_schemes (tenant_id, scale_id, code, name, description)
  values (v_tenant, v_scale_ord, 'ingles_4_destrezas', 'Evaluación de inglés por destrezas',
          'Cuatro destrezas a 25% cada una: Listening, Reading, Writing, Speaking.')
  returning id into v_scheme_eng;

  insert into grading_components (tenant_id, scheme_id, code, name, sort_order)
  values (v_tenant, v_scheme_eng, 'listening', 'Listening', 1),
         (v_tenant, v_scheme_eng, 'reading',   'Reading',   2),
         (v_tenant, v_scheme_eng, 'writing',   'Writing',   3),
         (v_tenant, v_scheme_eng, 'speaking',  'Speaking',  4);

  select id into v_cmp_listening from grading_components where scheme_id = v_scheme_eng and code = 'listening';
  select id into v_cmp_reading   from grading_components where scheme_id = v_scheme_eng and code = 'reading';
  select id into v_cmp_writing   from grading_components where scheme_id = v_scheme_eng and code = 'writing';
  select id into v_cmp_speaking  from grading_components where scheme_id = v_scheme_eng and code = 'speaking';

  insert into grading_scheme_versions (tenant_id, scheme_id, version, effective_from,
                                       rounding_mode, absent_counts_as, retake_policy, notes)
  values (v_tenant, v_scheme_eng, 1, date '2026-03-02', 'half_up', 'zero', 'best',
          'Versión inicial 2026. Cuatro destrezas a 25% cada una, cada una promediando sus evaluaciones.')
  returning id into v_ver_eng_1;

  insert into grading_scheme_component_weights (tenant_id, scheme_version_id, component_id, weight, aggregation, drop_lowest_n)
  values (v_tenant, v_ver_eng_1, v_cmp_listening, 0.250000, 'mean', 0),
         (v_tenant, v_ver_eng_1, v_cmp_reading,   0.250000, 'mean', 0),
         (v_tenant, v_ver_eng_1, v_cmp_writing,   0.250000, 'mean', 0),
         (v_tenant, v_ver_eng_1, v_cmp_speaking,  0.250000, 'mean', 0);

  update grading_scheme_versions
     set published_at = timestamptz '2026-02-20 09:00:00-05', published_by_id = v_teacher
   where id = v_ver_eng_1;

  -- =========================================================================
  -- Scheme 2: Math, vigesimal 0-20. Quizzes 40%, homework 20%, final 40%.
  -- =========================================================================
  insert into grading_schemes (tenant_id, scale_id, code, name, description)
  values (v_tenant, v_scale_vig, 'matematica_estandar', 'Evaluación vigesimal de matemática',
          'Quizzes 40%, tareas 20%, examen final 40%.')
  returning id into v_scheme_mat;

  insert into grading_components (tenant_id, scheme_id, code, name, sort_order)
  values (v_tenant, v_scheme_mat, 'quizzes',    'Quizzes',      1),
         (v_tenant, v_scheme_mat, 'homework',   'Tareas',       2),
         (v_tenant, v_scheme_mat, 'final_exam', 'Examen final', 3);

  select id into v_cmp_quiz  from grading_components where scheme_id = v_scheme_mat and code = 'quizzes';
  select id into v_cmp_hw    from grading_components where scheme_id = v_scheme_mat and code = 'homework';
  select id into v_cmp_final from grading_components where scheme_id = v_scheme_mat and code = 'final_exam';

  insert into grading_scheme_versions (tenant_id, scheme_id, version, effective_from,
                                       rounding_mode, rounding_decimals, absent_counts_as, retake_policy)
  values (v_tenant, v_scheme_mat, 1, date '2026-03-02', 'half_up', 0, 'zero', 'best')
  returning id into v_ver_mat_1;

  insert into grading_scheme_component_weights (tenant_id, scheme_version_id, component_id, weight, aggregation, drop_lowest_n)
  values (v_tenant, v_ver_mat_1, v_cmp_quiz,  0.400000, 'mean', 0),
         (v_tenant, v_ver_mat_1, v_cmp_hw,    0.200000, 'mean', 0),
         (v_tenant, v_ver_mat_1, v_cmp_final, 0.400000, 'mean', 0);

  update grading_scheme_versions
     set published_at = timestamptz '2026-02-20 09:00:00-05', published_by_id = v_teacher
   where id = v_ver_mat_1;

  -- English is the school default; Matemática overrides at course level below.
  update tenants set default_grading_scheme_id = v_scheme_eng where id = v_tenant;

  -- =========================================================================
  -- Curriculum
  -- =========================================================================
  insert into subjects (tenant_id, code, name, area_curricular, icon_key, is_tutoria, sort_order)
  values (v_tenant, 'ING', 'Inglés',     'Inglés como lengua extranjera', 'book',       false, 1),
         (v_tenant, 'MAT', 'Matemática', 'Matemática',                    'calculator', false, 2);

  select id into v_subj_ing from subjects where tenant_id = v_tenant and code = 'ING';
  select id into v_subj_mat from subjects where tenant_id = v_tenant and code = 'MAT';

  insert into courses (tenant_id, academic_year_id, subject_id, grade_level_id, name, code, weekly_hours, grading_scheme_id)
  values (v_tenant, v_year, v_subj_ing, v_g5, 'Inglés 5to', 'ING-5', 2, v_scheme_eng)
  returning id into v_course_ing;

  insert into courses (tenant_id, academic_year_id, subject_id, grade_level_id, name, code, weekly_hours, grading_scheme_id)
  values (v_tenant, v_year, v_subj_mat, v_g5, 'Matemática 5to', 'MAT-5', 2, v_scheme_mat)
  returning id into v_course_mat;

  -- =========================================================================
  -- Section, classes, weekly pattern (2 sessions per week each)
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

  -- Inglés: Mon + Thu. Matemática: Tue + Fri. Weekday 1 = Monday (ISO).
  insert into class_schedules (tenant_id, class_id, weekday, starts_at, ends_at, room, effective_from)
  values (v_tenant, v_class_ing, 1, time '10:00', time '11:00', 'Aula 12', date '2026-03-02'),
         (v_tenant, v_class_ing, 4, time '10:00', time '11:00', 'Aula 12', date '2026-03-02'),
         (v_tenant, v_class_mat, 2, time '10:00', time '11:00', 'Aula 12', date '2026-03-02'),
         (v_tenant, v_class_mat, 5, time '10:00', time '11:00', 'Aula 12', date '2026-03-02');

  -- =========================================================================
  -- Students: 10 enrolled in 5to B.
  -- =========================================================================
  insert into students (tenant_id, student_code, given_name, paternal_surname, maternal_surname, birthdate, sex, document_type, document_number, enrolled_on)
  values (v_tenant, 'EST-2026-001', 'Agustín',   'Soto',    'Ramos',    date '2010-04-12', 'M', 'DNI', '70123001', date '2026-03-02'),
         (v_tenant, 'EST-2026-002', 'Alonso',    'Guzmán',  'Ríos',     date '2010-02-28', 'M', 'DNI', '70123002', date '2026-03-02'),
         (v_tenant, 'EST-2026-003', 'Amanda',    'Vidal',   'Loayza',   date '2010-07-03', 'F', 'DNI', '70123003', date '2026-03-02'),
         (v_tenant, 'EST-2026-004', 'Ana',       'Morales', 'Sierra',   date '2010-11-19', 'F', 'DNI', '70123004', date '2026-03-02'),
         (v_tenant, 'EST-2026-005', 'Sofía',     'Ramírez', 'Ponce',    date '2010-06-08', 'F', 'DNI', '70123005', date '2026-03-02'),
         (v_tenant, 'EST-2026-006', 'Diego',     'Torres',  'Aguilar',  date '2010-09-25', 'M', 'DNI', '70123006', date '2026-03-02'),
         (v_tenant, 'EST-2026-007', 'Lucía',     'Huamán',  'Quispe',   date '2010-01-14', 'F', 'DNI', '70123007', date '2026-03-02'),
         (v_tenant, 'EST-2026-008', 'Mateo',     'Flores',  'Chávez',   date '2010-05-30', 'M', 'DNI', '70123008', date '2026-03-02'),
         (v_tenant, 'EST-2026-009', 'Valentina', 'Rojas',   'Zapata',   date '2010-08-21', 'F', 'DNI', '70123009', date '2026-03-02'),
         (v_tenant, 'EST-2026-010', 'Sebastián', 'Salazar', 'Paredes',  date '2010-12-02', 'M', 'DNI', '70123010', date '2026-03-02');

  insert into section_memberships (tenant_id, student_id, section_id, academic_year_id, joined_on)
  select v_tenant, s.id, v_section, v_year, date '2026-03-02'
    from students s where s.tenant_id = v_tenant;

  -- =========================================================================
  -- Sessions. "Today" is Monday 2026-08-24: the week of 17 Aug is done
  -- (completed), the weeks of 24/31 Aug and 7 Sep are upcoming (scheduled).
  -- schedule_id is resolved by weekday. status and actual_start_at are
  -- constrained to agree, so completed sessions are inserted complete.
  -- =========================================================================
  insert into class_sessions (tenant_id, class_id, schedule_id, term_id, session_date,
                              scheduled_start_at, scheduled_end_at, status, topic, room,
                              actual_start_at, actual_end_at, started_by_id)
  select v_tenant, d.class_id,
         (select cs.id from class_schedules cs
           where cs.class_id = d.class_id and cs.weekday = extract(isodow from d.day)::smallint limit 1),
         v_b3, d.day,
         (d.day + time '10:00') at time zone 'America/Lima',
         (d.day + time '11:00') at time zone 'America/Lima',
         d.status, d.topic, 'Aula 12',
         case when d.status = 'completed' then (d.day + time '10:00') at time zone 'America/Lima' end,
         case when d.status = 'completed' then (d.day + time '11:00') at time zone 'America/Lima' end,
         case when d.status = 'completed' then v_teacher end
    from (values
            -- Inglés: Mon + Thu
            (v_class_ing, date '2026-08-17', 'completed', 'Present perfect: introducción'),
            (v_class_ing, date '2026-08-20', 'completed', 'Listening: daily routines'),
            (v_class_ing, date '2026-08-24', 'scheduled', 'Reading: short stories'),
            (v_class_ing, date '2026-08-27', 'scheduled', 'Listening: interviews'),
            (v_class_ing, date '2026-08-31', 'scheduled', 'Writing: informal emails'),
            (v_class_ing, date '2026-09-03', 'scheduled', 'Grammar review'),
            (v_class_ing, date '2026-09-07', 'scheduled', 'Speaking: role play'),
            (v_class_ing, date '2026-09-10', 'scheduled', 'Reading comprehension'),
            -- Matemática: Tue + Fri
            (v_class_mat, date '2026-08-18', 'completed', 'Ecuaciones lineales'),
            (v_class_mat, date '2026-08-21', 'completed', 'Sistemas de ecuaciones'),
            (v_class_mat, date '2026-08-25', 'scheduled', 'Inecuaciones'),
            (v_class_mat, date '2026-08-28', 'scheduled', 'Funciones lineales'),
            (v_class_mat, date '2026-09-01', 'scheduled', 'Funciones cuadráticas'),
            (v_class_mat, date '2026-09-04', 'scheduled', 'Repaso: funciones'),
            (v_class_mat, date '2026-09-08', 'scheduled', 'Geometría analítica'),
            (v_class_mat, date '2026-09-11', 'scheduled', 'Repaso general')
         ) as d(class_id, day, status, topic);

  -- =========================================================================
  -- Assessments, all published, none scored yet.
  -- Inglés: 4 listening, 2 reading, 2 writing, 1 speaking.
  -- =========================================================================
  insert into assessments (tenant_id, class_id, term_id, scheme_id, component_id,
                           title, kind, max_score, due_at, status, published_at, created_by_id)
  values (v_tenant, v_class_ing, v_b3, v_scheme_eng, v_cmp_listening,
          'Listening 1', 'quiz', 20, timestamptz '2026-08-27 11:00:00-05',
          'published', timestamptz '2026-08-17 08:00:00-05', v_teacher),
         (v_tenant, v_class_ing, v_b3, v_scheme_eng, v_cmp_listening,
          'Listening 2', 'quiz', 20, timestamptz '2026-09-10 11:00:00-05',
          'published', timestamptz '2026-08-17 08:00:00-05', v_teacher),
         (v_tenant, v_class_ing, v_b3, v_scheme_eng, v_cmp_listening,
          'Listening 3', 'quiz', 20, timestamptz '2026-09-24 11:00:00-05',
          'published', timestamptz '2026-08-17 08:00:00-05', v_teacher),
         (v_tenant, v_class_ing, v_b3, v_scheme_eng, v_cmp_listening,
          'Listening 4', 'quiz', 20, timestamptz '2026-10-15 11:00:00-05',
          'published', timestamptz '2026-08-17 08:00:00-05', v_teacher),
         (v_tenant, v_class_ing, v_b3, v_scheme_eng, v_cmp_reading,
          'Reading 1', 'practica', 20, timestamptz '2026-09-03 11:00:00-05',
          'published', timestamptz '2026-08-17 08:00:00-05', v_teacher),
         (v_tenant, v_class_ing, v_b3, v_scheme_eng, v_cmp_reading,
          'Reading 2', 'practica', 20, timestamptz '2026-10-01 11:00:00-05',
          'published', timestamptz '2026-08-17 08:00:00-05', v_teacher),
         (v_tenant, v_class_ing, v_b3, v_scheme_eng, v_cmp_writing,
          'Writing 1', 'practica', 20, timestamptz '2026-09-17 11:00:00-05',
          'published', timestamptz '2026-08-17 08:00:00-05', v_teacher),
         (v_tenant, v_class_ing, v_b3, v_scheme_eng, v_cmp_writing,
          'Writing 2', 'practica', 20, timestamptz '2026-10-08 11:00:00-05',
          'published', timestamptz '2026-08-17 08:00:00-05', v_teacher),
         (v_tenant, v_class_ing, v_b3, v_scheme_eng, v_cmp_speaking,
          'Speaking 1', 'exposicion', 20, timestamptz '2026-10-22 11:00:00-05',
          'published', timestamptz '2026-08-17 08:00:00-05', v_teacher);

  -- Matemática: 4 quizzes, 2 tareas, 1 examen final.
  insert into assessments (tenant_id, class_id, term_id, scheme_id, component_id,
                           title, kind, max_score, due_at, status, published_at, created_by_id)
  values (v_tenant, v_class_mat, v_b3, v_scheme_mat, v_cmp_quiz,
          'Quiz 1', 'quiz', 20, timestamptz '2026-08-28 11:00:00-05',
          'published', timestamptz '2026-08-17 08:00:00-05', v_teacher),
         (v_tenant, v_class_mat, v_b3, v_scheme_mat, v_cmp_quiz,
          'Quiz 2', 'quiz', 20, timestamptz '2026-09-11 11:00:00-05',
          'published', timestamptz '2026-08-17 08:00:00-05', v_teacher),
         (v_tenant, v_class_mat, v_b3, v_scheme_mat, v_cmp_quiz,
          'Quiz 3', 'quiz', 20, timestamptz '2026-09-25 11:00:00-05',
          'published', timestamptz '2026-08-17 08:00:00-05', v_teacher),
         (v_tenant, v_class_mat, v_b3, v_scheme_mat, v_cmp_quiz,
          'Quiz 4', 'quiz', 20, timestamptz '2026-10-09 11:00:00-05',
          'published', timestamptz '2026-08-17 08:00:00-05', v_teacher),
         (v_tenant, v_class_mat, v_b3, v_scheme_mat, v_cmp_hw,
          'Tarea 1', 'tarea', 20, timestamptz '2026-09-04 11:00:00-05',
          'published', timestamptz '2026-08-17 08:00:00-05', v_teacher),
         (v_tenant, v_class_mat, v_b3, v_scheme_mat, v_cmp_hw,
          'Tarea 2', 'tarea', 20, timestamptz '2026-10-02 11:00:00-05',
          'published', timestamptz '2026-08-17 08:00:00-05', v_teacher),
         (v_tenant, v_class_mat, v_b3, v_scheme_mat, v_cmp_final,
          'Examen final', 'examen', 20, timestamptz '2026-10-23 11:00:00-05',
          'published', timestamptz '2026-08-17 08:00:00-05', v_teacher);

  perform app.log_event('tenant.seeded', 'tenant', v_tenant,
                        jsonb_build_object('source', 'seed/seed_demo_tenant.sql'));
end
$seed$;
