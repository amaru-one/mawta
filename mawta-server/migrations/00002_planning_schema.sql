-- Esquema de planificación de experiencias de aprendizaje (flujo "Plan del
-- trimestre"). Segunda migración: no reescribe nada de 00001, solo agrega.
--
-- Tabla de decisiones (resumen; el detalle vive en cada comentario de abajo):
--
--   | Decisión                                        | Qué se normalizó y por qué |
--   |-------------------------------------------------|------------------------------------------------------------------------------------|
--   | Experiencia de aprendizaje                      | Nueva tabla learning_experiences: una class, un term, fechas dentro del term, sin solaparse. Es la unidad de planificación del periodo; hoy no existía. |
--   | Criterio → capacidades (N:M)                   | evaluation_criteria.capability_id pasa a nullable y se copia a evaluation_criterion_capabilities. Un criterio mira una o más capacidades de su competencia; la FK compuesta (tenant_id, competency_id, capability_id) sigue probando la pertenencia. La columna vieja no se elimina para que el código actual siga corriendo. |
--   | Criterio anclado a la experiencia y al desempeño | evaluation_criteria gana experience_id y performance_id, ambos nullable: los criterios existentes (globales por competencia) siguen siendo válidos hasta que las pantallas nuevas los reemplacen. |
--   | Desempeños por grado                            | Nueva tabla grade_level_performances: texto oficial por competencia y grado, con la postura en_proceso/logra. El vínculo desempeño→capacidad (suggested_capability_id) es INFERIDO, no oficial: los programas no etiquetan desempeños por capacidad. |
--   | Estándares de aprendizaje                       | Nuevas tablas learning_standards (competencia, nivel 1-8, texto oficial) y standard_level_mappings ((modalidad, ciclo) → nivel esperado). Referencia de la conclusión descriptiva; NUNCA fuente de criterios. |
--   | Evidencias planificadas vs. assessments          | SE VINCULAN MÁS ADELANTE, no en esta migración. planned_evidences es la promesa de qué se observará y contra qué criterios; assessments es el ítem calificado que exige scheme y componente y alimenta el promedio interno. Unirlos aquí obligaría a decidir scheme/componente al planificar, lo que rompería el promedio interno. La tabla de decisiones del flujo (decisión 26) deja el enlace para el ticket que crea la evidencia real. |
--   | Esquema de sesiones                             | session_outline_entries: a lo sumo una fila por (experiencia, fecha de clase). Un bloque doble es una sola sesión, así que la unicidad es por fecha y no por franja horaria. |
--   | Días no laborables                              | non_teaching_days por año escolar, cargados en onboarding, para excluir feriados/vacaciones/gestión del conteo de sesiones. |
--   | Procedencia de propuestas                       | proposed_by ('mawta'/'teacher') + accepted_at en criterios, evidencias planificadas y entradas de esquema: una propuesta queda pendiente hasta que el docente la acepta o edita. |
--   | Seguimiento entre periodos                      | Sin tabla resumen: se calcula con una consulta sobre learning_experiences + experience_competencies (decisión 9 del flujo). |
--   | Fuera de alcance (diferido por decisión)        | Ajustes por estudiante, sistema de diseño, vista "Hoy" y agente de detalle de sesión. No se modelan aquí. |
--
-- Nada aquí calcula ni sugiere un nivel de logro oficial: el nivel es el
-- juicio del docente (RVM 094-2020 / RVM 048-2024) y vive en
-- competency_term_levels.

-- +goose Up

-- ---------------------------------------------------------------------------
-- grade_level_performances
-- ---------------------------------------------------------------------------
-- El desempeño de grado: el texto oficial del programa (RM 649-2016) que el
-- docente precisa en un criterio. Es dato curricular, cargado por onboarding,
-- nunca redactado por la app.
create table grade_level_performances (
  id                       uuid primary key default gen_random_uuid(),
  tenant_id                uuid not null references tenants (id),
  competency_id            uuid not null,
  grade_level_id           uuid not null,
  sort_order               smallint not null,
  official_text            text not null,
  en_proceso               boolean not null default false,
  expected_standard_level  smallint not null check (expected_standard_level between 1 and 8),
  suggested_capability_id  uuid,
  created_at               timestamptz not null default now(),
  updated_at               timestamptz not null default now(),
  deleted_at               timestamptz,
  constraint grade_level_performances_tenant_id_key unique (tenant_id, id),
  constraint grade_level_performances_competency_key unique (tenant_id, competency_id, id),
  constraint grade_level_performances_grade_key unique (tenant_id, grade_level_id, id),
  constraint grade_level_performances_competency_fk foreign key (tenant_id, competency_id)
    references competencies (tenant_id, id),
  constraint grade_level_performances_grade_fk foreign key (tenant_id, grade_level_id)
    references grade_levels (tenant_id, id),
  constraint grade_level_performances_suggested_capability_fk
    foreign key (tenant_id, competency_id, suggested_capability_id)
    references capabilities (tenant_id, competency_id, id)
);

comment on table grade_level_performances is
  'Los desempeños de grado del programa oficial: por competencia y por grado, con su texto oficial y su postura frente al estándar del ciclo. Es la única fuente de la que un criterio puede derivar (decisión 2 del flujo): un criterio es el precisado del docente de uno de estos textos en la situación de la experiencia.';
comment on column grade_level_performances.sort_order is
  'Posición del desempeño dentro de su competencia y grado. Los programas listan los desempeños en un orden pedagógico; ese orden se conserva para mostrarlos tal como aparecen en el documento oficial.';
comment on column grade_level_performances.official_text is
  'El texto literal del programa (RM 649-2016). Nunca se redacta ni se parafrasea en la app: el currículo no se inventa.';
comment on column grade_level_performances.en_proceso is
  'La postura del desempeño frente al estándar del ciclo: true = "en proceso hacia" el nivel esperado, false = "logra" el nivel esperado. Los programas de un grado intermedio describen avances hacia el estándar del fin de ciclo; los del grado final del ciclo describen el logro.';
comment on column grade_level_performances.expected_standard_level is
  'Nivel (1-8) del estándar de aprendizaje al que este desempeño apunta. Los programas lo declaran por grado; se guarda por fila para que el desempeño se lea junto al estándar correcto sin re-derivarlo del ciclo.';
comment on column grade_level_performances.suggested_capability_id is
  'INFERIDO, NO OFICIAL. Los programas no etiquetan desempeños por capacidad: este vínculo es una pista que se calcula al cargar el currículo y que el docente puede ignorar. Nunca reemplaza el juicio del docente sobre qué capacidades mira un criterio. La FK compuesta (tenant_id, competency_id, suggested_capability_id) garantiza que la pista apunte a una capacidad de la misma competencia.';

create unique index grade_level_performances_order_key
  on grade_level_performances (tenant_id, competency_id, grade_level_id, sort_order)
  where deleted_at is null;
create index grade_level_performances_grade_idx
  on grade_level_performances (grade_level_id) where deleted_at is null;

select app.enable_tenant_rls('grade_level_performances');
select app.attach_updated_at('grade_level_performances');
select app.attach_soft_delete_guard('grade_level_performances');

-- ---------------------------------------------------------------------------
-- learning_standards
-- ---------------------------------------------------------------------------
-- El estándar de aprendizaje: el texto oficial del CNEB por competencia y
-- nivel (1-8, un nivel por fin de ciclo). Referencia de la conclusión
-- descriptiva; NUNCA fuente de criterios (decisión 2 del flujo).
create table learning_standards (
  id             uuid primary key default gen_random_uuid(),
  tenant_id      uuid not null references tenants (id),
  competency_id  uuid not null,
  level          smallint not null check (level between 1 and 8),
  official_text  text not null,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now(),
  deleted_at     timestamptz,
  constraint learning_standards_tenant_id_key unique (tenant_id, id),
  constraint learning_standards_competency_key unique (tenant_id, competency_id, id),
  constraint learning_standards_competency_fk foreign key (tenant_id, competency_id)
    references competencies (tenant_id, id)
);

comment on table learning_standards is
  'Los estándares de aprendizaje del CNEB: por competencia y nivel (1-8), con su texto oficial. Son la referencia con la que se redacta la conclusión descriptiva de fin de ciclo, nunca una fuente de criterios: el criterio proviene del desempeño de grado, el estándar describe el punto de llegada del ciclo.';
comment on column learning_standards.level is
  'Nivel del estándar, 1-8: un nivel por fin de ciclo de la EBR. El mapeo (modalidad, ciclo) → nivel vive en standard_level_mappings.';
comment on column learning_standards.official_text is
  'El texto literal del CNEB. Nunca se redacta ni se parafrasea en la app.';

create unique index learning_standards_competency_level_key
  on learning_standards (tenant_id, competency_id, level) where deleted_at is null;

select app.enable_tenant_rls('learning_standards');
select app.attach_updated_at('learning_standards');
select app.attach_soft_delete_guard('learning_standards');

-- ---------------------------------------------------------------------------
-- standard_level_mappings
-- ---------------------------------------------------------------------------
-- (modalidad, ciclo) → nivel esperado del estándar. Necesario porque el nivel
-- del estándar no se deriva del grado: depende de la modalidad y del ciclo.
create table standard_level_mappings (
  id              uuid primary key default gen_random_uuid(),
  tenant_id       uuid not null references tenants (id),
  modality        text not null check (modality in ('ebr', 'ebe', 'eja')),
  cycle           text not null check (cycle in ('ciclo_i', 'ciclo_ii', 'ciclo_iii', 'ciclo_iv',
                                                 'ciclo_v', 'ciclo_vi', 'ciclo_vii')),
  expected_level  smallint not null check (expected_level between 1 and 8),
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  deleted_at      timestamptz,
  constraint standard_level_mappings_tenant_id_key unique (tenant_id, id)
);

comment on table standard_level_mappings is
  'Qué nivel de estándar (1-8) corresponde a cada combinación de modalidad y ciclo, ej. (ebr, ciclo_vii) → 7. Permite resolver "el estándar de fin de ciclo de esta class" a partir del grado, sin codificarlo en Go ni asumir que todos los colegios siguen la EBR regular.';
comment on column standard_level_mappings.modality is
  'Modalidad del servicio educativo: ebr (Educación Básica Regular), ebe (Educación Básica Especial), eja (Educación Básica Alternativa).';
comment on column standard_level_mappings.cycle is
  'Ciclo de la modalidad. En EBR: ciclo_i (0-2 años), ciclo_ii (3-5), ciclo_iii (1ro-2do primaria), ciclo_iv (3ro-4to), ciclo_v (5to-6to), ciclo_vi (1ro-2do secundaria), ciclo_vii (3ro-5to).';
comment on column standard_level_mappings.expected_level is
  'El nivel (1-8) del estándar de aprendizaje que cierra ese ciclo. Un ciclo termina en un nivel: este mapeo es la única fuente de esa correspondencia.';

create unique index standard_level_mappings_key
  on standard_level_mappings (tenant_id, modality, cycle) where deleted_at is null;

select app.enable_tenant_rls('standard_level_mappings');
select app.attach_updated_at('standard_level_mappings');
select app.attach_soft_delete_guard('standard_level_mappings');

-- ---------------------------------------------------------------------------
-- non_teaching_days
-- ---------------------------------------------------------------------------
-- Días sin clase del año escolar: feriados, rangos de vacaciones y días de
-- gestión. Los carga el colegio en onboarding, para que el conteo de sesiones
-- de una experiencia excluya lo que no es clase.
create table non_teaching_days (
  id                uuid primary key default gen_random_uuid(),
  tenant_id         uuid not null references tenants (id),
  academic_year_id  uuid not null,
  day               date not null,
  kind              text not null check (kind in ('feriado', 'vacaciones', 'gestion')),
  label             text,
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now(),
  deleted_at        timestamptz,
  constraint non_teaching_days_tenant_id_key unique (tenant_id, id),
  constraint non_teaching_days_year_key unique (tenant_id, academic_year_id, id),
  constraint non_teaching_days_year_fk foreign key (tenant_id, academic_year_id)
    references academic_years (tenant_id, id)
);

comment on table non_teaching_days is
  'Los días sin clase de un año escolar: feriados, vacaciones y días de gestión. Se cargan por onboarding (el colegio los declara, la app no los inventa) y sirven para excluir del conteo de sesiones de una experiencia las fechas que no son clase. Un rango de vacaciones se carga como una fila por día: el conteo y la exclusión son por fecha, y un rango obligaría a un chequeo de solapamiento de rangos para algo que es, en el fondo, un conjunto de fechas.';
comment on column non_teaching_days.kind is
  'feriado: fecha cívica o feriado nacional/regional. vacaciones: día dentro de un periodo de vacaciones del año escolar. gestion: día de gestión pedagógica o administrativa (los colegios lo usan para reuniones y planificación, sin estudiantes).';
comment on column non_teaching_days.label is
  'Nombre opcional para mostrar, ej. "San Pedro y San Pablo" o "Vacaciones de medio año". Null cuando el tipo basta.';

create unique index non_teaching_days_year_day_key
  on non_teaching_days (tenant_id, academic_year_id, day) where deleted_at is null;
create index non_teaching_days_year_idx
  on non_teaching_days (academic_year_id, day) where deleted_at is null;

select app.enable_tenant_rls('non_teaching_days');
select app.attach_updated_at('non_teaching_days');
select app.attach_soft_delete_guard('non_teaching_days');

-- ---------------------------------------------------------------------------
-- learning_experiences
-- ---------------------------------------------------------------------------
-- La experiencia de aprendizaje: la unidad con la que un docente planifica un
-- periodo para una class. Una class, un term, fechas dentro del term, sin
-- solaparse entre sí.
create table learning_experiences (
  id                uuid primary key default gen_random_uuid(),
  tenant_id         uuid not null references tenants (id),
  class_id          uuid not null,
  academic_year_id  uuid not null,
  term_id           uuid not null,
  title             text not null,
  idea_text          text not null,
  situation_text    text,
  starts_on         date not null,
  ends_on           date not null,
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now(),
  deleted_at        timestamptz,
  constraint learning_experiences_tenant_id_key unique (tenant_id, id),
  constraint learning_experiences_class_key unique (tenant_id, class_id, id),
  constraint learning_experiences_year_key unique (tenant_id, academic_year_id, id),
  constraint learning_experiences_class_fk foreign key (tenant_id, class_id)
    references classes (tenant_id, id),
  constraint learning_experiences_year_fk foreign key (tenant_id, academic_year_id)
    references academic_years (tenant_id, id),
  constraint learning_experiences_term_fk foreign key (tenant_id, academic_year_id, term_id)
    references terms (tenant_id, academic_year_id, id),
  constraint learning_experiences_range_valid check (starts_on <= ends_on),
  constraint learning_experiences_no_overlap
    exclude using gist (
      class_id with =,
      daterange(starts_on, ends_on, '[]') with &&
    ) where (deleted_at is null)
);

comment on table learning_experiences is
  'Una experiencia de aprendizaje: la unidad con la que un docente planifica un periodo para una class. Nace de la idea del docente (idea_text), se concreta en una situación (situation_text) y trabaja una o más competencias del área de la class (experience_competencies). Vive dentro de un term y sus fechas no pueden solaparse con las de otra experiencia de la misma class.';
comment on column learning_experiences.academic_year_id is
  'Copiado del term. No es una fuente independiente de verdad: existe para que learning_experiences_term_fk sea compuesta sobre él, lo que hace estructuralmente imposible que una experiencia apunte a un term de otro año escolar.';
comment on column learning_experiences.title is
  'Título con el que el docente reconoce la experiencia, ej. "La feria matemática del 5to B".';
comment on column learning_experiences.idea_text is
  'La idea original del docente, tal como la escribió en "Tengo una idea". Es la semilla de la experiencia y no se reescribe: la propuesta de Mawta se acepta o se edita aparte.';
comment on column learning_experiences.situation_text is
  'La situación significativa en la que la experiencia se desarrolla (CNEB). Null mientras aún no se ha redactado: la propuesta de Mawta puede llenarla, y el docente siempre decide.';
comment on column learning_experiences.starts_on is
  'Primer día de la experiencia, inclusive. Debe caer dentro del term (check_experience_inside_term) y no solaparse con otra experiencia de la misma class (learning_experiences_no_overlap).';
comment on column learning_experiences.ends_on is
  'Último día de la experiencia, inclusive. Misma regla que starts_on.';
comment on constraint learning_experiences_no_overlap on learning_experiences is
  'Dos experiencias no eliminadas de la misma class no pueden cubrir la misma fecha. El rango es inclusivo ''[]'': una experiencia que termina el lunes y otra que empieza ese mismo lunes se solapan — el docente no puede estar en dos experiencias a la vez.';

-- El term debe contener la experiencia. Un CHECK no puede consultar otra
-- tabla, así que esto es un trigger de restricción.
-- +goose StatementBegin
create or replace function app.check_experience_inside_term() returns trigger
  language plpgsql
  as $fn$
  declare
    v_term_starts date;
    v_term_ends   date;
  begin
    select t.starts_on, t.ends_on into v_term_starts, v_term_ends
      from terms t
     where t.tenant_id = new.tenant_id
       and t.id = new.term_id
       and t.deleted_at is null;

    if not found then
      raise exception 'term % not found in tenant %', new.term_id, new.tenant_id
        using errcode = 'foreign_key_violation';
    end if;

    if new.starts_on < v_term_starts or new.ends_on > v_term_ends then
      raise exception 'experience % (% .. %) falls outside its term (% .. %)',
        new.id, new.starts_on, new.ends_on, v_term_starts, v_term_ends
        using errcode = 'check_violation',
              hint = 'An experience must start and end inside its term.';
    end if;
    return new;
  end;
  $fn$;
-- +goose StatementEnd

create constraint trigger check_inside_term
  after insert or update of term_id, starts_on, ends_on on learning_experiences
  deferrable initially deferred
  for each row execute function app.check_experience_inside_term();

comment on function app.check_experience_inside_term() is
  'Un CHECK de fila no puede leer terms, así que el "dentro del term" es un trigger de restricción diferido: se dispara al COMMIT, lo que permite crear la experiencia y ajustar sus fechas en una misma transacción.';

-- El conteo de sesiones de una experiencia: por class y rango de fechas.
create index learning_experiences_class_range_idx
  on learning_experiences (class_id, starts_on, ends_on) where deleted_at is null;
-- "Tu trimestre": las experiencias del term de una class.
create index learning_experiences_term_idx
  on learning_experiences (term_id) where deleted_at is null;

select app.enable_tenant_rls('learning_experiences');
select app.attach_updated_at('learning_experiences');
select app.attach_soft_delete_guard('learning_experiences');

-- ---------------------------------------------------------------------------
-- experience_competencies
-- ---------------------------------------------------------------------------
-- El vínculo N:M experiencia ↔ competencia. Cada competencia vinculada debe
-- pertenecer al área de la course de la class: se exige por trigger, porque
-- la pertenencia no es una columna de esta fila sino un camino a través de
-- classes → courses → subjects.
create table experience_competencies (
  id              uuid primary key default gen_random_uuid(),
  tenant_id       uuid not null references tenants (id),
  experience_id   uuid not null,
  competency_id   uuid not null,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  deleted_at      timestamptz,
  constraint experience_competencies_tenant_id_key unique (tenant_id, id),
  constraint experience_competencies_experience_key unique (tenant_id, experience_id, id),
  constraint experience_competencies_competency_key unique (tenant_id, competency_id, id),
  constraint experience_competencies_experience_fk foreign key (tenant_id, experience_id)
    references learning_experiences (tenant_id, id),
  constraint experience_competencies_competency_fk foreign key (tenant_id, competency_id)
    references competencies (tenant_id, id)
);

comment on table experience_competencies is
  'Qué competencias trabaja una experiencia de aprendizaje. Una experiencia trabaja una o más competencias del área de la class (decisión 1 del flujo); esta tabla es ese vínculo N:M y es lo que hace computable el seguimiento entre periodos: qué competencia se trabajó en qué term es una consulta sobre esta tabla, sin tabla resumen.';
comment on constraint experience_competencies_experience_key on experience_competencies is
  'Permite que las tablas hijas lleven FKs compuestas (tenant_id, experience_id, ...) — la misma técnica que en 00001: una referencia entre tenants queda estructuralmente imposible.';

create unique index experience_competencies_pair_key
  on experience_competencies (tenant_id, experience_id, competency_id) where deleted_at is null;
create index experience_competencies_competency_idx
  on experience_competencies (competency_id) where deleted_at is null;

-- La competencia debe pertenecer al área de la course de la class de la
-- experiencia. Un CHECK no puede recorrer el camino classes → courses →
-- subjects, así que es un trigger.
-- +goose StatementBegin
create or replace function app.check_experience_competency_subject() returns trigger
  language plpgsql
  as $fn$
  declare
    v_subject uuid;
  begin
    select co.subject_id into v_subject
      from learning_experiences le
      join classes cl on cl.id = le.class_id and cl.tenant_id = le.tenant_id
      join courses co on co.id = cl.course_id and co.tenant_id = cl.tenant_id
     where le.id = new.experience_id
       and le.tenant_id = new.tenant_id
       and le.deleted_at is null;

    if not exists (
      select 1 from competencies c
       where c.id = new.competency_id
         and c.tenant_id = new.tenant_id
         and c.deleted_at is null
         and c.subject_id = v_subject
    ) then
      raise exception 'competency % does not belong to the subject of experience %''s class',
        new.competency_id, new.experience_id
        using errcode = 'foreign_key_violation',
              hint = 'An experience works competencies of its class''s subject only.';
    end if;
    return new;
  end;
  $fn$;
-- +goose StatementEnd

create trigger check_competency_subject before insert or update on experience_competencies
  for each row execute function app.check_experience_competency_subject();

comment on function app.check_experience_competency_subject() is
  'Cada competencia vinculada a una experiencia debe pertenecer al área de la course de la class. La pertenencia no es una columna de la fila (es un camino a través de classes → courses → subjects), así que no puede ser una FK compuesta ni un CHECK: es un trigger BEFORE que rechaza la fila.';

select app.enable_tenant_rls('experience_competencies');
select app.attach_updated_at('experience_competencies');
select app.attach_soft_delete_guard('experience_competencies');

-- ---------------------------------------------------------------------------
-- evaluation_criteria: anclaje a la experiencia y al desempeño
-- ---------------------------------------------------------------------------
-- Los criterios existentes son globales por competencia y siguen siéndolo:
-- experience_id y performance_id son nullable para que las pantallas actuales
-- no se rompan hasta que las nuevas los reemplacen.
alter table evaluation_criteria add column experience_id uuid;
alter table evaluation_criteria add column performance_id uuid;
alter table evaluation_criteria add column proposed_by text not null default 'teacher'
  check (proposed_by in ('mawta', 'teacher'));
alter table evaluation_criteria add column accepted_at timestamptz;

comment on column evaluation_criteria.experience_id is
  'La experiencia a la que pertenece este criterio. Null para los criterios globales por competencia que ya existían: siguen siendo válidos y visibles en las pantallas actuales hasta que el flujo de planificación los reemplace. La FK es compuesta (tenant_id, experience_id), así que un criterio no puede apuntar a una experiencia de otro tenant.';
comment on column evaluation_criteria.performance_id is
  'El desempeño de grado del que este criterio deriva (decisión 2 del flujo): un criterio es el precisado del docente de ese desempeño en la situación de la experiencia. Null cuando el docente lo escribió sin partir de un desempeño cargado. La FK compuesta (tenant_id, competency_id, performance_id) prueba que el desempeño es de la misma competencia del criterio.';
comment on column evaluation_criteria.proposed_by is
  'Quién redactó el criterio: ''mawta'' (propuesta del asistente) o ''teacher'' (el docente). El default es ''teacher'' para que los criterios existentes, migrados sin este dato, no aparezcan como propuestas de la máquina.';
comment on column evaluation_criteria.accepted_at is
  'Cuándo el docente aceptó o editó la propuesta. Null mientras la propuesta está pendiente: una propuesta de Mawta no es un criterio hasta que el docente la acepta o la edita.';

alter table evaluation_criteria
  add constraint evaluation_criteria_experience_fk foreign key (tenant_id, experience_id)
    references learning_experiences (tenant_id, id);
alter table evaluation_criteria
  add constraint evaluation_criteria_performance_fk
    foreign key (tenant_id, competency_id, performance_id)
    references grade_level_performances (tenant_id, competency_id, id);

-- El criterio debe pertenecer a la experiencia a la que dice pertenecer, y su
-- competencia debe estar vinculada a esa experiencia. Ninguna FK puede ver
-- ambas cosas a la vez, así que es un trigger.
-- +goose StatementBegin
create or replace function app.check_criterion_experience() returns trigger
  language plpgsql
  as $fn$
  begin
    if new.experience_id is null then
      return new;
    end if;

    if not exists (
      select 1
        from experience_competencies ec
       where ec.tenant_id = new.tenant_id
         and ec.experience_id = new.experience_id
         and ec.competency_id = new.competency_id
         and ec.deleted_at is null
    ) then
      raise exception 'competency % is not worked by experience %',
        new.competency_id, new.experience_id
        using errcode = 'foreign_key_violation',
              hint = 'Link the competency to the experience in experience_competencies first.';
    end if;
    return new;
  end;
  $fn$;
-- +goose StatementEnd

create trigger check_criterion_experience before insert or update
  of experience_id, competency_id on evaluation_criteria
  for each row execute function app.check_criterion_experience();

comment on function app.check_criterion_experience() is
  'Un criterio anclado a una experiencia solo puede hablar de una competencia que esa experiencia trabaja. Ninguna FK compuesta puede expresar esto (la fila de experience_competencies no existe todavía cuando se crea el criterio), así que es un trigger BEFORE.';

create index evaluation_criteria_experience_idx
  on evaluation_criteria (experience_id) where experience_id is not null and deleted_at is null;
create index evaluation_criteria_performance_idx
  on evaluation_criteria (performance_id) where performance_id is not null and deleted_at is null;

-- ---------------------------------------------------------------------------
-- evaluation_criterion_capabilities
-- ---------------------------------------------------------------------------
-- El vínculo N:M criterio ↔ capacidad. Un criterio mira una o más capacidades
-- de su competencia; la FK compuesta (tenant_id, competency_id,
-- capability_id) prueba la pertenencia.
create table evaluation_criterion_capabilities (
  id             uuid primary key default gen_random_uuid(),
  tenant_id      uuid not null references tenants (id),
  criterion_id   uuid not null,
  competency_id  uuid not null,
  capability_id  uuid not null,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now(),
  deleted_at     timestamptz,
  constraint evaluation_criterion_capabilities_tenant_id_key unique (tenant_id, id),
  constraint evaluation_criterion_capabilities_criterion_key unique (tenant_id, criterion_id, id),
  constraint evaluation_criterion_capabilities_criterion_fk
    foreign key (tenant_id, criterion_id) references evaluation_criteria (tenant_id, id),
  constraint evaluation_criterion_capabilities_capability_fk
    foreign key (tenant_id, competency_id, capability_id)
    references capabilities (tenant_id, competency_id, id)
);

comment on table evaluation_criterion_capabilities is
  'Qué capacidades mira un criterio de evaluación. Un criterio mira una o más capacidades de su competencia (N:M, decisión 2 del flujo): ser competente es usar las capacidades de forma combinada, así que un criterio puede mirar más de una. competency_id se desnormaliza del criterio para que la FK compuesta hacia capabilities pueda probar que la capacidad pertenece a la misma competencia.';
comment on column evaluation_criterion_capabilities.competency_id is
  'Desnormalizado desde el criterio. No es una fuente independiente de verdad: existe para que la FK compuesta (tenant_id, competency_id, capability_id) haga estructuralmente imposible vincular una capacidad de otra competencia.';
comment on constraint evaluation_criterion_capabilities_criterion_key on evaluation_criterion_capabilities is
  'Permite que otras tablas lleven FKs compuestas hacia esta, y mantiene la técnica de 00001: una referencia entre tenants es imposible.';

create unique index evaluation_criterion_capabilities_pair_key
  on evaluation_criterion_capabilities (tenant_id, criterion_id, capability_id)
  where deleted_at is null;
create index evaluation_criterion_capabilities_capability_idx
  on evaluation_criterion_capabilities (capability_id) where deleted_at is null;

-- La competencia desnormalizada debe coincidir con la del criterio. La FK
-- compuesta hacia evaluation_criteria no puede expresar esa igualdad.
-- +goose StatementBegin
create or replace function app.check_criterion_capability_competency() returns trigger
  language plpgsql
  as $fn$
  declare
    v_competency uuid;
  begin
    select ec.competency_id into v_competency
      from evaluation_criteria ec
     where ec.id = new.criterion_id
       and ec.tenant_id = new.tenant_id;

    if v_competency is distinct from new.competency_id then
      raise exception 'criterion % belongs to competency %, not %',
        new.criterion_id, v_competency, new.competency_id
        using errcode = 'foreign_key_violation',
              hint = 'Copy the criterion''s competency_id; do not supply your own.';
    end if;
    return new;
  end;
  $fn$;
-- +goose StatementEnd

create trigger check_criterion_capability_competency
  before insert or update of criterion_id, competency_id on evaluation_criterion_capabilities
  for each row execute function app.check_criterion_capability_competency();

comment on function app.check_criterion_capability_competency() is
  'La competency_id desnormalizada debe ser exactamente la del criterio. Sin esto, una fila podría pasar la FK compuesta hacia capabilities apuntando a una capacidad de la competencia correcta mientras el criterio habla de otra.';

select app.enable_tenant_rls('evaluation_criterion_capabilities');
select app.attach_updated_at('evaluation_criterion_capabilities');
select app.attach_soft_delete_guard('evaluation_criterion_capabilities');

-- La columna vieja pasa a nullable: el vínculo vive en la tabla de join. No se
-- elimina para que el código actual (que la lee y la escribe) siga corriendo.
alter table evaluation_criteria alter column capability_id drop not null;

comment on column evaluation_criteria.capability_id is
  'DEPRECATED: el vínculo criterio ↔ capacidad vive en evaluation_criterion_capabilities, que permite varias capacidades por criterio. Esta columna se mantiene (nullable, no eliminada) para que el código actual siga corriendo mientras las pantallas nuevas la reemplazan; la migración copió su valor a la tabla de join.';

-- Backfill: cada criterio existente conserva su capacidad en la tabla de
-- join, de modo que nada de lo que ya funciona deja de funcionar.
insert into evaluation_criterion_capabilities (tenant_id, criterion_id, competency_id, capability_id)
select ec.tenant_id, ec.id, ec.competency_id, ec.capability_id
  from evaluation_criteria ec
 where ec.capability_id is not null
   and not exists (
     select 1 from evaluation_criterion_capabilities x
      where x.tenant_id = ec.tenant_id
        and x.criterion_id = ec.id
        and x.capability_id = ec.capability_id
   );

-- Un criterio no eliminado mira al menos una capacidad. Un CHECK de fila no
-- puede contar filas hermanas, así que es un trigger de restricción diferido:
-- se dispara al COMMIT, lo que permite insertar el criterio y sus capacidades
-- en una misma transacción.
--
-- La columna vieja capability_id cuenta como vínculo: el código actual
-- (repo.CreateCriterion, el onboarding) todavía escribe esa columna y no
-- inserta filas en la tabla de join, y esta migración no puede romperlo. El
-- backfill de arriba copió su valor a la tabla de join, así que en la práctica
-- todo criterio tiene su vínculo normalizado; la tolerancia existe solo para
-- que el camino viejo siga corriendo hasta que las pantallas nuevas lo
-- reemplacen.
-- +goose StatementBegin
create or replace function app.check_criterion_has_capability() returns trigger
  language plpgsql
  as $fn$
  declare
    v_criterion uuid;
    v_tenant    uuid;
  begin
    if tg_op = 'DELETE' then
      v_criterion := old.criterion_id;
      v_tenant    := old.tenant_id;
    else
      v_criterion := new.criterion_id;
      v_tenant    := new.tenant_id;
    end if;

    -- El criterio pudo haberse eliminado en la misma transacción; no hay nada
    -- que verificar.
    if not exists (select 1 from evaluation_criteria ec
                    where ec.id = v_criterion
                      and ec.tenant_id = v_tenant
                      and ec.deleted_at is null) then
      return null;
    end if;

    if not exists (
      select 1 from evaluation_criterion_capabilities x
       where x.criterion_id = v_criterion
         and x.deleted_at is null
    ) and not exists (
      select 1 from evaluation_criteria ec
       where ec.id = v_criterion
         and ec.deleted_at is null
         and ec.capability_id is not null
    ) then
      raise exception 'criterion % has no capabilities left',
        v_criterion
        using errcode = 'check_violation',
              hint = 'A criterion looks at one or more capabilities of its competency.';
    end if;
    return null;
  end;
  $fn$;
-- +goose StatementEnd

create constraint trigger check_criterion_capabilities
  after insert or update or delete on evaluation_criterion_capabilities
  deferrable initially deferred
  for each row execute function app.check_criterion_has_capability();

-- Insertar un criterio sin capacidades también debe fallar: el trigger de
-- arriba no se dispara si nunca se inserta una fila en la tabla de join.
-- +goose StatementBegin
create or replace function app.check_criterion_has_capability_on_write() returns trigger
  language plpgsql
  as $fn$
  begin
    if new.deleted_at is not null then
      return null;
    end if;

    if not exists (
      select 1 from evaluation_criterion_capabilities x
       where x.criterion_id = new.id
         and x.deleted_at is null
    ) and new.capability_id is null then
      raise exception 'criterion % has no capabilities',
        new.id
        using errcode = 'check_violation',
              hint = 'Insert the criterion and its capabilities in the same transaction.';
    end if;
    return null;
  end;
  $fn$;
-- +goose StatementEnd

create constraint trigger check_criterion_on_write
  after insert or update of deleted_at, capability_id on evaluation_criteria
  deferrable initially deferred
  for each row execute function app.check_criterion_has_capability_on_write();

comment on function app.check_criterion_has_capability() is
  'Un criterio no eliminado mira al menos una capacidad (decisión 2 del flujo), sea a través de evaluation_criterion_capabilities (camino nuevo, N:M) o de la columna vieja capability_id (camino legacy que esta migración no rompe). Diferido al COMMIT: crear un criterio y sus capacidades en una misma transacción es el caso normal, y sin la deferral ese insert sería imposible.';

-- ---------------------------------------------------------------------------
-- planned_evidences
-- ---------------------------------------------------------------------------
-- La evidencia planificada: qué se va a observar en la experiencia y contra
-- qué criterios. No es la evidencia real (assessments): el enlace se hace en
-- un ticket posterior (ver la tabla de decisiones del encabezado).
create table planned_evidences (
  id               uuid primary key default gen_random_uuid(),
  tenant_id        uuid not null references tenants (id),
  experience_id    uuid not null,
  name             text not null,
  kind             text not null check (kind in ('produccion', 'actuacion', 'prueba_escrita')),
  session_entry_id uuid,
  proposed_by      text not null default 'teacher' check (proposed_by in ('mawta', 'teacher')),
  accepted_at      timestamptz,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now(),
  deleted_at       timestamptz,
  constraint planned_evidences_tenant_id_key unique (tenant_id, id),
  constraint planned_evidences_experience_key unique (tenant_id, experience_id, id),
  constraint planned_evidences_experience_fk foreign key (tenant_id, experience_id)
    references learning_experiences (tenant_id, id)
);

comment on table planned_evidences is
  'Una evidencia planificada dentro de una experiencia: qué se va a observar (name), de qué tipo (kind) y contra qué criterios (planned_evidence_criteria). Es una PROMESA, no la evidencia real: la evidencia calificada sigue siendo assessments, que exige scheme y componente y alimenta el promedio interno. El enlace entre ambas se hace en un ticket posterior, cuando exista el flujo que crea la evidencia real.';
comment on column planned_evidences.kind is
  'produccion: un producto (maqueta, informe, portafolio). actuacion: una actuación (exposición, debate, demostración). prueba_escrita: una prueba escrita. La norma (RVM 094-2020) pide evidencias de distinto tipo por competencia; el tipo se restringe aquí para que el conteo por tipo sea confiable.';
comment on column planned_evidences.session_entry_id is
  'La entrada del esquema de sesiones donde se planea recoger esta evidencia. Null cuando aún no se ha ubicado en una sesión. La FK es compuesta (tenant_id, experience_id, session_entry_id), así que la evidencia no puede ubicarse en una sesión de otra experiencia.';
comment on column planned_evidences.proposed_by is
  'Quién propuso la evidencia: ''mawta'' (el asistente) o ''teacher'' (el docente). El default es ''teacher''.';
comment on column planned_evidences.accepted_at is
  'Cuándo el docente aceptó o editó la propuesta. Null mientras está pendiente.';

create index planned_evidences_experience_idx
  on planned_evidences (experience_id) where deleted_at is null;

select app.enable_tenant_rls('planned_evidences');
select app.attach_updated_at('planned_evidences');
select app.attach_soft_delete_guard('planned_evidences');

-- ---------------------------------------------------------------------------
-- session_outline_entries
-- ---------------------------------------------------------------------------
-- El esquema de sesiones de una experiencia: a lo sumo una entrada por fecha
-- de clase. Un bloque doble es una sola sesión (decisión 15 del flujo).
create table session_outline_entries (
  id                  uuid primary key default gen_random_uuid(),
  tenant_id           uuid not null references tenants (id),
  experience_id       uuid not null,
  class_date          date not null,
  title               text not null,
  topics              text,
  planned_evidence_id uuid,
  proposed_by         text not null default 'teacher' check (proposed_by in ('mawta', 'teacher')),
  accepted_at         timestamptz,
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now(),
  deleted_at          timestamptz,
  constraint session_outline_entries_tenant_id_key unique (tenant_id, id),
  constraint session_outline_entries_experience_key unique (tenant_id, experience_id, id),
  constraint session_outline_entries_experience_fk foreign key (tenant_id, experience_id)
    references learning_experiences (tenant_id, id)
);

comment on table session_outline_entries is
  'El esquema de sesiones de una experiencia: una entrada por fecha de clase, con un título y una línea de temas. Es deliberadamente ligero: no reemplaza a class_sessions (que son las sesiones reales con asistencia y audio) sino que planifica qué se hará en cada fecha. Las fechas sin entrada quedan permitidas: el esquema no tiene que cubrir todo.';
comment on column session_outline_entries.class_date is
  'La fecha de clase. Debe caer dentro del rango de la experiencia (check_session_entry_date): una entrada fuera del rango es rechazada. La unicidad session_outline_entries_date_key es por fecha y no por franja horaria porque un bloque doble es una sola sesión (decisión 15 del flujo).';
comment on column session_outline_entries.title is
  'Título de la sesión, ej. "Lanzamiento de la situación".';
comment on column session_outline_entries.topics is
  'Línea de temas, texto libre. Null cuando aún no se ha redactado.';
comment on column session_outline_entries.planned_evidence_id is
  'La evidencia planificada que se recogerá en esta sesión, si ya se decidió. La FK es compuesta (tenant_id, experience_id, planned_evidence_id), así que no puede apuntar a una evidencia de otra experiencia.';
comment on column session_outline_entries.proposed_by is
  'Quién propuso la entrada: ''mawta'' (el asistente) o ''teacher'' (el docente). El default es ''teacher''.';
comment on column session_outline_entries.accepted_at is
  'Cuándo el docente aceptó o editó la propuesta. Null mientras está pendiente.';

create unique index session_outline_entries_date_key
  on session_outline_entries (tenant_id, experience_id, class_date) where deleted_at is null;
create index session_outline_entries_evidence_idx
  on session_outline_entries (planned_evidence_id)
  where planned_evidence_id is not null and deleted_at is null;

-- La fecha debe caer dentro del rango de la experiencia. Un CHECK de fila no
-- puede leer learning_experiences, así que es un trigger.
-- +goose StatementBegin
create or replace function app.check_session_entry_date() returns trigger
  language plpgsql
  as $fn$
  declare
    v_starts date;
    v_ends   date;
  begin
    select le.starts_on, le.ends_on into v_starts, v_ends
      from learning_experiences le
     where le.id = new.experience_id
       and le.tenant_id = new.tenant_id
       and le.deleted_at is null;

    if not found then
      raise exception 'experience % not found in tenant %', new.experience_id, new.tenant_id
        using errcode = 'foreign_key_violation';
    end if;

    if new.class_date < v_starts or new.class_date > v_ends then
      raise exception 'session entry date % is outside experience % (% .. %)',
        new.class_date, new.experience_id, v_starts, v_ends
        using errcode = 'check_violation',
              hint = 'A session outline entry must fall inside its experience.';
    end if;
    return new;
  end;
  $fn$;
-- +goose StatementEnd

create trigger check_session_entry_date before insert or update
  of experience_id, class_date on session_outline_entries
  for each row execute function app.check_session_entry_date();

comment on function app.check_session_entry_date() is
  'La fecha de una entrada del esquema debe caer dentro del rango de su experiencia. Ninguna FK compuesta puede expresar "entre starts_on y ends_on" (el rango son dos columnas de una sola fila), así que es un trigger BEFORE.';

select app.enable_tenant_rls('session_outline_entries');
select app.attach_updated_at('session_outline_entries');
select app.attach_soft_delete_guard('session_outline_entries');

-- Ahora que session_outline_entries existe, la ubicación de una evidencia
-- planificada puede apuntar a ella con una FK compuesta que prueba que ambas
-- filas son de la misma experiencia.
alter table planned_evidences
  add constraint planned_evidences_session_entry_fk
    foreign key (tenant_id, experience_id, session_entry_id)
    references session_outline_entries (tenant_id, experience_id, id);

-- Y simétricamente: la evidencia planificada que una entrada del esquema
-- declara debe ser de la misma experiencia. La FK compuesta lo prueba.
alter table session_outline_entries
  add constraint session_outline_entries_evidence_fk
    foreign key (tenant_id, experience_id, planned_evidence_id)
    references planned_evidences (tenant_id, experience_id, id);

-- ---------------------------------------------------------------------------
-- planned_evidence_criteria
-- ---------------------------------------------------------------------------
-- Qué criterios observa una evidencia planificada. Los criterios pueden venir
-- de competencias distintas de la misma experiencia (decisión 11 del flujo).
create table planned_evidence_criteria (
  id             uuid primary key default gen_random_uuid(),
  tenant_id      uuid not null references tenants (id),
  evidence_id    uuid not null,
  criterion_id   uuid not null,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now(),
  deleted_at     timestamptz,
  constraint planned_evidence_criteria_tenant_id_key unique (tenant_id, id),
  constraint planned_evidence_criteria_evidence_key unique (tenant_id, evidence_id, id),
  constraint planned_evidence_criteria_criterion_key unique (tenant_id, criterion_id, id),
  constraint planned_evidence_criteria_evidence_fk foreign key (tenant_id, evidence_id)
    references planned_evidences (tenant_id, id),
  constraint planned_evidence_criteria_criterion_fk foreign key (tenant_id, criterion_id)
    references evaluation_criteria (tenant_id, id)
);

comment on table planned_evidence_criteria is
  'Qué criterios observa una evidencia planificada. Los criterios pueden venir de competencias distintas de la misma experiencia: una misma evidencia puede observar varias competencias (decisión 11 del flujo). El requisito de que el criterio pertenezca a la misma experiencia se exige por trigger: la FK compuesta hacia evaluation_criteria no puede ver experience_id.';
comment on constraint planned_evidence_criteria_evidence_key on planned_evidence_criteria is
  'Permite que otras tablas lleven FKs compuestas hacia esta, y mantiene la técnica de 00001: una referencia entre tenants es imposible.';

create unique index planned_evidence_criteria_pair_key
  on planned_evidence_criteria (tenant_id, evidence_id, criterion_id) where deleted_at is null;
create index planned_evidence_criteria_criterion_idx
  on planned_evidence_criteria (criterion_id) where deleted_at is null;

-- El criterio debe pertenecer a la misma experiencia que la evidencia.
-- +goose StatementBegin
create or replace function app.check_evidence_criterion_experience() returns trigger
  language plpgsql
  as $fn$
  declare
    v_evidence_experience  uuid;
    v_criterion_experience uuid;
  begin
    select pe.experience_id into v_evidence_experience
      from planned_evidences pe
     where pe.id = new.evidence_id
       and pe.tenant_id = new.tenant_id;

    select ec.experience_id into v_criterion_experience
      from evaluation_criteria ec
     where ec.id = new.criterion_id
       and ec.tenant_id = new.tenant_id;

    if v_evidence_experience is null
       or v_criterion_experience is distinct from v_evidence_experience then
      raise exception 'criterion % does not belong to experience %',
        new.criterion_id, v_evidence_experience
        using errcode = 'foreign_key_violation',
              hint = 'A planned evidence observes criteria of its own experience only.';
    end if;
    return new;
  end;
  $fn$;
-- +goose StatementEnd

create trigger check_evidence_criterion_experience
  before insert or update of evidence_id, criterion_id on planned_evidence_criteria
  for each row execute function app.check_evidence_criterion_experience();

comment on function app.check_evidence_criterion_experience() is
  'Una evidencia planificada observa criterios de su propia experiencia. Un criterio global (experience_id null) nunca es observable por una evidencia planificada: la evidencia observa criterios que el docente precisó para esta experiencia.';

select app.enable_tenant_rls('planned_evidence_criteria');
select app.attach_updated_at('planned_evidence_criteria');
select app.attach_soft_delete_guard('planned_evidence_criteria');

-- +goose Down

drop table if exists planned_evidence_criteria cascade;
drop table if exists session_outline_entries cascade;
drop table if exists planned_evidences cascade;
drop table if exists evaluation_criterion_capabilities cascade;
drop table if exists experience_competencies cascade;
drop table if exists learning_experiences cascade;
drop table if exists non_teaching_days cascade;
drop table if exists standard_level_mappings cascade;
drop table if exists learning_standards cascade;
drop table if exists grade_level_performances cascade;

-- Dos triggers de esta migración viven sobre evaluation_criteria, una tabla de
-- 00001 que aquí no se elimina: hay que quitarlos a mano antes de las
-- funciones, o el DROP FUNCTION falla por dependencia.
drop trigger if exists check_criterion_on_write on evaluation_criteria;
drop trigger if exists check_criterion_experience on evaluation_criteria;

-- Las funciones de trigger de esta migración viven en app; se eliminan
-- explícitamente para que el Down sea limpio por sí solo (el Down de 00001
-- elimina el esquema completo con CASCADE).
drop function if exists app.check_evidence_criterion_experience();
drop function if exists app.check_session_entry_date();
drop function if exists app.check_criterion_has_capability_on_write();
drop function if exists app.check_criterion_has_capability();
drop function if exists app.check_criterion_capability_competency();
drop function if exists app.check_criterion_experience();
drop function if exists app.check_experience_competency_subject();
drop function if exists app.check_experience_inside_term();

-- Las columnas agregadas a evaluation_criteria se eliminan (la tabla misma es
-- de 00001 y no se toca). capability_id NO se elimina: existía antes de esta
-- migración; solo se restaura su NOT NULL.
alter table evaluation_criteria drop constraint if exists evaluation_criteria_performance_fk;
alter table evaluation_criteria drop constraint if exists evaluation_criteria_experience_fk;
drop index if exists evaluation_criteria_performance_idx;
drop index if exists evaluation_criteria_experience_idx;
alter table evaluation_criteria drop column if exists accepted_at;
alter table evaluation_criteria drop column if exists proposed_by;
alter table evaluation_criteria drop column if exists performance_id;
alter table evaluation_criteria drop column if exists experience_id;
alter table evaluation_criteria alter column capability_id set not null;
