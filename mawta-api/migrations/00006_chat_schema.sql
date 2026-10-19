-- Chat de dirección: el rol del servicio del chat, su contrato de lectura y sus
-- propias tablas.
--
-- El servicio del chat (Python, mawta-chat) se conecta como mawta_chat. Nunca
-- lee las tablas de Mawta directamente: solo las vistas de chat_api, que son el
-- contrato entre los dos servicios. Escribe únicamente en el esquema chat.
--
-- Dueño de las vistas: mawta_chat_api, un rol sin login y sin BYPASSRLS. Una
-- vista se ejecuta con los permisos de su dueño; si fuera el superusuario que
-- corre las migraciones, ignoraría el RLS y el chat vería todos los colegios.
-- Con un dueño común, el RLS (FORCE) de las tablas de Mawta se aplica igual,
-- con el app.tenant_id que fija la sesión del chat.
--
-- La base langgraph (checkpoints del grafo) no está aquí: la gestiona LangGraph.

-- +goose Up

-- Mismo patrón que mawta_app en 00001: los roles son globales al clúster y
-- dbtest migra varias bases en paralelo, así que se atrapa la carrera en vez de
-- comprobar antes. Los límites se fijan solo al crear el rol.
-- +goose StatementBegin
do $$
begin
  create role mawta_chat login connection limit 10;
  alter role mawta_chat set statement_timeout = '15s';
  alter role mawta_chat set lock_timeout = '2s';
  alter role mawta_chat set idle_in_transaction_session_timeout = '30s';
exception
  when duplicate_object then null;
  when unique_violation then null;
end
$$;
-- +goose StatementEnd

-- +goose StatementBegin
do $$
begin
  create role mawta_chat_api nologin;
exception
  when duplicate_object then null;
  when unique_violation then null;
end
$$;
-- +goose StatementEnd

create schema chat_api;
create schema chat;

comment on schema chat_api is 'Contrato de lectura del servicio del chat de dirección: vistas de solo lectura sobre las tablas de Mawta, propiedad de mawta_chat_api. mawta_chat solo puede leer estas vistas, nunca las tablas de public.';
comment on schema chat is 'Datos propios del servicio del chat de dirección: hilos, mensajes, banco de preguntas y seudónimos. Solo mawta_chat los lee y escribe; mawta_app (Go) no tiene acceso.';

grant usage on schema app to mawta_chat, mawta_chat_api;
grant usage on schema chat_api, chat to mawta_chat;

-- ---------------------------------------------------------------------------
-- chat.threads
-- ---------------------------------------------------------------------------
create table chat.threads (
  id          uuid primary key default gen_random_uuid(),
  tenant_id   uuid not null references tenants (id),
  user_id     uuid not null references users (id),
  title       text not null default 'Nuevo chat' check (char_length(title) between 1 and 200),
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  deleted_at  timestamptz,
  constraint threads_tenant_id_key unique (tenant_id, id)
);

comment on table chat.threads is 'Un chat del director. Un director tiene varios; cada uno empieza con contexto limpio. RLS por colegio y, además, una política restrictiva por usuario: un director solo ve sus propios chats.';
comment on column chat.threads.title is 'PII (adulto): texto libre. Lo genera el chat a partir de la primera pregunta (ya seudonimizada) o lo escribe el director al renombrar.';

create index threads_user_idx on chat.threads (tenant_id, user_id, updated_at desc) where deleted_at is null;

select app.attach_updated_at('chat.threads');
select app.enable_tenant_rls('chat.threads');
create policy owner_only on chat.threads as restrictive
  using (user_id = app.current_actor_id())
  with check (user_id = app.current_actor_id());

-- ---------------------------------------------------------------------------
-- chat.messages
-- ---------------------------------------------------------------------------
create table chat.messages (
  id                uuid primary key default gen_random_uuid(),
  tenant_id         uuid not null references tenants (id),
  thread_id         uuid not null,
  user_id           uuid not null references users (id),
  author            text not null check (author in ('director', 'mawta')),
  protocol_version  smallint not null default 1 check (protocol_version >= 1),
  blocks            jsonb not null default '[]'::jsonb check (jsonb_typeof(blocks) = 'array'),
  tool_calls        jsonb not null default '[]'::jsonb check (jsonb_typeof(tool_calls) = 'array'),
  model             text,
  input_tokens      integer check (input_tokens >= 0),
  output_tokens     integer check (output_tokens >= 0),
  latency_ms        integer check (latency_ms >= 0),
  created_at        timestamptz not null default now(),
  constraint messages_tenant_id_key unique (tenant_id, id),
  constraint messages_thread_fk foreign key (tenant_id, thread_id)
    references chat.threads (tenant_id, id) on delete cascade
);

comment on table chat.messages is 'Cada mensaje de un chat, del director o de Mawta, con todo lo necesario para auditarlo y mejorar el chat después: bloques, herramientas usadas, modelo, tokens y latencia. user_id es el dueño del chat (desnormalizado) para la política restrictiva por usuario.';
comment on column chat.messages.blocks is 'PII (menor y adulto): texto libre. Bloques del protocolo v1 (estado, texto, tabla, grafico, error, fin) tal como los vio el modelo: los nombres de alumnos y profesores van seudonimizados (D001) y se restauran solo al mostrar.';
comment on column chat.messages.tool_calls is 'PII (menor y adulto): resultados de herramientas. Herramientas llamadas en el turno, con argumentos y resultados, seudonimizados igual que blocks.';

create index messages_thread_idx on chat.messages (tenant_id, thread_id, created_at);

select app.enable_tenant_rls('chat.messages');
create policy owner_only on chat.messages as restrictive
  using (user_id = app.current_actor_id())
  with check (user_id = app.current_actor_id());

-- ---------------------------------------------------------------------------
-- chat.question_bank
-- ---------------------------------------------------------------------------
create table chat.question_bank (
  id          uuid primary key default gen_random_uuid(),
  tenant_id   uuid not null references tenants (id),
  message_id  uuid not null,
  question    text not null check (char_length(question) > 0),
  status      text not null
                check (status in ('respondida', 'necesita_tool', 'parcial', 'fuera_de_alcance')),
  tool_name   text,
  created_at  timestamptz not null default now(),
  constraint question_bank_message_fk foreign key (tenant_id, message_id)
    references chat.messages (tenant_id, id) on delete cascade
);

comment on table chat.question_bank is 'Banco de preguntas: cada pregunta del director y cómo terminó. necesita_tool marca las que el chat no pudo responder por falta de una herramienta; fuera_de_alcance, las que no le corresponden. Es a la vez el backlog de herramientas y la suite de evaluación.';
comment on column chat.question_bank.question is 'PII (menor y adulto): texto libre. La pregunta tal como la vio el modelo, seudonimizada (D001).';
comment on column chat.question_bank.tool_name is 'Herramienta que respondió, o la que habría hecho falta cuando status = necesita_tool.';

create index question_bank_status_idx on chat.question_bank (tenant_id, status, created_at);

select app.enable_tenant_rls('chat.question_bank');

-- ---------------------------------------------------------------------------
-- chat.pseudonyms
-- ---------------------------------------------------------------------------
create table chat.pseudonyms (
  id           uuid primary key default gen_random_uuid(),
  tenant_id    uuid not null references tenants (id),
  entity_type  text not null check (entity_type in ('student', 'teacher')),
  entity_id    uuid not null,
  alias        text not null check (char_length(alias) between 1 and 40),
  created_at   timestamptz not null default now(),
  constraint pseudonyms_entity_key unique (tenant_id, entity_type, entity_id),
  constraint pseudonyms_alias_key unique (tenant_id, alias)
);

comment on table chat.pseudonyms is 'Seudónimos estables por colegio (D001): el modelo nunca recibe nombres reales de alumnos ni profesores, solo estos alias. entity_id apunta a students.id o teachers.id según entity_type; no lleva FK porque cubre dos tablas.';

select app.enable_tenant_rls('chat.pseudonyms');

grant select, insert, update, delete on all tables in schema chat to mawta_chat;

-- ---------------------------------------------------------------------------
-- chat_api: el contrato de lectura
-- ---------------------------------------------------------------------------
grant select on tenants, academic_years, grade_levels, sections to mawta_chat_api;

create view chat_api.school as
select t.id, t.name, t.city, t.region, t.timezone
  from tenants t
 where t.deleted_at is null;

comment on view chat_api.school is 'El colegio de la sesión del chat (una fila por el RLS de tenants).';

create view chat_api.sections as
select s.id,
       ay.year     as academic_year,
       ay.status   as academic_year_status,
       g.label     as grade,
       g.long_label as grade_long,
       g.stage,
       s.label     as section,
       s.name,
       s.shift,
       s.status
  from sections s
  join grade_levels g    on g.tenant_id = s.tenant_id and g.id = s.grade_level_id
  join academic_years ay on ay.tenant_id = s.tenant_id and ay.id = s.academic_year_id
 where s.deleted_at is null
   and g.deleted_at is null
   and ay.deleted_at is null;

comment on view chat_api.sections is 'Secciones del colegio de la sesión, con su grado y año académico.';

alter view chat_api.school owner to mawta_chat_api;
alter view chat_api.sections owner to mawta_chat_api;

grant select on all tables in schema chat_api to mawta_chat;

-- +goose Down

drop schema if exists chat_api cascade;
drop schema if exists chat cascade;

revoke select on tenants, academic_years, grade_levels, sections from mawta_chat_api;
revoke usage on schema app from mawta_chat, mawta_chat_api;

-- +goose StatementBegin
do $$
begin
  if exists (select 1 from pg_roles where rolname = 'mawta_chat') then
    execute 'drop owned by mawta_chat';
    execute 'drop role mawta_chat';
  end if;
  if exists (select 1 from pg_roles where rolname = 'mawta_chat_api') then
    execute 'drop owned by mawta_chat_api';
    execute 'drop role mawta_chat_api';
  end if;
end
$$;
-- +goose StatementEnd
