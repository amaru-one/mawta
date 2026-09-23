-- ---------------------------------------------------------------------------
-- Cursos y las dos clases.
--
-- Ambas classes apuntan a la MISMA section (1ro A), que es lo que hace que
-- compartan roster: el listado de una clase se deriva de section_memberships,
-- así que los 10 estudiantes son exactamente los mismos en Matemática y en
-- Ciencias Sociales, sin duplicar una sola fila.
--
-- classes_course_fk y classes_section_fk son FK COMPUESTAS sobre
-- academic_year_id y grade_level_id: una class no puede mezclar una course de
-- un grado con una section de otro, ni cruzar años.
-- ---------------------------------------------------------------------------

insert into courses
  (id, tenant_id, academic_year_id, subject_id, grade_level_id, name,
   weekly_hours, grading_scheme_id)
values
  ('c0000000-0000-4000-8000-000000000051', '84d84ee4-816d-4035-a1ad-55efeee4f11e',
   'c0000000-0000-4000-8000-000000000030', 'c0000000-0000-4000-8000-000000000050',
   'c0000000-0000-4000-8000-000000000040', 'Matemática 1ro', 5.00,
   'c0000000-0000-4000-8000-000000000080'),
  ('c0000000-0000-4000-8000-000000000056', '84d84ee4-816d-4035-a1ad-55efeee4f11e',
   'c0000000-0000-4000-8000-000000000030', 'c0000000-0000-4000-8000-000000000055',
   'c0000000-0000-4000-8000-000000000040', 'Ciencias Sociales 1ro', 3.00,
   'c0000000-0000-4000-8000-000000000085');

insert into classes
  (id, tenant_id, academic_year_id, grade_level_id, course_id, section_id,
   name, code, default_room, status)
values
  ('c0000000-0000-4000-8000-000000000052', '84d84ee4-816d-4035-a1ad-55efeee4f11e',
   'c0000000-0000-4000-8000-000000000030', 'c0000000-0000-4000-8000-000000000040',
   'c0000000-0000-4000-8000-000000000051', 'c0000000-0000-4000-8000-000000000041',
   'Matemática 1ro A', 'MAT-1A', 'Aula 101', 'active'),
  ('c0000000-0000-4000-8000-000000000057', '84d84ee4-816d-4035-a1ad-55efeee4f11e',
   'c0000000-0000-4000-8000-000000000030', 'c0000000-0000-4000-8000-000000000040',
   'c0000000-0000-4000-8000-000000000056', 'c0000000-0000-4000-8000-000000000041',
   'Ciencias Sociales 1ro A', 'CCSS-1A', 'Aula 101', 'active');

-- Jeffrey dicta Matemática, Gonzalo Ciencias Sociales. Ambos 'titular':
-- class_teachers_one_titular impide dos titulares solapados en una misma
-- class, porque eso haría que "mis clases" se contara doble.
insert into class_teachers
  (tenant_id, class_id, teacher_id, role, starts_on)
values
  ('84d84ee4-816d-4035-a1ad-55efeee4f11e', 'c0000000-0000-4000-8000-000000000052',
   'd74f215c-b8be-4f62-bdd0-f725fa25ab3f', 'titular', '2026-03-02'),
  ('84d84ee4-816d-4035-a1ad-55efeee4f11e', 'c0000000-0000-4000-8000-000000000057',
   'dd9d0f46-8518-4f83-9f98-5ab0c25b738b', 'titular', '2026-03-02');

-- El patrón semanal. Matemática 5 h/sem repartidas en 3 franjas, Ciencias
-- Sociales 3 h/sem en 2 franjas. Las horas son locales (America/Lima) y no
-- se solapan entre sí: comparten el Aula 101 y el mismo grupo de alumnos.
insert into class_schedules
  (tenant_id, class_id, weekday, starts_at, ends_at, room, effective_from)
values
  ('84d84ee4-816d-4035-a1ad-55efeee4f11e', 'c0000000-0000-4000-8000-000000000052', 1, '08:00', '09:30', 'Aula 101', '2026-03-02'),
  ('84d84ee4-816d-4035-a1ad-55efeee4f11e', 'c0000000-0000-4000-8000-000000000052', 3, '08:00', '09:30', 'Aula 101', '2026-03-02'),
  ('84d84ee4-816d-4035-a1ad-55efeee4f11e', 'c0000000-0000-4000-8000-000000000052', 5, '10:00', '11:00', 'Aula 101', '2026-03-02'),
  ('84d84ee4-816d-4035-a1ad-55efeee4f11e', 'c0000000-0000-4000-8000-000000000057', 2, '08:00', '09:30', 'Aula 101', '2026-03-02'),
  ('84d84ee4-816d-4035-a1ad-55efeee4f11e', 'c0000000-0000-4000-8000-000000000057', 4, '10:00', '11:30', 'Aula 101', '2026-03-02');
