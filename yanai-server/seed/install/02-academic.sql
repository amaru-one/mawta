-- ---------------------------------------------------------------------------
-- Año escolar 2026, sus tres trimestres, el grado y el aula de 10 estudiantes.
-- ---------------------------------------------------------------------------

insert into academic_years
  (id, tenant_id, year, name, starts_on, ends_on, term_structure, status)
values
  ('c0000000-0000-4000-8000-000000000030', '84d84ee4-816d-4035-a1ad-55efeee4f11e',
   2026, 'Año escolar 2026', '2026-03-02', '2026-12-18', 'trimestre', 'active');

-- terms_no_overlap usa daterange(starts_on, ends_on, '[]') — INCLUSIVO en
-- ambos extremos — así que dos trimestres consecutivos no pueden compartir
-- fecha de frontera: T-I cierra el 29-05 y T-II abre el 01-06, no el 29-05.
--
-- stage nulo: el colegio usa un solo calendario para todos los niveles.
--
-- LOS TRES ENTRAN 'active' A PROPÓSITO. app.sync_score_denormalised() es un
-- trigger BEFORE INSERT sobre scores que rechaza toda nota dirigida a un
-- trimestre 'closed' o 'archived' — la garantía de que una nota ya reportada
-- no cambia después. Por eso los tres quedan abiertos aquí: el cierre de T-I
-- y T-II ocurre al final de seed/seed_demo.sql, una vez cargada su
-- evidencia, igual que un grading_scheme_version se publica después de tener
-- sus pesos.
--
-- Si instalas un colegio SIN cargar datos de demostración, los tres
-- trimestres quedan abiertos, que es el estado correcto para un año que aún
-- no ha registrado nada.
-- terms_closed_consistent exige que (status in closed/archived) coincida
-- exactamente con (closed_at is not null), y se cumple en ambos momentos.
insert into terms
  (id, tenant_id, academic_year_id, stage, sequence, name, short_name,
   starts_on, ends_on, status, grades_due_on, closed_at, closed_by_id)
values
  ('c0000000-0000-4000-8000-000000000031', '84d84ee4-816d-4035-a1ad-55efeee4f11e',
   'c0000000-0000-4000-8000-000000000030', null, 1, 'Trimestre I', 'T-I',
   '2026-03-02', '2026-05-29', 'active', '2026-06-05', null, null),
  ('c0000000-0000-4000-8000-000000000032', '84d84ee4-816d-4035-a1ad-55efeee4f11e',
   'c0000000-0000-4000-8000-000000000030', null, 2, 'Trimestre II', 'T-II',
   '2026-06-01', '2026-08-28', 'active', '2026-09-04', null, null),
  ('c0000000-0000-4000-8000-000000000033', '84d84ee4-816d-4035-a1ad-55efeee4f11e',
   'c0000000-0000-4000-8000-000000000030', null, 3, 'Trimestre III', 'T-III',
   '2026-08-31', '2026-12-18', 'active', '2026-12-23', null, null);

-- ordinal 7 en la numeración 1-11 que cubre primaria y secundaria: 1ro de
-- secundaria es el séptimo grado de la escolaridad. cycle queda nulo — esa
-- columna solo tiene sentido en Inicial.
insert into grade_levels
  (id, tenant_id, code, label, long_label, stage, cycle, ordinal)
values
  ('c0000000-0000-4000-8000-000000000040', '84d84ee4-816d-4035-a1ad-55efeee4f11e',
   '1S', '1ro', 'Primero de secundaria', 'secundaria', null, 7);

-- El aula. Ambas clases (Matemática y Ciencias Sociales) apuntan a esta misma
-- section, que es lo que hace que compartan exactamente el mismo roster.
-- Jeffrey es además el tutor de aula.
insert into sections
  (id, tenant_id, academic_year_id, grade_level_id, label, name,
   tutor_teacher_id, shift, capacity, status)
values
  ('c0000000-0000-4000-8000-000000000041', '84d84ee4-816d-4035-a1ad-55efeee4f11e',
   'c0000000-0000-4000-8000-000000000030', 'c0000000-0000-4000-8000-000000000040',
   'A', '1ro A', 'd74f215c-b8be-4f62-bdd0-f725fa25ab3f', 'manana', 30, 'active');
