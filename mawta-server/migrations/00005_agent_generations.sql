-- Generaciones de los agentes de Mawta (ticket 6). Mawta es un sistema de
-- varios agentes acotados — planificación primero, después sesiones y
-- conclusiones descriptivas — que comparten esta misma tabla: cada fila es un
-- pedido de "✦ Generar con Mawta" y su resultado.
--
-- El job encolado (tabla jobs) solo lleva el id de la generación: jobs no
-- tiene RLS ni columna de resultado, así que nunca se expone. La app consulta
-- esta tabla (GET /generations/{id}) hasta que la generación termina.

-- +goose Up
create table agent_generations (
  id                     uuid primary key default gen_random_uuid(),
  tenant_id              uuid not null references tenants (id),
  agent                  text not null check (agent in ('planning')),
  kind                   text not null,
  class_id               uuid not null,
  experience_id          uuid,
  requested_by           uuid not null,
  target_key             text not null,
  status                 text not null default 'pending'
                           check (status in ('pending', 'running', 'completed', 'failed')),
  input                  jsonb not null default '{}'::jsonb,
  result                 jsonb,
  error                  text,
  error_detail           text,
  model                  text,
  prompt_version         text,
  input_tokens           integer not null default 0 check (input_tokens >= 0),
  output_tokens          integer not null default 0 check (output_tokens >= 0),
  cache_read_tokens      integer not null default 0 check (cache_read_tokens >= 0),
  cache_write_tokens     integer not null default 0 check (cache_write_tokens >= 0),
  cost_usd               numeric(10, 6) not null default 0 check (cost_usd >= 0),
  attempts               smallint not null default 0 check (attempts >= 0),
  deadline_at            timestamptz not null default now() + interval '5 minutes',
  started_at             timestamptz,
  finished_at            timestamptz,
  created_at             timestamptz not null default now(),
  updated_at             timestamptz not null default now(),
  constraint agent_generations_tenant_id_key unique (tenant_id, id),
  constraint agent_generations_class_fk foreign key (tenant_id, class_id)
    references classes (tenant_id, id),
  constraint agent_generations_experience_fk foreign key (tenant_id, experience_id)
    references learning_experiences (tenant_id, id),
  constraint agent_generations_requested_by_fk foreign key (tenant_id, requested_by)
    references teachers (tenant_id, id),
  constraint agent_generations_planning_kind check (
    agent <> 'planning' or kind in ('experience', 'criteria', 'evidences', 'sessions')),
  constraint agent_generations_finished_consistent check (
    (status in ('completed', 'failed')) = (finished_at is not null)),
  constraint agent_generations_result_consistent check (
    status <> 'completed' or result is not null),
  constraint agent_generations_error_consistent check (
    status <> 'failed' or error is not null)
);

-- Una sola generación en curso por objetivo: pedir dos veces "Generar
-- criterios" para la misma competencia devuelve la que ya corre.
create unique index agent_generations_target_key
  on agent_generations (tenant_id, target_key) where status in ('pending', 'running');
create index agent_generations_class_idx on agent_generations (tenant_id, class_id, created_at desc);

comment on table agent_generations is
  'Un pedido a un agente de Mawta ("✦ Generar con Mawta") y su resultado. Los agentes son acotados: reciben datos curados de la base, responden en un formato fijo que el servidor valida, y lo que proponen se guarda pendiente (proposed_by = mawta, accepted_at null) hasta que el docente lo acepta o lo edita. Nunca sugieren niveles de logro ni reciben datos de estudiantes en la planificación.';
comment on column agent_generations.agent is
  'Qué agente atiende el pedido. planning es el primero; los agentes de sesiones y de conclusiones amplían este check en su propia migración.';
comment on column agent_generations.kind is
  'Qué genera, según el agente. planning: experience (propuesta de experiencia desde la idea del docente; no se guarda como experiencia), criteria, evidences o sessions (se guardan como propuestas pendientes de la experiencia).';
comment on column agent_generations.experience_id is
  'La experiencia sobre la que se genera. Null en kind = experience: la propuesta todavía no es una experiencia.';
comment on column agent_generations.requested_by is
  'El docente que pidió la generación. Solo para rastro: el acceso se decide por la clase, como en el resto de la planificación.';
comment on column agent_generations.target_key is
  'Identifica el objetivo de la generación (ej. exp:<id>:criteria:<competencia>). Con agent_generations_target_key garantiza una sola generación en curso por objetivo.';
comment on column agent_generations.input is
  'Lo que pidió el docente (ej. su idea y las competencias elegidas). No incluye datos de estudiantes.';
comment on column agent_generations.result is
  'Lo que hizo una generación completada: la propuesta (kind = experience) o los ids de lo que insertó como pendiente.';
comment on column agent_generations.error is
  'Mensaje para el docente, en español, cuando la generación falla. Se expone en la API.';
comment on column agent_generations.error_detail is
  'Causa técnica del fallo, para soporte. Nunca se expone en la API.';
comment on column agent_generations.cost_usd is
  'Costo estimado de las llamadas al modelo de esta generación, según la tabla de precios del servidor. Sirve para seguir el gasto por agente y por colegio.';
comment on column agent_generations.deadline_at is
  'Después de esta hora una generación sin terminar se da por fallida: el worker no la empieza y la API la muestra como failed. Cubre el caso de un worker que muere a mitad de camino.';

select app.enable_tenant_rls('agent_generations');
select app.attach_updated_at('agent_generations');

-- +goose Down
drop table if exists agent_generations;
