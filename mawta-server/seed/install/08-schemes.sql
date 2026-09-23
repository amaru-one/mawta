-- ---------------------------------------------------------------------------
-- Esquemas de calificación interna, uno por área.
--
-- Esto calcula el promedio INTERNO vigesimal del colegio — un insumo para el
-- docente, nunca el nivel de logro oficial.
--
-- Orden obligatorio, aprendido de fixture.sql:
--   1. scheme y components
--   2. version SIN publicar (forbid_publish_without_components es un trigger
--      BEFORE normal, no diferido: si se inserta ya publicada busca los pesos
--      y todavía no existen)
--   3. los pesos (check_component_weights_sum SÍ es DEFERRED y exige que
--      sumen exactamente 1 al hacer commit)
--   4. UPDATE que la publica
--
-- effective_from debe preceder al trimestre más antiguo que gobierna, o
-- class_effective_grading_schemes no resuelve nada para T-I.
-- ---------------------------------------------------------------------------

insert into grading_schemes (id, tenant_id, scale_id, code, name, description, is_active)
values
  ('c0000000-0000-4000-8000-000000000080', '84d84ee4-816d-4035-a1ad-55efeee4f11e',
   'c0000000-0000-4000-8000-000000000075', 'matematica_1ro',
   'Matemática 1ro — estándar', 'Prácticas 40%, exámenes 40%, proyectos 20%.', true),
  ('c0000000-0000-4000-8000-000000000085', '84d84ee4-816d-4035-a1ad-55efeee4f11e',
   'c0000000-0000-4000-8000-000000000075', 'ccss_1ro',
   'Ciencias Sociales 1ro — estándar', 'Fuentes 30%, exámenes 40%, proyecto 30%.', true);

insert into grading_components (id, tenant_id, scheme_id, code, name, sort_order)
values
  ('c0000000-0000-4000-8000-000000000081', '84d84ee4-816d-4035-a1ad-55efeee4f11e',
   'c0000000-0000-4000-8000-000000000080', 'practicas', 'Prácticas calificadas', 1),
  ('c0000000-0000-4000-8000-000000000082', '84d84ee4-816d-4035-a1ad-55efeee4f11e',
   'c0000000-0000-4000-8000-000000000080', 'examenes', 'Exámenes', 2),
  ('c0000000-0000-4000-8000-000000000083', '84d84ee4-816d-4035-a1ad-55efeee4f11e',
   'c0000000-0000-4000-8000-000000000080', 'proyectos', 'Proyectos', 3),
  ('c0000000-0000-4000-8000-000000000086', '84d84ee4-816d-4035-a1ad-55efeee4f11e',
   'c0000000-0000-4000-8000-000000000085', 'fuentes', 'Análisis de fuentes', 1),
  ('c0000000-0000-4000-8000-000000000087', '84d84ee4-816d-4035-a1ad-55efeee4f11e',
   'c0000000-0000-4000-8000-000000000085', 'examenes', 'Exámenes', 2),
  ('c0000000-0000-4000-8000-000000000088', '84d84ee4-816d-4035-a1ad-55efeee4f11e',
   'c0000000-0000-4000-8000-000000000085', 'proyecto', 'Proyecto integrador', 3);

-- min_evaluated_weight_for_grade = 0.20: no se muestra nota parcial hasta que
-- al menos el 20% del peso del trimestre esté evaluado, para no reportar "AD"
-- a partir de una sola práctica.
-- retake_policy 'capped' con tope 0.70 (= A): la recuperación pedagógica
-- peruana no debe poder producir un AD.
insert into grading_scheme_versions
  (id, tenant_id, scheme_id, version, effective_from, rounding_mode,
   rounding_decimals, absent_counts_as, retake_policy, retake_cap_normalized,
   min_evaluated_weight_for_grade, notes)
values
  ('c0000000-0000-4000-8000-000000000084', '84d84ee4-816d-4035-a1ad-55efeee4f11e',
   'c0000000-0000-4000-8000-000000000080', 1, '2026-01-01', 'half_up', 0,
   'zero', 'capped', 0.70, 0.20, 'Vigente todo el año escolar 2026.'),
  ('c0000000-0000-4000-8000-000000000089', '84d84ee4-816d-4035-a1ad-55efeee4f11e',
   'c0000000-0000-4000-8000-000000000085', 1, '2026-01-01', 'half_up', 0,
   'zero', 'capped', 0.70, 0.20, 'Vigente todo el año escolar 2026.');

-- drop_lowest_n = 1 en prácticas: se descarta la práctica más baja de cada
-- estudiante antes de promediar. Qué nota se descartó queda por estudiante en
-- computed_grade_components, para que el docente pueda explicar el número.
insert into grading_scheme_component_weights
  (tenant_id, scheme_version_id, component_id, weight, drop_lowest_n, aggregation, is_required)
values
  ('84d84ee4-816d-4035-a1ad-55efeee4f11e', 'c0000000-0000-4000-8000-000000000084',
   'c0000000-0000-4000-8000-000000000081', 0.40, 1, 'weighted_mean', true),
  ('84d84ee4-816d-4035-a1ad-55efeee4f11e', 'c0000000-0000-4000-8000-000000000084',
   'c0000000-0000-4000-8000-000000000082', 0.40, 0, 'weighted_mean', true),
  ('84d84ee4-816d-4035-a1ad-55efeee4f11e', 'c0000000-0000-4000-8000-000000000084',
   'c0000000-0000-4000-8000-000000000083', 0.20, 0, 'weighted_mean', true),
  ('84d84ee4-816d-4035-a1ad-55efeee4f11e', 'c0000000-0000-4000-8000-000000000089',
   'c0000000-0000-4000-8000-000000000086', 0.30, 0, 'weighted_mean', true),
  ('84d84ee4-816d-4035-a1ad-55efeee4f11e', 'c0000000-0000-4000-8000-000000000089',
   'c0000000-0000-4000-8000-000000000087', 0.40, 0, 'weighted_mean', true),
  ('84d84ee4-816d-4035-a1ad-55efeee4f11e', 'c0000000-0000-4000-8000-000000000089',
   'c0000000-0000-4000-8000-000000000088', 0.30, 0, 'weighted_mean', true);

update grading_scheme_versions
   set published_at = '2026-01-01 00:00:00-05',
       published_by_id = 'd74f215c-b8be-4f62-bdd0-f725fa25ab3f'
 where id in ('c0000000-0000-4000-8000-000000000084',
              'c0000000-0000-4000-8000-000000000089');
