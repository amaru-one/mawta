-- Chat de dirección: lo que necesitan las herramientas del nivel 1
-- (chat-director D003): periodos, clases, alumnos, competencias y niveles de
-- logro del colegio de la sesión.
--
-- Las vistas solo entregan datos limpios. Las reglas del glosario (racha de C,
-- área no aprobada, proyección de promoción) viven en el SQL de cada
-- herramienta de mawta-chat, no aquí.
--
-- Mismo patrón que 00006: dueño mawta_chat_api (sin login, sin BYPASSRLS), así
-- que el RLS forzado de cada tabla aísla el colegio con el app.tenant_id de la
-- sesión del chat.

-- +goose Up

grant select on terms, classes, courses, subjects, class_teachers, teachers, students,
  section_memberships, competencies, competency_term_levels, grade_scale_levels
  to mawta_chat_api;

create view chat_api.terms as
select t.id,
       ay.year     as academic_year,
       ay.status   as academic_year_status,
       t.stage,
       t.sequence,
       t.name,
       t.short_name,
       t.starts_on,
       t.ends_on,
       t.status,
       (now() at time zone tn.timezone)::date between t.starts_on and t.ends_on as is_current,
       exists (
         select 1 from competency_term_levels l
          where l.tenant_id = t.tenant_id and l.term_id = t.id
            and l.superseded_at is null and l.deleted_at is null
       ) as has_levels
  from terms t
  join academic_years ay on ay.tenant_id = t.tenant_id and ay.id = t.academic_year_id
  join tenants tn        on tn.id = t.tenant_id
 where t.deleted_at is null
   and ay.deleted_at is null;

comment on view chat_api.terms is 'Periodos (bimestres, trimestres o semestres) del colegio de la sesión. is_current: contiene la fecha de hoy en la zona del colegio. has_levels: algún nivel de logro vigente se afirmó en el periodo; los niveles se afirman al cierre, así que el periodo en curso suele no tenerlos.';

create view chat_api.classes as
select c.id,
       ay.year       as academic_year,
       ay.status     as academic_year_status,
       g.label       as grade,
       g.long_label  as grade_long,
       g.ordinal     as grade_ordinal,
       g.stage,
       s.id          as section_id,
       s.label       as section,
       s.name        as section_name,
       s.shift,
       su.code       as subject_code,
       su.name       as subject_name,
       su.is_tutoria,
       titular.display_name as teacher,
       tutor.display_name   as tutor
  from classes c
  join sections s        on s.tenant_id = c.tenant_id and s.id = c.section_id
  join grade_levels g    on g.tenant_id = s.tenant_id and g.id = s.grade_level_id
  join academic_years ay on ay.tenant_id = s.tenant_id and ay.id = s.academic_year_id
  join courses co        on co.tenant_id = c.tenant_id and co.id = c.course_id
  join subjects su       on su.tenant_id = co.tenant_id and su.id = co.subject_id
  join tenants tn        on tn.id = c.tenant_id
  left join lateral (
    select te.display_name
      from class_teachers ct
      join teachers te on te.tenant_id = ct.tenant_id and te.id = ct.teacher_id
     where ct.tenant_id = c.tenant_id and ct.class_id = c.id and ct.role = 'titular'
       and ct.deleted_at is null and te.deleted_at is null
       and ct.starts_on <= (now() at time zone tn.timezone)::date
       and (ct.ends_on is null or ct.ends_on >= (now() at time zone tn.timezone)::date)
     order by ct.starts_on desc
     limit 1
  ) titular on true
  left join teachers tutor on tutor.tenant_id = s.tenant_id and tutor.id = s.tutor_teacher_id
                          and tutor.deleted_at is null
 where c.deleted_at is null
   and s.deleted_at is null
   and g.deleted_at is null
   and ay.deleted_at is null
   and co.deleted_at is null
   and su.deleted_at is null;

comment on view chat_api.classes is 'Clases del colegio de la sesión: el área que se dicta en cada sección, su docente titular vigente hoy y el tutor de la sección.';

create view chat_api.students as
select st.id         as student_id,
       st.given_name,
       st.preferred_name,
       st.paternal_surname,
       st.maternal_surname,
       concat_ws(' ', coalesce(st.preferred_name, st.given_name), st.paternal_surname,
                 st.maternal_surname) as full_name,
       ay.year       as academic_year,
       ay.status     as academic_year_status,
       g.label       as grade,
       g.long_label  as grade_long,
       g.ordinal     as grade_ordinal,
       g.stage,
       s.id          as section_id,
       s.label       as section,
       s.name        as section_name,
       sm.joined_on,
       sm.left_on,
       sm.status     as membership_status
  from section_memberships sm
  join students st       on st.tenant_id = sm.tenant_id and st.id = sm.student_id
  join sections s        on s.tenant_id = sm.tenant_id and s.id = sm.section_id
  join grade_levels g    on g.tenant_id = s.tenant_id and g.id = s.grade_level_id
  join academic_years ay on ay.tenant_id = sm.tenant_id and ay.id = sm.academic_year_id
 where sm.deleted_at is null
   and st.deleted_at is null
   and s.deleted_at is null
   and g.deleted_at is null
   and ay.deleted_at is null;

comment on view chat_api.students is 'DATOS PERSONALES DE MENORES (identificación). Una fila por matrícula de un alumno en una sección: nombre, sección, grado y fechas (left_on exclusiva, nula mientras sigue).';

create view chat_api.competencies as
select c.id,
       su.code       as subject_code,
       su.name       as subject_name,
       su.sort_order as subject_order,
       c.code,
       c.name,
       c.sort_order
  from competencies c
  join subjects su on su.tenant_id = c.tenant_id and su.id = c.subject_id
 where c.kind in ('area', 'adicional_area')
   and c.is_active
   and not su.is_tutoria
   and c.deleted_at is null
   and su.deleted_at is null;

comment on view chat_api.competencies is 'Competencias de área del colegio de la sesión. Las transversales (sin área) y las de tutoría quedan fuera: no cuentan para la promoción ni para los resúmenes por área.';

create view chat_api.levels as
select l.id,
       st.id         as student_id,
       concat_ws(' ', coalesce(st.preferred_name, st.given_name), st.paternal_surname,
                 st.maternal_surname) as full_name,
       st.paternal_surname,
       st.maternal_surname,
       ay.year       as academic_year,
       ay.status     as academic_year_status,
       g.label       as grade,
       g.long_label  as grade_long,
       g.ordinal     as grade_ordinal,
       g.stage,
       s.id          as section_id,
       s.label       as section,
       s.name        as section_name,
       su.code       as subject_code,
       su.name       as subject_name,
       su.sort_order as subject_order,
       c.code        as competency_code,
       c.name        as competency_name,
       c.sort_order  as competency_order,
       t.id          as term_id,
       t.sequence    as term_sequence,
       t.name        as term_name,
       t.short_name  as term_short_name,
       sl.code       as level,
       sl.ordinal    as level_ordinal
  from competency_term_levels l
  join students st          on st.tenant_id = l.tenant_id and st.id = l.student_id
  join competencies c       on c.tenant_id = l.tenant_id and c.id = l.competency_id
  join subjects su          on su.tenant_id = c.tenant_id and su.id = c.subject_id
  join terms t              on t.tenant_id = l.tenant_id and t.id = l.term_id
  join academic_years ay    on ay.tenant_id = l.tenant_id and ay.id = l.academic_year_id
  join grade_scale_levels sl on sl.tenant_id = l.tenant_id and sl.id = l.scale_level_id
  join classes cl           on cl.tenant_id = l.tenant_id and cl.id = l.class_id
  join sections s           on s.tenant_id = cl.tenant_id and s.id = cl.section_id
  join grade_levels g       on g.tenant_id = s.tenant_id and g.id = s.grade_level_id
 where l.superseded_at is null
   and l.deleted_at is null
   and c.kind in ('area', 'adicional_area')
   and not su.is_tutoria
   and st.deleted_at is null
   and c.deleted_at is null
   and su.deleted_at is null
   and t.deleted_at is null
   and ay.deleted_at is null
   and cl.deleted_at is null
   and s.deleted_at is null
   and g.deleted_at is null;

comment on view chat_api.levels is 'DATOS PERSONALES DE MENORES (académico, oficial). Los niveles de logro vigentes (la afirmación del docente que no fue corregida) de cada alumno por competencia de área y periodo, con la sección de la clase donde se afirmó. Sin fila = sin nivel, nunca C. Las competencias transversales, las de tutoría y las corregidas no aparecen.';

alter view chat_api.terms owner to mawta_chat_api;
alter view chat_api.classes owner to mawta_chat_api;
alter view chat_api.students owner to mawta_chat_api;
alter view chat_api.competencies owner to mawta_chat_api;
alter view chat_api.levels owner to mawta_chat_api;

grant select on chat_api.terms, chat_api.classes, chat_api.students, chat_api.competencies,
  chat_api.levels to mawta_chat;

-- +goose Down

drop view if exists chat_api.levels;
drop view if exists chat_api.competencies;
drop view if exists chat_api.students;
drop view if exists chat_api.classes;
drop view if exists chat_api.terms;

revoke select on terms, classes, courses, subjects, class_teachers, teachers, students,
  section_memberships, competencies, competency_term_levels, grade_scale_levels
  from mawta_chat_api;
