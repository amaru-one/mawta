-- ===========================================================================
-- Yanai — datos de demostración para I.E. San Felipe, 1ro A, año 2026.
--
-- QUÉ ES ESTO
--   El relleno: un año escolar vivido. Sesiones dictadas, asistencia,
--   evaluaciones con sus notas, valoraciones por criterio, niveles de logro
--   afirmados y conclusiones descriptivas. Sirve para ver la aplicación con
--   datos realistas y para probar; no es la instalación de un colegio.
--
-- NO CORRE SOLO
--   Requiere que ya se hayan ejecutado, en orden:
--     seed/install/01-create-school.sh
--     seed/install/02-academic.sql .. 09-classes.sql
--   Si no encuentra esa estructura, aborta sin insertar nada.
--
-- CÓMO SE EJECUTA
--   Como superusuario, contra la base que ya tiene la estructura:
--     psql "$ADMIN_DATABASE_URL" -v ON_ERROR_STOP=1 -f seed/seed_demo.sql
--   O pegándolo entero en el Query Tool de pgAdmin: no contiene ningún
--   comando con backslash.
--
-- EL TRIMESTRE EN VIVO
--   T-I y T-II se cierran al final de este archivo, con su evidencia dentro.
--   T-III queda ABIERTO y a medias: clases ya diseñadas hasta diciembre,
--   evaluaciones publicadas, notas solo de lo ya vencido, y NINGÚN nivel de
--   logro afirmado. El corte pasado/futuro se calcula con la fecha real en
--   Lima, así que el archivo envejece solo.
--
-- ORDEN QUE NO SE PUEDE ALTERAR
--   * Las notas entran ANTES de cerrar los trimestres (§10):
--     app.sync_score_denormalised() rechaza toda nota hacia un trimestre
--     cerrado, que es la garantía de que una nota reportada no cambia.
--   * La corrección de §9 marca superseded_at y luego inserta el reemplazo:
--     scores es append-only y un UPDATE lanza excepción.
--
-- DATOS FICTICIOS
--   Ningún estudiante corresponde a una persona real. NO EJECUTAR CONTRA UNA
--   BASE CON DATOS REALES.
--
-- BASE NORMATIVA
--   CNEB y RVM N° 094-2020-MINEDU. Las referencias entre paréntesis apuntan a
--   los numerales de esa norma.
-- ===========================================================================

begin;

-- Falla ruidosamente si falta la estructura, en vez de insertar a medias.
do $$
begin
  if not exists (select 1 from classes
                  where id = 'c0000000-0000-4000-8000-000000000052') then
    raise exception 'Falta la estructura del colegio. Ejecuta primero '
                    'seed/install/01-create-school.sh y luego 02-academic.sql '
                    'hasta 09-classes.sql.';
  end if;
  if exists (select 1 from class_sessions
              where class_id = 'c0000000-0000-4000-8000-000000000052') then
    raise exception 'Los datos de demostración ya están cargados. Este archivo '
                    'espera una estructura recién instalada; no borra nada.';
  end if;
end
$$;



-- §1 ==================================================================
-- ---------------------------------------------------------------------------
-- Sesiones de clase, generadas desde el patrón semanal.
--
-- "Las clases ya están diseñadas" para todo el año: cada franja de
-- class_schedules se expande a una sesión por cada fecha lectiva dentro de
-- los tres trimestres. Las pasadas quedan 'completed' con asistencia tomada;
-- las futuras 'scheduled' y sin asistencia.
--
-- El corte es la fecha ACTUAL EN LIMA, no current_date: el servidor corre en
-- UTC y America/Lima va cinco horas por detrás, así que current_date adelanta
-- el corte hasta cinco horas cada día. El colegio vive en su propia zona.
-- Recargar la plantilla en otro momento del año reparte pasado y futuro
-- correctamente sin editar nada.
--
-- class_sessions_started_consistent exige actual_start_at cuando el estado es
-- in_progress o completed; class_sessions_attendance_consistent exige que
-- attendance_taken_at y attendance_taken_by_id sean ambos nulos o ambos no.
-- ---------------------------------------------------------------------------

insert into class_sessions
  (id, tenant_id, academic_year_id, class_id, schedule_id, term_id,
   session_date, scheduled_start_at, scheduled_end_at,
   actual_start_at, actual_end_at, status, room,
   started_by_id, attendance_taken_at, attendance_taken_by_id)
select md5('sess:' || cs.id::text || ':' || d::text)::uuid,
       '84d84ee4-816d-4035-a1ad-55efeee4f11e',
       'c0000000-0000-4000-8000-000000000030',
       cs.class_id, cs.id, t.id, d,
       (d::date + cs.starts_at) at time zone 'America/Lima',
       (d::date + cs.ends_at)   at time zone 'America/Lima',
       case when d < (now() at time zone 'America/Lima')::date then (d::date + cs.starts_at) at time zone 'America/Lima' end,
       case when d < (now() at time zone 'America/Lima')::date then (d::date + cs.ends_at)   at time zone 'America/Lima' end,
       case when d < (now() at time zone 'America/Lima')::date then 'completed' else 'scheduled' end,
       cs.room,
       case when d < (now() at time zone 'America/Lima')::date then ct.teacher_id end,
       case when d < (now() at time zone 'America/Lima')::date then (d::date + cs.ends_at) at time zone 'America/Lima' end,
       case when d < (now() at time zone 'America/Lima')::date then ct.teacher_id end
  from class_schedules cs
  join class_teachers ct
    on ct.class_id = cs.class_id and ct.role = 'titular'
  join terms t
    on t.tenant_id = '84d84ee4-816d-4035-a1ad-55efeee4f11e'
  cross join lateral generate_series(t.starts_on, t.ends_on, interval '1 day') as g(d)
 where cs.tenant_id = '84d84ee4-816d-4035-a1ad-55efeee4f11e'
   and extract(isodow from g.d) = cs.weekday
   and g.d >= cs.effective_from;


-- §2 ==================================================================
-- ---------------------------------------------------------------------------
-- Asistencia de las sesiones ya dictadas.
--
-- El denominador se evalúa A LA FECHA DE LA SESIÓN, no a hoy: el roster sale
-- de section_memberships acotado por joined_on/left_on, así que un estudiante
-- que se retirara a mitad de año conservaría su asistencia previa y no
-- aparecería en las sesiones posteriores.
--
-- El reparto es determinista: un hash del par (sesión, estudiante) decide el
-- estado, así que recargar la plantilla da exactamente la misma asistencia.
-- Alrededor de 88% presente, 6% tarde, 3% ausente, 2% justificada, 1% excusada.
--
-- attendance_minutes_late_only_when_late: minutes_late debe ser nulo salvo
-- cuando el estado es 'late'.
-- excused = el colegio autorizó por adelantado; justified = se aceptó el
-- motivo después. Ninguna de las dos cuenta en contra del estudiante.
-- ---------------------------------------------------------------------------

insert into attendance_records
  (id, tenant_id, session_id, student_id, class_id, session_date,
   status, minutes_late, source, recorded_by_id, recorded_at)
select md5('att:' || cs.id::text || ':' || sm.student_id::text)::uuid,
       '84d84ee4-816d-4035-a1ad-55efeee4f11e',
       cs.id, sm.student_id, cs.class_id, cs.session_date,
       v.status,
       case when v.status = 'late' then 5 + (v.bucket % 20) end,
       'manual',
       cs.attendance_taken_by_id,
       cs.attendance_taken_at
  from class_sessions cs
  join section_memberships sm
    on sm.section_id = 'c0000000-0000-4000-8000-000000000041'
   and sm.joined_on <= cs.session_date
   and (sm.left_on is null or sm.left_on > cs.session_date)
  cross join lateral (
    select b, case
                when b < 88 then 'present'
                when b < 94 then 'late'
                when b < 97 then 'absent'
                when b < 99 then 'justified'
                else 'excused'
              end
      from (select ('x' || substr(md5('att:' || cs.id::text || ':' || sm.student_id::text), 1, 8))::bit(32)::bigint % 100 as b) q
  ) as v(bucket, status)
 where cs.status = 'completed';


-- §3 ==================================================================
-- ---------------------------------------------------------------------------
-- Evaluaciones.
--
-- El reparto por trimestre es deliberado y es lo que hace comprobable que
-- "sin fila" no significa "C" (5.1.2.2 p.1):
--
--            T-I                     T-II                    T-III (en curso)
--   MAT      C1, C2                  C2, C3                  C3, C4
--   CCSS     C1                      C1, C2                  C2
--
-- MAT-C4 no se toca hasta T-III; CCSS-C3 no se trabaja en todo el año. Un
-- reporte que lea esas ausencias como "En inicio" está mintiendo.
--
-- assessments_published_consistent obliga a published_at cuando el estado es
-- published o closed; assessments_max_score_matches_scale exige max_score
-- exactamente cuando value_scale es 'numeric'; y una rúbrica nunca puede
-- llevar counts_toward_internal = true (assessments_rubric_not_internal),
-- porque no tiene fila en scores de la que sacar un promedio.
--
-- Las de T-I y T-II van 'closed': su trimestre ya cerró y no admiten notas
-- nuevas. Las de T-III quedan 'published' — evaluación en vivo.
-- ---------------------------------------------------------------------------

insert into assessments
  (id, tenant_id, class_id, term_id, scheme_id, component_id, title, kind,
   value_scale, max_score, counts_toward_internal, weight_within_component,
   due_at, status, published_at, closed_at, created_by_id)
select md5('asm:' || v.code)::uuid,
       '84d84ee4-816d-4035-a1ad-55efeee4f11e',
       v.class_id::uuid, v.term_id::uuid, v.scheme_id::uuid, v.component_id::uuid,
       v.title, v.kind, v.value_scale,
       case when v.value_scale = 'numeric' then 20 end,
       (v.value_scale = 'numeric'), 1,
       (v.due::date + time '23:59') at time zone 'America/Lima',
       v.status,
       (v.published::date + time '08:00') at time zone 'America/Lima',
       case when v.status = 'closed'
            then (v.closed::date + time '18:00') at time zone 'America/Lima' end,
       v.created_by::uuid
  from (values
    -- ============================ MATEMÁTICA — T-I (cerrado) =============
    ('MAT-T1-P1','c0000000-0000-4000-8000-000000000052','c0000000-0000-4000-8000-000000000031','c0000000-0000-4000-8000-000000000080','c0000000-0000-4000-8000-000000000081','Práctica 1 — Números enteros','practica','numeric','closed','2026-03-20','2026-03-16','2026-06-08','d74f215c-b8be-4f62-bdd0-f725fa25ab3f'),
    ('MAT-T1-P2','c0000000-0000-4000-8000-000000000052','c0000000-0000-4000-8000-000000000031','c0000000-0000-4000-8000-000000000080','c0000000-0000-4000-8000-000000000081','Práctica 2 — Operaciones con racionales','practica','numeric','closed','2026-04-17','2026-04-13','2026-06-08','d74f215c-b8be-4f62-bdd0-f725fa25ab3f'),
    ('MAT-T1-P3','c0000000-0000-4000-8000-000000000052','c0000000-0000-4000-8000-000000000031','c0000000-0000-4000-8000-000000000080','c0000000-0000-4000-8000-000000000081','Práctica 3 — Ecuaciones lineales','practica','numeric','closed','2026-05-15','2026-05-11','2026-06-08','d74f215c-b8be-4f62-bdd0-f725fa25ab3f'),
    ('MAT-T1-EX','c0000000-0000-4000-8000-000000000052','c0000000-0000-4000-8000-000000000031','c0000000-0000-4000-8000-000000000080','c0000000-0000-4000-8000-000000000082','Examen de Trimestre I','examen','numeric','closed','2026-05-26','2026-05-18','2026-06-08','d74f215c-b8be-4f62-bdd0-f725fa25ab3f'),
    ('MAT-T1-PR','c0000000-0000-4000-8000-000000000052','c0000000-0000-4000-8000-000000000031','c0000000-0000-4000-8000-000000000080','c0000000-0000-4000-8000-000000000083','Proyecto — Presupuesto familiar','proyecto','numeric','closed','2026-05-22','2026-04-20','2026-06-08','d74f215c-b8be-4f62-bdd0-f725fa25ab3f'),
    ('MAT-T1-RU','c0000000-0000-4000-8000-000000000052','c0000000-0000-4000-8000-000000000031','c0000000-0000-4000-8000-000000000080','c0000000-0000-4000-8000-000000000083','Rúbrica — Argumentación matemática','proyecto','rubric','closed','2026-05-22','2026-04-20','2026-06-08','d74f215c-b8be-4f62-bdd0-f725fa25ab3f'),
    -- ============================ MATEMÁTICA — T-II (cerrado) ============
    ('MAT-T2-P1','c0000000-0000-4000-8000-000000000052','c0000000-0000-4000-8000-000000000032','c0000000-0000-4000-8000-000000000080','c0000000-0000-4000-8000-000000000081','Práctica 4 — Sistemas de ecuaciones','practica','numeric','closed','2026-06-19','2026-06-15','2026-09-07','d74f215c-b8be-4f62-bdd0-f725fa25ab3f'),
    ('MAT-T2-P2','c0000000-0000-4000-8000-000000000052','c0000000-0000-4000-8000-000000000032','c0000000-0000-4000-8000-000000000080','c0000000-0000-4000-8000-000000000081','Práctica 5 — Proporcionalidad','practica','numeric','closed','2026-07-17','2026-07-13','2026-09-07','d74f215c-b8be-4f62-bdd0-f725fa25ab3f'),
    ('MAT-T2-P3','c0000000-0000-4000-8000-000000000052','c0000000-0000-4000-8000-000000000032','c0000000-0000-4000-8000-000000000080','c0000000-0000-4000-8000-000000000081','Práctica 6 — Polígonos y perímetros','practica','numeric','closed','2026-08-14','2026-08-10','2026-09-07','d74f215c-b8be-4f62-bdd0-f725fa25ab3f'),
    ('MAT-T2-EX','c0000000-0000-4000-8000-000000000052','c0000000-0000-4000-8000-000000000032','c0000000-0000-4000-8000-000000000080','c0000000-0000-4000-8000-000000000082','Examen de Trimestre II','examen','numeric','closed','2026-08-25','2026-08-17','2026-09-07','d74f215c-b8be-4f62-bdd0-f725fa25ab3f'),
    ('MAT-T2-PR','c0000000-0000-4000-8000-000000000052','c0000000-0000-4000-8000-000000000032','c0000000-0000-4000-8000-000000000080','c0000000-0000-4000-8000-000000000083','Proyecto — Maqueta a escala','proyecto','numeric','closed','2026-08-21','2026-07-20','2026-09-07','d74f215c-b8be-4f62-bdd0-f725fa25ab3f'),
    -- ============================ MATEMÁTICA — T-III (EN VIVO) ===========
    ('MAT-T3-P1','c0000000-0000-4000-8000-000000000052','c0000000-0000-4000-8000-000000000033','c0000000-0000-4000-8000-000000000080','c0000000-0000-4000-8000-000000000081','Práctica 7 — Área y volumen','practica','numeric','published','2026-09-11','2026-09-07',null,'d74f215c-b8be-4f62-bdd0-f725fa25ab3f'),
    ('MAT-T3-P2','c0000000-0000-4000-8000-000000000052','c0000000-0000-4000-8000-000000000033','c0000000-0000-4000-8000-000000000080','c0000000-0000-4000-8000-000000000081','Práctica 8 — Tablas y gráficos estadísticos','practica','numeric','published','2026-09-18','2026-09-14',null,'d74f215c-b8be-4f62-bdd0-f725fa25ab3f'),
    ('MAT-T3-P3','c0000000-0000-4000-8000-000000000052','c0000000-0000-4000-8000-000000000033','c0000000-0000-4000-8000-000000000080','c0000000-0000-4000-8000-000000000081','Práctica 9 — Medidas de tendencia central','practica','numeric','published','2026-10-09','2026-09-21',null,'d74f215c-b8be-4f62-bdd0-f725fa25ab3f'),
    ('MAT-T3-EX','c0000000-0000-4000-8000-000000000052','c0000000-0000-4000-8000-000000000033','c0000000-0000-4000-8000-000000000080','c0000000-0000-4000-8000-000000000082','Examen de Trimestre III','examen','numeric','published','2026-12-04','2026-09-21',null,'d74f215c-b8be-4f62-bdd0-f725fa25ab3f'),
    -- ============================ CC.SS. — T-I (cerrado) =================
    ('CCS-T1-F1','c0000000-0000-4000-8000-000000000057','c0000000-0000-4000-8000-000000000031','c0000000-0000-4000-8000-000000000085','c0000000-0000-4000-8000-000000000086','Análisis de fuentes — Poblamiento americano','tarea','numeric','closed','2026-03-26','2026-03-19','2026-06-08','dd9d0f46-8518-4f83-9f98-5ab0c25b738b'),
    ('CCS-T1-F2','c0000000-0000-4000-8000-000000000057','c0000000-0000-4000-8000-000000000031','c0000000-0000-4000-8000-000000000085','c0000000-0000-4000-8000-000000000086','Análisis de fuentes — Culturas preincas','tarea','numeric','closed','2026-04-30','2026-04-23','2026-06-08','dd9d0f46-8518-4f83-9f98-5ab0c25b738b'),
    ('CCS-T1-EX','c0000000-0000-4000-8000-000000000057','c0000000-0000-4000-8000-000000000031','c0000000-0000-4000-8000-000000000085','c0000000-0000-4000-8000-000000000087','Examen de Trimestre I','examen','numeric','closed','2026-05-28','2026-05-19','2026-06-08','dd9d0f46-8518-4f83-9f98-5ab0c25b738b'),
    ('CCS-T1-PR','c0000000-0000-4000-8000-000000000057','c0000000-0000-4000-8000-000000000031','c0000000-0000-4000-8000-000000000085','c0000000-0000-4000-8000-000000000088','Proyecto — Línea de tiempo del Tahuantinsuyo','proyecto','numeric','closed','2026-05-21','2026-04-16','2026-06-08','dd9d0f46-8518-4f83-9f98-5ab0c25b738b'),
    -- ============================ CC.SS. — T-II (cerrado) ================
    ('CCS-T2-F1','c0000000-0000-4000-8000-000000000057','c0000000-0000-4000-8000-000000000032','c0000000-0000-4000-8000-000000000085','c0000000-0000-4000-8000-000000000086','Análisis de fuentes — Conquista y virreinato','tarea','numeric','closed','2026-06-25','2026-06-18','2026-09-07','dd9d0f46-8518-4f83-9f98-5ab0c25b738b'),
    ('CCS-T2-F2','c0000000-0000-4000-8000-000000000057','c0000000-0000-4000-8000-000000000032','c0000000-0000-4000-8000-000000000085','c0000000-0000-4000-8000-000000000086','Análisis de fuentes — Cartografía del Perú','tarea','numeric','closed','2026-07-30','2026-07-23','2026-09-07','dd9d0f46-8518-4f83-9f98-5ab0c25b738b'),
    ('CCS-T2-EX','c0000000-0000-4000-8000-000000000057','c0000000-0000-4000-8000-000000000032','c0000000-0000-4000-8000-000000000085','c0000000-0000-4000-8000-000000000087','Examen de Trimestre II','examen','numeric','closed','2026-08-27','2026-08-18','2026-09-07','dd9d0f46-8518-4f83-9f98-5ab0c25b738b'),
    ('CCS-T2-RU','c0000000-0000-4000-8000-000000000057','c0000000-0000-4000-8000-000000000032','c0000000-0000-4000-8000-000000000085','c0000000-0000-4000-8000-000000000088','Rúbrica — Exposición sobre el espacio geográfico','exposicion','rubric','closed','2026-08-20','2026-07-16','2026-09-07','dd9d0f46-8518-4f83-9f98-5ab0c25b738b'),
    -- ============================ CC.SS. — T-III (EN VIVO) ===============
    ('CCS-T3-F1','c0000000-0000-4000-8000-000000000057','c0000000-0000-4000-8000-000000000033','c0000000-0000-4000-8000-000000000085','c0000000-0000-4000-8000-000000000086','Análisis de fuentes — Cuencas y regiones naturales','tarea','numeric','published','2026-09-17','2026-09-10',null,'dd9d0f46-8518-4f83-9f98-5ab0c25b738b'),
    ('CCS-T3-EX','c0000000-0000-4000-8000-000000000057','c0000000-0000-4000-8000-000000000033','c0000000-0000-4000-8000-000000000085','c0000000-0000-4000-8000-000000000087','Examen de Trimestre III','examen','numeric','published','2026-12-03','2026-09-21',null,'dd9d0f46-8518-4f83-9f98-5ab0c25b738b')
  ) as v(code, class_id, term_id, scheme_id, component_id, title, kind,
         value_scale, status, due, published, closed, created_by);


-- §4 ==================================================================
-- ---------------------------------------------------------------------------
-- Qué criterios evalúa cada evidencia.
--
-- Este es el puente que hace reportable el logro POR COMPETENCIA: la
-- cobertura se deriva uniendo assessment_criteria -> evaluation_criteria
-- .competency_id. Sin estas filas, una evaluación es solo una nota suelta que
-- no dice nada sobre ninguna competencia.
--
-- El etiquetado realiza el reparto declarado en 12-assessments.sql.
-- ---------------------------------------------------------------------------

insert into assessment_criteria (tenant_id, assessment_id, criterion_id)
select '84d84ee4-816d-4035-a1ad-55efeee4f11e',
       md5('asm:'  || v.asm)::uuid,
       md5('crit:' || v.crit)::uuid
  from (values
    ('MAT-T1-P1','MAT-C1-CR1'),('MAT-T1-P1','MAT-C1-CR2'),
    ('MAT-T1-P2','MAT-C1-CR2'),('MAT-T1-P2','MAT-C1-CR3'),
    ('MAT-T1-P3','MAT-C2-CR1'),('MAT-T1-P3','MAT-C2-CR2'),
    ('MAT-T1-EX','MAT-C1-CR1'),('MAT-T1-EX','MAT-C2-CR1'),
    ('MAT-T1-PR','MAT-C1-CR3'),
    ('MAT-T1-RU','MAT-C1-CR3'),('MAT-T1-RU','MAT-C2-CR3'),
    ('MAT-T2-P1','MAT-C2-CR1'),('MAT-T2-P1','MAT-C2-CR2'),
    ('MAT-T2-P2','MAT-C2-CR2'),('MAT-T2-P2','MAT-C2-CR3'),
    ('MAT-T2-P3','MAT-C3-CR1'),('MAT-T2-P3','MAT-C3-CR2'),
    ('MAT-T2-EX','MAT-C2-CR1'),('MAT-T2-EX','MAT-C3-CR2'),
    ('MAT-T2-PR','MAT-C3-CR1'),
    ('MAT-T3-P1','MAT-C3-CR2'),
    ('MAT-T3-P2','MAT-C4-CR1'),
    ('MAT-T3-P3','MAT-C4-CR1'),('MAT-T3-P3','MAT-C4-CR2'),
    ('MAT-T3-EX','MAT-C3-CR2'),('MAT-T3-EX','MAT-C4-CR2'),
    ('CCS-T1-F1','CCSS-C1-CR1'),
    ('CCS-T1-F2','CCSS-C1-CR1'),('CCS-T1-F2','CCSS-C1-CR2'),
    ('CCS-T1-EX','CCSS-C1-CR2'),('CCS-T1-EX','CCSS-C1-CR3'),
    ('CCS-T1-PR','CCSS-C1-CR2'),
    ('CCS-T2-F1','CCSS-C1-CR1'),('CCS-T2-F1','CCSS-C1-CR3'),
    ('CCS-T2-F2','CCSS-C2-CR2'),
    ('CCS-T2-EX','CCSS-C1-CR3'),('CCS-T2-EX','CCSS-C2-CR1'),
    ('CCS-T2-RU','CCSS-C2-CR1'),('CCS-T2-RU','CCSS-C2-CR2'),('CCS-T2-RU','CCSS-C2-CR3'),
    ('CCS-T3-F1','CCSS-C2-CR2'),('CCS-T3-F1','CCSS-C2-CR3'),
    ('CCS-T3-EX','CCSS-C2-CR1'),('CCS-T3-EX','CCSS-C2-CR3')
  ) as v(asm, crit);


-- §5 ==================================================================
-- ---------------------------------------------------------------------------
-- Notas de las evaluaciones numéricas.
--
-- class_id y term_id NO se suministran: un trigger BEFORE INSERT los copia de
-- la assessment y falla si son inconsistentes.
--
-- Cada estudiante tiene una base de desempeño estable, con variación
-- determinista por evaluación. No es ruido decorativo: los niveles de logro
-- que se afirman más abajo deben poder sostenerse con la evidencia, y un
-- estudiante que rinde 18 en todo no puede terminar en "En proceso".
--
-- Fabián Ibáñez va bajo en Matemática de forma sostenida — es quien produce
-- el caso de C en dos trimestres consecutivos que obliga a una conclusión
-- descriptiva que justifique la falta de progreso (5.1.1.3 p.3).
--
-- T-III está EN CURSO: solo tienen notas las evaluaciones ya vencidas. El
-- Examen de Trimestre III (04-12 y 03-12) y la Práctica 9 (09-10) todavía no
-- tienen ninguna fila, que es lo que hace que el peso evaluado sea parcial.
-- ---------------------------------------------------------------------------

insert into scores
  (id, tenant_id, assessment_id, student_id, attempt_number, attempt_kind,
   status, raw_value, max_value, late_days, source, recorded_by_id, recorded_at)
select md5('score:' || a.id::text || ':' || st.id::text)::uuid,
       '84d84ee4-816d-4035-a1ad-55efeee4f11e',
       a.id, st.id, 1, 'original',
       g.status,
       case when g.status = 'graded' then g.val end,
       20,
       0, 'manual', a.created_by_id,
       a.due_at + interval '3 days'
  from assessments a
  join students st
    on st.tenant_id = '84d84ee4-816d-4035-a1ad-55efeee4f11e'
   and st.student_code like 'EST-DEMO-2026-%'
  cross join lateral (
    select h,
           -- base por estudiante, ajustada a la baja en Matemática para Fabián
           greatest(0, least(20,
             base + (h % 5) - 2
             - case when st.student_code = 'EST-DEMO-2026-06'
                     and a.class_id = 'c0000000-0000-4000-8000-000000000052'
                    then 3 else 0 end
           )) as val,
           case when h % 37 = 0 then 'absent'
                when h % 41 = 0 then 'not_submitted'
                else 'graded' end as status
      from (
        select ('x' || substr(md5('score:' || a.id::text || ':' || st.id::text), 1, 8))::bit(32)::bigint % 1000 as h,
               case st.student_code
                 when 'EST-DEMO-2026-01' then 18  -- Ana Lucía
                 when 'EST-DEMO-2026-02' then 16  -- Bruno
                 when 'EST-DEMO-2026-03' then 17  -- Camila
                 when 'EST-DEMO-2026-04' then 13  -- Diego
                 when 'EST-DEMO-2026-05' then 16  -- Elena
                 when 'EST-DEMO-2026-06' then 11  -- Fabián
                 when 'EST-DEMO-2026-07' then 15  -- Gabriela
                 when 'EST-DEMO-2026-08' then 12  -- Héctor
                 when 'EST-DEMO-2026-09' then 16  -- Isabel
                 else 12                          -- Joaquín
               end as base
      ) q
  ) as g(h, val, status)
 where a.value_scale = 'numeric'
   and a.tenant_id = '84d84ee4-816d-4035-a1ad-55efeee4f11e'
   -- solo lo ya vencido: T-III está en curso
   and a.due_at < (now() at time zone 'America/Lima');


-- §6 ==================================================================
-- ---------------------------------------------------------------------------
-- Valoración por criterio de las dos rúbricas.
--
-- Una assessment 'rubric' no tiene fila en scores: no lleva max_score ni nota
-- general, y se valora ÚNICAMENTE aquí, criterio por criterio, en la misma
-- escala ordinal AD/A/B/C que usa el nivel de competencia.
--
-- Esto no es un nivel de logro de la competencia. Es evidencia sobre un
-- criterio concreto; el nivel lo afirma el docente después, habiendo leído
-- todo el periodo.
--
-- criterion_scores_value_matches_scale: value_scale 'ordinal' exige
-- scale_level_id y prohíbe raw_value/max_value.
-- La FK a assessment_criteria impide valorar un criterio con el que la
-- evaluación nunca fue etiquetada.
-- ---------------------------------------------------------------------------

insert into criterion_scores
  (id, tenant_id, assessment_id, criterion_id, student_id, value_scale,
   scale_level_id, recorded_by_id, recorded_at)
select md5('cscore:' || ac.assessment_id::text || ':' || ac.criterion_id::text || ':' || st.id::text)::uuid,
       '84d84ee4-816d-4035-a1ad-55efeee4f11e',
       ac.assessment_id, ac.criterion_id, st.id, 'ordinal',
       lv.id, a.created_by_id, a.due_at + interval '4 days'
  from assessment_criteria ac
  join assessments a on a.id = ac.assessment_id
  join students st
    on st.tenant_id = '84d84ee4-816d-4035-a1ad-55efeee4f11e'
   and st.student_code like 'EST-DEMO-2026-%'
  cross join lateral (
    select case
             when b >= 85 then 'AD'
             when b >= 70 then 'A'
             when b >= 55 then 'B'
             else 'C'
           end as code
      from (
        select least(100, greatest(0,
                 case st.student_code
                   when 'EST-DEMO-2026-01' then 88 when 'EST-DEMO-2026-02' then 76
                   when 'EST-DEMO-2026-03' then 82 when 'EST-DEMO-2026-04' then 62
                   when 'EST-DEMO-2026-05' then 77 when 'EST-DEMO-2026-06' then 48
                   when 'EST-DEMO-2026-07' then 72 when 'EST-DEMO-2026-08' then 58
                   when 'EST-DEMO-2026-09' then 78 else 60 end
                 + (('x' || substr(md5('cs:' || ac.criterion_id::text || ':' || st.id::text), 1, 8))::bit(32)::bigint % 13) - 6
               )) as b
      ) q
  ) as g
  join grade_scale_levels lv
    on lv.scale_id = 'c0000000-0000-4000-8000-000000000070'
   and lv.code = g.code
 where a.value_scale = 'rubric';


-- §7 ==================================================================
-- ---------------------------------------------------------------------------
-- Niveles de logro por competencia y trimestre — EL REGISTRO OFICIAL.
--
-- Esta es la fila que va a SIAGIE y que al cierre del año decide la situación
-- final. Tres reglas de la RVM 094-2020 están materializadas aquí:
--
-- 1. LA AFIRMA EL DOCENTE, NO EL CÁLCULO (5.1.1.3 p.2-3). scale_level_id es
--    juicio humano. suggested_level_id guarda lo que Yanai propuso a partir
--    de la evidencia ponderada, y se conserva solo para medir cuántas veces
--    se anula la sugerencia — no tiene valor normativo. Dos estudiantes
--    llevan aquí una anulación deliberada del docente.
--
-- 2. SOLO T-I Y T-II. T-III está en curso: nadie ha afirmado nada todavía y
--    no debe existir ni una fila suya. Afirmar un nivel a mitad de periodo
--    es exactamente lo que la norma no quiere.
--
-- 3. LA AUSENCIA ES SIGNIFICATIVA (5.1.2.2 p.1). Solo se afirma nivel de las
--    competencias efectivamente trabajadas y evaluadas en el periodo. MAT-C4
--    no tiene ninguna fila antes de T-III y CCSS-C3 no tiene ninguna en todo
--    el año: no se desarrollaron. Leer esas ausencias como "C" sería inventar
--    un juicio que ningún docente emitió.
--
-- ctl_regular_key admite una sola fila vigente por (estudiante, competencia,
-- trimestre), así que una corrección debe marcar superseded_at antes de
-- insertar el reemplazo.
-- ---------------------------------------------------------------------------

with evidencia as (
  -- El promedio normalizado del estudiante en esa competencia y trimestre,
  -- derivado de la evidencia real ya registrada.
  select sc.student_id, a.term_id, a.class_id, ec.competency_id,
         avg(sc.raw_value / sc.max_value) as norm
    from scores sc
    join assessments a  on a.id = sc.assessment_id
    join assessment_criteria ac on ac.assessment_id = a.id
    join evaluation_criteria ec on ec.id = ac.criterion_id
   where sc.status = 'graded'
     and sc.superseded_at is null
   group by sc.student_id, a.term_id, a.class_id, ec.competency_id
),
sugerido as (
  select e.*, lv.id as sug_id, lv.ordinal as sug_ord
    from evidencia e
    join grade_scale_levels lv
      on lv.scale_id = 'c0000000-0000-4000-8000-000000000070'
     and e.norm >= lv.min_normalized
     and (e.norm < lv.max_normalized or lv.max_normalized = 1.00)
),
afirmado as (
  select s.*,
         -- Dos anulaciones deliberadas del docente:
         --   Diego (04) en CCSS-C1 de T-I sube un nivel: sostuvo en clase una
         --   explicación de proceso histórico que las pruebas escritas no
         --   capturaron.
         --   Camila (03) en MAT-C2 de T-II baja un nivel: el promedio daba
         --   destacado, pero la docente juzgó que la evidencia no sostenía
         --   "AD" en argumentación.
         case
           when st.student_code = 'EST-DEMO-2026-04'
            and s.competency_id = 'c0000000-0000-4000-8000-000000000065'
            and s.term_id = 'c0000000-0000-4000-8000-000000000031'
             then least(4, s.sug_ord + 1)
           when st.student_code = 'EST-DEMO-2026-03'
            and s.competency_id = 'c0000000-0000-4000-8000-000000000062'
            and s.term_id = 'c0000000-0000-4000-8000-000000000032'
             then greatest(1, s.sug_ord - 1)
           else s.sug_ord
         end as final_ord
    from sugerido s
    join students st on st.id = s.student_id
)
insert into competency_term_levels
  (id, tenant_id, student_id, competency_id, academic_year_id, term_id,
   class_id, scale_level_id, suggested_level_id, asserted_by_id, asserted_at, note)
select md5('ctl:' || a.student_id::text || ':' || a.competency_id::text || ':' || a.term_id::text)::uuid,
       '84d84ee4-816d-4035-a1ad-55efeee4f11e',
       a.student_id, a.competency_id, 'c0000000-0000-4000-8000-000000000030',
       a.term_id, a.class_id, fin.id, a.sug_id, ct.teacher_id,
       -- Fecha explícita, no derivada de terms.closed_at: en este punto del
       -- archivo los trimestres siguen abiertos (se cierran en 17) para que
       -- las notas hayan podido entrar. El docente afirma poco antes del
       -- cierre, que es como ocurre en un colegio.
       case t.sequence when 1 then timestamptz '2026-06-06 12:00:00-05'
                       when 2 then timestamptz '2026-09-05 12:00:00-05' end,
       case when a.final_ord <> a.sug_ord
            then 'Nivel afirmado por el docente apartándose de la sugerencia calculada.' end
  from afirmado a
  join grade_scale_levels fin
    on fin.scale_id = 'c0000000-0000-4000-8000-000000000070'
   and fin.ordinal = a.final_ord
  join class_teachers ct on ct.class_id = a.class_id and ct.role = 'titular'
  join terms t on t.id = a.term_id
 where t.sequence in (1, 2);

-- La transversal TR-C2 en T-II. Va aparte a propósito: no está adscrita a un
-- área ni a un solo docente (5.1.1.3 p.8), así que asserted_by_id queda NULO
-- y no hay class_id. suggested_level_id también es nulo: no se calculó nada,
-- porque ninguna assessment alimenta una competencia transversal. Es el caso
-- de "el docente afirmó sin ningún insumo calculado" en estado puro.
--
-- Y no cuenta para la promoción (5.1.3 p.9), por kind = 'transversal'.
insert into competency_term_levels
  (id, tenant_id, student_id, competency_id, academic_year_id, term_id,
   class_id, scale_level_id, suggested_level_id, asserted_by_id, asserted_at, note)
select md5('ctl-tr:' || st.id::text)::uuid,
       '84d84ee4-816d-4035-a1ad-55efeee4f11e',
       st.id, 'c0000000-0000-4000-8000-000000000069',
       'c0000000-0000-4000-8000-000000000030',
       'c0000000-0000-4000-8000-000000000032',
       null, lv.id, null, null,
       '2026-09-05 12:00:00-05',
       'Nivel acordado en reunión de docentes: la competencia transversal no pertenece a un área.'
  from students st
  join grade_scale_levels lv
    on lv.scale_id = 'c0000000-0000-4000-8000-000000000070'
   and lv.code = case
                   when st.student_code in ('EST-DEMO-2026-01','EST-DEMO-2026-03') then 'AD'
                   when st.student_code in ('EST-DEMO-2026-06','EST-DEMO-2026-08') then 'B'
                   else 'A'
                 end
 where st.tenant_id = '84d84ee4-816d-4035-a1ad-55efeee4f11e'
   and st.student_code like 'EST-DEMO-2026-%';


-- §8 ==================================================================
-- ---------------------------------------------------------------------------
-- Conclusiones descriptivas.
--
-- "Juicio docente basado en evidencias […] Señala avances, dificultades y
-- recomendaciones" (094-2020, glosario). En Secundaria son OBLIGATORIAS
-- cuando el nivel es C, y en dos casos adicionales:
--
--   * consecutive_c — C en dos o más periodos consecutivos. Además de
--     obligatoria, el texto DEBE justificar por qué no hay progreso
--     (5.1.1.3 p.3).
--   * inclusion_support — el estudiante enfrenta barreras educativas, así que
--     lleva una en TODO periodo sin importar el nivel, y debe indicar los
--     apoyos y ajustes razonables brindados (5.1.1.3 p.7).
--
-- Toda conclusión incluye recomendaciones personalizadas dentro del propio
-- body: no hay columna que lo afirme, porque nada puede verificar que un
-- texto libre realmente contenga una recomendación.
--
-- Precedencia aplicada cuando concurren varias razones:
--   consecutive_c > inclusion_support > level_c > optional
--
-- Solo una fila 'final' satisface un requisito obligatorio; un 'draft' no
-- desbloquea el cierre del periodo. Todas van 'final' salvo una, dejada en
-- draft a propósito para que ese camino tenga datos.
-- ---------------------------------------------------------------------------

with nivel as (
  select ctl.*, lv.code as nivel_code, lv.label as nivel_label,
         c.name as comp_name, t.sequence as seq
    from competency_term_levels ctl
    join grade_scale_levels lv on lv.id = ctl.scale_level_id
    join competencies c on c.id = ctl.competency_id
    join terms t on t.id = ctl.term_id
   where ctl.superseded_at is null
),
previo as (
  -- ¿La misma competencia estuvo en C en el trimestre inmediatamente anterior?
  select n.id, exists (
           select 1 from nivel p
            where p.student_id = n.student_id
              and p.competency_id = n.competency_id
              and p.seq = n.seq - 1
              and p.nivel_code = 'C'
         ) as c_previo
    from nivel n
),
clasificado as (
  select n.*, st.inclusion_support, st.given_name,
         case
           when n.nivel_code = 'C' and p.c_previo then 'consecutive_c'
           when st.inclusion_support                then 'inclusion_support'
           when n.nivel_code = 'C'                  then 'level_c'
           when n.nivel_code = 'AD'                 then 'optional'
           else null
         end as requisito
    from nivel n
    join previo p on p.id = n.id
    join students st on st.id = n.student_id
)
insert into descriptive_conclusions
  (id, tenant_id, student_id, competency_id, academic_year_id, term_id,
   class_id, body, requirement, status, authored_by_id, authored_at)
select md5('dc:' || cl.student_id::text || ':' || cl.competency_id::text || ':' || cl.term_id::text)::uuid,
       '84d84ee4-816d-4035-a1ad-55efeee4f11e',
       cl.student_id, cl.competency_id, cl.academic_year_id, cl.term_id,
       cl.class_id,
       case cl.requisito
         when 'consecutive_c' then
           cl.given_name || ' se mantiene en "En inicio" en «' || cl.comp_name ||
           '» por segundo periodo consecutivo. El trabajo del periodo muestra que '||
           'reconoce la tarea pero no logra sostener el procedimiento hasta el final, '||
           'y la dificultad es la misma que en el periodo anterior: no llega a apoyarse '||
           'en la representación previa antes de operar, así que las estrategias nuevas '||
           'no se afianzan sobre las anteriores. El apoyo brindado hasta ahora fue de '||
           'refuerzo grupal, insuficiente para este caso. Recomendaciones: '||
           'acompañamiento individual dos veces por semana centrado en representar '||
           'antes de calcular; retomar la evidencia del periodo anterior para que '||
           'compare sus propios procedimientos; y coordinación con la familia para '||
           'asegurar tiempo de trabajo en casa.'
         when 'inclusion_support' then
           cl.given_name || ' alcanza el nivel "' || cl.nivel_label || '" en «' ||
           cl.comp_name || '». Durante el periodo se brindaron los siguientes apoyos y '||
           'ajustes razonables: tiempo adicional en las evaluaciones escritas, '||
           'consignas segmentadas en pasos y ubicación preferente en el aula. '||
           'Con esos apoyos participa de forma sostenida y completa las tareas. '||
           'Recomendaciones: mantener los ajustes el próximo periodo, incorporar '||
           'organizadores visuales para las tareas de varios pasos, y revisar con '||
           'la familia y el equipo SAANEE la pertinencia de los apoyos actuales.'
         when 'level_c' then
           cl.given_name || ' se ubica en "En inicio" en «' || cl.comp_name ||
           '». Participa en las actividades y entrega sus trabajos, pero la evidencia '||
           'del periodo muestra que aún requiere acompañamiento para sostener el '||
           'procedimiento completo sin ayuda. Recomendaciones: retomar las tareas '||
           'entregadas señalando el punto exacto donde se interrumpe el razonamiento, '||
           'y practicar con situaciones de menor complejidad antes de volver a las '||
           'del nivel del grado.'
         else
           cl.given_name || ' alcanza el nivel "' || cl.nivel_label || '" en «' ||
           cl.comp_name || '»: resuelve con autonomía y fundamenta sus decisiones '||
           'apoyándose en la evidencia trabajada. Recomendaciones: proponerle '||
           'situaciones de mayor demanda cognitiva y darle un rol de apoyo entre '||
           'pares, cuidando que ello no reemplace su propio avance.'
       end,
       cl.requisito,
       -- Una sola queda en draft, para que ese camino tenga datos: un draft no
       -- satisface un requisito obligatorio ni desbloquea el cierre.
       case when cl.given_name = 'Joaquín' and cl.seq = 2 then 'draft' else 'final' end,
       coalesce(cl.asserted_by_id, 'd74f215c-b8be-4f62-bdd0-f725fa25ab3f'),
       case cl.seq when 1 then timestamptz '2026-06-06 15:00:00-05'
                   when 2 then timestamptz '2026-09-05 15:00:00-05' end
  from clasificado cl
 where cl.requisito is not null;


-- §9 ==================================================================
-- ---------------------------------------------------------------------------
-- Correcciones: la cadena de supersesión.
--
-- scores, criterion_scores, competency_term_levels y descriptive_conclusions
-- son APPEND-ONLY. Una corrección NO actualiza la fila: marca superseded_at
-- en la vigente e inserta el reemplazo con supersedes_id apuntando a ella.
-- En scores y criterion_scores esto lo impone un trigger forbid_mutation que
-- lanza excepción si cambia cualquier columna que no sea
-- superseded_at/deleted_at — la convención la hace cumplir la base, no solo
-- el código Go.
--
-- Sin al menos un ejemplo cargado, todo el camino de corrección queda sin
-- datos que lo ejerciten. Se corrige una nota de la Práctica 7 de Matemática
-- (T-III, en curso: el trimestre sigue abierto y admite la corrección).
-- ---------------------------------------------------------------------------

-- 1. Marcar la vigente como superada. Es lo único que el trigger permite
--    tocar en una fila existente.
update scores
   set superseded_at = timestamptz '2026-09-14 09:30:00-05'
 where id = md5('score:' || md5('asm:MAT-T3-P1')::uuid::text || ':'
                         || 'c0000000-0000-4000-8000-000000000105')::uuid;

-- 2. Insertar el reemplazo, encadenado con supersedes_id. La nota sube de su
--    valor original a 17: al revisar, la docente halló un ejercicio bien
--    resuelto que no se había contabilizado.
insert into scores
  (id, tenant_id, assessment_id, student_id, attempt_number, attempt_kind,
   status, raw_value, max_value, late_days, feedback, source,
   recorded_by_id, recorded_at, supersedes_id)
select md5('score-fix:' || sc.id::text)::uuid,
       sc.tenant_id, sc.assessment_id, sc.student_id, sc.attempt_number,
       sc.attempt_kind, 'graded', 17, sc.max_value, sc.late_days,
       'Recalificación: el ejercicio 4 estaba correcto y no se había sumado.',
       'manual', sc.recorded_by_id, timestamptz '2026-09-14 09:30:00-05', sc.id
  from scores sc
 where sc.id = md5('score:' || md5('asm:MAT-T3-P1')::uuid::text || ':'
                            || 'c0000000-0000-4000-8000-000000000105')::uuid;


-- §10 ==================================================================
-- ---------------------------------------------------------------------------
-- Cierre de los dos primeros trimestres. VA AL FINAL, no al crearlos.
--
-- app.sync_score_denormalised() rechaza toda nota dirigida a un trimestre
-- 'closed' o 'archived'. Es la garantía de que una nota ya reportada no
-- cambia después — y significa que el cierre solo puede ocurrir una vez que
-- toda la evidencia del periodo está dentro.
--
-- T-III NO se cierra: está en curso, y es lo que hace que la plantilla
-- represente un colegio trabajando y no un año terminado.
--
-- terms_closed_consistent exige que (status in closed/archived) coincida
-- exactamente con (closed_at is not null), así que ambas columnas se
-- escriben en la misma sentencia.
-- ---------------------------------------------------------------------------

update terms
   set status    = 'closed',
       closed_at = case sequence
                     when 1 then timestamptz '2026-06-08 17:00:00-05'
                     when 2 then timestamptz '2026-09-07 17:00:00-05'
                   end,
       closed_by_id = 'd74f215c-b8be-4f62-bdd0-f725fa25ab3f'
 where tenant_id = '84d84ee4-816d-4035-a1ad-55efeee4f11e'
   and sequence in (1, 2);

commit;
