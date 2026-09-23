-- ---------------------------------------------------------------------------
-- Áreas curriculares y competencias CNEB.
--
-- Se cargan las competencias COMPLETAS de cada área, no solo las que se
-- trabajan este año: el CNEB define el área entera, y una competencia sin
-- trabajar debe poder distinguirse de una inexistente.
--
-- competencies.kind decide qué cuenta para la promoción (RVM 094-2020, 5.1.3
-- p.9-11): 'area' cuenta; 'transversal' NUNCA cuenta y no lleva subject_id
-- (competencies_transversal_has_no_subject lo fuerza).
-- ---------------------------------------------------------------------------

insert into subjects
  (id, tenant_id, code, name, area_curricular, icon_key, is_tutoria, sort_order)
values
  ('c0000000-0000-4000-8000-000000000050', '84d84ee4-816d-4035-a1ad-55efeee4f11e',
   'MAT', 'Matemática', 'Matemática', 'calculadora', false, 1),
  ('c0000000-0000-4000-8000-000000000055', '84d84ee4-816d-4035-a1ad-55efeee4f11e',
   'CCSS', 'Ciencias Sociales', 'Ciencias Sociales', 'mundo', false, 2);

insert into competencies
  (id, tenant_id, subject_id, code, name, kind, sort_order, is_active)
values
  -- Matemática: las cuatro competencias del área.
  ('c0000000-0000-4000-8000-000000000061', '84d84ee4-816d-4035-a1ad-55efeee4f11e',
   'c0000000-0000-4000-8000-000000000050', 'MAT-C1',
   'Resuelve problemas de cantidad', 'area', 1, true),
  ('c0000000-0000-4000-8000-000000000062', '84d84ee4-816d-4035-a1ad-55efeee4f11e',
   'c0000000-0000-4000-8000-000000000050', 'MAT-C2',
   'Resuelve problemas de regularidad, equivalencia y cambio', 'area', 2, true),
  ('c0000000-0000-4000-8000-000000000063', '84d84ee4-816d-4035-a1ad-55efeee4f11e',
   'c0000000-0000-4000-8000-000000000050', 'MAT-C3',
   'Resuelve problemas de forma, movimiento y localización', 'area', 3, true),
  ('c0000000-0000-4000-8000-000000000064', '84d84ee4-816d-4035-a1ad-55efeee4f11e',
   'c0000000-0000-4000-8000-000000000050', 'MAT-C4',
   'Resuelve problemas de gestión de datos e incertidumbre', 'area', 4, true),

  -- Ciencias Sociales: las tres competencias del área.
  ('c0000000-0000-4000-8000-000000000065', '84d84ee4-816d-4035-a1ad-55efeee4f11e',
   'c0000000-0000-4000-8000-000000000055', 'CCSS-C1',
   'Construye interpretaciones históricas', 'area', 1, true),
  ('c0000000-0000-4000-8000-000000000066', '84d84ee4-816d-4035-a1ad-55efeee4f11e',
   'c0000000-0000-4000-8000-000000000055', 'CCSS-C2',
   'Gestiona responsablemente el espacio y el ambiente', 'area', 2, true),
  ('c0000000-0000-4000-8000-000000000067', '84d84ee4-816d-4035-a1ad-55efeee4f11e',
   'c0000000-0000-4000-8000-000000000055', 'CCSS-C3',
   'Gestiona responsablemente los recursos económicos', 'area', 3, true),

  -- Las dos competencias transversales CNEB. subject_id nulo: no están
  -- adscritas a un área ni a un solo docente (5.1.1.3 p.8), y no cuentan
  -- para la promoción (5.1.3 p.9).
  ('c0000000-0000-4000-8000-000000000068', '84d84ee4-816d-4035-a1ad-55efeee4f11e',
   null, 'TR-C1',
   'Se desenvuelve en los entornos virtuales generados por las TIC', 'transversal', 1, true),
  ('c0000000-0000-4000-8000-000000000069', '84d84ee4-816d-4035-a1ad-55efeee4f11e',
   null, 'TR-C2',
   'Gestiona su aprendizaje de manera autónoma', 'transversal', 2, true);
