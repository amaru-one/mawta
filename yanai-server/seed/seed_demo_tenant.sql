-- Demo tenant: full worked example, in one file.
--
-- Not a goose migration. Apply the schema migrations first, then run this
-- file directly:
--   psql "$DATABASE_URL" -f seed/seed_demo_tenant.sql
-- See README.md for the local/VPS apply commands and the dry-run/undo
-- pattern. See SPEC.md for the insert shapes and how to onboard a real
-- school using this file as the worked example.
--
-- Two independent `do $$ ... end $$;` blocks, applied in this order because
-- the second looks up rows only the first creates (tenant, academic year,
-- terms, grade levels, the teacher), guarded with `raise exception` if
-- missing. Kept as separate blocks rather than merged into one shared
-- declare section: several variable names (v_class, v_course, v_section,
-- v_scheme, ...) are reused across blocks for different entities, which
-- would collide in a single declare.
--
-- Not idempotent: each block relies on a unique index to reject a second run
-- (tenants_modular_code_key for the base tenant, subjects_tenant_code_key
-- for Arte). Re-applying means resetting the database, not re-running the
-- file. Because RLS is FORCEd on every tenant table, every block sets
-- app.tenant_id itself before writing anything — not a workaround, the
-- isolation working as designed against the script itself.
--
-- 1. Base tenant — one section (5to B), one class: Matemática 5to B
--    (vigesimal 0-20, quizzes 40% / tareas 20% / examen final 40%). The CNEB
--    competencias for Matemática (4) plus the two competencias
--    transversales, each broken down into its capacidades
--    (`capabilities`). The competencia in play this bimestre — MAT-C2,
--    regularidad/equivalencia/cambio — also gets its desempeños
--    (`performance_standards`, grade 5) and the teacher's own criterios de
--    evaluación (`evaluation_criteria`) precising them. `Quiz 0` — already
--    taken and scored on the numeric scale (`scores`) and tagged with the
--    criterios it was read against (`assessment_criteria`) — is the
--    "already recording" half of the scenario; Quizzes 1-4 stay
--    published and unscored, the "still planned" half. Students
--    EST-2026-001..010. Sessions seeded around a "today" of 2026-08-24
--    (Monday): one week completed, three weeks scheduled. Also the two grade
--    scales: minedu_ad_a_b_c, which the official niveles de logro are
--    recorded on, and vigesimal_0_20 for the school's
--    own optional internal weighted system — never the official CNEB record.
-- 2. Arte 3ro A — a second subject, with the two CNEB Arte y Cultura
--    competencias modelled properly (not just as grading_components): real
--    `competencies` rows, their 6 capacidades, one desempeño per capacidad
--    at grade 3, and one criterio de evaluación per desempeño, each linked
--    to the rubrica assessment that evidences it via `assessment_criteria`.
--    Students EST-2026-011..020. 6 published-but-unscored rúbricas — the
--    register is set up, not filled in.
--
-- Fixed ids baked into bruno/yanai-api.yaml, the deployed SPA build, and the
-- server README — keep stable across reseeds:
--   tenant 11111111-1111-4111-8111-111111111111
--   actor  22222222-2222-4222-8222-222222222222 (Janice Quispe's user)

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

  v_scheme_mat  uuid;  v_ver_mat_1 uuid;
  v_cmp_quiz uuid; v_cmp_hw uuid; v_cmp_final uuid;

  v_subj_mat uuid;
  v_mc1 uuid; v_mc2 uuid; v_mc3 uuid; v_mc4 uuid;  -- MAT-C1..C4 competency ids

  v_cap1 uuid; v_cap2 uuid; v_cap3 uuid; v_cap4 uuid;  -- MAT-C2's 4 capacidades
  v_ps1  uuid; v_ps2  uuid; v_ps3  uuid; v_ps4  uuid;  -- their desempeños, grade 5
  v_crit1 uuid; v_crit2 uuid; v_crit3 uuid;            -- criterios precisados

  v_course_mat uuid;
  v_section uuid;
  v_class_mat uuid;
  v_quiz0 uuid;

  v_s1 uuid; v_s2 uuid; v_s3 uuid; v_s4 uuid; v_s5 uuid;
  v_s6 uuid; v_s7 uuid; v_s8 uuid; v_s9 uuid; v_s10 uuid;
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

  -- The full 1ro-5to catalog is kept even though only grade 5 has a class in
  -- this file: Arte 3ro A (added below) needs grade 3 from the same catalog,
  -- and a real school's grade_levels table is not scoped to "grades with a
  -- class today".
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
  -- These two are NOT the same scale wearing different clothes, and the seed
  -- used to say they were ("differ only in `kind`", both 0-20 passing at 11).
  -- That equivalence — C 0-10, B 11-13, A 14-17, AD 18-20 — is Anexo 07 of
  -- RVM 094-2020, the transitional annex that applied to the 2020 school year
  -- and expired when transitoria 8.3 extended the literal scale to all of
  -- Secundaria on 1 March 2021. No current norm maps AD/A/B/C onto a mark.
  --
  --   minedu_ad_a_b_c  the CNEB niveles de logro. Ordinal, and deliberately
  --                    NOT vigesimal: its envelope is 1-4, the numbers the
  --                    norm itself assigns when it has to convert (C=1,
  --                    B=2.5, A=3, AD=4 — Anexo 09, RVM 048-2024). It has no
  --                    passing_value, because "aprobado" is not a property of
  --                    a level: an área is approved only if it meets the
  --                    conditions in the cuadro of 5.1.3, which depend on the
  --                    grade. B suffices in 1.deg/3.deg/4.deg and does not in
  --                    2.deg/5.deg. internal/promotion decides that; nothing
  --                    reads a cutoff.
  --
  --   vigesimal_0_20   a genuine numeric scale with a genuine cutoff. Legitimate
  --                    for the school's own internal system (D.S. 009-2006-ED
  --                    art. 37.4.f lets a private IE set "los sistemas de
  --                    evaluación y control de las/los estudiantes") and for
  --                    pre-2020 historical records. It must never be the
  --                    official record of a competencia.
  --
  -- The band edges on the ordinal scale survive only as the heuristic that
  -- turns a weighted score into a *suggested* level for the teacher to accept
  -- or override. They carry no normative weight and nothing may write an
  -- official level from them alone.
  -- =========================================================================
  insert into grade_scales (tenant_id, code, name, kind, min_value, max_value, passing_value, decimals)
  values (v_tenant, 'minedu_ad_a_b_c', 'Niveles de logro MINEDU (AD/A/B/C)', 'ordinal', 1, 4, null, 0)
  returning id into v_scale_ord;

  insert into grade_scales (tenant_id, code, name, kind, min_value, max_value, passing_value, decimals)
  values (v_tenant, 'vigesimal_0_20', 'Escala vigesimal 0-20 (sistema interno de la IE)', 'numeric', 0, 20, 11, 0)
  returning id into v_scale_vig;

  -- is_passing is false throughout here: the column does not apply to this
  -- scale, and a true anywhere would be a claim the norm does not make. It is
  -- advisory only and no code reads it.
  insert into grade_scale_levels (tenant_id, scale_id, code, label, short_label, ordinal, min_normalized, max_normalized, is_passing, color_key)
  values (v_tenant, v_scale_ord, 'C',  'En inicio',        'C',  1, 0.00000, 0.55000, false, 'tier-c'),
         (v_tenant, v_scale_ord, 'B',  'En proceso',       'B',  2, 0.55000, 0.70000, false, 'warning'),
         (v_tenant, v_scale_ord, 'A',  'Logro esperado',   'A',  3, 0.70000, 0.90000, false, 'success'),
         (v_tenant, v_scale_ord, 'AD', 'Logro destacado',  'AD', 4, 0.90000, 1.00000, false, 'accent');

  insert into grade_scale_levels (tenant_id, scale_id, code, label, short_label, ordinal, min_normalized, max_normalized, is_passing, color_key)
  values (v_tenant, v_scale_vig, '00-10', 'Desaprobado',   'C',  1, 0.00000, 0.55000, false, 'tier-c'),
         (v_tenant, v_scale_vig, '11-13', 'En proceso',    'B',  2, 0.55000, 0.70000, true,  'warning'),
         (v_tenant, v_scale_vig, '14-17', 'Logro esperado','A',  3, 0.70000, 0.90000, true,  'success'),
         (v_tenant, v_scale_vig, '18-20', 'Logro destacado','AD',4, 0.90000, 1.00000, true,  'accent');

  -- =========================================================================
  -- Scheme: Math, vigesimal 0-20. Quizzes 40%, homework 20%, final 40%.
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

  -- Matemática is the tenant's only subject with a scheme, so it is also the
  -- default; Arte overrides at course level below, as it did before.
  update tenants set default_grading_scheme_id = v_scheme_mat where id = v_tenant;

  -- =========================================================================
  -- Curriculum
  -- =========================================================================
  insert into subjects (tenant_id, code, name, area_curricular, icon_key, is_tutoria, sort_order)
  values (v_tenant, 'MAT', 'Matemática', 'Matemática', 'calculator', false, 1);

  select id into v_subj_mat from subjects where tenant_id = v_tenant and code = 'MAT';

  -- =========================================================================
  -- Competencias del CNEB
  --
  -- The unit RVM 094-2020 actually regulates: a nivel de logro is asserted per
  -- competencia per periodo, never per área ("no se asignará un nivel de logro
  -- a cada área curricular", 5.1.1.3 p.12).
  --
  -- `kind` decides what counts towards promotion (5.1.3 p.9-11): 'area'
  -- counts, 'transversal' never does. The two transversales carry no
  -- subject_id — they are adscribed to no área and to no single teacher
  -- (5.1.1.3 p.8), and each IE decides how their level is assigned.
  -- =========================================================================
  insert into competencies (tenant_id, subject_id, code, name, kind, sort_order)
  values
    (v_tenant, v_subj_mat, 'MAT-C1', 'Resuelve problemas de cantidad', 'area', 1),
    (v_tenant, v_subj_mat, 'MAT-C2', 'Resuelve problemas de regularidad, equivalencia y cambio', 'area', 2),
    (v_tenant, v_subj_mat, 'MAT-C3', 'Resuelve problemas de forma, movimiento y localización', 'area', 3),
    (v_tenant, v_subj_mat, 'MAT-C4', 'Resuelve problemas de gestión de datos e incertidumbre', 'area', 4);

  insert into competencies (tenant_id, subject_id, code, name, kind, sort_order)
  values
    (v_tenant, null, 'TRANS-TIC', 'Se desenvuelve en los entornos virtuales generados por las TIC', 'transversal', 1),
    (v_tenant, null, 'TRANS-AUT', 'Gestiona su aprendizaje de manera autónoma', 'transversal', 2);

  select id into v_mc1 from competencies where tenant_id = v_tenant and code = 'MAT-C1';
  select id into v_mc2 from competencies where tenant_id = v_tenant and code = 'MAT-C2';
  select id into v_mc3 from competencies where tenant_id = v_tenant and code = 'MAT-C3';
  select id into v_mc4 from competencies where tenant_id = v_tenant and code = 'MAT-C4';

  -- =========================================================================
  -- Capacidades: the CNEB's fixed sub-skills of each competencia. Seeded for
  -- all four Matemática competencias, not just the one in play this bimestre,
  -- so the subject's capacidad catalog is complete rather than partial — a
  -- school loading its own copy of the national list loads it up front.
  -- =========================================================================
  insert into capabilities (tenant_id, competency_id, code, name, sort_order)
  values
    (v_tenant, v_mc1, 'CAP1', 'Traduce cantidades a expresiones numéricas', 1),
    (v_tenant, v_mc1, 'CAP2', 'Comunica su comprensión sobre los números y las operaciones', 2),
    (v_tenant, v_mc1, 'CAP3', 'Usa estrategias y procedimientos de estimación y cálculo', 3),
    (v_tenant, v_mc1, 'CAP4', 'Argumenta afirmaciones sobre las relaciones numéricas y las operaciones', 4),

    (v_tenant, v_mc2, 'CAP1', 'Traduce datos y condiciones a expresiones algebraicas', 1),
    (v_tenant, v_mc2, 'CAP2', 'Comunica su comprensión sobre las relaciones algebraicas', 2),
    (v_tenant, v_mc2, 'CAP3', 'Usa estrategias y procedimientos para encontrar equivalencias y reglas generales', 3),
    (v_tenant, v_mc2, 'CAP4', 'Argumenta afirmaciones sobre relaciones de cambio y equivalencia', 4),

    (v_tenant, v_mc3, 'CAP1', 'Modela objetos con formas geométricas y sus transformaciones', 1),
    (v_tenant, v_mc3, 'CAP2', 'Comunica su comprensión sobre las formas y relaciones geométricas', 2),
    (v_tenant, v_mc3, 'CAP3', 'Usa estrategias y procedimientos para medir y orientarse en el espacio', 3),
    (v_tenant, v_mc3, 'CAP4', 'Argumenta afirmaciones sobre relaciones geométricas', 4),

    (v_tenant, v_mc4, 'CAP1', 'Representa datos con gráficos y medidas estadísticas o probabilísticas', 1),
    (v_tenant, v_mc4, 'CAP2', 'Comunica la comprensión de los conceptos estadísticos y probabilísticos', 2),
    (v_tenant, v_mc4, 'CAP3', 'Usa estrategias y procedimientos para recopilar y procesar datos', 3),
    (v_tenant, v_mc4, 'CAP4', 'Argumenta afirmaciones sobre relaciones probabilísticas y estadísticas', 4);

  select id into v_cap1 from capabilities where tenant_id = v_tenant and competency_id = v_mc2 and code = 'CAP1';
  select id into v_cap2 from capabilities where tenant_id = v_tenant and competency_id = v_mc2 and code = 'CAP2';
  select id into v_cap3 from capabilities where tenant_id = v_tenant and competency_id = v_mc2 and code = 'CAP3';
  select id into v_cap4 from capabilities where tenant_id = v_tenant and competency_id = v_mc2 and code = 'CAP4';

  -- =========================================================================
  -- Desempeños (grade 5) for MAT-C2 only — the strand actually in play this
  -- bimestre (Bimestre III's syllabus is algebra: ecuaciones, sistemas,
  -- inecuaciones, funciones). The other three competencias' capacidades are
  -- left with no desempeño row yet: a school loads desempeños grade by grade
  -- as it gets to them, and evaluation_criteria.performance_standard_id is
  -- nullable for exactly this reason.
  -- =========================================================================
  insert into performance_standards (tenant_id, capability_id, grade_level_id, code, description)
  values
    (v_tenant, v_cap1, v_g5, 'G5', 'Establece relaciones entre datos y condiciones de equivalencia, cambio y aproximación, y las expresa en un modelo referido a sistemas de ecuaciones lineales, ecuaciones cuadráticas o funciones.'),
    (v_tenant, v_cap2, v_g5, 'G5', 'Expresa su comprensión sobre las relaciones entre magnitudes proporcionales o entre progresiones, usando lenguaje algebraico y diversas representaciones.'),
    (v_tenant, v_cap3, v_g5, 'G5', 'Selecciona y emplea estrategias de cálculo y procedimientos para reducir sistemas de ecuaciones lineales, resolver ecuaciones cuadráticas o determinar la regla de formación de una progresión.'),
    (v_tenant, v_cap4, v_g5, 'G5', 'Plantea afirmaciones sobre relaciones de cambio y equivalencia identificadas en una situación, y las justifica con propiedades y su experiencia.');

  select id into v_ps1 from performance_standards where tenant_id = v_tenant and capability_id = v_cap1 and grade_level_id = v_g5;
  select id into v_ps2 from performance_standards where tenant_id = v_tenant and capability_id = v_cap2 and grade_level_id = v_g5;
  select id into v_ps3 from performance_standards where tenant_id = v_tenant and capability_id = v_cap3 and grade_level_id = v_g5;
  select id into v_ps4 from performance_standards where tenant_id = v_tenant and capability_id = v_cap4 and grade_level_id = v_g5;

  -- =========================================================================
  -- Criterios de evaluación: what Janice actually wrote and shared, precising
  -- three of the four desempeños above for the "Ecuaciones lineales" /
  -- "Sistemas de ecuaciones" stretch of the syllabus. `Quiz 0` below is
  -- evaluated against exactly these three.
  -- =========================================================================
  insert into evaluation_criteria (tenant_id, competency_id, performance_standard_id, code, description, sort_order)
  values
    (v_tenant, v_mc2, v_ps1, 'CRIT1', 'Traduce un problema verbal que involucra dos incógnitas a un sistema de dos ecuaciones lineales.', 1),
    (v_tenant, v_mc2, v_ps3, 'CRIT2', 'Emplea el método de reducción o sustitución para resolver un sistema de dos ecuaciones lineales con una única solución.', 2),
    (v_tenant, v_mc2, v_ps4, 'CRIT3', 'Verifica la solución de un sistema de ecuaciones lineales reemplazándola en las ecuaciones originales y justifica su validez.', 3);

  select id into v_crit1 from evaluation_criteria where tenant_id = v_tenant and competency_id = v_mc2 and code = 'CRIT1';
  select id into v_crit2 from evaluation_criteria where tenant_id = v_tenant and competency_id = v_mc2 and code = 'CRIT2';
  select id into v_crit3 from evaluation_criteria where tenant_id = v_tenant and competency_id = v_mc2 and code = 'CRIT3';

  insert into courses (tenant_id, academic_year_id, subject_id, grade_level_id, name, code, weekly_hours, grading_scheme_id)
  values (v_tenant, v_year, v_subj_mat, v_g5, 'Matemática 5to', 'MAT-5', 2, v_scheme_mat)
  returning id into v_course_mat;

  -- =========================================================================
  -- Section, class, weekly pattern (2 sessions per week)
  -- =========================================================================
  insert into sections (tenant_id, academic_year_id, grade_level_id, label, name, tutor_teacher_id, shift, capacity)
  values (v_tenant, v_year, v_g5, 'B', '5to B', v_teacher, 'manana', 32)
  returning id into v_section;

  insert into classes (tenant_id, academic_year_id, course_id, section_id, name, code, default_room)
  values (v_tenant, v_year, v_course_mat, v_section, 'Matemática 5to B', 'MAT-5B', 'Aula 12')
  returning id into v_class_mat;

  insert into class_teachers (tenant_id, class_id, teacher_id, role, starts_on)
  values (v_tenant, v_class_mat, v_teacher, 'titular', date '2026-03-02');

  -- Weekday 1 = Monday (ISO). Tue + Fri.
  insert into class_schedules (tenant_id, class_id, weekday, starts_at, ends_at, room, effective_from)
  values (v_tenant, v_class_mat, 2, time '10:00', time '11:00', 'Aula 12', date '2026-03-02'),
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

  select id into v_s1  from students where tenant_id = v_tenant and student_code = 'EST-2026-001';
  select id into v_s2  from students where tenant_id = v_tenant and student_code = 'EST-2026-002';
  select id into v_s3  from students where tenant_id = v_tenant and student_code = 'EST-2026-003';
  select id into v_s4  from students where tenant_id = v_tenant and student_code = 'EST-2026-004';
  select id into v_s5  from students where tenant_id = v_tenant and student_code = 'EST-2026-005';
  select id into v_s6  from students where tenant_id = v_tenant and student_code = 'EST-2026-006';
  select id into v_s7  from students where tenant_id = v_tenant and student_code = 'EST-2026-007';
  select id into v_s8  from students where tenant_id = v_tenant and student_code = 'EST-2026-008';
  select id into v_s9  from students where tenant_id = v_tenant and student_code = 'EST-2026-009';
  select id into v_s10 from students where tenant_id = v_tenant and student_code = 'EST-2026-010';

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
  -- Assessments. Quiz 0 was already taken and graded, right after the
  -- "Ecuaciones lineales" session; Quizzes 1-4, the two tareas and the exam
  -- are published and still ahead — the "still planned" half of the
  -- scenario.
  -- =========================================================================
  insert into assessments (tenant_id, class_id, term_id, scheme_id, component_id,
                           title, kind, max_score, due_at, status, published_at, created_by_id)
  values (v_tenant, v_class_mat, v_b3, v_scheme_mat, v_cmp_quiz,
          'Quiz 0', 'quiz', 20, timestamptz '2026-08-19 11:00:00-05',
          'published', timestamptz '2026-08-17 08:00:00-05', v_teacher)
  returning id into v_quiz0;

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

  -- Which criterios Quiz 0 evidences.
  insert into assessment_criteria (tenant_id, assessment_id, criterion_id)
  values (v_tenant, v_quiz0, v_crit1),
         (v_tenant, v_quiz0, v_crit2),
         (v_tenant, v_quiz0, v_crit3);

  -- =========================================================================
  -- Quiz 0 scores: a realistic spread, one late submission apiece for two
  -- students, and Diego not submitting at all.
  -- =========================================================================
  insert into scores (tenant_id, assessment_id, student_id, max_value, raw_value, status, late_days, recorded_by_id, recorded_at)
  values (v_tenant, v_quiz0, v_s1,  20, 15, 'graded', 0, v_teacher, timestamptz '2026-08-20 09:00:00-05'),
         (v_tenant, v_quiz0, v_s2,  20, 12, 'graded', 1, v_teacher, timestamptz '2026-08-20 09:00:00-05'),
         (v_tenant, v_quiz0, v_s3,  20, 18, 'graded', 0, v_teacher, timestamptz '2026-08-20 09:00:00-05'),
         (v_tenant, v_quiz0, v_s4,  20, 9,  'graded', 0, v_teacher, timestamptz '2026-08-20 09:00:00-05'),
         (v_tenant, v_quiz0, v_s5,  20, 20, 'graded', 0, v_teacher, timestamptz '2026-08-20 09:00:00-05'),
         (v_tenant, v_quiz0, v_s6,  20, null, 'not_submitted', 0, v_teacher, timestamptz '2026-08-20 09:00:00-05'),
         (v_tenant, v_quiz0, v_s7,  20, 14, 'graded', 0, v_teacher, timestamptz '2026-08-20 09:00:00-05'),
         (v_tenant, v_quiz0, v_s8,  20, 7,  'graded', 2, v_teacher, timestamptz '2026-08-20 09:00:00-05'),
         (v_tenant, v_quiz0, v_s9,  20, 17, 'graded', 0, v_teacher, timestamptz '2026-08-20 09:00:00-05'),
         (v_tenant, v_quiz0, v_s10, 20, 11, 'graded', 0, v_teacher, timestamptz '2026-08-20 09:00:00-05');

  -- =========================================================================
  -- No per-criterio levels. There is no such thing any more: a criterio is a
  -- tag on a piece of evidencia saying what to look at in it, and the only
  -- judgement recorded anywhere is the nivel de logro of the competencia
  -- below. See migration 00009.
  --
  -- What Janice has to go on for MAT-C2 is therefore exactly what a real
  -- teacher has: Quiz 0's marks above, and the criterios those marks were read
  -- against (assessment_criteria, seeded further up).
  -- =========================================================================

  -- =========================================================================
  -- The official record: the nivel de logro per competencia.
  --
  -- Asserted by the teacher after reading the period's evidence -- not
  -- computed from it, and not an average of the marks (RVM 094-2020 5.1.1.3).
  -- Diego has no row at all: he submitted nothing and MAT-C2 was never
  -- evaluated for him this period. That absence is meaningful and must never
  -- be rendered as C (5.1.2.2 p.1).
  --
  -- Only MAT-C2 is asserted. MAT-C1/C3/C4 were not developed this bimestre,
  -- so they correctly have no rows either.
  -- =========================================================================
  insert into competency_term_levels
    (tenant_id, student_id, competency_id, term_id, class_id, scale_level_id, asserted_by_id)
  select v_tenant, x.student_id, v_mc2, v_b3, v_class_mat, l.id, v_teacher
    from (values
            (v_s1,  'A'),
            (v_s2,  'B'),
            (v_s3,  'AD'),
            (v_s4,  'C'),
            (v_s5,  'AD'),
            (v_s7,  'A'),
            (v_s8,  'C'),
            (v_s9,  'A'),
            (v_s10, 'B')
         ) as x(student_id, level_code)
    join grade_scale_levels l on l.tenant_id = v_tenant and l.scale_id = v_scale_ord and l.code = x.level_code;

  perform app.log_event('tenant.seeded', 'tenant', v_tenant,
                        jsonb_build_object('source', 'seed/seed_demo_tenant.sql'));
end
$seed$;

do $add$
declare
  v_tenant     uuid := '11111111-1111-4111-8111-111111111111';

  v_year       uuid;
  v_b3         uuid;
  v_g3         uuid;
  v_teacher    uuid;
  v_scale_ord  uuid;

  v_subject    uuid;
  v_ac1 uuid; v_ac2 uuid;  -- ART-C1, ART-C2 competency ids

  v_scheme     uuid;
  v_version    uuid;
  v_cmp_apre   uuid;
  v_cmp_crea   uuid;

  v_cap1 uuid; v_cap2 uuid; v_cap3 uuid;  -- ART-C1's 3 capacidades
  v_cap4 uuid; v_cap5 uuid; v_cap6 uuid;  -- ART-C2's 3 capacidades
  v_ps1 uuid; v_ps2 uuid; v_ps3 uuid;
  v_ps4 uuid; v_ps5 uuid; v_ps6 uuid;
  v_crit1 uuid; v_crit2 uuid; v_crit3 uuid;
  v_crit4 uuid; v_crit5 uuid; v_crit6 uuid;

  v_course     uuid;
  v_section    uuid;
  v_class      uuid;
  v_a1 uuid; v_a2 uuid; v_a3 uuid; v_a4 uuid; v_a5 uuid; v_a6 uuid;
begin
  perform set_config('app.tenant_id', v_tenant::text, true);

  -- =========================================================================
  -- Resolve what already exists. Each lookup is checked: a null here means
  -- the demo seed was never applied, and the inserts below would otherwise
  -- fail on a foreign key with a much less useful message.
  -- =========================================================================
  select id into v_year
    from academic_years
   where tenant_id = v_tenant and year = 2026 and deleted_at is null;
  if v_year is null then
    raise exception 'academic year 2026 not found — apply the base block of this file first';
  end if;

  select id into v_b3
    from terms
   where tenant_id = v_tenant and academic_year_id = v_year
     and sequence = 3 and deleted_at is null;
  if v_b3 is null then
    raise exception 'Bimestre III not found for academic year 2026';
  end if;

  select id into v_g3
    from grade_levels
   where tenant_id = v_tenant and code = '3' and deleted_at is null;
  if v_g3 is null then
    raise exception 'grade level 3 not found';
  end if;

  select id into v_teacher
    from teachers
   where tenant_id = v_tenant and employee_code = 'DOC-0142' and deleted_at is null;
  if v_teacher is null then
    raise exception 'teacher DOC-0142 (Janice Quispe) not found';
  end if;

  -- The MINEDU qualitative scale the tenant already has. Reused, not
  -- re-created: this is what makes every Arte grade report as AD/A/B/C.
  select id into v_scale_ord
    from grade_scales
   where tenant_id = v_tenant and code = 'minedu_ad_a_b_c' and deleted_at is null;
  if v_scale_ord is null then
    raise exception 'grade scale minedu_ad_a_b_c not found';
  end if;

  -- =========================================================================
  -- Subject
  --
  -- icon_key must be one of the sprite names in yanai-ui/src/lib/icons.ts;
  -- anything else silently falls back to 'book' in toIconName().
  -- =========================================================================
  insert into subjects (tenant_id, code, name, area_curricular, icon_key, is_tutoria, sort_order)
  values (v_tenant, 'ART', 'Arte y Cultura', 'Arte y Cultura', 'sparkles', false, 2)
  returning id into v_subject;

  -- =========================================================================
  -- Competencias: real rows now, not just grading_components standing in for
  -- them — the gap this block used to leave (see seed/SPEC.md Change Log).
  -- Without these, Arte could never carry a competency_term_levels row and
  -- was invisible to the promotion projection.
  -- =========================================================================
  insert into competencies (tenant_id, subject_id, code, name, kind, sort_order)
  values
    (v_tenant, v_subject, 'ART-C1', 'Aprecia de manera crítica manifestaciones artístico-culturales', 'area', 1),
    (v_tenant, v_subject, 'ART-C2', 'Crea proyectos desde los lenguajes artísticos', 'area', 2);

  select id into v_ac1 from competencies where tenant_id = v_tenant and code = 'ART-C1';
  select id into v_ac2 from competencies where tenant_id = v_tenant and code = 'ART-C2';

  -- =========================================================================
  -- Capacidades: the CNEB's 3 fixed sub-skills of each competencia. These are
  -- the same 6 titles the old version of this block used directly as rubrica
  -- assessment titles — they were already the real capacidad names, just
  -- homed on the wrong table.
  -- =========================================================================
  insert into capabilities (tenant_id, competency_id, code, name, sort_order)
  values
    (v_tenant, v_ac1, 'CAP1', 'Percibe manifestaciones artístico-culturales', 1),
    (v_tenant, v_ac1, 'CAP2', 'Contextualiza las manifestaciones artístico-culturales', 2),
    (v_tenant, v_ac1, 'CAP3', 'Reflexiona creativa y críticamente sobre manifestaciones artístico-culturales', 3),
    (v_tenant, v_ac2, 'CAP1', 'Explora y experimenta los lenguajes de las artes', 1),
    (v_tenant, v_ac2, 'CAP2', 'Aplica procesos creativos', 2),
    (v_tenant, v_ac2, 'CAP3', 'Evalúa y comunica sus procesos y proyectos', 3);

  select id into v_cap1 from capabilities where tenant_id = v_tenant and competency_id = v_ac1 and code = 'CAP1';
  select id into v_cap2 from capabilities where tenant_id = v_tenant and competency_id = v_ac1 and code = 'CAP2';
  select id into v_cap3 from capabilities where tenant_id = v_tenant and competency_id = v_ac1 and code = 'CAP3';
  select id into v_cap4 from capabilities where tenant_id = v_tenant and competency_id = v_ac2 and code = 'CAP1';
  select id into v_cap5 from capabilities where tenant_id = v_tenant and competency_id = v_ac2 and code = 'CAP2';
  select id into v_cap6 from capabilities where tenant_id = v_tenant and competency_id = v_ac2 and code = 'CAP3';

  -- =========================================================================
  -- Desempeños, grade 3.
  -- =========================================================================
  insert into performance_standards (tenant_id, capability_id, grade_level_id, code, description)
  values
    (v_tenant, v_cap1, v_g3, 'G3', 'Describe los elementos visuales, sonoros y kinestésicos que percibe en una manifestación artístico-cultural de su región.'),
    (v_tenant, v_cap2, v_g3, 'G3', 'Relaciona una manifestación artístico-cultural con las ideas, necesidades e intereses de las personas o comunidades que la producen.'),
    (v_tenant, v_cap3, v_g3, 'G3', 'Emite una opinión personal sobre una manifestación artístico-cultural, sustentada en criterios estéticos y en su experiencia.'),
    (v_tenant, v_cap4, v_g3, 'G3', 'Experimenta de manera individual y colaborativa con materiales, herramientas y técnicas de los lenguajes artísticos.'),
    (v_tenant, v_cap5, v_g3, 'G3', 'Desarrolla un proyecto artístico personal o colectivo aplicando un proceso creativo que incluye boceto, ejecución y ajustes.'),
    (v_tenant, v_cap6, v_g3, 'G3', 'Explica las decisiones tomadas durante su proceso creativo y las comunica a un público.');

  select id into v_ps1 from performance_standards where tenant_id = v_tenant and capability_id = v_cap1 and grade_level_id = v_g3;
  select id into v_ps2 from performance_standards where tenant_id = v_tenant and capability_id = v_cap2 and grade_level_id = v_g3;
  select id into v_ps3 from performance_standards where tenant_id = v_tenant and capability_id = v_cap3 and grade_level_id = v_g3;
  select id into v_ps4 from performance_standards where tenant_id = v_tenant and capability_id = v_cap4 and grade_level_id = v_g3;
  select id into v_ps5 from performance_standards where tenant_id = v_tenant and capability_id = v_cap5 and grade_level_id = v_g3;
  select id into v_ps6 from performance_standards where tenant_id = v_tenant and capability_id = v_cap6 and grade_level_id = v_g3;

  -- =========================================================================
  -- Criterios de evaluación: one per desempeño, precised for the rubricas
  -- below.
  -- =========================================================================
  insert into evaluation_criteria (tenant_id, competency_id, performance_standard_id, code, description, sort_order)
  values
    (v_tenant, v_ac1, v_ps1, 'CRIT1', 'Describe con vocabulario específico los elementos visuales presentes en una manifestación artístico-cultural cusqueña observada en clase.', 1),
    (v_tenant, v_ac1, v_ps2, 'CRIT2', 'Explica el contexto histórico y social del arte popular cusqueño presentado en clase.', 2),
    (v_tenant, v_ac1, v_ps3, 'CRIT3', 'Argumenta una opinión personal sobre el significado de una obra observada, sustentada en al menos dos criterios estéticos.', 3),
    (v_tenant, v_ac2, v_ps4, 'CRIT4', 'Experimenta con al menos dos técnicas de dibujo y color para representar un mismo tema.', 1),
    (v_tenant, v_ac2, v_ps5, 'CRIT5', 'Desarrolla el boceto y la primera versión de un proyecto artístico personal a partir de un tema propuesto.', 2),
    (v_tenant, v_ac2, v_ps6, 'CRIT6', 'Socializa su proyecto artístico ante sus compañeros y explica al menos dos decisiones tomadas durante su creación.', 3);

  select id into v_crit1 from evaluation_criteria where tenant_id = v_tenant and competency_id = v_ac1 and code = 'CRIT1';
  select id into v_crit2 from evaluation_criteria where tenant_id = v_tenant and competency_id = v_ac1 and code = 'CRIT2';
  select id into v_crit3 from evaluation_criteria where tenant_id = v_tenant and competency_id = v_ac1 and code = 'CRIT3';
  select id into v_crit4 from evaluation_criteria where tenant_id = v_tenant and competency_id = v_ac2 and code = 'CRIT4';
  select id into v_crit5 from evaluation_criteria where tenant_id = v_tenant and competency_id = v_ac2 and code = 'CRIT5';
  select id into v_crit6 from evaluation_criteria where tenant_id = v_tenant and competency_id = v_ac2 and code = 'CRIT6';

  -- =========================================================================
  -- Grading scheme: the two CNEB competencias for Arte y Cultura, 50% each.
  --
  -- Two components, not six: a component is a weighted bucket, and the six
  -- rubricas are assessments inside it, averaged by `mean`. MINEDU does not
  -- prescribe weights between competencias; equal split follows the earlier
  -- precedent set for other subjects in this file's history.
  --
  -- A scheme is needed at all because the tenant default is now
  -- `matematica_estandar`: without the course-level override below, Arte
  -- would be graded vigesimal on quizzes/tareas/examen.
  -- =========================================================================
  insert into grading_schemes (tenant_id, scale_id, code, name, description)
  values (v_tenant, v_scale_ord, 'arte_competencias', 'Evaluación de Arte y Cultura por competencias',
          'Las dos competencias CNEB del área de Arte y Cultura, a peso igual, '
          'con sus capacidades como criterios de evaluación.')
  returning id into v_scheme;

  insert into grading_components (tenant_id, scheme_id, code, name, sort_order)
  values (v_tenant, v_scheme, 'aprecia_criticamente', 'Aprecia de manera crítica manifestaciones artístico-culturales', 1),
         (v_tenant, v_scheme, 'crea_proyectos',       'Crea proyectos desde los lenguajes artísticos',                 2);

  select id into v_cmp_apre from grading_components where scheme_id = v_scheme and code = 'aprecia_criticamente';
  select id into v_cmp_crea from grading_components where scheme_id = v_scheme and code = 'crea_proyectos';

  -- effective_from is the start of the school year, NOT today, even though the
  -- class is being registered mid-year. `class_effective_grading_schemes`
  -- picks a version with `effective_from <= term.starts_on`; dated today this
  -- version would not resolve for Bimestre III (which started 2026-07-27) and
  -- the class would have a scheme but no version.
  insert into grading_scheme_versions (tenant_id, scheme_id, version, effective_from,
                                       rounding_mode, absent_counts_as, retake_policy, notes)
  values (v_tenant, v_scheme, 1, date '2026-03-02', 'half_up', 'zero', 'best',
          'Versión inicial 2026. Dos competencias CNEB a 50% cada una; cada '
          'capacidad se evalúa como criterio (rúbrica) dentro de su competencia.')
  returning id into v_version;

  -- The deferred check_weights_sum trigger requires these to sum to exactly 1.
  insert into grading_scheme_component_weights (tenant_id, scheme_version_id, component_id, weight, aggregation, drop_lowest_n)
  values (v_tenant, v_version, v_cmp_apre, 0.500000, 'mean', 0),
         (v_tenant, v_version, v_cmp_crea, 0.500000, 'mean', 0);

  -- Publishing is a second checkpoint: a version with no components, or with
  -- components that do not sum to 1, cannot be published.
  update grading_scheme_versions
     set published_at = now(), published_by_id = v_teacher
   where id = v_version;

  -- =========================================================================
  -- Course. grading_scheme_id is the per-course override; without it the
  -- class falls back to tenants.default_grading_scheme_id.
  -- =========================================================================
  insert into courses (tenant_id, academic_year_id, subject_id, grade_level_id,
                       name, code, weekly_hours, grading_scheme_id)
  values (v_tenant, v_year, v_subject, v_g3, 'Arte 3ro', 'ART-3', 2, v_scheme)
  returning id into v_course;

  -- =========================================================================
  -- Section 3ro A
  --
  -- tutor_teacher_id is left null: the demo tenant has one teacher, she
  -- already tutors 5to B, and a homeroom tutor is not a role one person holds
  -- for several sections. Nothing in the API reads the column.
  -- =========================================================================
  insert into sections (tenant_id, academic_year_id, grade_level_id, label, name,
                        tutor_teacher_id, shift, capacity)
  values (v_tenant, v_year, v_g3, 'A', '3ro A', null, 'manana', 32)
  returning id into v_section;

  -- =========================================================================
  -- Students: 10 new, enrolled in 3ro A.
  --
  -- Codes continue from the base block's roster (which ends at
  -- EST-2026-010) and DNIs from 70123010, because both are uniquely indexed
  -- per tenant. Birthdates ~2012, since these are 3ro de secundaria.
  --
  -- The cohort is dated from the start of the school year: 3ro A existed as a
  -- roster all along, it is only the Arte class that is new mid-year.
  -- =========================================================================
  insert into students (tenant_id, student_code, given_name, paternal_surname, maternal_surname,
                        birthdate, sex, document_type, document_number, enrolled_on)
  values (v_tenant, 'EST-2026-011', 'Matías',    'Villalobos', 'Ccama',      date '2012-02-14', 'M', 'DNI', '70123011', date '2026-03-02'),
         (v_tenant, 'EST-2026-012', 'Valeria',   'Paucar',     'Anaya',      date '2012-06-03', 'F', 'DNI', '70123012', date '2026-03-02'),
         (v_tenant, 'EST-2026-013', 'Iker',      'Aguirre',    'Sinchi',     date '2012-09-27', 'M', 'DNI', '70123013', date '2026-03-02'),
         (v_tenant, 'EST-2026-014', 'Rafaela',   'Centeno',    'Huamaní',    date '2012-01-18', 'F', 'DNI', '70123014', date '2026-03-02'),
         (v_tenant, 'EST-2026-015', 'Salvador',  'Ríos',       'Cusi',       date '2012-11-09', 'M', 'DNI', '70123015', date '2026-03-02'),
         (v_tenant, 'EST-2026-016', 'Brianna',   'Olarte',     'Qquehue',    date '2012-04-22', 'F', 'DNI', '70123016', date '2026-03-02'),
         (v_tenant, 'EST-2026-017', 'Gael',      'Espinoza',   'Ttito',      date '2012-07-15', 'M', 'DNI', '70123017', date '2026-03-02'),
         (v_tenant, 'EST-2026-018', 'Aitana',    'Meza',       'Curasi',     date '2012-10-30', 'F', 'DNI', '70123018', date '2026-03-02'),
         (v_tenant, 'EST-2026-019', 'Liam',      'Delgado',    'Pauccar',    date '2012-03-08', 'M', 'DNI', '70123019', date '2026-03-02'),
         (v_tenant, 'EST-2026-020', 'Zoe',       'Carrión',    'Mamani',     date '2012-12-01', 'F', 'DNI', '70123020', date '2026-03-02');

  -- Scoped to the ten codes just written. Deliberately NOT the base block's
  -- `where s.tenant_id = v_tenant`: that would re-enroll every student in the
  -- school into 3ro A and trip section_memberships_one_at_a_time.
  insert into section_memberships (tenant_id, student_id, section_id, academic_year_id, joined_on)
  select v_tenant, s.id, v_section, v_year, date '2026-03-02'
    from students s
   where s.tenant_id = v_tenant
     and s.student_code between 'EST-2026-011' and 'EST-2026-020'
     and s.deleted_at is null;

  -- =========================================================================
  -- The class, its titular, and its weekly pattern.
  --
  -- Mondays and Thursdays, 09:00-10:00 — clear of Matemática 5to B's Tue/Fri
  -- 10:00 slot.
  --
  -- Dated today rather than backdated to 2026-03-02: this class is being
  -- registered mid-year, so the titular assignment and the timetable start
  -- now. Change both dates to '2026-03-02' to pretend it ran all year.
  -- =========================================================================
  insert into classes (tenant_id, academic_year_id, course_id, section_id, name, code, default_room)
  values (v_tenant, v_year, v_course, v_section, 'Arte 3ro A', 'ART-3A', 'Aula 7')
  returning id into v_class;

  insert into class_teachers (tenant_id, class_id, teacher_id, role, starts_on)
  values (v_tenant, v_class, v_teacher, 'titular', date '2026-08-25');

  -- Weekday 1 = Monday, 4 = Thursday (ISO).
  insert into class_schedules (tenant_id, class_id, weekday, starts_at, ends_at, room, effective_from)
  values (v_tenant, v_class, 1, time '09:00', time '10:00', 'Aula 7', date '2026-08-25'),
         (v_tenant, v_class, 4, time '09:00', time '10:00', 'Aula 7', date '2026-08-25');

  -- =========================================================================
  -- Sessions: four weeks forward from today, all `scheduled`. None are
  -- completed — the class did not exist last week. Drop this block if an
  -- empty timetable is wanted; nothing below depends on it.
  -- =========================================================================
  insert into class_sessions (tenant_id, class_id, schedule_id, term_id, session_date,
                              scheduled_start_at, scheduled_end_at, status, topic, room)
  select v_tenant, v_class,
         (select cs.id from class_schedules cs
           where cs.class_id = v_class and cs.weekday = extract(isodow from d.day)::smallint limit 1),
         v_b3, d.day,
         (d.day + time '09:00') at time zone 'America/Lima',
         (d.day + time '10:00') at time zone 'America/Lima',
         'scheduled', d.topic, 'Aula 7'
    from (values
            (date '2026-08-27', 'Presentación: los lenguajes del arte'),
            (date '2026-08-31', 'Percepción: elementos visuales en el entorno'),
            (date '2026-09-03', 'Arte popular cusqueño: contexto e historia'),
            (date '2026-09-07', 'Exploración: técnicas de dibujo y color'),
            (date '2026-09-10', 'Apreciación crítica: obra y significado'),
            (date '2026-09-14', 'Proceso creativo: boceto del proyecto'),
            (date '2026-09-17', 'Desarrollo del proyecto artístico'),
            (date '2026-09-21', 'Socialización: presentación de avances')
         ) as d(day, topic);

  -- One ad-hoc session: Wednesday 2026-08-26, 14:00-15:00. The class has no
  -- Wednesday slot, so `schedule_id` stays null — that is what an ad-hoc
  -- session is, a dated instance with no recurring pattern behind it. It does
  -- not touch class_schedules: adding a Wednesday row there would make it
  -- recur every week, which is not what a one-off class is.
  insert into class_sessions (tenant_id, class_id, schedule_id, term_id, session_date,
                              scheduled_start_at, scheduled_end_at, status, topic, room)
  values (v_tenant, v_class, null, v_b3, date '2026-08-26',
          (date '2026-08-26' + time '14:00') at time zone 'America/Lima',
          (date '2026-08-26' + time '15:00') at time zone 'America/Lima',
          'scheduled', 'Taller: manifestaciones artístico-culturales del Cusco', 'Aula 7');

  -- =========================================================================
  -- Assessments: 6 rúbricas, 3 per competencia, one per criterio de
  -- evaluación above (linked via assessment_criteria below). All published,
  -- none scored: the register is set up, not filled in. Due dates fall on
  -- class days inside Bimestre III (ends 2026-10-30), at the hour the class
  -- ends.
  -- =========================================================================
  insert into assessments (tenant_id, class_id, term_id, scheme_id, component_id,
                           title, kind, max_score, due_at, status, published_at, created_by_id)
  select v_tenant, v_class, v_b3, v_scheme, a.component_id,
         a.title, 'rubrica', 20, a.due_at,
         'published', timestamptz '2026-08-25 09:00:00-05', v_teacher
    from (values
            -- Competencia 1: Aprecia de manera crítica manifestaciones artístico-culturales
            (v_cmp_apre, 'Percibe manifestaciones artístico-culturales',                          timestamptz '2026-09-10 10:00:00-05'),
            (v_cmp_apre, 'Contextualiza manifestaciones artístico-culturales',                    timestamptz '2026-09-24 10:00:00-05'),
            (v_cmp_apre, 'Reflexiona creativa y críticamente sobre manifestaciones artístico-culturales', timestamptz '2026-10-08 10:00:00-05'),
            -- Competencia 2: Crea proyectos desde los lenguajes artísticos
            (v_cmp_crea, 'Explora y experimenta los lenguajes del arte',                          timestamptz '2026-09-17 10:00:00-05'),
            (v_cmp_crea, 'Aplica procesos creativos',                                             timestamptz '2026-10-01 10:00:00-05'),
            (v_cmp_crea, 'Evalúa y socializa sus procesos y proyectos',                           timestamptz '2026-10-22 10:00:00-05')
         ) as a(component_id, title, due_at);

  select id into v_a1 from assessments where tenant_id = v_tenant and class_id = v_class and title = 'Percibe manifestaciones artístico-culturales';
  select id into v_a2 from assessments where tenant_id = v_tenant and class_id = v_class and title = 'Contextualiza manifestaciones artístico-culturales';
  select id into v_a3 from assessments where tenant_id = v_tenant and class_id = v_class and title = 'Reflexiona creativa y críticamente sobre manifestaciones artístico-culturales';
  select id into v_a4 from assessments where tenant_id = v_tenant and class_id = v_class and title = 'Explora y experimenta los lenguajes del arte';
  select id into v_a5 from assessments where tenant_id = v_tenant and class_id = v_class and title = 'Aplica procesos creativos';
  select id into v_a6 from assessments where tenant_id = v_tenant and class_id = v_class and title = 'Evalúa y socializa sus procesos y proyectos';

  insert into assessment_criteria (tenant_id, assessment_id, criterion_id)
  values (v_tenant, v_a1, v_crit1),
         (v_tenant, v_a2, v_crit2),
         (v_tenant, v_a3, v_crit3),
         (v_tenant, v_a4, v_crit4),
         (v_tenant, v_a5, v_crit5),
         (v_tenant, v_a6, v_crit6);

  perform app.log_event('class.created', 'class', v_class,
                        jsonb_build_object('source', 'seed/seed_demo_tenant.sql (Arte block)',
                                           'code', 'ART-3A', 'students', 10));
end
$add$;


-- ===========================================================================
-- 3. Las seis áreas de 5to B — the teacher's real weekday.
--
-- Blocks 1 and 2 leave the demo teacher with two classes of one hour each, so
-- Home has almost nothing to draw. This block gives 5to B the six áreas a
-- Peruvian secondary section actually takes, all taught by the same teacher to
-- the same ten students, on a real 08:00-16:00 timetable:
--
--     A  08:00 - 09:30      B  10:00 - 11:30      C  11:30 - 12:15
--     D  13:15 - 14:00      E  14:30 - 16:00
--     recreos 09:30-10:00 and 14:00-14:30, almuerzo 12:15-13:15
--
--          Lun          Mar          Mié          Jue          Vie
--     A    Comunic.     C. y Tec.    C. Soc.      Comunic.     C. y Tec.
--     B    C. Soc.      Matemática*  Arte         C. y Tec.    Matemática*
--     C    C. y Tec.    Comunic.     Tutoría      C. Soc.      Arte
--     D    Tutoría      Arte         Comunic.     Tutoría      C. Soc.
--     E    Arte         C. Soc.      Matemática   Matemática   Comunic.
--
-- * Matemática's Tue/Fri 10:00-11:00 sessions already exist from block 1 and
--   are NOT touched: this block is additive. They run 60 min inside a 90 min
--   slot, which is why those two days have a free half hour at 11:00 — real
--   timetables are irregular, and it keeps the block from rewriting rows that
--   carry the only scored data in the seed.
--
-- Matemática 5to B counts as one of the six, so only five classes are new. No
-- new students and no new section_memberships: the ten of 5to B are already
-- enrolled, and section_memberships_one_at_a_time rejects a second row. The
-- six classes share a roster through the section, not through re-enrolment.
--
-- Deliberately NOT seeded: criterios de evaluación, assessments and scores for
-- the five new áreas. Their competencias show on the criterios screen as
-- explicit gaps, which is this file's documented demo state (see SPEC.md);
-- Matemática stays the one área with a filled register.
--
-- DATES ARE FIXED, like the rest of the file, around a "today" of Thursday
-- 2026-09-03: the week of 24 Aug is completed, the week of 31 Aug is the one
-- in progress, the week of 7 Sep is scheduled. That means this block goes
-- stale — after mid-September Home is empty again. Anchoring `v_weeks` to
-- date_trunc('week', current_date) is the one-line fix if that starts to hurt.
-- ===========================================================================
do $areas$
declare
  v_tenant   constant uuid := '11111111-1111-4111-8111-111111111111';
  -- Sessions dated before this land as `completed`, the rest as `scheduled`.
  v_today    constant date := date '2026-09-03';
  v_year     uuid;
  v_b3       uuid;
  v_g5       uuid;
  v_teacher  uuid;
  v_scale    uuid;
  v_section  uuid;
  v_mat      uuid;
  v_art3     uuid;
  v_subj     uuid;
  v_scheme   uuid;
  v_version  uuid;
  v_course   uuid;
  v_class    uuid;
  v_c1       uuid;
  v_c2       uuid;
  v_cmp1     uuid;
  v_cmp2     uuid;
  r          record;
begin
  perform set_config('app.tenant_id', v_tenant::text, true);

  -- =========================================================================
  -- Resolve what blocks 1 and 2 created. A null here means this block is
  -- running first, and every insert below would fail on a foreign key with a
  -- far less useful message.
  -- =========================================================================
  select id into v_year from academic_years
   where tenant_id = v_tenant and year = 2026 and deleted_at is null;
  if v_year is null then
    raise exception 'academic year 2026 not found — apply the base block of this file first';
  end if;

  select id into v_b3 from terms
   where tenant_id = v_tenant and academic_year_id = v_year and sequence = 3 and deleted_at is null;
  if v_b3 is null then
    raise exception 'Bimestre III not found for academic year 2026';
  end if;

  select id into v_g5 from grade_levels
   where tenant_id = v_tenant and code = '5' and deleted_at is null;
  if v_g5 is null then
    raise exception 'grade level 5 not found';
  end if;

  select id into v_teacher from teachers
   where tenant_id = v_tenant and employee_code = 'DOC-0142' and deleted_at is null;
  if v_teacher is null then
    raise exception 'teacher DOC-0142 (Janice Quispe) not found';
  end if;

  select id into v_scale from grade_scales
   where tenant_id = v_tenant and code = 'minedu_ad_a_b_c' and deleted_at is null;
  if v_scale is null then
    raise exception 'grade scale minedu_ad_a_b_c not found';
  end if;

  select id into v_section from sections
   where tenant_id = v_tenant and academic_year_id = v_year and name = '5to B' and deleted_at is null;
  if v_section is null then
    raise exception 'section 5to B not found — apply the base block of this file first';
  end if;

  select id into v_mat from classes
   where tenant_id = v_tenant and code = 'MAT-5B' and deleted_at is null;
  if v_mat is null then
    raise exception 'class MAT-5B not found — apply the base block of this file first';
  end if;

  select id into v_art3 from classes
   where tenant_id = v_tenant and code = 'ART-3A' and deleted_at is null;
  if v_art3 is null then
    raise exception 'class ART-3A not found — apply the Arte block of this file first';
  end if;

  -- =========================================================================
  -- The five new áreas.
  --
  -- Arte y Cultura reuses the subject, competencias and grading scheme the
  -- Arte block already created (subjects_tenant_code_key would reject a second
  -- ART row anyway) — hence the "look up, insert only if missing" shape. Its
  -- course and class are new, because 3ro A and 5to B are different sections
  -- at different grades.
  --
  -- Two competencias per área, no criterios: see the block header.
  -- =========================================================================
  for r in
    select * from (values
      ('COM',  'Comunicación',           'Comunicación',          'book',         false, 3,
       'COM-5', 'Comunicación 5to', 'COM-5B', 'Comunicación 5to B', 'Aula 8',
       'comunicacion_competencias', 'Evaluación de Comunicación por competencias',
       'COM-C1', 'Se comunica oralmente en su lengua materna',
       'COM-C2', 'Lee diversos tipos de textos escritos en su lengua materna',
       array['El texto argumentativo: tesis y argumentos',
             'Lectura: inferencias en textos discontinuos',
             'Debate: turnos, escucha y réplica',
             'El ensayo escolar: estructura',
             'Cohesión y coherencia en el párrafo',
             'Lectura crítica: intención del autor',
             'Exposición oral con soporte visual',
             'Revisión y edición del ensayo']),

      ('CYT',  'Ciencia y Tecnología',   'Ciencia y Tecnología',  'presentation', false, 4,
       'CYT-5', 'Ciencia y Tecnología 5to', 'CYT-5B', 'Ciencia y Tecnología 5to B', 'Lab 1',
       'cyt_competencias', 'Evaluación de Ciencia y Tecnología por competencias',
       'CYT-C1', 'Indaga mediante métodos científicos para construir conocimientos',
       'CYT-C2', 'Explica el mundo físico basándose en conocimientos sobre los seres vivos, materia y energía',
       array['La célula: estructura y función',
             'Diseño de una indagación: variables',
             'Laboratorio: observación al microscopio',
             'Energía y transformaciones',
             'Registro y análisis de datos',
             'Ecosistemas y flujo de energía',
             'Informe de indagación',
             'Materia: propiedades y cambios']),

      ('CCSS', 'Ciencias Sociales',      'Ciencias Sociales',     'world',        false, 5,
       'CCSS-5', 'Ciencias Sociales 5to', 'CCSS-5B', 'Ciencias Sociales 5to B', 'Aula 9',
       'ccss_competencias', 'Evaluación de Ciencias Sociales por competencias',
       'CCSS-C1', 'Construye interpretaciones históricas',
       'CCSS-C2', 'Gestiona responsablemente el espacio y el ambiente',
       array['El Perú del siglo XX: procesos',
             'Fuentes históricas: primarias y secundarias',
             'Migración interna y crecimiento urbano',
             'Interpretación de mapas temáticos',
             'Gestión de riesgos en el territorio',
             'Cambio climático y comunidad local',
             'Línea de tiempo: hitos republicanos',
             'Debate: memoria y ciudadanía']),

      ('ART',  'Arte y Cultura',         'Arte y Cultura',        'sparkles',     false, 2,
       'ART-5', 'Arte 5to', 'ART-5B', 'Arte 5to B', 'Aula 7',
       'arte_competencias', 'Evaluación de Arte y Cultura por competencias',
       'ART-C1', 'Aprecia de manera crítica manifestaciones artístico-culturales',
       'ART-C2', 'Crea proyectos desde los lenguajes artísticos',
       array['Lenguajes artísticos: introducción',
             'Arte popular cusqueño: contexto',
             'Técnicas de dibujo y color',
             'Boceto del proyecto personal',
             'Composición y encuadre',
             'Desarrollo del proyecto',
             'Apreciación crítica de obra',
             'Socialización de avances']),

      ('TUT',  'Tutoría y Orientación Educativa', 'Tutoría',      'checklist',    true,  6,
       'TUT-5', 'Tutoría 5to', 'TUT-5B', 'Tutoría 5to B', 'Aula 12',
       'tutoria_competencias', 'Evaluación de Tutoría por competencias',
       'TUT-C1', 'Construye su identidad',
       'TUT-C2', 'Convive y participa democráticamente en la búsqueda del bien común',
       array['Proyecto de vida: primeras decisiones',
             'Convivencia: acuerdos del aula',
             'Manejo de conflictos entre pares',
             'Orientación vocacional: intereses',
             'Uso responsable de redes sociales',
             'Salud emocional y autocuidado',
             'Participación estudiantil',
             'Balance del bimestre'])
    ) as a(subj_code, subj_name, area_curricular, icon, tutoria, subj_sort,
           course_code, course_name, class_code, class_name, room,
           scheme_code, scheme_name,
           c1_code, c1_name, c2_code, c2_name, topics)
  loop
    -- ---- subject + competencias (reused when the code already exists) ----
    select id into v_subj from subjects
     where tenant_id = v_tenant and code = r.subj_code and deleted_at is null;
    if v_subj is null then
      insert into subjects (tenant_id, code, name, area_curricular, icon_key, is_tutoria, sort_order)
      values (v_tenant, r.subj_code, r.subj_name, r.area_curricular, r.icon, r.tutoria, r.subj_sort)
      returning id into v_subj;

      insert into competencies (tenant_id, subject_id, code, name, kind, sort_order)
      values (v_tenant, v_subj, r.c1_code, r.c1_name, 'area', 1),
             (v_tenant, v_subj, r.c2_code, r.c2_name, 'area', 2);
    end if;

    select id into v_c1 from competencies where tenant_id = v_tenant and code = r.c1_code;
    select id into v_c2 from competencies where tenant_id = v_tenant and code = r.c2_code;
    if v_c1 is null or v_c2 is null then
      raise exception 'competencias % / % missing for subject %', r.c1_code, r.c2_code, r.subj_code;
    end if;

    -- ---- grading scheme: the two competencias at 50% each ----
    select id into v_scheme from grading_schemes
     where tenant_id = v_tenant and code = r.scheme_code and deleted_at is null;
    if v_scheme is null then
      insert into grading_schemes (tenant_id, scale_id, code, name, description)
      values (v_tenant, v_scale, r.scheme_code, r.scheme_name,
              'Las dos competencias CNEB del área, a peso igual, en la escala MINEDU AD/A/B/C.')
      returning id into v_scheme;

      insert into grading_components (tenant_id, scheme_id, code, name, sort_order)
      values (v_tenant, v_scheme, r.c1_code, r.c1_name, 1),
             (v_tenant, v_scheme, r.c2_code, r.c2_name, 2);

      select id into v_cmp1 from grading_components where scheme_id = v_scheme and code = r.c1_code;
      select id into v_cmp2 from grading_components where scheme_id = v_scheme and code = r.c2_code;

      -- effective_from is the start of the school year, not today:
      -- class_effective_grading_schemes resolves by term.starts_on, and
      -- Bimestre III started 2026-07-27. Dated later, the class would have a
      -- scheme but no version.
      insert into grading_scheme_versions (tenant_id, scheme_id, version, effective_from,
                                           rounding_mode, absent_counts_as, retake_policy, notes)
      values (v_tenant, v_scheme, 1, date '2026-03-02', 'half_up', 'zero', 'best',
              'Versión inicial 2026. Dos competencias CNEB a 50% cada una.')
      returning id into v_version;

      -- check_weights_sum is deferred and requires exactly 1.
      insert into grading_scheme_component_weights (tenant_id, scheme_version_id, component_id,
                                                    weight, aggregation, drop_lowest_n)
      values (v_tenant, v_version, v_cmp1, 0.500000, 'mean', 0),
             (v_tenant, v_version, v_cmp2, 0.500000, 'mean', 0);

      update grading_scheme_versions
         set published_at = now(), published_by_id = v_teacher
       where id = v_version;
    end if;

    -- ---- course, class, titular ----
    insert into courses (tenant_id, academic_year_id, subject_id, grade_level_id,
                         name, code, weekly_hours, grading_scheme_id)
    values (v_tenant, v_year, v_subj, v_g5, r.course_name, r.course_code, 5, v_scheme)
    returning id into v_course;

    insert into classes (tenant_id, academic_year_id, course_id, section_id, name, code, default_room)
    values (v_tenant, v_year, v_course, v_section, r.class_name, r.class_code, r.room)
    returning id into v_class;

    insert into class_teachers (tenant_id, class_id, teacher_id, role, starts_on)
    values (v_tenant, v_class, v_teacher, 'titular', date '2026-03-02');

    -- ---- the weekly pattern, and three weeks of dated sessions ----
    -- Schedules are inserted first, then every session is generated from them
    -- by crossing the pattern with the three week-Mondays. Topics cycle
    -- through the área's list in date order.
    insert into class_schedules (tenant_id, class_id, weekday, starts_at, ends_at, room, effective_from)
    select v_tenant, v_class, s.weekday, s.starts_at, s.ends_at, r.room, date '2026-03-02'
      from (values
              ('COM-5B', 1, time '08:00', time '09:30'),
              ('COM-5B', 2, time '11:30', time '12:15'),
              ('COM-5B', 3, time '13:15', time '14:00'),
              ('COM-5B', 4, time '08:00', time '09:30'),
              ('COM-5B', 5, time '14:30', time '16:00'),

              ('CYT-5B', 1, time '11:30', time '12:15'),
              ('CYT-5B', 2, time '08:00', time '09:30'),
              ('CYT-5B', 4, time '10:00', time '11:30'),
              ('CYT-5B', 5, time '08:00', time '09:30'),

              ('CCSS-5B', 1, time '10:00', time '11:30'),
              ('CCSS-5B', 2, time '14:30', time '16:00'),
              ('CCSS-5B', 3, time '08:00', time '09:30'),
              ('CCSS-5B', 4, time '11:30', time '12:15'),
              ('CCSS-5B', 5, time '13:15', time '14:00'),

              ('ART-5B', 1, time '14:30', time '16:00'),
              ('ART-5B', 2, time '13:15', time '14:00'),
              ('ART-5B', 3, time '10:00', time '11:30'),
              ('ART-5B', 5, time '11:30', time '12:15'),

              ('TUT-5B', 1, time '13:15', time '14:00'),
              ('TUT-5B', 3, time '11:30', time '12:15'),
              ('TUT-5B', 4, time '13:15', time '14:00')
           ) as s(class_code, weekday, starts_at, ends_at)
     where s.class_code = r.class_code;

    insert into class_sessions (tenant_id, class_id, schedule_id, term_id, session_date,
                                scheduled_start_at, scheduled_end_at, status, topic, room,
                                actual_start_at, actual_end_at, started_by_id)
    select v_tenant, v_class, x.sched_id, v_b3, x.day,
           (x.day + x.starts_at) at time zone 'America/Lima',
           (x.day + x.ends_at)   at time zone 'America/Lima',
           x.status,
           r.topics[((x.n - 1) % array_length(r.topics, 1)) + 1],
           r.room,
           case when x.status = 'completed' then (x.day + x.starts_at) at time zone 'America/Lima' end,
           case when x.status = 'completed' then (x.day + x.ends_at)   at time zone 'America/Lima' end,
           case when x.status = 'completed' then v_teacher end
      from (
        select sc.id as sched_id, sc.starts_at, sc.ends_at,
               (w.mon + (sc.weekday - 1)) as day,
               case when (w.mon + (sc.weekday - 1)) < v_today then 'completed' else 'scheduled' end as status,
               row_number() over (order by (w.mon + (sc.weekday - 1)), sc.starts_at) as n
          from class_schedules sc
          cross join (values (date '2026-08-24'), (date '2026-08-31'), (date '2026-09-07')) as w(mon)
         where sc.class_id = v_class and sc.deleted_at is null
      ) as x;

    perform app.log_event('class.created', 'class', v_class,
                          jsonb_build_object('source', 'seed/seed_demo_tenant.sql (áreas block)',
                                             'code', r.class_code, 'students', 10));
  end loop;

  -- =========================================================================
  -- Matemática 5to B joins the timetable in blocks Wed E and Thu E.
  --
  -- Additive only: its Tue/Fri 10:00-11:00 pattern and every session block 1
  -- created stay exactly as they are, because those sessions are the ones the
  -- scored Quiz 0 hangs off the same class as.
  -- =========================================================================
  insert into class_schedules (tenant_id, class_id, weekday, starts_at, ends_at, room, effective_from)
  values (v_tenant, v_mat, 3, time '14:30', time '16:00', 'Aula 12', date '2026-08-24'),
         (v_tenant, v_mat, 4, time '14:30', time '16:00', 'Aula 12', date '2026-08-24');

  insert into class_sessions (tenant_id, class_id, schedule_id, term_id, session_date,
                              scheduled_start_at, scheduled_end_at, status, topic, room,
                              actual_start_at, actual_end_at, started_by_id)
  select v_tenant, v_mat, x.sched_id, v_b3, x.day,
         (x.day + time '14:30') at time zone 'America/Lima',
         (x.day + time '16:00') at time zone 'America/Lima',
         x.status,
         (array['Práctica dirigida: sistemas de ecuaciones',
                'Inecuaciones lineales',
                'Funciones lineales: gráfica',
                'Funciones cuadráticas: vértice',
                'Modelamiento con funciones',
                'Taller de resolución de problemas'])[((x.n - 1) % 6) + 1],
         'Aula 12',
         case when x.status = 'completed' then (x.day + time '14:30') at time zone 'America/Lima' end,
         case when x.status = 'completed' then (x.day + time '16:00') at time zone 'America/Lima' end,
         case when x.status = 'completed' then v_teacher end
    from (
      select sc.id as sched_id,
             (w.mon + (sc.weekday - 1)) as day,
             case when (w.mon + (sc.weekday - 1)) < v_today then 'completed' else 'scheduled' end as status,
             row_number() over (order by (w.mon + (sc.weekday - 1))) as n
        from class_schedules sc
        cross join (values (date '2026-08-24'), (date '2026-08-31'), (date '2026-09-07')) as w(mon)
       where sc.class_id = v_mat and sc.effective_from = date '2026-08-24' and sc.deleted_at is null
    ) as x;

  -- =========================================================================
  -- Arte 3ro A moves out of the way.
  --
  -- Block 2 put it on Mon/Thu 09:00-10:00, which was clear of Matemática's
  -- Tue/Fri 10:00 slot but sits inside 5to B's new 08:00-09:30 block. Moved to
  -- Wed/Fri 16:15-17:15 — after 5to B's day ends — so the demo timetable has
  -- no overlapping sessions anywhere. The grid would draw two overlapping
  -- classes on top of each other; how to split them is an open design
  -- question, and the seed should not be what forces it.
  --
  -- The two schedule rows are moved in place, so every session's schedule_id
  -- stays valid; only weekday, times and dates change. Monday sessions shift
  -- +2 days and Thursday ones +1.
  --
  -- The ad-hoc update is pinned to block 2's own row (schedule_id null AND
  -- session_date 2026-08-26) rather than to every ad-hoc session of the class.
  -- On a fresh database those are the same thing, but a database that has been
  -- used has ad-hoc sessions a person created through the app: moving them all
  -- to 16:15 collides the moment two share a date (class_sessions_class_start_key),
  -- and rewriting rows a teacher entered is not the seed's business anyway.
  -- Such a session can still overlap 5to B's new timetable; that is left alone
  -- deliberately.
  -- =========================================================================
  update class_schedules set weekday = 3, starts_at = time '16:15', ends_at = time '17:15'
   where class_id = v_art3 and weekday = 1 and deleted_at is null;
  update class_schedules set weekday = 5, starts_at = time '16:15', ends_at = time '17:15'
   where class_id = v_art3 and weekday = 4 and deleted_at is null;

  update class_sessions cs
     set session_date = d.nd,
         scheduled_start_at = (d.nd + time '16:15') at time zone 'America/Lima',
         scheduled_end_at   = (d.nd + time '17:15') at time zone 'America/Lima'
    from (
      select id,
             session_date + (case extract(isodow from session_date)
                               when 1 then 2 when 4 then 1 else 0 end)::int as nd
        from class_sessions
       where class_id = v_art3 and schedule_id is not null and deleted_at is null
    ) as d
   where cs.id = d.id;

  update class_sessions
     set scheduled_start_at = (session_date + time '16:15') at time zone 'America/Lima',
         scheduled_end_at   = (session_date + time '17:15') at time zone 'America/Lima'
   where class_id = v_art3 and schedule_id is null
     and session_date = date '2026-08-26' and deleted_at is null;
end
$areas$;
