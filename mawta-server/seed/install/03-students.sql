-- ---------------------------------------------------------------------------
-- Los 10 estudiantes de 1ro A y su matrícula en la section.
--
-- DATOS PERSONALES DE MENORES — TODOS FICTICIOS.
-- Ningún nombre corresponde a una persona real. Los DNI (88000001-88000010) y
-- los códigos SIAGIE (2026000000000N) están fabricados con formato válido
-- para ejercitar los CHECK del esquema, pero fuera de cualquier rango emitido
-- por RENIEC o MINEDU. No cargar este archivo en una base con datos reales.
--
-- Nacidos en 2013: 12-13 años cumplidos en 2026, la edad normativa de 1ro de
-- secundaria.
-- ---------------------------------------------------------------------------

insert into students
  (id, tenant_id, student_code, siagie_code, given_name, paternal_surname,
   maternal_surname, preferred_name, birthdate, sex, document_type,
   document_number, enrolled_on, status, inclusion_support)
values
  ('c0000000-0000-4000-8000-000000000101', '84d84ee4-816d-4035-a1ad-55efeee4f11e',
   'EST-DEMO-2026-01', '20260000000001', 'Ana Lucía', 'Alvarado', 'Quispe',
   'Ana', '2013-04-17', 'F', 'DNI', '88000001', '2026-03-02', 'active', false),
  ('c0000000-0000-4000-8000-000000000102', '84d84ee4-816d-4035-a1ad-55efeee4f11e',
   'EST-DEMO-2026-02', '20260000000002', 'Bruno', 'Castillo', 'Mamani',
   null, '2013-09-02', 'M', 'DNI', '88000002', '2026-03-02', 'active', false),
  ('c0000000-0000-4000-8000-000000000103', '84d84ee4-816d-4035-a1ad-55efeee4f11e',
   'EST-DEMO-2026-03', '20260000000003', 'Camila', 'Flores', 'Huamán',
   null, '2013-01-25', 'F', 'DNI', '88000003', '2026-03-02', 'active', false),
  ('c0000000-0000-4000-8000-000000000104', '84d84ee4-816d-4035-a1ad-55efeee4f11e',
   'EST-DEMO-2026-04', '20260000000004', 'Diego', 'Gutiérrez', 'Ccahuana',
   null, '2013-06-11', 'M', 'DNI', '88000004', '2026-03-02', 'active', false),
  ('c0000000-0000-4000-8000-000000000105', '84d84ee4-816d-4035-a1ad-55efeee4f11e',
   'EST-DEMO-2026-05', '20260000000005', 'Elena', 'Herrera', 'Sulca',
   null, '2013-11-30', 'F', 'DNI', '88000005', '2026-03-02', 'active', false),
  ('c0000000-0000-4000-8000-000000000106', '84d84ee4-816d-4035-a1ad-55efeee4f11e',
   'EST-DEMO-2026-06', '20260000000006', 'Fabián', 'Ibáñez', 'Vargas',
   null, '2013-03-08', 'M', 'DNI', '88000006', '2026-03-02', 'active', false),
  ('c0000000-0000-4000-8000-000000000107', '84d84ee4-816d-4035-a1ad-55efeee4f11e',
   'EST-DEMO-2026-07', '20260000000007', 'Gabriela', 'Jiménez', 'Ticona',
   'Gaby', '2013-07-22', 'F', 'DNI', '88000007', '2026-03-02', 'active', false),
  ('c0000000-0000-4000-8000-000000000108', '84d84ee4-816d-4035-a1ad-55efeee4f11e',
   'EST-DEMO-2026-08', '20260000000008', 'Héctor', 'Lazo', 'Puma',
   null, '2013-02-14', 'M', 'DNI', '88000008', '2026-03-02', 'active', true),
  ('c0000000-0000-4000-8000-000000000109', '84d84ee4-816d-4035-a1ad-55efeee4f11e',
   'EST-DEMO-2026-09', '20260000000009', 'Isabel', 'Medina', 'Chávez',
   null, '2013-10-05', 'F', 'DNI', '88000009', '2026-03-02', 'active', false),
  ('c0000000-0000-4000-8000-000000000110', '84d84ee4-816d-4035-a1ad-55efeee4f11e',
   'EST-DEMO-2026-10', '20260000000010', 'Joaquín', 'Núñez', 'Apaza',
   null, '2013-05-19', 'M', 'DNI', '88000010', '2026-03-02', 'active', false);

-- section_memberships_one_at_a_time impide que un estudiante esté en dos
-- sections solapadas dentro del mismo año, así que "el roster de 1ro A en la
-- fecha D" es siempre un conjunto único. left_on nulo y status 'active' van
-- juntos por section_memberships_active_consistent.
insert into section_memberships
  (tenant_id, student_id, section_id, academic_year_id, joined_on, status)
select '84d84ee4-816d-4035-a1ad-55efeee4f11e', s.id,
       'c0000000-0000-4000-8000-000000000041',
       'c0000000-0000-4000-8000-000000000030', '2026-03-02', 'active'
  from students s
 where s.tenant_id = '84d84ee4-816d-4035-a1ad-55efeee4f11e'
   and s.student_code like 'EST-DEMO-2026-%';
