-- Esquema completo de la aplicación Mawta, como una sola migración.

-- +goose Up

create extension if not exists btree_gist;  -- uuid WITH = dentro de restricciones EXCLUDE
create extension if not exists pg_trgm;     -- cajas de búsqueda de clases/alumnos

create schema if not exists app;
create schema if not exists privacy;

comment on schema app is 'Funciones auxiliares de contexto de sesión y funciones de trigger compartidas. No contiene datos de negocio.';
comment on schema privacy is 'Vistas y utilidades para descubrir y auditar columnas de datos personales (herramientas para la Ley 29733).';

-- Postgres no tiene un tipo range nativo sobre `time`; class_schedules necesita uno para rechazar
-- franjas semanales superpuestas para la misma clase.
create type timerange as range (subtype = time);
comment on type timerange is 'Intervalo de hora local dentro de un día de la semana. Usado por las restricciones de exclusión de class_schedules.';

-- ---------------------------------------------------------------------------
-- Rol de la aplicación
-- ---------------------------------------------------------------------------
-- RLS solo es real si el rol de conexión NO es el dueño de la tabla: un dueño de tabla
-- omite las políticas a menos que se establezca FORCE ROW LEVEL SECURITY, e incluso así
-- los roles BYPASSRLS las ignoran. El servicio en Go debe conectarse como mawta_app.

-- pg_roles es global al clúster, no a la base de datos: cuando varias bases se
-- migran en paralelo (como hace dbtest, una base por test), el chequeo
-- "if not exists" seguido de "create role" no es atómico entre conexiones y
-- dos migraciones concurrentes pueden ver ambas "no existe" antes de que
-- cualquiera cree el rol. Se atrapan duplicate_object y unique_violation en vez
-- de comprobar antes: bajo esa carrera Postgres no siempre llega a detectar el
-- nombre duplicado por catálogo (42710) antes de insertar — a veces el choque
-- solo aparece como violación del índice único de pg_authid (23505).
-- +goose StatementBegin
do $$
begin
  create role mawta_app login;
exception
  when duplicate_object then null;
  when unique_violation then null;
end
$$;
-- +goose StatementEnd

grant usage on schema public, app, privacy to mawta_app;
alter default privileges in schema public grant select, insert, update, delete on tables to mawta_app;
alter default privileges in schema public grant usage, select on sequences to mawta_app;
alter default privileges in schema privacy grant select on tables to mawta_app;

-- ---------------------------------------------------------------------------
-- Contexto de sesión
-- ---------------------------------------------------------------------------

-- +goose StatementBegin
create or replace function app.current_tenant_id() returns uuid
  language sql stable
  as $fn$
    select nullif(current_setting('app.tenant_id', true), '')::uuid;
  $fn$;
-- +goose StatementEnd

comment on function app.current_tenant_id() is
  'Tenant de la sesión actual, leído de SET LOCAL app.tenant_id. Devuelve NULL cuando no está definido, de modo que cada predicado RLS evalúa a NULL (es decir, ninguna fila) en lugar de lanzar un error — una consulta que olvida su filtro de tenant no devuelve nada.';

-- +goose StatementBegin
create or replace function app.current_actor_id() returns uuid
  language sql stable
  as $fn$
    select nullif(current_setting('app.actor_id', true), '')::uuid;
  $fn$;
-- +goose StatementEnd

comment on function app.current_actor_id() is
  'Usuario autenticado de la sesión actual, de SET LOCAL app.actor_id. Se usa como valor por defecto en columnas de actor en filas de auditoría y eventos.';

-- ---------------------------------------------------------------------------
-- Funciones de trigger compartidas
-- ---------------------------------------------------------------------------

-- +goose StatementBegin
create or replace function app.set_updated_at() returns trigger
  language plpgsql
  as $fn$
  begin
    new.updated_at := now();
    return new;
  end;
  $fn$;
-- +goose StatementEnd

-- ---------------------------------------------------------------------------
-- Utilidades de DDL
-- ---------------------------------------------------------------------------

-- +goose StatementBegin
create or replace function app.attach_updated_at(p_table regclass) returns void
  language plpgsql
  as $fn$
  begin
    execute format(
      'create trigger set_updated_at before update on %s for each row execute function app.set_updated_at()',
      p_table);
  end;
  $fn$;
-- +goose StatementEnd

-- Se permiten los borrados físicos (hard delete) mientras el proyecto está en desarrollo; esta función
-- se mantiene como no-op para que las migraciones posteriores que la llaman sigan funcionando.
-- +goose StatementBegin
create or replace function app.attach_soft_delete_guard(p_table regclass) returns void
  language plpgsql
  as $fn$
  begin
    -- no-op: se permite el DELETE físico durante el desarrollo
  end;
  $fn$;
-- +goose StatementEnd

-- +goose StatementBegin
create or replace function app.enable_tenant_rls(p_table regclass) returns void
  language plpgsql
  as $fn$
  begin
    execute format('alter table %s enable row level security', p_table);
    execute format('alter table %s force row level security', p_table);
    execute format(
      'create policy tenant_isolation on %s using (tenant_id = app.current_tenant_id()) with check (tenant_id = app.current_tenant_id())',
      p_table);
  end;
  $fn$;
-- +goose StatementEnd

comment on function app.enable_tenant_rls(regclass) is
  'Aplica la política estándar de aislamiento de esquema compartido a una tabla con alcance de tenant. FORCE es deliberado: hace que la política también aplique al dueño de la tabla, de modo que una migración o una sesión de operaciones no pueda leer accidentalmente entre tenants.';


-- ---------------------------------------------------------------------------
-- tenants
-- ---------------------------------------------------------------------------
create table tenants (
  id                       uuid primary key default gen_random_uuid(),
  name                     text not null,
  legal_name               text,
  modular_code             text,
  kind                     text not null default 'publica'
                             check (kind in ('publica', 'privada', 'parroquial', 'internacional')),
  city                     text,
  region                   text,
  timezone                 text not null default 'America/Lima',
  status                   text not null default 'active' check (status in ('active', 'suspended', 'closed')),
  created_at               timestamptz not null default now(),
  updated_at               timestamptz not null default now(),
  deleted_at               timestamptz
);

comment on table tenants is 'Un colegio (institución educativa). Raíz de toda política RLS: app.current_tenant_id() resuelve a una fila aquí.';
comment on column tenants.modular_code is 'Código modular MINEDU de la institución educativa, cuando tiene uno. Null para colegios privados fuera del registro.';
comment on column tenants.timezone is 'Zona horaria IANA del colegio. Todos los timestamps se almacenan en UTC; este es el único lugar donde se define un día calendario local, y es contra el que se calcula "HOY".';
create unique index tenants_modular_code_key
  on tenants (modular_code) where modular_code is not null and deleted_at is null;

-- Un nombre IANA inválido rompe silenciosamente cada consulta de "hoy", así que se rechaza al escribir.
-- Esto es un trigger y no un CHECK porque la validación necesita una consulta en
-- pg_timezone_names, y las expresiones CHECK no pueden contener subconsultas.
-- +goose StatementBegin
create or replace function app.validate_tenant_timezone() returns trigger
  language plpgsql
  as $fn$
  begin
    if not exists (select 1 from pg_timezone_names where name = new.timezone) then
      raise exception 'unknown IANA timezone %', new.timezone using errcode = 'check_violation';
    end if;
    return new;
  end;
  $fn$;
-- +goose StatementEnd

create trigger validate_timezone before insert or update of timezone on tenants
  for each row execute function app.validate_tenant_timezone();

alter table tenants enable row level security;
alter table tenants force row level security;
create policy tenant_isolation on tenants
  using (id = app.current_tenant_id())
  with check (id = app.current_tenant_id());

select app.attach_updated_at('tenants');
select app.attach_soft_delete_guard('tenants');

-- ---------------------------------------------------------------------------
-- users
-- ---------------------------------------------------------------------------
-- Deliberadamente SIN alcance de tenant: una persona puede enseñar en dos colegios y debe
-- mantener una sola credencial. El aislamiento se maneja a través de memberships.
create table users (
  id                    uuid primary key default gen_random_uuid(),
  email                 text not null,
  given_name            text not null,
  family_name           text not null,
  display_name          text,
  phone                 text,
  status                text not null default 'active' check (status in ('invited', 'active', 'suspended', 'deactivated')),
  username              text,
  password_hash         text,
  password_changed_at   timestamptz,
  last_login_at         timestamptz,
  failed_login_count    smallint not null default 0 check (failed_login_count >= 0),
  locked_until          timestamptz,
  created_at            timestamptz not null default now(),
  updated_at            timestamptz not null default now(),
  deleted_at            timestamptz,
  constraint users_credential_complete check ((username is null) = (password_hash is null)),
  constraint users_username_shape check (username is null or username ~ '^[a-z0-9._-]{3,64}$')
);

comment on table users is
  'PII (adulto). Principales de autenticación: los cuatro roles de membership (teacher, student, supervisor, admin). Contiene la credencial (username + password_hash). No tiene alcance de tenant: el aislamiento se maneja a través de memberships, mediante la política tenant_isolation de abajo, que la política login_lookup complementa de forma acotada. No contiene datos de menores — los estudiantes no son usuarios y no tienen inicio de sesión: memberships.role puede decir ''student'', pero ninguna fila de students se vincula jamás a una fila de users, y solo role=''teacher'' puede completar un inicio de sesión hoy (ver memberships.role abajo).';
comment on column users.email is 'PII (adulto): contacto. Se pasa a minúsculas al escribir; la unicidad se aplica sobre lower(email).';
comment on column users.phone is 'PII (adulto): contacto.';
comment on column users.username is
  'PII (adulto): el identificador de inicio de sesión. Único globalmente sobre lower(username), igual que email y por la misma razón — una persona, una credencial, un colegio (ver memberships_one_school_per_user). Se pasa a minúsculas al escribir; users_username_shape lo restringe a [a-z0-9._-]{3,64} para que lower() sea una identidad verdadera. Email sigue siendo un dato de contacto y nunca es un inicio de sesión.';
comment on column users.password_hash is
  'Hash bcrypt (costo desde BCRYPT_COST, por defecto 12) de la contraseña de la cuenta. Nunca se registra en logs, nunca se devuelve en ningún endpoint, solo lo lee internal/repo/auth.go. Null significa que la cuenta no tiene contraseña y no puede iniciar sesión; users_credential_complete mantiene eso emparejado con un username null.';
comment on column users.password_changed_at is
  'Cuándo se estableció la contraseña por última vez. Cada fila de user_sessions del usuario se revoca (reason = ''password_change'') cuando cambia.';
comment on column users.last_login_at is 'Último inicio de sesión exitoso, escrito por repo.RecordLoginSuccess.';
comment on column users.failed_login_count is
  'Inicios de sesión fallidos consecutivos desde el último éxito. Se reinicia a 0 en un éxito. Al llegar a LOGIN_MAX_FAILURES la cuenta se bloquea mediante locked_until, sin importar la contraseña en el siguiente intento.';
comment on column users.locked_until is
  'Expiración del bloqueo. Mientras esté en el futuro, todo intento de inicio de sesión para esta cuenta se rechaza con account_locked sin importar la contraseña.';

create unique index users_email_key on users (lower(email)) where deleted_at is null;
create unique index users_username_key on users (lower(username))
  where username is not null and deleted_at is null;

select app.attach_updated_at('users');
select app.attach_soft_delete_guard('users');

-- ---------------------------------------------------------------------------
-- memberships
-- ---------------------------------------------------------------------------
create table memberships (
  id          uuid primary key default gen_random_uuid(),
  tenant_id   uuid not null references tenants (id),
  user_id     uuid not null references users (id),
  role        text not null check (role in ('teacher', 'student', 'supervisor', 'admin')),
  status      text not null default 'active' check (status in ('invited', 'active', 'suspended', 'revoked')),
  joined_at   timestamptz not null default now(),
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  deleted_at  timestamptz,
  constraint memberships_tenant_id_key unique (tenant_id, id)
);

comment on table memberships is
  'Qué usuario actúa en qué colegio, y con qué rol. El join que hace visible una fila de users bajo RLS, y la fila a la que resuelve un inicio de sesión. Cuatro roles: ''teacher'' (el único que hoy puede completar un inicio de sesión), ''student'', ''supervisor'', ''admin''. Los otros tres están modelados — las verificaciones de permisos se escriben de forma genérica contra role — para poder habilitarlos más adelante solo ampliando domain.LoginEnabledRoles; un intento de inicio de sesión de uno de ellos hoy se rechaza con role_not_enabled. memberships_one_school_per_user limita a un usuario a exactamente un membership activo, así que el flujo de inicio de sesión nunca tiene que elegir entre varios.';
comment on constraint memberships_tenant_id_key on memberships is 'Redundante respecto a la PK, pero necesaria para que las tablas hijas puedan llevar una FK compuesta (tenant_id, membership_id) — eso es lo que hace que una referencia entre tenants sea estructuralmente imposible y no solo improbable.';

create unique index memberships_tenant_user_key
  on memberships (tenant_id, user_id) where deleted_at is null;
-- Cada solicitud resuelve el membership actuante a partir del usuario de la sesión.
create index memberships_user_idx on memberships (user_id) where deleted_at is null;
-- Un usuario tiene como máximo un membership activo o invitado a la vez. Los memberships
-- revocados se excluyen a propósito: dejar un colegio no debe bloquear
-- unirse a otro.
create unique index memberships_one_school_per_user
  on memberships (user_id) where deleted_at is null and status <> 'revoked';

select app.enable_tenant_rls('memberships');
select app.attach_updated_at('memberships');
select app.attach_soft_delete_guard('memberships');

-- El RLS de users depende de que exista memberships, así que la política se crea aquí.
alter table users enable row level security;
alter table users force row level security;
create policy tenant_isolation on users
  using (exists (select 1 from memberships m
                  where m.user_id = users.id
                    and m.tenant_id = app.current_tenant_id()
                    and m.deleted_at is null))
  with check (exists (select 1 from memberships m
                       where m.user_id = users.id
                         and m.tenant_id = app.current_tenant_id()
                         and m.deleted_at is null));

comment on policy tenant_isolation on users is
  'Una fila de users es visible para un tenant solo mientras un membership no eliminado los vincule, lo que evita la enumeración entre tenants de correos de docentes. Nótese la consecuencia de orden: el membership debe insertarse antes de que la fila de user pueda volver a leerse.';

-- Las políticas permisivas se combinan con OR, así que esto no amplía nada mientras haya un tenant
-- definido — solo aplica dentro de internal/db.WithAuthTx, el único
-- modo de transacción sin tenant y con esta GUC activa. Se necesita en ambas tablas:
-- resolver un inicio de sesión implica leer la fila de users correspondiente
-- (FindLoginCandidate) y luego el membership del usuario (ResolveMembership,
-- para saber en qué tenant/rol abrir una sesión real).
create policy login_lookup on users
  using      (app.current_tenant_id() is null and current_setting('app.auth_lookup', true) = 'on')
  with check (app.current_tenant_id() is null and current_setting('app.auth_lookup', true) = 'on');

create policy login_lookup on memberships
  using      (app.current_tenant_id() is null and current_setting('app.auth_lookup', true) = 'on')
  with check (app.current_tenant_id() is null and current_setting('app.auth_lookup', true) = 'on');

comment on policy login_lookup on users is
  'La excepción de orden. Al iniciar sesión, y en cada validación de cookie de sesión, todavía no hay tenant — el tenant es el RESULTADO de resolver una credencial o un token de sesión — así que tenant_isolation nunca puede coincidir. Esta política abre users a una transacción que haya establecido explícitamente app.auth_lookup=''on'' Y no tenga tenant, algo que solo hace internal/db.WithAuthTx. La política de cualquier otra tabla sigue evaluando tenant_id = NULL en esa transacción y no devuelve nada, así que el radio de impacto de un error en este camino es solo esta tabla. Deliberadamente NO se resolvió con una función security definer ni con WithSystemTx: FORCE ROW LEVEL SECURITY también ata al dueño de la tabla, así que cualquiera de las dos opciones necesitaría un dueño superusuario (o BYPASSRLS) y otorgaría una omisión total de RLS en lugar de reducir privilegios.';
comment on policy login_lookup on memberships is
  'La misma excepción previa al tenant que users.login_lookup, por la misma razón: ResolveMembership debe leer un membership antes de conocer su tenant, para saber en qué tenant abrir una sesión real.';

-- ---------------------------------------------------------------------------
-- user_sessions
-- ---------------------------------------------------------------------------
create table user_sessions (
  id             uuid primary key default gen_random_uuid(),
  token_hash     bytea not null,
  user_id        uuid not null references users (id),
  tenant_id      uuid not null references tenants (id),
  membership_id  uuid not null,
  role           text not null check (role in ('teacher', 'student', 'supervisor', 'admin')),
  created_at     timestamptz not null default now(),
  last_seen_at   timestamptz not null default now(),
  expires_at     timestamptz not null,
  revoked_at     timestamptz,
  revoked_reason text check (revoked_reason in ('logout', 'expired', 'idle', 'password_change', 'admin')),
  user_agent     text,
  ip             inet,
  constraint user_sessions_membership_fk foreign key (tenant_id, membership_id)
    references memberships (tenant_id, id),
  constraint user_sessions_expires_after_created check (expires_at > created_at),
  constraint user_sessions_revocation_consistent
    check ((revoked_at is null) = (revoked_reason is null))
);

comment on table user_sessions is
  'Sesiones del lado del servidor. El navegador guarda un token opaco de 256 bits en una cookie HttpOnly; aquí solo se almacena su sha256, así que leer esta tabla no permite suplantar a nadie. Deliberadamente NO tiene política RLS, por la misma razón que jobs.tenant_id: una fila aquí debe poder leerse antes de que se pueda establecer app.current_tenant_id(), ya que resolverla ES cómo se llega a conocer el tenant. El aislamiento es estructural en su lugar: el único lector es internal/repo/auth.go, siempre por token_hash exacto, y la FK compuesta hacia memberships (tenant_id, membership_id) hace imposible insertar una fila de sesión entre tenants.';
comment on column user_sessions.token_hash is
  'sha256 del token en crudo. El token en crudo solo existe en el header Set-Cookie y en el almacén de cookies del navegador — nunca se guarda, se registra en logs ni se devuelve de nuevo. sha256 en vez de bcrypt a propósito: la entrada son 256 bits de crypto/rand, ya inadivinables, así que no necesita factor de trabajo, y esto se lee en cada solicitud.';
comment on column user_sessions.tenant_id is
  'Desnormalizado desde el membership para que una sola lectura previa al tenant resuelva todo el contexto RLS, sin una segunda consulta a través de memberships mientras el tenant aún es desconocido.';
comment on column user_sessions.role is
  'Copiado del membership al iniciar sesión y verificado de nuevo contra el membership vigente en cada solicitud (internal/httpapi.sessionAuth), de modo que un rol revocado o degradado después del inicio de sesión surte efecto de inmediato en lugar de esperar a que expire la sesión.';
comment on column user_sessions.expires_at is
  'Expiración absoluta, establecida al iniciar sesión a partir de SESSION_TTL. Nunca se extiende. La expiración por inactividad es una verificación aparte, calculada en Go a partir de last_seen_at contra SESSION_IDLE_TIMEOUT.';
comment on column user_sessions.last_seen_at is
  'Se actualiza como máximo una vez por hora por sesión (repo.TouchSession), no en cada solicitud — escribir en cada solicitud convertiría cada GET en una transacción de lectura-escritura.';
comment on column user_sessions.revoked_reason is
  'logout (iniciado por el usuario), expired/idle (revocado de forma perezosa al momento de la validación — no hay un scheduler en este código, ver internal/worker/SPEC.md, así que nada las depura de forma proactiva), password_change (cada sesión del usuario, al cambiar la contraseña), admin (reservado para una futura revocación iniciada por un administrador).';

create unique index user_sessions_token_hash_key on user_sessions (token_hash);
create index user_sessions_user_idx   on user_sessions (user_id)    where revoked_at is null;
create index user_sessions_expiry_idx on user_sessions (expires_at) where revoked_at is null;

-- ---------------------------------------------------------------------------
-- teachers
-- ---------------------------------------------------------------------------
-- Se relaciona con membership, no con user: el perfil ("Docente de Secundaria",
-- hired_on) es por colegio, y pasar por membership garantiza que exista exactamente
-- un camino de un teacher a un tenant.
create table teachers (
  id                       uuid primary key default gen_random_uuid(),
  tenant_id                uuid not null references tenants (id),
  membership_id            uuid not null,
  employee_code            text,
  display_name             text not null,
  title                    text,
  hired_on                 date,
  weekly_hours_contracted  numeric(5, 2) check (weekly_hours_contracted >= 0),
  status                   text not null default 'active' check (status in ('active', 'on_leave', 'inactive')),
  created_at               timestamptz not null default now(),
  updated_at               timestamptz not null default now(),
  deleted_at               timestamptz,
  constraint teachers_tenant_id_key unique (tenant_id, id),
  constraint teachers_membership_fk foreign key (tenant_id, membership_id)
    references memberships (tenant_id, id)
);

comment on table teachers is 'PII (adulto). Perfil docente por colegio. display_name, title y hired_on se muestran directamente; el correo y el inicio de sesión viven en la fila de users vinculada.';
comment on column teachers.title is 'Etiqueta de rol, ej. "Docente de Secundaria". Texto libre: los colegios lo redactan de forma inconsistente y es solo para mostrar.';
comment on column teachers.hired_on is 'Fecha de inicio en este colegio. A partir de este valor se muestra "Desde marzo 2021 · 5 años".';
comment on column teachers.weekly_hours_contracted is 'Horas semanales contratadas. El valor mostrado como "30h Semanales" se calcula en cambio a partir de class_schedules; esta es la cifra del contrato contra la cual conciliar.';

create unique index teachers_membership_key on teachers (membership_id) where deleted_at is null;
create unique index teachers_employee_code_key
  on teachers (tenant_id, employee_code) where employee_code is not null and deleted_at is null;

select app.enable_tenant_rls('teachers');
select app.attach_updated_at('teachers');
select app.attach_soft_delete_guard('teachers');


-- ---------------------------------------------------------------------------
-- academic_years
-- ---------------------------------------------------------------------------
create table academic_years (
  id              uuid primary key default gen_random_uuid(),
  tenant_id       uuid not null references tenants (id),
  year            smallint not null check (year between 2000 and 2100),
  name            text not null,
  starts_on       date not null,
  ends_on         date not null,
  term_structure  text not null default 'bimestre'
                    check (term_structure in ('bimestre', 'trimestre', 'semestre')),
  status          text not null default 'planned'
                    check (status in ('planned', 'active', 'closed')),
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  deleted_at      timestamptz,
  constraint academic_years_tenant_id_key unique (tenant_id, id),
  constraint academic_years_range_valid check (ends_on > starts_on)
);

comment on table academic_years is 'Un año escolar para un tenant, ej. 2026. En Perú va aproximadamente de marzo a diciembre.';
comment on column academic_years.term_structure is 'Cómo se subdivide el año: bimestre, trimestre o semestre. Un colegio puede usar una estructura distinta de un año a otro.';

create unique index academic_years_tenant_year_key
  on academic_years (tenant_id, year) where deleted_at is null;
create unique index academic_years_one_active_key
  on academic_years (tenant_id) where status = 'active' and deleted_at is null;

select app.enable_tenant_rls('academic_years');
select app.attach_updated_at('academic_years');
select app.attach_soft_delete_guard('academic_years');

-- ---------------------------------------------------------------------------
-- terms
-- ---------------------------------------------------------------------------
create table terms (
  id                uuid primary key default gen_random_uuid(),
  tenant_id         uuid not null references tenants (id),
  academic_year_id  uuid not null,
  stage             text check (stage in ('inicial', 'primaria', 'secundaria', 'otro')),
  sequence          smallint not null check (sequence between 1 and 6),
  name              text not null,
  short_name        text,
  starts_on         date not null,
  ends_on           date not null,
  status            text not null default 'planned'
                      check (status in ('planned', 'active', 'closed', 'archived')),
  grades_due_on     date,
  closed_at         timestamptz,
  closed_by_id      uuid references teachers (id),
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now(),
  deleted_at        timestamptz,
  constraint terms_tenant_id_key unique (tenant_id, id),
  constraint terms_year_key unique (tenant_id, academic_year_id, id),
  constraint terms_year_fk foreign key (tenant_id, academic_year_id)
    references academic_years (tenant_id, id),
  constraint terms_range_valid check (ends_on > starts_on),
  constraint terms_closed_consistent
    check ((status in ('closed', 'archived')) = (closed_at is not null)),
  constraint terms_no_overlap
    exclude using gist (
      academic_year_id with =,
      coalesce(stage, '') with =,
      daterange(starts_on, ends_on, '[]') with &&
    )
    where (deleted_at is null)
);

comment on table terms is 'Un bimestre, trimestre o semestre dentro de una fila de academic_years. name se muestra como ("Bimestre II"); acota a un solo term todo un panel de actividad.';
comment on column terms.stage is 'A qué nivel educativo aplica este term, para un colegio que usa estructuras de periodo distintas por nivel (ej. Primaria en trimestres, Secundaria en bimestres, en el mismo año escolar). Null significa que el term aplica a todos los niveles — el caso común de un colegio con un solo calendario.';
comment on column terms.sequence is 'Posición ordinal dentro del año, acotada a (academic_year_id, stage). Bimestre II es sequence 2. Limitado a 6 para que un valor mal escrito no pueda crear un term fantasma.';
comment on column terms.grades_due_on is 'Fecha límite para registrar notas. Impulsa los recordatorios de "notas pendientes".';
comment on column terms.closed_at is 'Cuándo se cerró el term. Un term cerrado rechaza nuevas scores, que es lo que evita que una nota ya reportada cambie después.';
comment on constraint terms_no_overlap on terms is 'Dos terms del mismo año y stage no pueden cubrir la misma fecha, así que "el term que contiene esta sesión de clase" es siempre una sola fila. coalesce(stage, '''') en vez de comparar stage directamente: una restricción de exclusión (como un índice único) nunca trata dos NULL como iguales, así que sin esto dos terms sin stage del mismo año podrían solaparse silenciosamente.';

create unique index terms_year_sequence_key
  on terms (academic_year_id, coalesce(stage, ''), sequence) where deleted_at is null;
-- Casi todo agregado es "para el term actual", resuelto por fecha.
create index terms_tenant_range_idx on terms (tenant_id, starts_on, ends_on) where deleted_at is null;

select app.enable_tenant_rls('terms');
select app.attach_updated_at('terms');
select app.attach_soft_delete_guard('terms');

-- ---------------------------------------------------------------------------
-- grade_levels
-- ---------------------------------------------------------------------------
-- Una tabla, no un enum ni un smallint: las clases se agrupan bajo "1ER
-- GRADO".."5TO GRADO" (secundaria peruana), pero "Math 8B" implica
-- un colegio que numera los grados 1-11, y los colegios internacionales usan "Year 9".
create table grade_levels (
  id          uuid primary key default gen_random_uuid(),
  tenant_id   uuid not null references tenants (id),
  code        text not null,
  label       text not null,
  long_label  text not null,
  stage       text not null default 'secundaria'
                check (stage in ('inicial', 'primaria', 'secundaria', 'otro')),
  cycle       text check (cycle in ('ciclo_i', 'ciclo_ii', 'ciclo_iii', 'ciclo_iv', 'ciclo_v', 'ciclo_vi', 'ciclo_vii')),
  ordinal     smallint not null,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  deleted_at  timestamptz,
  constraint grade_levels_tenant_id_key unique (tenant_id, id)
);

comment on table grade_levels is 'Los grados tal como los nombra el colegio. Modelado como filas para que un colegio pueda usar 1ro-5to de secundaria, grados 1-11, o Year 7-11 sin cambiar el esquema.';
comment on column grade_levels.label is 'Forma corta usada dentro de un nombre de clase, ej. "5to" en "Inglés 5to B".';
comment on column grade_levels.long_label is 'Forma de encabezado de sección, ej. "5TO GRADO".';
comment on column grade_levels.cycle is 'Ciclo I o Ciclo II, con sentido solo cuando stage = ''inicial''. Ciclo I cubre 0-2 años, Ciclo II cubre 3-5 años; cada uno tiene su propia obligatoriedad de conclusión descriptiva.';
comment on column grade_levels.ordinal is 'Orden de clasificación para la lista de clases agrupadas. Distinto de code, que puede no ordenarse de forma natural.';

create unique index grade_levels_tenant_code_key
  on grade_levels (tenant_id, code) where deleted_at is null;
create unique index grade_levels_tenant_ordinal_key
  on grade_levels (tenant_id, ordinal) where deleted_at is null;

select app.enable_tenant_rls('grade_levels');
select app.attach_updated_at('grade_levels');
select app.attach_soft_delete_guard('grade_levels');


-- ---------------------------------------------------------------------------
-- subjects
-- ---------------------------------------------------------------------------
create table subjects (
  id              uuid primary key default gen_random_uuid(),
  tenant_id       uuid not null references tenants (id),
  code            text not null,
  name            text not null,
  area_curricular text,
  icon_key        text,
  is_tutoria      boolean not null default false,
  sort_order      smallint not null default 0,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  deleted_at      timestamptz,
  constraint subjects_tenant_id_key unique (tenant_id, id)
);

comment on table subjects is 'Un curso o asignatura del colegio: Matemática, Comunicación, Inglés, Historia, Geografía, Tutoría.';
comment on column subjects.area_curricular is 'Área curricular MINEDU a la que pertenece la asignatura, ej. "Ciencias Sociales" para Historia y Geografía. Se mantiene en español: es un término propio del currículo nacional, no una categoría genérica.';
comment on column subjects.icon_key is 'Clave estable para el ícono de las tarjetas de clase (calculadora, libro, banco, mundo). Se almacena en vez de derivarse del nombre, para que renombrar una asignatura no cambie su ícono.';
comment on column subjects.is_tutoria is 'Tutoría se programa como una asignatura pero no se califica en la escala de logro. "Tutoría 5to A" aparece entre las clases; debe excluirse de los agregados de distribución de logro.';

create unique index subjects_tenant_code_key
  on subjects (tenant_id, code) where deleted_at is null;

select app.enable_tenant_rls('subjects');
select app.attach_updated_at('subjects');
select app.attach_soft_delete_guard('subjects');

-- ---------------------------------------------------------------------------
-- competencies
-- ---------------------------------------------------------------------------
-- competencies.kind (RVM 094-2020 num. 5.1.3 p.9-11: las transversales nunca
-- cuentan para la promoción; las adicionales cuentan solo cuando están organizadas en un
-- área) y el subject_id nulable que requiere (las transversales no pertenecen a
-- ningún área) se definen aquí en su forma final en vez de aplicarse luego con un ALTER.
create table competencies (
  id           uuid primary key default gen_random_uuid(),
  tenant_id    uuid not null references tenants (id),
  subject_id   uuid,
  code         text not null,
  name         text not null,
  description  text,
  kind         text not null default 'area'
                 check (kind in ('area', 'transversal', 'adicional_area', 'adicional_libre')),
  sort_order   smallint not null default 0,
  is_active    boolean not null default true,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now(),
  deleted_at   timestamptz,
  constraint competencies_tenant_id_key unique (tenant_id, id),
  constraint competencies_subject_fk foreign key (tenant_id, subject_id)
    references subjects (tenant_id, id),
  constraint competencies_transversal_has_no_subject
    check ((kind = 'transversal') = (subject_id is null))
);

comment on table competencies is 'Una competencia MINEDU dentro de una asignatura, ej. "Se comunica oralmente en inglés como lengua extranjera". Las evidencias (assessments) llegan aquí a través de sus criterios de evaluación.';
comment on column competencies.code is 'Código del currículo nacional cuando existe, o un código propio del colegio si no. No es único entre tenants por diseño: dos colegios pueden codificar la misma competencia de forma distinta.';
comment on column competencies.kind is
  'Qué cuenta esta competencia para la promoción (RVM 094-2020 num. 5.1.3 p.9-11). ''area'': una competencia CNEB de un área curricular o taller — cuenta. ''adicional_area'': una competencia agregada por el colegio y organizada en un área curricular — cuenta (5.1.3 p.11). ''adicional_libre'': una competencia agregada por el colegio no organizada en un área — no cuenta (p.10). ''transversal'': una de las dos competencias transversales CNEB — nunca cuenta (p.9), y no lleva subject_id.';
comment on column competencies.subject_id is
  'El área curricular o taller al que pertenece esta competencia. Null solo para kind = ''transversal'': las dos competencias transversales CNEB no están adscritas a un área ni a un solo docente (5.1.1.3 p.8), y cada IE decide cómo se asigna su nivel.';

create unique index competencies_subject_code_key
  on competencies (tenant_id, subject_id, code) where deleted_at is null;
-- competencies_subject_code_key es parcial sobre una columna nulable, así que no
-- restringe a las transversales; estas necesitan su propia unicidad.
create unique index competencies_transversal_code_key
  on competencies (tenant_id, code)
  where subject_id is null and deleted_at is null;

select app.enable_tenant_rls('competencies');
select app.attach_updated_at('competencies');
select app.attach_soft_delete_guard('competencies');

-- ---------------------------------------------------------------------------
-- courses
-- ---------------------------------------------------------------------------
-- asignatura x grado x año. "Inglés 5to" como oferta curricular, antes
-- de dividirse en sections A/B/C. La política de calificación puede sobrescribirse aquí.
create table courses (
  id                uuid primary key default gen_random_uuid(),
  tenant_id         uuid not null references tenants (id),
  academic_year_id  uuid not null,
  subject_id        uuid not null,
  grade_level_id    uuid not null,
  name              text not null,
  code              text,
  weekly_hours      numeric(4, 2) check (weekly_hours >= 0),
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now(),
  deleted_at        timestamptz,
  constraint courses_tenant_id_key unique (tenant_id, id),
  constraint courses_year_key unique (tenant_id, academic_year_id, id),
  constraint courses_year_grade_key unique (tenant_id, academic_year_id, grade_level_id, id),
  constraint courses_year_fk foreign key (tenant_id, academic_year_id)
    references academic_years (tenant_id, id),
  constraint courses_subject_fk foreign key (tenant_id, subject_id)
    references subjects (tenant_id, id),
  constraint courses_grade_level_fk foreign key (tenant_id, grade_level_id)
    references grade_levels (tenant_id, id)
);

comment on table courses is 'Una asignatura dictada en un grado en un año determinado. Se ubica entre subjects y classes para que el currículo y la política de calificación se definan una vez por grado, no una vez por section.';
comment on column courses.weekly_hours is 'Horas semanales nominales según el plan de estudios. La cifra real viene de class_schedules; este es el plan contra el cual comparar.';

-- Dos índices en vez de uno: el caso común (sin code) sigue admitiendo una
-- sola course por asignatura+grado+año; una course con code (ej. módulos
-- paralelos de Educación para el Trabajo, "Computación" y "Cocina" en el
-- mismo grado y año) puede coexistir con otras siempre que cada code sea
-- distinto.
create unique index courses_natural_key_no_code
  on courses (tenant_id, academic_year_id, subject_id, grade_level_id)
  where code is null and deleted_at is null;
create unique index courses_natural_key_coded
  on courses (tenant_id, academic_year_id, subject_id, grade_level_id, code)
  where code is not null and deleted_at is null;

select app.enable_tenant_rls('courses');
select app.attach_updated_at('courses');
select app.attach_soft_delete_guard('courses');

-- ---------------------------------------------------------------------------
-- capabilities
-- ---------------------------------------------------------------------------
-- Una capacidad MINEDU: una de las sub-habilidades que componen una competencia
-- (CNEB). Adquirir capacidades por separado no significa por sí solo que un estudiante
-- sea competente — ser competente es usarlas de forma combinada — así que un criterio de
-- evaluación debe relacionarse con una capacidad específica y no flotar libre de
-- la estructura propia de la competencia.
create table capabilities (
  id            uuid primary key default gen_random_uuid(),
  tenant_id     uuid not null references tenants (id),
  competency_id uuid not null,
  code          text not null,
  name          text not null,
  description   text,
  sort_order    smallint not null default 0,
  is_active     boolean not null default true,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now(),
  deleted_at    timestamptz,
  constraint capabilities_tenant_id_key unique (tenant_id, id),
  constraint capabilities_competency_key unique (tenant_id, competency_id, id),
  constraint capabilities_competency_fk foreign key (tenant_id, competency_id)
    references competencies (tenant_id, id)
);

comment on table capabilities is 'Una capacidad MINEDU, ej. "Utiliza estrategias y conocimientos matemáticos" bajo la competencia "Resuelve problemas de cantidad".';
comment on column capabilities.code is 'Código del currículo nacional cuando existe, o un código propio del colegio si no.';

create unique index capabilities_competency_code_key
  on capabilities (tenant_id, competency_id, code) where deleted_at is null;

select app.enable_tenant_rls('capabilities');
select app.attach_updated_at('capabilities');
select app.attach_soft_delete_guard('capabilities');

-- ---------------------------------------------------------------------------
-- evaluation_criteria
-- ---------------------------------------------------------------------------
create table evaluation_criteria (
  id                       uuid primary key default gen_random_uuid(),
  tenant_id                uuid not null references tenants (id),
  competency_id            uuid not null,
  capability_id            uuid not null,
  code                     text,
  description              text not null,
  sort_order               smallint not null default 0,
  is_active                boolean not null default true,
  created_at               timestamptz not null default now(),
  updated_at               timestamptz not null default now(),
  deleted_at               timestamptz,
  constraint evaluation_criteria_tenant_id_key unique (tenant_id, id),
  constraint evaluation_criteria_competency_fk foreign key (tenant_id, competency_id)
    references competencies (tenant_id, id),
  constraint evaluation_criteria_capability_fk foreign key (tenant_id, competency_id, capability_id)
    references capabilities (tenant_id, competency_id, id)
);

comment on table evaluation_criteria is 'Un criterio de evaluación: el precisado propio del docente de un desempeño, ej. "Explica su punto de vista citando el texto" bajo la capacidad "Reflexiona y evalúa la forma, el contenido y contexto del texto". Esta es la capa que los docentes cargan en el sistema para evaluar una competencia.';
comment on column evaluation_criteria.capability_id is 'La capacidad que precisa este criterio. Obligatoria, y la FK compuesta (tenant_id, competency_id, capability_id) prueba que pertenece a la misma competencia indicada en esta fila -- un criterio no puede registrarse bajo una competencia mientras apunta a la capacidad de otra.';

create index evaluation_criteria_competency_idx
  on evaluation_criteria (tenant_id, competency_id) where deleted_at is null;
create index evaluation_criteria_capability_idx
  on evaluation_criteria (capability_id) where deleted_at is null;

select app.enable_tenant_rls('evaluation_criteria');
select app.attach_updated_at('evaluation_criteria');
select app.attach_soft_delete_guard('evaluation_criteria');


-- ---------------------------------------------------------------------------
-- sections
-- ---------------------------------------------------------------------------
create table sections (
  id                uuid primary key default gen_random_uuid(),
  tenant_id         uuid not null references tenants (id),
  academic_year_id  uuid not null,
  grade_level_id    uuid not null,
  label             text not null,
  name              text not null,
  tutor_teacher_id  uuid,
  shift             text not null default 'manana'
                      check (shift in ('manana', 'tarde', 'noche', 'completo')),
  capacity          smallint check (capacity > 0),
  status            text not null default 'active' check (status in ('active', 'archived')),
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now(),
  deleted_at        timestamptz,
  constraint sections_tenant_id_key unique (tenant_id, id),
  constraint sections_year_key unique (tenant_id, academic_year_id, id),
  constraint sections_year_grade_key unique (tenant_id, academic_year_id, grade_level_id, id),
  constraint sections_year_fk foreign key (tenant_id, academic_year_id)
    references academic_years (tenant_id, id),
  constraint sections_grade_level_fk foreign key (tenant_id, grade_level_id)
    references grade_levels (tenant_id, id),
  constraint sections_tutor_fk foreign key (tenant_id, tutor_teacher_id)
    references teachers (tenant_id, id)
);

comment on table sections is 'Un grupo de estudiantes que avanza junto en todas las asignaturas durante un año escolar, ej. "5to B". El roster: un estudiante pertenece a una section, y por lo tanto a cada class dictada a esa section.';
comment on column sections.label is 'Solo la letra de la section, ej. "B".';
comment on column sections.name is 'Forma de presentación que combina grado y letra, ej. "5to B". Se almacena en vez de derivarse porque cada colegio usa su propio espaciado y abreviaturas.';
comment on column sections.tutor_teacher_id is 'Tutor de aula. Distinto del docente de la clase de Tutoría, que se programa por separado.';

create unique index sections_natural_key
  on sections (tenant_id, academic_year_id, grade_level_id, label) where deleted_at is null;
create index sections_tutor_idx on sections (tutor_teacher_id) where deleted_at is null;

select app.enable_tenant_rls('sections');
select app.attach_updated_at('sections');
select app.attach_soft_delete_guard('sections');

-- ---------------------------------------------------------------------------
-- students
-- ---------------------------------------------------------------------------
create table students (
  id               uuid primary key default gen_random_uuid(),
  tenant_id        uuid not null references tenants (id),
  student_code     text,
  siagie_code      text check (siagie_code ~ '^[0-9]{14}$'),
  given_name       text not null,
  paternal_surname text not null,
  maternal_surname text,
  preferred_name   text,
  birthdate        date,
  sex              text check (sex in ('F', 'M', 'X', 'unspecified')),
  document_type    text check (document_type in ('DNI', 'CE', 'PAS', 'PTP', 'otro')),
  document_number  text,
  enrolled_on      date,
  left_on          date,
  status           text not null default 'active'
                     check (status in ('active', 'withdrawn', 'transferred', 'graduated')),
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now(),
  deleted_at       timestamptz,
  constraint students_tenant_id_key unique (tenant_id, id),
  constraint students_document_pair check ((document_type is null) = (document_number is null)),
  constraint students_left_after_enrolled check (left_on is null or enrolled_on is null or left_on >= enrolled_on)
);

comment on table students is
  'DATOS PERSONALES DE MENORES. Cada fila es un niño o niña. Contiene: nombres legales, fecha de nacimiento, sexo y documento nacional de identidad. Se procesa bajo la Ley 29733 (Perú) con consentimiento parental que conserva el colegio. Cada lectura debe registrarse en events (action=''student.read'').';

comment on column students.student_code is 'PII (menor): identificador. Código de matrícula interno del colegio.';
comment on column students.siagie_code is 'PII (menor): identificador. El código SIAGIE de 14 dígitos, el identificador nacional de MINEDU para estudiantes, ej. "12345678920001". Nulable: no todos los estudiantes tienen uno asignado todavía. Único por tenant y no globalmente: la fila antigua de un estudiante trasladado en su colegio anterior conserva el mismo código, y RLS ocultaría esa fila al nuevo colegio si la unicidad se aplicara entre tenants.';
comment on column students.given_name is 'PII (menor): nombre.';
comment on column students.paternal_surname is 'PII (menor): nombre. La convención peruana mantiene los dos apellidos por separado; concatenarlos pierde información.';
comment on column students.maternal_surname is 'PII (menor): nombre.';
comment on column students.preferred_name is 'PII (menor): nombre. Cómo llama realmente el docente al estudiante.';
comment on column students.birthdate is 'PII (menor): sensible. Está presente porque la edad determina tanto la ubicación curricular como el régimen de consentimiento; no se necesita para las pantallas principales de la aplicación.';
comment on column students.sex is 'PII (menor): sensible.';
comment on column students.document_number is 'PII (menor): identificador estatal. DNI o equivalente. La columna de mayor riesgo en el esquema.';

create unique index students_tenant_code_key
  on students (tenant_id, student_code) where student_code is not null and deleted_at is null;
create unique index students_siagie_code_key
  on students (tenant_id, siagie_code) where siagie_code is not null and deleted_at is null;
create unique index students_tenant_document_key
  on students (tenant_id, document_type, document_number) where document_number is not null and deleted_at is null;
-- "Buscar alumno..." sobre un roster, tecleado carácter por carácter.
create index students_name_trgm_idx on students
  using gin ((coalesce(given_name, '') || ' ' || coalesce(paternal_surname, '') || ' ' || coalesce(maternal_surname, '')) gin_trgm_ops);

select app.enable_tenant_rls('students');
select app.attach_updated_at('students');
select app.attach_soft_delete_guard('students');

-- ---------------------------------------------------------------------------
-- section_memberships
-- ---------------------------------------------------------------------------
create table section_memberships (
  id                uuid primary key default gen_random_uuid(),
  tenant_id         uuid not null references tenants (id),
  student_id        uuid not null,
  section_id        uuid not null,
  academic_year_id  uuid not null,
  joined_on         date not null,
  left_on           date,
  status            text not null default 'active'
                      check (status in ('active', 'withdrawn', 'transferred', 'promoted')),
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now(),
  deleted_at        timestamptz,
  constraint section_memberships_student_fk foreign key (tenant_id, student_id)
    references students (tenant_id, id),
  constraint section_memberships_section_fk foreign key (tenant_id, section_id)
    references sections (tenant_id, id),
  constraint section_memberships_year_fk foreign key (tenant_id, academic_year_id)
    references academic_years (tenant_id, id),
  constraint section_memberships_range_valid check (left_on is null or left_on >= joined_on),
  constraint section_memberships_active_consistent
    check ((status = 'active') = (left_on is null)),
  constraint section_memberships_one_at_a_time
    exclude using gist (
      student_id with =,
      academic_year_id with =,
      daterange(joined_on, left_on, '[)') with &&
    ) where (deleted_at is null)
);

comment on table section_memberships is
  'DATOS PERSONALES DE MENORES (asociación). El roster temporal: qué estudiante estuvo en qué section, durante qué fechas dentro de un año escolar. El roster de una clase se deriva de aquí, así que los denominadores de asistencia siempre se evalúan a la fecha de la sesión y no a la fecha de hoy.';
comment on column section_memberships.left_on is 'Fecha de fin exclusiva. Null mientras el estudiante sigue en la section. Un estudiante que se va a mitad de bimestre conserva toda fila previa de asistencia y de score.';
comment on constraint section_memberships_one_at_a_time on section_memberships is
  'Un estudiante no puede estar en dos sections en la misma fecha dentro de un año escolar. Este es el invariante que hace que "el roster de la clase X en la fecha D" sea siempre un conjunto único e inequívoco.';

-- La consulta del roster: primero por section, luego filtrado por fecha.
create index section_memberships_section_idx
  on section_memberships (section_id, joined_on, left_on) where deleted_at is null;
-- "542 Alumnos" -- estudiantes distintos entre las sections de un docente.
create index section_memberships_student_idx
  on section_memberships (student_id) where deleted_at is null;

select app.enable_tenant_rls('section_memberships');
select app.attach_updated_at('section_memberships');
select app.attach_soft_delete_guard('section_memberships');


-- ---------------------------------------------------------------------------
-- classes
-- ---------------------------------------------------------------------------
create table classes (
  id                uuid primary key default gen_random_uuid(),
  tenant_id         uuid not null references tenants (id),
  academic_year_id  uuid not null,
  grade_level_id    uuid not null,
  course_id         uuid not null,
  section_id        uuid not null,
  name              text not null,
  code              text,
  default_room      text,
  status            text not null default 'active'
                      check (status in ('active', 'archived', 'cancelled')),
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now(),
  deleted_at        timestamptz,
  constraint classes_tenant_id_key unique (tenant_id, id),
  constraint classes_year_key unique (tenant_id, academic_year_id, id),
  constraint classes_year_fk foreign key (tenant_id, academic_year_id)
    references academic_years (tenant_id, id),
  constraint classes_grade_level_fk foreign key (tenant_id, grade_level_id)
    references grade_levels (tenant_id, id),
  constraint classes_course_fk foreign key (tenant_id, academic_year_id, grade_level_id, course_id)
    references courses (tenant_id, academic_year_id, grade_level_id, id),
  constraint classes_section_fk foreign key (tenant_id, academic_year_id, grade_level_id, section_id)
    references sections (tenant_id, academic_year_id, grade_level_id, id)
);

comment on table classes is 'Una course dictada a una section: "Inglés 5to B". La unidad en la que realmente trabaja el docente — casi toda la aplicación se enfoca en una sola class. classes_course_fk/classes_section_fk son compuestas sobre academic_year_id y grade_level_id, así que una class no puede apuntar a una course o section de un año distinto al suyo, ni combinar una course y una section de grados distintos entre sí.';
comment on column classes.grade_level_id is 'Copiado del grado de la course/section que dicta. No es una fuente independiente de verdad: existe para que classes_course_fk/classes_section_fk puedan ser compuestas sobre él y así impedir una class que mezcle una course de un grado con una section de otro.';
comment on column classes.name is 'Nombre para mostrar. Se almacena porque es la cadena sobre la que buscan los docentes, y porque "Historia 5to C" y "Math 8B" no siguen una única regla de derivación.';

create unique index classes_course_section_key
  on classes (tenant_id, course_id, section_id) where deleted_at is null;
-- "Buscar por clase" -- búsqueda por subcadena mientras el docente escribe.
create index classes_name_trgm_idx on classes using gin (name gin_trgm_ops);
create index classes_section_idx on classes (section_id) where deleted_at is null;

select app.enable_tenant_rls('classes');
select app.attach_updated_at('classes');
select app.attach_soft_delete_guard('classes');

-- ---------------------------------------------------------------------------
-- class_teachers
-- ---------------------------------------------------------------------------
-- Con fechas, porque un docente que sale de licencia a mitad de año no debe reescribir quién dictó
-- (ni quién calificó) las sesiones previas al cambio.
create table class_teachers (
  id          uuid primary key default gen_random_uuid(),
  tenant_id   uuid not null references tenants (id),
  class_id    uuid not null,
  teacher_id  uuid not null,
  role        text not null default 'titular'
                check (role in ('titular', 'auxiliar', 'practicante', 'reemplazo')),
  starts_on   date not null,
  ends_on     date,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  deleted_at  timestamptz,
  constraint class_teachers_class_fk foreign key (tenant_id, class_id)
    references classes (tenant_id, id),
  constraint class_teachers_teacher_fk foreign key (tenant_id, teacher_id)
    references teachers (tenant_id, id),
  constraint class_teachers_range_valid check (ends_on is null or ends_on >= starts_on),
  constraint class_teachers_one_titular
    exclude using gist (
      class_id with =,
      daterange(starts_on, ends_on, '[)') with &&
    ) where (role = 'titular' and deleted_at is null)
);

comment on table class_teachers is 'Quién dicta una class, en qué calidad, durante qué fechas. Una class tiene exactamente un titular a la vez y cualquier número de auxiliares.';
comment on constraint class_teachers_one_titular on class_teachers is 'Dos titulares en la misma fecha harían que "mis clases" se contaran dos veces.';

-- Base de "mis clases hoy" y del conteo total de clases de un docente.
create index class_teachers_teacher_idx
  on class_teachers (teacher_id, starts_on, ends_on) where deleted_at is null;
create unique index class_teachers_key
  on class_teachers (class_id, teacher_id, starts_on) where deleted_at is null;

select app.enable_tenant_rls('class_teachers');
select app.attach_updated_at('class_teachers');
select app.attach_soft_delete_guard('class_teachers');

-- ---------------------------------------------------------------------------
-- class_schedules
-- ---------------------------------------------------------------------------
-- El patrón semanal recurrente, una fila por franja semanal. Se muestran
-- directamente para las clases más adelante en la semana ("Lunes 11:30 – 12:30" /
-- "Martes 3:00 – 4:00 PM" en una sola tarjeta = dos filas). También se cuentan
-- para mostrar "4 sesiones/semana" o "2/sem".
create table class_schedules (
  id              uuid primary key default gen_random_uuid(),
  tenant_id       uuid not null references tenants (id),
  class_id        uuid not null,
  weekday         smallint not null check (weekday between 1 and 7),
  starts_at       time not null,
  ends_at         time not null,
  room            text,
  effective_from  date not null,
  effective_to    date,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  deleted_at      timestamptz,
  constraint class_schedules_tenant_id_key unique (tenant_id, id),
  constraint class_schedules_class_fk foreign key (tenant_id, class_id)
    references classes (tenant_id, id),
  constraint class_schedules_time_valid check (ends_at > starts_at),
  constraint class_schedules_range_valid check (effective_to is null or effective_to > effective_from),
  constraint class_schedules_no_overlap
    exclude using gist (
      class_id with =,
      weekday with =,
      timerange(starts_at, ends_at, '[)') with &&,
      daterange(effective_from, effective_to, '[)') with &&
    ) where (deleted_at is null)
);

comment on table class_schedules is 'El patrón semanal recurrente de una class: una fila por franja semanal. Distinto de class_sessions, que son las instancias concretas con fecha. Un cambio de horario cierra la fila antigua con effective_to y abre una nueva, así que las sesiones pasadas se siguen explicando por sí mismas.';
comment on column class_schedules.weekday is 'Día de la semana ISO-8601, 1 = lunes .. 7 = domingo. Coincide con extract(isodow), para que el generador pueda hacer join sin aritmética.';
comment on column class_schedules.starts_at is 'Hora local de reloj en la zona horaria del tenant. Deliberadamente no es timestamptz: "10:00 los lunes" debe sobrevivir a un cambio de horario tipo DST, y el instante UTC concreto se materializa en class_sessions.';
comment on constraint class_schedules_no_overlap on class_schedules is 'Una class no puede ocupar dos franjas superpuestas el mismo día de la semana mientras ambas estén vigentes. No intenta detectar a un docente con doble reserva entre dos clases distintas — ver las notas sobre conflictos de horario entre clases.';

-- El patrón semanal del docente, por día de la semana.
create index class_schedules_class_idx
  on class_schedules (class_id, weekday) where deleted_at is null;
-- Generador de sesiones: qué franjas están vigentes para un rango de fechas.
create index class_schedules_effective_idx
  on class_schedules (tenant_id, effective_from, effective_to) where deleted_at is null;

select app.enable_tenant_rls('class_schedules');
select app.attach_updated_at('class_schedules');
select app.attach_soft_delete_guard('class_schedules');


-- ---------------------------------------------------------------------------
-- class_sessions
-- ---------------------------------------------------------------------------
create table class_sessions (
  id                          uuid primary key default gen_random_uuid(),
  tenant_id                   uuid not null references tenants (id),
  academic_year_id            uuid not null,
  class_id                    uuid not null,
  schedule_id                 uuid,
  term_id                     uuid,
  session_date                date not null,
  scheduled_start_at          timestamptz not null,
  scheduled_end_at            timestamptz not null,
  actual_start_at             timestamptz,
  actual_end_at               timestamptz,
  status                      text not null default 'scheduled'
                                check (status in ('scheduled', 'in_progress', 'completed', 'cancelled', 'rescheduled')),
  topic                       text,
  room                        text,
  started_by_id               uuid,
  attendance_taken_at         timestamptz,
  attendance_taken_by_id      uuid,
  created_at                  timestamptz not null default now(),
  updated_at                  timestamptz not null default now(),
  deleted_at                  timestamptz,
  constraint class_sessions_tenant_id_key unique (tenant_id, id),
  constraint class_sessions_year_fk foreign key (tenant_id, academic_year_id)
    references academic_years (tenant_id, id),
  constraint class_sessions_class_fk foreign key (tenant_id, academic_year_id, class_id)
    references classes (tenant_id, academic_year_id, id),
  constraint class_sessions_schedule_fk foreign key (tenant_id, schedule_id)
    references class_schedules (tenant_id, id),
  constraint class_sessions_term_fk foreign key (tenant_id, academic_year_id, term_id)
    references terms (tenant_id, academic_year_id, id),
  constraint class_sessions_started_by_fk foreign key (tenant_id, started_by_id)
    references teachers (tenant_id, id),
  constraint class_sessions_attendance_by_fk foreign key (tenant_id, attendance_taken_by_id)
    references teachers (tenant_id, id),
  constraint class_sessions_window_valid check (scheduled_end_at > scheduled_start_at),
  constraint class_sessions_actual_valid
    check (actual_end_at is null or actual_start_at is null or actual_end_at >= actual_start_at),
  constraint class_sessions_started_consistent
    check ((status in ('in_progress', 'completed')) <= (actual_start_at is not null)),
  constraint class_sessions_attendance_consistent
    check ((attendance_taken_at is null) = (attendance_taken_by_id is null))
);

comment on table class_sessions is 'Una instancia con fecha concreta de una class. Ciclo de vida scheduled -> in_progress -> completed, con cancelled y rescheduled como alternativas terminales. La tarjeta "HOY · SIN INICIAR" es una fila scheduled para hoy; el botón "Iniciar clase" la mueve a in_progress y registra actual_start_at.';
comment on column class_sessions.academic_year_id is 'Copiado del academic_year_id de la class al crear la sesión. class_sessions_class_fk/class_sessions_term_fk son compuestas sobre esta columna, así que una sesión no puede apuntar a un term de un año distinto al de su class.';
comment on column class_sessions.schedule_id is 'La franja recurrente de la que proviene esta instancia. Null para una sesión puntual agregada a mano, para que una clase de reposición ad hoc sea representable sin inventar una regla semanal.';
comment on column class_sessions.topic is 'Qué cubre la sesión, ej. "Present perfect tense". Se muestra tanto para la próxima sesión como para las pasadas.';
comment on column class_sessions.attendance_taken_at is 'Null significa que la asistencia nunca se marcó, que es exactamente lo que activa el recordatorio de "Asistencia sin marcar". Distinto de una sesión donde todos estuvieron ausentes.';
comment on constraint class_sessions_started_consistent on class_sessions is 'Implicación booleana: in_progress o completed requiere actual_start_at. Una sesión no puede estar en curso sin haber iniciado.';

create unique index class_sessions_class_start_key
  on class_sessions (class_id, scheduled_start_at) where deleted_at is null;
-- "HOY": todas las sesiones de un tenant para una fecha local, unidas al
-- docente a través de class_teachers. tenant_id primero para mantenerlo dentro del tenant.
create index class_sessions_tenant_date_idx
  on class_sessions (tenant_id, session_date, status) where deleted_at is null;
-- "PRÓXIMAS CLASES" / "CLASES ANTERIORES": una class, ordenada por fecha,
-- recorrida en ambas direcciones desde hoy.
create index class_sessions_class_date_idx
  on class_sessions (class_id, session_date desc) where deleted_at is null;
-- "Pendientes": sesiones completadas sin asistencia registrada.
create index class_sessions_attendance_pending_idx
  on class_sessions (tenant_id, session_date)
  where attendance_taken_at is null and status in ('in_progress', 'completed') and deleted_at is null;
-- "Clases dictadas 214": sesiones completadas por term.
create index class_sessions_term_idx
  on class_sessions (term_id, status) where deleted_at is null;

select app.enable_tenant_rls('class_sessions');
select app.attach_updated_at('class_sessions');
select app.attach_soft_delete_guard('class_sessions');

-- ---------------------------------------------------------------------------
-- attendance_records
-- ---------------------------------------------------------------------------
create table attendance_records (
  id             uuid primary key default gen_random_uuid(),
  tenant_id      uuid not null references tenants (id),
  session_id     uuid not null,
  student_id     uuid not null,
  class_id       uuid not null,
  session_date   date not null,
  status         text not null
                   check (status in ('present', 'late', 'absent', 'excused', 'justified')),
  minutes_late   smallint check (minutes_late >= 0),
  note           text,
  source         text not null default 'manual'
                   check (source in ('manual', 'bulk', 'import', 'auto')),
  recorded_by_id uuid not null,
  recorded_at    timestamptz not null default now(),
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now(),
  deleted_at     timestamptz,
  constraint attendance_records_session_fk foreign key (tenant_id, session_id)
    references class_sessions (tenant_id, id),
  constraint attendance_records_student_fk foreign key (tenant_id, student_id)
    references students (tenant_id, id),
  constraint attendance_records_class_fk foreign key (tenant_id, class_id)
    references classes (tenant_id, id),
  constraint attendance_records_recorded_by_fk foreign key (tenant_id, recorded_by_id)
    references teachers (tenant_id, id),
  constraint attendance_records_late_consistent
    check (minutes_late is null or status = 'late')
);

comment on table attendance_records is
  'DATOS PERSONALES DE MENORES (conductuales). Una fila por estudiante por sesión. Se registran con un toque a la vez o en bloque vía "Todos presentes"; de aquí se lee la "Asistencia 94%".';
comment on column attendance_records.status is 'excused y justified son distintos: excused significa que el colegio autorizó la ausencia por adelantado, justified significa que se aceptó un motivo válido después. Ambas son ausencias para la familia, ninguna cuenta en contra del estudiante.';
comment on column attendance_records.class_id is 'Desnormalizado desde la sesión. Presente para que las tasas de asistencia por class no necesiten un join, y se mantiene por trigger en vez de por la aplicación.';
comment on column attendance_records.session_date is 'Desnormalizado desde la sesión. La regla de ausencias consecutivas recorre los registros de un estudiante en orden de fecha; sin esto el recorrido necesitaría un join y un ordenamiento en cada evaluación.';
comment on column attendance_records.source is 'Cómo se creó la fila. bulk marca un toque de "Todos presentes", lo cual vale la pena distinguir de los toques individuales al juzgar qué tan confiable es el dato.';

-- Mantiene honestas las columnas desnormalizadas: se copian de la sesión, nunca
-- las provee quien llama.
-- +goose StatementBegin
create or replace function app.sync_attendance_denormalised() returns trigger
  language plpgsql
  as $fn$
  begin
    select s.class_id, s.session_date
      into new.class_id, new.session_date
      from class_sessions s
     where s.id = new.session_id
       and s.tenant_id = new.tenant_id;

    if not found then
      raise exception 'session % not found in tenant %', new.session_id, new.tenant_id
        using errcode = 'foreign_key_violation';
    end if;
    return new;
  end;
  $fn$;
-- +goose StatementEnd

create trigger sync_denormalised before insert or update of session_id on attendance_records
  for each row execute function app.sync_attendance_denormalised();

create unique index attendance_records_session_student_key
  on attendance_records (session_id, student_id) where deleted_at is null;
-- La lista de asistencia (roll-call) de una sesión.
create index attendance_records_session_idx
  on attendance_records (session_id) where deleted_at is null;
-- El historial de asistencia de un estudiante en orden de fecha.
create index attendance_records_student_date_idx
  on attendance_records (student_id, session_date desc) where deleted_at is null;
-- "Asistencia 94%": una class durante un term.
create index attendance_records_class_date_idx
  on attendance_records (class_id, session_date) where deleted_at is null;

select app.enable_tenant_rls('attendance_records');
select app.attach_updated_at('attendance_records');
select app.attach_soft_delete_guard('attendance_records');


-- ---------------------------------------------------------------------------
-- grade_scales
-- ---------------------------------------------------------------------------
create table grade_scales (
  id             uuid primary key default gen_random_uuid(),
  tenant_id      uuid not null references tenants (id),
  code           text not null,
  name           text not null,
  kind           text not null check (kind in ('ordinal', 'numeric', 'percentage')),
  min_value      numeric(8, 4) not null,
  max_value      numeric(8, 4) not null,
  decimals       smallint not null default 0 check (decimals between 0 and 4),
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now(),
  deleted_at     timestamptz,
  constraint grade_scales_tenant_id_key unique (tenant_id, id),
  constraint grade_scales_range_valid check (max_value > min_value)
);

comment on table grade_scales is 'Cómo expresa un colegio una nota. ordinal = MINEDU AD/A/B/C, numeric = vigesimal 0-20, percentage = 0-100. Toda escala se mapea al mismo eje normalizado 0-1, que es lo que permite entrenar un mismo modelo entre tenants.';
comment on column grade_scales.kind is 'Solo afecta la presentación. ordinal muestra el código del nivel, numeric muestra el valor, percentage muestra un porcentaje. Las tres se normalizan de forma idéntica.';
comment on column grade_scales.min_value is 'El valor más bajo que la escala puede expresar: 0 para vigesimal, y para una escala ordinal el piso numérico de su banda más baja.';
comment on column grade_scales.decimals is 'Precisión de presentación. Lo vigesimal normalmente se reporta como número entero aunque las scores en crudo sean decimales.';

create unique index grade_scales_tenant_code_key
  on grade_scales (tenant_id, code) where deleted_at is null;

select app.enable_tenant_rls('grade_scales');
select app.attach_updated_at('grade_scales');
select app.attach_soft_delete_guard('grade_scales');

-- ---------------------------------------------------------------------------
-- grade_scale_levels
-- ---------------------------------------------------------------------------
create table grade_scale_levels (
  id              uuid primary key default gen_random_uuid(),
  tenant_id       uuid not null references tenants (id),
  scale_id        uuid not null,
  code            text not null,
  label           text not null,
  short_label     text,
  ordinal         smallint not null,
  min_normalized  numeric(6, 5) not null check (min_normalized >= 0 and min_normalized <= 1),
  max_normalized  numeric(6, 5) not null check (max_normalized >= 0 and max_normalized <= 1),
  color_key       text,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  deleted_at      timestamptz,
  constraint grade_scale_levels_tenant_id_key unique (tenant_id, id),
  constraint grade_scale_levels_scale_fk foreign key (tenant_id, scale_id)
    references grade_scales (tenant_id, id),
  constraint grade_scale_levels_band_valid check (max_normalized > min_normalized),
  constraint grade_scale_levels_no_gap_overlap
    exclude using gist (
      scale_id with =,
      numrange(min_normalized, max_normalized, '[)') with &&
    ) where (deleted_at is null)
);

comment on table grade_scale_levels is 'Las bandas de una escala. Para AD/A/B/C estas son las notas reportadas; para una escala numérica son las bandas de color detrás del número. "Distribución de logros" agrupa por esta tabla, y "Logro esperado / A" lee label y code de una sola fila.';
comment on column grade_scale_levels.code is 'Lo que se imprime en la etiqueta: "AD", "A", "B", "C".';
comment on column grade_scale_levels.label is 'Texto completo: "Logro destacado", "Logro esperado", "En proceso", "En inicio". Se muestran el label y el code juntos.';
comment on column grade_scale_levels.min_normalized is 'Límite inferior inclusivo en el eje 0-1. Las bandas son semiabiertas [min, max), así que un valor cae en exactamente una banda.';
comment on column grade_scale_levels.max_normalized is 'Límite superior exclusivo, salvo en la banda más alta, que la búsqueda trata como cerrada para que un puntaje perfecto tenga un nivel.';
comment on constraint grade_scale_levels_no_gap_overlap on grade_scale_levels is 'Dos bandas de una misma escala no pueden solaparse. No se impiden los huecos aquí — un hueco es detectable pero no siempre es un error durante la autoría, así que se verifica cuando la escala se usa por primera vez.';

create unique index grade_scale_levels_scale_code_key
  on grade_scale_levels (tenant_id, scale_id, code) where deleted_at is null;
-- Búsqueda de nivel: dado un valor normalizado, encuentra su banda. Se ejecuta una vez por computed grade.
create index grade_scale_levels_lookup_idx
  on grade_scale_levels (scale_id, min_normalized, max_normalized) where deleted_at is null;

select app.enable_tenant_rls('grade_scale_levels');
select app.attach_updated_at('grade_scale_levels');
select app.attach_soft_delete_guard('grade_scale_levels');

-- ---------------------------------------------------------------------------
-- assessments
-- ---------------------------------------------------------------------------
create table assessments (
  id                        uuid primary key default gen_random_uuid(),
  tenant_id                 uuid not null references tenants (id),
  class_id                  uuid not null,
  term_id                   uuid,
  session_id                uuid,
  title                     text not null,
  description               text,
  student_id                uuid,
  kind                      text not null default 'produccion'
                              check (kind in ('produccion', 'actuacion')),
  value_scale               text not null default 'numeric'
                              check (value_scale in ('numeric', 'ordinal')),
  max_score                 numeric(8, 4) check (max_score > 0),
  due_at                    timestamptz,
  status                    text not null default 'draft'
                              check (status in ('draft', 'published', 'closed', 'cancelled')),
  published_at              timestamptz,
  closed_at                 timestamptz,
  created_by_id             uuid,
  created_at                timestamptz not null default now(),
  updated_at                timestamptz not null default now(),
  deleted_at                timestamptz,
  constraint assessments_tenant_id_key unique (tenant_id, id),
  constraint assessments_class_fk foreign key (tenant_id, class_id)
    references classes (tenant_id, id),
  constraint assessments_term_fk foreign key (tenant_id, term_id)
    references terms (tenant_id, id),
  constraint assessments_session_fk foreign key (tenant_id, session_id)
    references class_sessions (tenant_id, id),
  constraint assessments_created_by_fk foreign key (tenant_id, created_by_id)
    references teachers (tenant_id, id),
  constraint assessments_student_fk foreign key (tenant_id, student_id)
    references students (tenant_id, id),
  constraint assessments_published_consistent
    check ((status in ('published', 'closed')) <= (published_at is not null)),
  constraint assessments_closed_consistent
    check ((status = 'closed') = (closed_at is not null)),
  constraint assessments_max_score_matches_scale
    check ((value_scale = 'numeric') = (max_score is not null))
);

comment on table assessments is 'Una evidencia de una class: lo que los estudiantes producen o actúan y que el docente valora contra criterios de evaluación. Nace de una evidencia planificada (planned_evidence_id) o la crea el docente con "Añadir evidencia". Se valora en una sola escala (value_scale) y nunca lleva peso: informa el juicio del docente sobre el nivel de logro de la competencia y no lo calcula.';
comment on column assessments.term_id is 'El term al que pertenece esta evidencia. Nulable: una recuperación pedagógica o evaluación de subsanación suele ocurrir fuera del periodo lectivo regular, así que no tiene term que cerrar.';
comment on column assessments.student_id is 'Null significa que la evidencia aplica a toda la class, que es el caso original y sigue siendo el más común. Si está definido, es evidencia solo para ese estudiante, ej. una tarea de recuperación dada a uno solo.';
comment on column assessments.kind is
  'Producción (algo que los estudiantes elaboran) o actuación (algo que hacen frente a otros): los dos tipos de evidencia que nombra la RVM 094-2020 (glosario p.9). Mismo vocabulario que planned_evidences.kind.';
comment on column assessments.value_scale is
  'Cómo se valora esta evidencia, y es una propiedad de la evidencia, no de la pantalla. ''numeric'': una nota cruda sobre max_score (el máximo lo fija el docente), que la interfaz presenta como porcentaje. ''ordinal'': un nivel AD/A/B/C sobre esa evidencia. Ninguno de los dos es un nivel de logro: el nivel de una competencia se afirma en competency_term_levels por un docente que ha leído todo el periodo, y nada puede derivarlo de estos valores.';
comment on column assessments.max_score is 'El denominador sobre el que se mide cada score de esta evidencia, ej. 20 o 18. Solo aplica a value_scale = ''numeric''; null cuando es ''ordinal''.';
comment on column assessments.due_at is 'Fecha límite. Define qué evidencias cuentan como pendientes de valorar en el dashboard de la class.';
comment on column assessments.status is 'draft es invisible para el docente en la pantalla de valoración. Una evidencia debe publicarse antes de poder recibir scores.';

-- La evidencia de este estudiante para esta class y term.
create index assessments_class_term_idx
  on assessments (class_id, term_id, status) where deleted_at is null;
-- Leer la propia evidencia de un estudiante para una class+term es el camino más frecuente.
create index assessments_student_idx
  on assessments (class_id, term_id, student_id)
  where student_id is not null and deleted_at is null;
-- "Pendientes": evidencias publicadas ya vencidas.
create index assessments_due_idx
  on assessments (tenant_id, due_at)
  where status = 'published' and deleted_at is null;
create index assessments_session_idx on assessments (session_id) where session_id is not null and deleted_at is null;

select app.enable_tenant_rls('assessments');
select app.attach_updated_at('assessments');
select app.attach_soft_delete_guard('assessments');

-- ---------------------------------------------------------------------------
-- assessment_criteria
-- ---------------------------------------------------------------------------
-- El camino de una score en crudo al reporte por competencia: la cobertura de
-- una competencia se deriva uniendo assessment_criteria -> evaluation_criteria
-- .competency_id. Esta fila es lo que hace que un criterio forme parte de una
-- evidencia dada. El criterio es la regla con la que se lee la evidencia, no
-- lo que se califica: la valoración es una sola por estudiante y evidencia
-- (scores).
create table assessment_criteria (
  id             uuid primary key default gen_random_uuid(),
  tenant_id      uuid not null references tenants (id),
  assessment_id  uuid not null,
  criterion_id   uuid not null,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now(),
  deleted_at     timestamptz,
  constraint assessment_criteria_assessment_fk foreign key (tenant_id, assessment_id)
    references assessments (tenant_id, id),
  constraint assessment_criteria_criterion_fk foreign key (tenant_id, criterion_id)
    references evaluation_criteria (tenant_id, id),
  constraint assessment_criteria_tenant_key unique (tenant_id, assessment_id, criterion_id)
);

comment on table assessment_criteria is 'A qué criterios de evaluación habla una evidencia, ej. una "Tarea 1" etiquetada contra dos criterios de "Resuelve problemas de cantidad". Toda evidencia tiene al menos un criterio: es lo que la hace llegar a una competencia (el servidor lo exige al crearla).';
comment on constraint assessment_criteria_tenant_key on assessment_criteria is 'A diferencia del resto de esta migración, esta es una unique constraint completa, no parcial por deleted_at is null: Postgres solo permite que una FK apunte a una unique/primary key completa, nunca a un índice parcial, y una FK compuesta hacia esta tabla la necesitaría completa. Sin consecuencia práctica hoy — nada en Go borra una fila de assessment_criteria (linkAssessmentCriteria solo inserta) — pero si algún día se agrega un "destag", debe reactivar la fila existente en vez de insertar una nueva para el mismo par.';

create index assessment_criteria_criterion_idx on assessment_criteria (criterion_id);

select app.enable_tenant_rls('assessment_criteria');
select app.attach_updated_at('assessment_criteria');
select app.attach_soft_delete_guard('assessment_criteria');

-- ---------------------------------------------------------------------------
-- scores
-- ---------------------------------------------------------------------------
create table scores (
  id                        uuid primary key default gen_random_uuid(),
  tenant_id                 uuid not null references tenants (id),
  assessment_id             uuid not null,
  student_id                uuid not null,
  class_id                  uuid not null,
  term_id                   uuid,
  status                    text not null default 'graded'
                              check (status in ('graded', 'excused', 'absent', 'not_submitted')),
  raw_value                 numeric(8, 4),
  max_value                 numeric(8, 4),
  scale_level_id            uuid,
  feedback                  text,
  source                    text not null default 'manual'
                              check (source in ('manual', 'bulk', 'import', 'voice', 'auto')),
  recorded_by_id            uuid not null,
  recorded_at               timestamptz not null default now(),
  supersedes_id             uuid,
  superseded_at             timestamptz,
  created_at                timestamptz not null default now(),
  updated_at                timestamptz not null default now(),
  deleted_at                timestamptz,
  constraint scores_tenant_id_key unique (tenant_id, id),
  constraint scores_assessment_fk foreign key (tenant_id, assessment_id)
    references assessments (tenant_id, id),
  constraint scores_student_fk foreign key (tenant_id, student_id)
    references students (tenant_id, id),
  constraint scores_class_fk foreign key (tenant_id, class_id)
    references classes (tenant_id, id),
  constraint scores_term_fk foreign key (tenant_id, term_id)
    references terms (tenant_id, id),
  constraint scores_recorded_by_fk foreign key (tenant_id, recorded_by_id)
    references teachers (tenant_id, id),
  constraint scores_supersedes_fk foreign key (tenant_id, supersedes_id)
    references scores (tenant_id, id),
  constraint scores_scale_level_fk foreign key (tenant_id, scale_level_id)
    references grade_scale_levels (tenant_id, id),
  constraint scores_max_value_positive
    check (max_value is null or max_value > 0),
  constraint scores_value_matches_status
    check ((status = 'graded') = (raw_value is not null or scale_level_id is not null)),
  constraint scores_single_value
    check (raw_value is null or scale_level_id is null),
  constraint scores_value_in_range
    check (raw_value is null or (max_value is not null and raw_value >= 0 and raw_value <= max_value))
);

comment on table scores is
  'DATOS PERSONALES DE MENORES (académico). De solo inserción. La valoración de un estudiante en una evidencia: una nota cruda sobre el máximo (raw_value, max_value) o un nivel AD/A/B/C (scale_level_id), según value_scale de la evidencia, y nada derivado — sin porcentaje, sin peso. Corregir una score inserta una fila nueva que reemplaza a la anterior.';
comment on column scores.status is 'graded lleva un valor. not_submitted, absent y excused no llevan ninguno: son información para el docente sobre por qué falta la valoración.';
comment on column scores.raw_value is 'El número que escribió el docente, sobre max_value, ej. 14 sobre 18. Solo cuando la evidencia es numeric y status = graded.';
comment on column scores.max_value is 'Copiado de la evidencia al momento de escribir y congelado, así que cambiar después el máximo de una evidencia no puede reinterpretar notas ya ingresadas.';
comment on column scores.scale_level_id is 'El nivel AD/A/B/C que el docente dio a esta evidencia, como fila de grade_scale_levels. Solo cuando la evidencia es ordinal y status = graded. No es el nivel de logro de la competencia.';
comment on column scores.supersedes_id is 'La fila que esta reemplaza tras una corrección. El enlace apunta solo hacia atrás: un superseded_by_id hacia adelante tendría que escribirse en el mismo momento que superseded_at.';
comment on column scores.superseded_at is 'Se establece cuando una fila más nueva reemplaza a esta. Una fila con superseded_at null y deleted_at null es el valor vigente. Se escribe antes de insertar el reemplazo — ver scores_live_key.';
comment on column scores.class_id is 'Desnormalizado desde la evidencia. Se mantiene por trigger; permite que los agregados por class se salten un join.';
comment on column scores.term_id is 'Desnormalizado desde la evidencia. Nulable: una score de recuperación o subsanación puede registrarse contra una evidencia sin term (ver assessments.term_id).';

-- Exactamente una fila vigente por (evidencia, estudiante). Corregir una score está
-- entonces ordenado: cerrar la fila anterior (fijar superseded_at), luego insertar el
-- reemplazo. Un índice parcial no puede ser DEFERRABLE, así que las dos no pueden solaparse.
create unique index scores_live_key
  on scores (assessment_id, student_id)
  where superseded_at is null and deleted_at is null;
-- "Pendientes": quién en esta evidencia no tiene score vigente.
create index scores_assessment_idx
  on scores (assessment_id) where superseded_at is null and deleted_at is null;
-- Las scores vigentes de un estudiante para un term.
create index scores_student_term_idx
  on scores (student_id, term_id) where superseded_at is null and deleted_at is null;
create index scores_class_term_idx
  on scores (class_id, term_id) where superseded_at is null and deleted_at is null;
create index scores_supersedes_idx on scores (supersedes_id) where supersedes_id is not null;

-- Las columnas desnormalizadas se copian de la evidencia, nunca se proveen. Las
-- verificaciones de term cerrado, evidencia en borrador y valor que no corresponde a
-- la escala viven en esta misma función a propósito: dependen de columnas que no
-- existen en la fila entrante. Como triggers BEFORE INSERT separados se dispararían en
-- orden alfabético, una verificación que corriera antes que esta leería un term null y pasaría.
-- +goose StatementBegin
create or replace function app.sync_score_denormalised() returns trigger
  language plpgsql
  as $fn$
  declare
    v_assessment_status text;
    v_term_status       text;
    v_value_scale       text;
  begin
    select a.class_id, a.term_id, a.status, t.status, a.value_scale
      into new.class_id, new.term_id, v_assessment_status, v_term_status, v_value_scale
      from assessments a
      left join terms t on t.id = a.term_id
     where a.id = new.assessment_id
       and a.tenant_id = new.tenant_id;

    if not found then
      raise exception 'assessment % not found in tenant %', new.assessment_id, new.tenant_id
        using errcode = 'foreign_key_violation';
    end if;

    if v_assessment_status = 'draft' then
      raise exception 'assessment % is still a draft and cannot be scored', new.assessment_id
        using errcode = 'check_violation';
    end if;

    -- Un term cerrado deja de aceptar valoraciones. Esto es lo que hace que una libreta
    -- cerrada sea real y no solo una convención. Una evidencia sin term no tiene term que
    -- cerrar, así que la verificación se omite.
    if v_term_status in ('closed', 'archived') then
      raise exception 'term % is closed; scores cannot be added or changed', new.term_id
        using errcode = 'restrict_violation',
              hint = 'Reopen the term explicitly, which is an audited action, or record the change as a subsanación in the current term.';
    end if;

    -- El valor tiene que ser del tipo de la escala de la evidencia.
    if v_value_scale = 'numeric' and new.scale_level_id is not null then
      raise exception 'assessment % is numeric and cannot take a level', new.assessment_id
        using errcode = 'check_violation';
    end if;
    if v_value_scale = 'ordinal' and new.raw_value is not null then
      raise exception 'assessment % is ordinal and cannot take a numeric mark', new.assessment_id
        using errcode = 'check_violation';
    end if;

    return new;
  end;
  $fn$;
-- +goose StatementEnd

create trigger sync_denormalised before insert on scores
  for each row execute function app.sync_score_denormalised();

-- Las valoraciones son temporales. Una score nunca se actualiza en el lugar.
-- +goose StatementBegin
create or replace function app.forbid_score_mutation() returns trigger
  language plpgsql
  as $fn$
  begin
    if new.assessment_id  is distinct from old.assessment_id
       or new.student_id  is distinct from old.student_id
       or new.status         is distinct from old.status
       or new.raw_value      is distinct from old.raw_value
       or new.max_value      is distinct from old.max_value
       or new.scale_level_id is distinct from old.scale_level_id
       or new.recorded_by_id is distinct from old.recorded_by_id
       or new.recorded_at    is distinct from old.recorded_at then
      raise exception 'scores are append-only (score %); insert a superseding row instead of updating', old.id
        using errcode = 'restrict_violation',
              hint = 'Stamp superseded_at on this row FIRST, then insert the replacement with supersedes_id set. scores_live_key is a partial unique index and cannot be deferred, so two live rows for one student and evidence cannot overlap.';
    end if;
    return new;
  end;
  $fn$;
-- +goose StatementEnd

create trigger forbid_mutation before update on scores
  for each row execute function app.forbid_score_mutation();

select app.enable_tenant_rls('scores');
select app.attach_updated_at('scores');
select app.attach_soft_delete_guard('scores');

-- ---------------------------------------------------------------------------
-- voice_notes
-- ---------------------------------------------------------------------------
create table voice_notes (
  id                    uuid primary key default gen_random_uuid(),
  tenant_id             uuid not null references tenants (id),
  session_id            uuid not null,
  student_id            uuid not null,
  class_id              uuid not null,
  teacher_id            uuid not null,
  recorded_at           timestamptz not null default now(),
  duration_ms           integer not null check (duration_ms >= 0),
  storage_key           text,
  audio                 bytea,
  mime_type             text,
  byte_size             bigint check (byte_size >= 0),
  transcription_status  text not null default 'pending'
                          check (transcription_status in ('pending', 'queued', 'processing', 'completed', 'failed', 'skipped')),
  transcript            text,
  created_at            timestamptz not null default now(),
  updated_at            timestamptz not null default now(),
  deleted_at            timestamptz,
  constraint voice_notes_tenant_id_key unique (tenant_id, id),
  constraint voice_notes_session_fk foreign key (tenant_id, session_id)
    references class_sessions (tenant_id, id),
  constraint voice_notes_student_fk foreign key (tenant_id, student_id)
    references students (tenant_id, id),
  constraint voice_notes_class_fk foreign key (tenant_id, class_id)
    references classes (tenant_id, id),
  constraint voice_notes_teacher_fk foreign key (tenant_id, teacher_id)
    references teachers (tenant_id, id),
  constraint voice_notes_transcript_consistent
    check ((transcription_status = 'completed') <= (transcript is not null))
);

comment on table voice_notes is
  'DATOS PERSONALES DE MENORES (conductual, vía la transcripción). Una nota hablada del docente sobre un estudiante, grabada durante una sesión. El audio es la voz del docente; la transcripción es habla libre sobre un menor, la columna de mayor riesgo en el esquema después de los datos de identificación propios de los estudiantes.';

comment on column voice_notes.duration_ms is 'Duración en milisegundos. Se muestra como "0:04" junto al control de reproducción.';
comment on column voice_notes.storage_key is
  'Puntero heredado a disco, de antes de que el audio pasara a esta tabla. Se deja en su lugar para que las grabaciones previas a la migración en STORAGE_DIR sigan siendo reproducibles; las filas nuevas lo dejan null.';
comment on column voice_notes.audio is
  'El audio grabado en sí. No es PII de un menor: es la voz del docente, grabada con su conocimiento mientras narra una observación — la parte sensible es el contenido hablado (ver la columna transcript), no la huella de voz. Sustituye a storage_key: se escribe aquí dentro de la misma transacción que la inserción de la fila, así que una nota y su audio nunca pueden desincronizarse como sí podría pasar entre una fila de BD y un archivo en disco.';
comment on column voice_notes.transcript is 'PII (menor): habla libre sobre un niño o niña. Nulable y purgable por separado del audio, para que un colegio pueda eliminar transcripciones y conservar las duraciones para analítica.';

-- Las notas de una sesión, y por estudiante dentro de ella.
create index voice_notes_session_idx on voice_notes (session_id) where deleted_at is null;
-- Todas las notas de un estudiante, más reciente primero -- el insumo para el resumen.
create index voice_notes_student_idx
  on voice_notes (student_id, recorded_at desc) where deleted_at is null;
-- El worker de transcripción: la cola de notas aún pendientes.
create index voice_notes_transcription_idx
  on voice_notes (tenant_id, transcription_status)
  where transcription_status in ('pending', 'queued', 'failed') and deleted_at is null;
-- "Notas de voz 486" de un docente durante un term.
create index voice_notes_teacher_idx
  on voice_notes (teacher_id, recorded_at) where deleted_at is null;

select app.enable_tenant_rls('voice_notes');
select app.attach_updated_at('voice_notes');
select app.attach_soft_delete_guard('voice_notes');

-- ---------------------------------------------------------------------------
-- notifications
-- ---------------------------------------------------------------------------
create table notifications (
  id                   uuid primary key default gen_random_uuid(),
  tenant_id            uuid not null references tenants (id),
  recipient_teacher_id uuid not null,
  kind                 text not null check (kind in ('alert', 'reminder')),
  category             text not null,
  severity             text not null default 'info' check (severity in ('info', 'low', 'medium', 'high')),
  title                text not null,
  body                 text,
  payload              jsonb not null default '{}'::jsonb,
  student_id           uuid,
  class_id             uuid,
  session_id           uuid,
  assessment_id        uuid,
  source               text not null default 'system'
                         check (source in ('system', 'rule', 'model', 'teacher')),
  created_at           timestamptz not null default now(),
  read_at              timestamptz,
  dismissed_at         timestamptz,
  updated_at           timestamptz not null default now(),
  deleted_at           timestamptz,
  constraint notifications_recipient_fk foreign key (tenant_id, recipient_teacher_id)
    references teachers (tenant_id, id),
  constraint notifications_student_fk foreign key (tenant_id, student_id)
    references students (tenant_id, id),
  constraint notifications_class_fk foreign key (tenant_id, class_id)
    references classes (tenant_id, id),
  constraint notifications_session_fk foreign key (tenant_id, session_id)
    references class_sessions (tenant_id, id),
  constraint notifications_assessment_fk foreign key (tenant_id, assessment_id)
    references assessments (tenant_id, id)
);

comment on table notifications is 'DATOS PERSONALES DE MENORES (derivado). El feed de notificaciones. Los títulos y cuerpos de las alertas nombran estudiantes individuales y declaran inferencias sobre ellos, así que una fila de notification es dato de estudiante aunque esté dirigida a un docente. kind determina los filtros de Alertas/Recordatorios; read_at determina el punto de no leído y el estado atenuado "Leído". Cada fila lleva la entidad que la disparó, para que al tocarla se llegue al estudiante o la class en vez de a un callejón sin salida.';

comment on column notifications.category is 'Subtipo legible por máquina dentro de kind. Sobre esto agrupa y filtra el cliente; title y body son para humanos.';

-- El feed, más reciente primero, opcionalmente filtrado por kind.
create index notifications_feed_idx
  on notifications (recipient_teacher_id, created_at desc) where deleted_at is null;
-- La insignia de la campana: ¿tiene este docente algo sin leer?
create index notifications_unread_idx
  on notifications (recipient_teacher_id, kind)
  where read_at is null and dismissed_at is null and deleted_at is null;
create index notifications_student_idx on notifications (student_id) where student_id is not null;

select app.enable_tenant_rls('notifications');
select app.attach_updated_at('notifications');
select app.attach_soft_delete_guard('notifications');


-- ---------------------------------------------------------------------------
-- events
-- ---------------------------------------------------------------------------
-- Particionada por mes desde el primer día. Esta tabla está diseñada para leerse como una
-- serie de tiempo -- "cada acción sobre este estudiante, en orden", "cada edición de nota
-- este bimestre" -- no solo como un registro de auditoría, y crecerá más que cualquier otra
-- tabla del esquema. Retirar datos antiguos debe ser un DETACH, no un DELETE.
create table events (
  id             uuid not null default gen_random_uuid(),
  tenant_id      uuid not null,
  occurred_at    timestamptz not null default now(),
  actor_type     text not null default 'user'
                   check (actor_type in ('user', 'system', 'job', 'model', 'import')),
  actor_id       uuid,
  actor_teacher_id uuid,
  action         text not null,
  entity_type    text not null,
  entity_id      uuid,
  student_id     uuid,
  class_id       uuid,
  session_id     uuid,
  term_id        uuid,
  request_id     text,
  payload        jsonb not null default '{}'::jsonb,
  primary key (id, occurred_at)
) partition by range (occurred_at);

comment on table events is
  'Registro de solo inserción de cada acción relevante, incluyendo cada lectura de un registro de estudiante. Particionado por mes e indexado para acceso como serie de tiempo porque es el corpus de entrenamiento para detección de riesgo y proyección de notas, no solo un registro de auditoría. Nunca se actualiza, nunca se elimina — los meses antiguos se desconectan (DETACH).';

comment on column events.occurred_at is 'Cuándo ocurrió la acción, en UTC. También es la clave de partición, así que forma parte de la llave primaria.';
comment on column events.tenant_id is 'Acota la política RLS. Deliberadamente no es una FK hacia tenants: el registro debe sobrevivir al borrado de todo lo que describe, y una FK sobre una tabla particionada tan grande haría que cada operación a nivel de tenant tomara locks en cada partición.';
comment on column events.actor_id is 'La fila de users que actuó. Null para actores system y job. No es una FK: los events sobreviven a las filas que referencian, y un event nunca debe bloquearse ni propagarse en cascada por un cambio en el actor.';
comment on column events.action is 'Verbo en forma entidad.verbo: student.read, score.recorded, session.started, attendance.marked, voice_note.saved. La columna más importante para el entrenamiento de modelos, así que es una taxonomía de texto libre en vez de un enum restringido que necesitaría una migración por cada verbo nuevo.';
comment on column events.student_id is 'Sujeto desnormalizado de la acción. Presente para que "todo lo que le pasó a este estudiante" sea un solo recorrido de índice en vez de una búsqueda en jsonb, y para que una solicitud de acceso bajo la Ley 29733 pueda responderse directamente.';
comment on column events.class_id is 'Contexto de class desnormalizado, para series de actividad por class sin desempaquetar payload.';
comment on column events.request_id is 'Correlaciona los events escritos durante una misma solicitud a la API, que es lo que convierte una lista de filas en una secuencia causal.';
comment on column events.payload is 'Detalle específico de la acción. Deliberadamente sin esquema: restringirlo convertiría agregar una acción en una migración.';

-- Independiente de la pantalla, pero toda consulta de retención y de acceso del titular la necesita.
create index events_tenant_time_idx on events (tenant_id, occurred_at desc);
-- "Todo lo que le pasó a este estudiante", incluyendo las lecturas.
create index events_student_time_idx on events (student_id, occurred_at desc);
-- Auditoría del historial de una entidad: qué nota cambió cuándo, y quién lo hizo.
create index events_entity_idx on events (entity_type, entity_id, occurred_at desc);
-- Extracción de features de serie de tiempo: un tipo de acción a través de un periodo.
create index events_action_time_idx on events (action, occurred_at desc);
create index events_class_time_idx on events (class_id, occurred_at desc);

-- Particiones mensuales. La partición DEFAULT es una red de seguridad para que una fila que
-- llegue tarde o con el reloj desfasado nunca sea rechazada; el job mensual que pre-crea
-- las particiones debe mantenerla vacía.
-- +goose StatementBegin
do $$
declare
  m date := date '2026-01-01';
begin
  while m < date '2028-01-01' loop
    execute format(
      'create table events_%s partition of events for values from (%L) to (%L)',
      to_char(m, 'YYYY_MM'), m, (m + interval '1 month')::date);
    m := (m + interval '1 month')::date;
  end loop;
end
$$;
-- +goose StatementEnd

create table events_default partition of events default;

comment on table events_default is 'Partición comodín. Debe permanecer vacía: si caen filas aquí significa que el job de creación de particiones se ha atrasado.';

-- +goose StatementBegin
create or replace function app.ensure_events_partition(p_month date) returns void
  language plpgsql
  as $fn$
  declare
    v_start date := date_trunc('month', p_month)::date;
    v_name  text := format('events_%s', to_char(v_start, 'YYYY_MM'));
  begin
    if to_regclass(v_name) is null then
      execute format(
        'create table %I partition of events for values from (%L) to (%L)',
        v_name, v_start, (v_start + interval '1 month')::date);
    end if;
  end;
  $fn$;
-- +goose StatementEnd

comment on function app.ensure_events_partition(date) is 'Creación idempotente de particiones, llamada por un job programado con varios meses de anticipación.';

-- De solo inserción, forzado en vez de asumido.
-- +goose StatementBegin
create or replace function app.forbid_event_mutation() returns trigger
  language plpgsql
  as $fn$
  begin
    raise exception 'events is append-only (attempted % on %)', tg_op, tg_table_name
      using errcode = 'restrict_violation';
  end;
  $fn$;
-- +goose StatementEnd

create trigger forbid_mutation before update or delete on events
  for each row execute function app.forbid_event_mutation();

alter table events enable row level security;
alter table events force row level security;
create policy tenant_isolation on events
  using (tenant_id = app.current_tenant_id())
  with check (tenant_id = app.current_tenant_id());

-- +goose StatementBegin
create or replace function app.log_event(
  p_action      text,
  p_entity_type text,
  p_entity_id   uuid default null,
  p_payload     jsonb default '{}'::jsonb,
  p_student_id  uuid default null,
  p_class_id    uuid default null,
  p_session_id  uuid default null
) returns uuid
  language plpgsql
  as $fn$
  declare
    v_id uuid;
  begin
    insert into events (tenant_id, actor_id, action, entity_type, entity_id,
                        student_id, class_id, session_id, payload,
                        request_id)
    values (app.current_tenant_id(), app.current_actor_id(), p_action, p_entity_type, p_entity_id,
            p_student_id, p_class_id, p_session_id, p_payload,
            nullif(current_setting('app.request_id', true), ''))
    returning id into v_id;
    return v_id;
  end;
  $fn$;
-- +goose StatementEnd

comment on function app.log_event(text, text, uuid, jsonb, uuid, uuid, uuid) is
  'Función de escritura de conveniencia que completa tenant, actor y request a partir de la sesión. Las lecturas de registros de estudiante se registran a través de esta desde la capa de acceso a datos — Postgres no puede disparar triggers sobre SELECT, así que la garantía se hace cumplir en Go y se respalda con pgaudit.';

-- ---------------------------------------------------------------------------
-- jobs
-- ---------------------------------------------------------------------------
create table jobs (
  id            bigint generated always as identity primary key,
  tenant_id     uuid references tenants (id),
  kind          text not null,
  queue         text not null default 'default',
  priority      smallint not null default 1 check (priority between 1 and 4),
  payload       jsonb not null default '{}'::jsonb,
  status        text not null default 'available'
                  check (status in ('available', 'running', 'retryable', 'scheduled',
                                    'completed', 'cancelled', 'discarded')),
  attempts      smallint not null default 0 check (attempts >= 0),
  max_attempts  smallint not null default 20 check (max_attempts > 0),
  run_after     timestamptz not null default now(),
  attempted_at  timestamptz,
  attempted_by  text,
  finalized_at  timestamptz,
  errors        jsonb not null default '[]'::jsonb,
  tags          text[] not null default '{}',
  unique_key    text,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now(),
  constraint jobs_finalized_consistent
    check ((status in ('completed', 'cancelled', 'discarded')) = (finalized_at is not null)),
  constraint jobs_errors_is_array check (jsonb_typeof(errors) = 'array')
);

comment on table jobs is
  'La cola de trabajo, en Postgres. La transcripción de notas de voz y las generaciones de los agentes pasan por aquí. Se reclama con SELECT ... FOR UPDATE SKIP LOCKED, que es la única razón por la que una cola en la base de datos primaria es viable a esta escala.';

comment on column jobs.tenant_id is 'Nulable: el trabajo de mantenimiento entre tenants no tiene tenant. Por eso jobs no lleva política RLS — un worker legítimamente abarca varios tenants y establece app.tenant_id por cada job.';
comment on column jobs.kind is
  'Qué handler ejecuta el job. Los tipos vigentes son ''voice_note.transcribe'' (transcripción de voz a texto en español para una nota grabada) y ''agent.generate'' (una generación de los agentes de Mawta). Texto libre sin CHECK: las filas de tipos retirados fallan como ''unknown job kind'' en vez de reescribirse.';
comment on column jobs.priority is 'El menor corre primero. La transcripción de una nota que el docente está viendo tiene prioridad sobre un trabajo de mantenimiento nocturno.';
comment on column jobs.run_after is 'El momento más temprano en que este job puede reclamarse. Sirve tanto para programación como para el backoff exponencial.';
comment on column jobs.attempted_by is 'Identidad del worker que sostiene el lease actual, para diagnosticar un job atascado.';
comment on column jobs.errors is 'Arreglo de solo inserción de registros de fallo, uno por intento. Se conserva completo porque un job que eventualmente tuvo éxito tras tres fallos de transcripción es en sí mismo una señal sobre la calidad del audio.';
comment on column jobs.unique_key is 'Clave de deduplicación. Evita que una ráfaga de ediciones de score encole cuarenta recomputaciones de notas idénticas para el mismo estudiante.';

-- La consulta de reclamo: un solo índice parcial que hace todo el trabajo.
create index jobs_claim_idx
  on jobs (queue, priority, run_after, id)
  where status in ('available', 'retryable', 'scheduled');
create unique index jobs_unique_key_idx
  on jobs (kind, unique_key)
  where unique_key is not null and status in ('available', 'retryable', 'scheduled', 'running');
create index jobs_tenant_kind_idx on jobs (tenant_id, kind, created_at desc);
-- Depuración del trabajo terminado.
create index jobs_finalized_idx on jobs (finalized_at) where finalized_at is not null;

select app.attach_updated_at('jobs');


-- ---------------------------------------------------------------------------
-- El registro derivado de datos personales
-- ---------------------------------------------------------------------------
create view privacy.pii_columns as
select
  n.nspname                        as schema_name,
  c.relname                        as table_name,
  a.attname                        as column_name,
  format_type(a.atttypid, a.atttypmod) as data_type,
  case
    when d.description like 'PII (menor y adulto)%' then 'minor_and_adult'
    when d.description like 'PII (menor)%'          then 'minor'
    when d.description like 'PII (adulto)%'         then 'adult'
    else 'unclassified'
  end                              as subject,
  nullif(trim(substring(d.description from 'PII \([^)]*\):\s*([^.]*)')), '') as category,
  d.description                    as note
from pg_class c
join pg_namespace n  on n.oid = c.relnamespace
join pg_attribute a  on a.attrelid = c.oid and a.attnum > 0 and not a.attisdropped
join pg_description d on d.objoid = c.oid and d.objsubid = a.attnum
where n.nspname = 'public'
  and c.relkind in ('r', 'p')
  and d.description like 'PII %';

comment on view privacy.pii_columns is 'Cada columna documentada como portadora de datos personales, derivada del texto de COMMENT ON. Responde "dónde guarda esta base de datos información sobre menores" con un solo SELECT, y no puede desactualizarse respecto a los comentarios que lee.';

create view privacy.minor_data_tables as
select
  n.nspname   as schema_name,
  c.relname   as table_name,
  d.description as note
from pg_class c
join pg_namespace n on n.oid = c.relnamespace
join pg_description d on d.objoid = c.oid and d.objsubid = 0
where n.nspname = 'public'
  and c.relkind in ('r', 'p')
  and d.description like '%DATOS PERSONALES DE MENORES%';

comment on view privacy.minor_data_tables is 'Tablas cuyo comentario declara que contienen datos sobre menores. La unidad sobre la que opera un procedimiento de retención o de borrado.';

-- Una salvaguarda contra que el registro se desactualice silenciosamente respecto al esquema: cualquier tabla
-- que referencia a un student pero no se declara a sí misma como portadora de datos de menores.
create view privacy.undeclared_student_references as
select
  c.relname as table_name,
  a.attname as column_name
from pg_class c
join pg_namespace n on n.oid = c.relnamespace
join pg_attribute a on a.attrelid = c.oid and a.attnum > 0 and not a.attisdropped
left join pg_description d on d.objoid = c.oid and d.objsubid = 0
where n.nspname = 'public'
  and c.relkind in ('r', 'p')
  and not c.relispartition
  and a.attname = 'student_id'
  and coalesce(d.description, '') not like '%DATOS PERSONALES DE MENORES%'
  and c.relname <> 'events';

comment on view privacy.undeclared_student_references is 'Debe devolver cero filas. Cualquier tabla que lleve un student_id sin declararse a sí misma en el registro es un hueco de documentación; se verifica que esto esté vacío en CI para que las tablas nuevas no puedan saltarse la declaración. Las particiones se omiten porque heredan la declaración de su tabla padre en vez de llevar su propio comentario, y events se omite por nombre: referencia a todo tipo de entidad y vive bajo sus propias reglas de retención.';



-- ---------------------------------------------------------------------------
-- Educación inclusiva.
--
-- 5.1.1.3 p.7 (texto de la 048-2024): para estudiantes que enfrentan barreras educativas la
-- conclusión descriptiva debe registrar los apoyos educativos y ajustes
-- razonables brindados *en todo periodo*, sin importar el nivel alcanzado.
-- ---------------------------------------------------------------------------

alter table students
  add column inclusion_support boolean not null default false;

comment on column students.inclusion_support is
  'DATOS PERSONALES DE MENORES (sensible). True cuando el estudiante enfrenta barreras educativas y recibe apoyos educativos / ajustes razonables. Hace obligatoria una conclusión descriptiva en todo periodo sin importar el nivel alcanzado, y esa conclusión debe indicar los apoyos brindados (RVM 048-2024, 5.1.1.3 p.7 último párrafo). Deliberadamente es una bandera, no un diagnóstico: el esquema registra la obligación, no la condición.';

-- ---------------------------------------------------------------------------
-- El registro en sí.
-- ---------------------------------------------------------------------------

create table competency_term_levels (
  id                 uuid primary key default gen_random_uuid(),
  tenant_id          uuid not null references tenants (id),
  student_id         uuid not null,
  competency_id      uuid not null,
  academic_year_id   uuid not null,
  term_id            uuid,
  class_id           uuid,
  scale_level_id     uuid not null,
  asserted_by_id     uuid,
  asserted_at        timestamptz not null default now(),
  note               text,
  supersedes_id      uuid,
  superseded_at      timestamptz,
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now(),
  deleted_at         timestamptz,
  constraint ctl_tenant_id_key unique (tenant_id, id),
  constraint ctl_student_fk foreign key (tenant_id, student_id)
    references students (tenant_id, id),
  constraint ctl_competency_fk foreign key (tenant_id, competency_id)
    references competencies (tenant_id, id),
  constraint ctl_year_fk foreign key (tenant_id, academic_year_id)
    references academic_years (tenant_id, id),
  constraint ctl_term_year_fk foreign key (tenant_id, academic_year_id, term_id)
    references terms (tenant_id, academic_year_id, id),
  constraint ctl_class_year_fk foreign key (tenant_id, academic_year_id, class_id)
    references classes (tenant_id, academic_year_id, id),
  constraint ctl_level_fk foreign key (tenant_id, scale_level_id)
    references grade_scale_levels (tenant_id, id),
  constraint ctl_asserted_by_fk foreign key (tenant_id, asserted_by_id)
    references teachers (tenant_id, id),
  constraint ctl_supersedes_fk foreign key (tenant_id, supersedes_id)
    references competency_term_levels (tenant_id, id)
);

comment on table competency_term_levels is
  'DATOS PERSONALES DE MENORES (académico, oficial). El nivel de logro de una competencia para un estudiante en un periodo — la fila que va a SIAGIE y, al cierre del año, decide la situación final. Escrito por el juicio de un docente sobre la evidencia del periodo (5.1.1.3 p.2-3), nunca por un cálculo. Una competencia no desarrollada ni evaluada explícitamente en el periodo simplemente no tiene fila (5.1.2.2 p.1) — la ausencia es significativa y no debe leerse como C.';
comment on column competency_term_levels.scale_level_id is 'El nivel afirmado, como una fila de grade_scale_levels (AD/A/B/C en la escala ordinal MINEDU). El único valor que es oficial.';
comment on column competency_term_levels.class_id is 'Desde qué class afirmó el docente, para trazabilidad y permisos. No forma parte de la identidad del registro: la norma conoce competencias y periodos, no classes, y una competencia obtiene exactamente un nivel por periodo.';
comment on column competency_term_levels.superseded_at is 'Se establece cuando una corrección reemplaza esta fila. Null significa vigente. Se escribe antes de insertar el reemplazo, ya que ctl_regular_key/ctl_recuperacion_key admiten solo una fila vigente por estudiante, competencia y term (o año, sin term).';
comment on column competency_term_levels.asserted_by_id is 'El docente que hizo el juicio. Nulable: una competencia transversal no está adscrita a un solo docente, así que su nivel puede afirmarse sin uno.';
comment on column competency_term_levels.academic_year_id is 'Copiado del academic_year_id de la class desde la que se afirmó el nivel. Existe para que ctl_recuperacion_key pueda acotar la unicidad de las filas sin term (recuperación) a un año, ya que term_id nulo no sirve por sí solo para eso, y para que ctl_term_year_fk/ctl_class_year_fk sean compuestas sobre esta columna — así una fila del año 2026 no puede apuntar a un term o class de otro año.';
comment on column competency_term_levels.term_id is 'El periodo regular para el que se afirmó este nivel. Nulable: un nivel proveniente de recuperación pedagógica o evaluación de subsanación puede afirmarse sin un term regular detrás. ctl_regular_key cubre las filas con term; ctl_recuperacion_key cubre las filas sin term, acotadas por academic_year_id en su lugar — un índice único no puede comparar dos NULL como iguales, así que term_id solo no bastaría para dar la misma garantía a esas filas.';

-- Dos índices en vez de uno: term_id nulo (recuperación) no puede depender
-- de la comparación de NULL de un índice único para su propia unicidad, así
-- que las filas con y sin term regular llevan cada una su propia garantía.
create unique index ctl_regular_key
  on competency_term_levels (student_id, competency_id, term_id)
  where term_id is not null and superseded_at is null and deleted_at is null;
create unique index ctl_recuperacion_key
  on competency_term_levels (student_id, competency_id, academic_year_id)
  where term_id is null and superseded_at is null and deleted_at is null;

-- La lectura de cierre de año: cada nivel vigente de un estudiante, term más reciente primero.
create index ctl_student_idx
  on competency_term_levels (student_id, term_id)
  where superseded_at is null and deleted_at is null;

-- Las afirmaciones de una class para un periodo.
create index ctl_class_term_idx
  on competency_term_levels (class_id, term_id)
  where superseded_at is null and deleted_at is null;

select app.enable_tenant_rls('competency_term_levels');
select app.attach_updated_at('competency_term_levels');
select app.attach_soft_delete_guard('competency_term_levels');

-- ---------------------------------------------------------------------------
-- Conclusiones descriptivas.
--
-- EBR Secundaria (5.1.1.3 p.7.d, 5.1.2.1.b p.8, 5.1.2.2 p.6, todo texto de la
-- 048-2024): obligatoria cuando el nivel es C, opcional en los demás casos. Dos casos
-- adicionales obligatorios: C en dos o más periodos consecutivos, donde la conclusión
-- debe justificar la falta de progreso (5.1.1.3 p.3); y estudiantes con
-- inclusion_support, en todo periodo (5.1.1.3 p.7).
-- ---------------------------------------------------------------------------

create table descriptive_conclusions (
  id                       uuid primary key default gen_random_uuid(),
  tenant_id                uuid not null references tenants (id),
  student_id               uuid not null,
  competency_id            uuid not null,
  academic_year_id         uuid not null,
  term_id                  uuid,
  class_id                 uuid,
  body                     text not null,
  requirement              text not null default 'optional'
                             check (requirement in (
                               'level_c', 'level_b', 'level_a', 'cycle_i_mandatory',
                               'consecutive_c', 'inclusion_support', 'optional'
                             )),
  status                   text not null default 'draft'
                             check (status in ('draft', 'final')),
  authored_by_id           uuid not null,
  authored_at              timestamptz not null default now(),
  supersedes_id            uuid,
  superseded_at            timestamptz,
  created_at               timestamptz not null default now(),
  updated_at               timestamptz not null default now(),
  deleted_at                timestamptz,
  constraint dc_tenant_id_key unique (tenant_id, id),
  constraint dc_student_fk foreign key (tenant_id, student_id)
    references students (tenant_id, id),
  constraint dc_competency_fk foreign key (tenant_id, competency_id)
    references competencies (tenant_id, id),
  constraint dc_year_fk foreign key (tenant_id, academic_year_id)
    references academic_years (tenant_id, id),
  constraint dc_term_fk foreign key (tenant_id, term_id)
    references terms (tenant_id, id),
  constraint dc_class_fk foreign key (tenant_id, class_id)
    references classes (tenant_id, id),
  constraint dc_authored_by_fk foreign key (tenant_id, authored_by_id)
    references teachers (tenant_id, id),
  constraint dc_supersedes_fk foreign key (tenant_id, supersedes_id)
    references descriptive_conclusions (tenant_id, id),
  constraint dc_body_not_blank check (btrim(body) <> '')
);

comment on table descriptive_conclusions is
  'DATOS PERSONALES DE MENORES (académico, oficial). La conclusión descriptiva de una competencia en un periodo: "juicio docente basado en evidencias […] Señala avances, dificultades y recomendaciones" (094-2020, glosario). Toda conclusión debe llevar recomendaciones personalizadas dentro del propio body ("En todos los casos, las conclusiones descriptivas deben incluir recomendaciones personalizadas orientadas al desarrollo de cada competencia", 5.1.1.3 p.7) — no hay una columna aparte que lo afirme, porque nada puede verificar que un texto libre realmente contenga una recomendación; es responsabilidad del docente al redactar body, igual que siempre. Va a SIAGIE junto al nivel. Solo una fila ''final'' satisface un requisito obligatorio; un ''draft'' no desbloquea el cierre del periodo.';
comment on column descriptive_conclusions.requirement is
  'Por qué existe esta conclusión, y su obligatoriedad varía por nivel educativo. ''level_c'': la competencia está en C — obligatoria en Secundaria, Primaria e Inicial Ciclo II. ''level_b'': obligatoria en Primaria e Inicial Ciclo II. ''level_a'': obligatoria en Inicial Ciclo II. ''cycle_i_mandatory'': toda competencia en Inicial Ciclo I lleva una, sin importar el nivel. ''consecutive_c'': C en dos o más periodos consecutivos — obligatoria *y* el texto debe justificar por qué no hay progreso (5.1.1.3 p.3). ''inclusion_support'': el estudiante enfrenta barreras educativas, así que es obligatoria en todo periodo y debe indicar los apoyos y ajustes razonables brindados (5.1.1.3 p.7). ''optional'': el nivel supera el mínimo obligatorio para el nivel educativo del estudiante, escrita porque el docente lo consideró conveniente. La establece el servidor a partir del nivel vigente, el grado del estudiante, y el estudiante, nunca se confía en el cliente.';
comment on column descriptive_conclusions.academic_year_id is 'Copiado del academic_year_id de la class desde la que se escribió la conclusión. Existe por la misma razón que en competency_term_levels: dc_recuperacion_key acota la unicidad de las filas sin term (recuperación) a un año, y dc_year_fk/dc_term_fk componen sobre esta columna para que una fila del año 2026 no apunte a un term de otro año.';
comment on column descriptive_conclusions.term_id is 'El periodo regular de esta conclusión. Nulable por la misma razón que competency_term_levels.term_id: una conclusión escrita a partir de recuperación pedagógica o evaluación de subsanación puede no tener un term regular detrás — el caso que hace obligatoria una conclusión de un estudiante que sigue en C tras la recuperación, o de inclusion_support en todo periodo, incluido uno de recuperación.';

create unique index dc_regular_key
  on descriptive_conclusions (student_id, competency_id, term_id)
  where term_id is not null and superseded_at is null and deleted_at is null;
create unique index dc_recuperacion_key
  on descriptive_conclusions (student_id, competency_id, academic_year_id)
  where term_id is null and superseded_at is null and deleted_at is null;

create index dc_term_idx
  on descriptive_conclusions (term_id, class_id)
  where superseded_at is null and deleted_at is null;

select app.enable_tenant_rls('descriptive_conclusions');
select app.attach_updated_at('descriptive_conclusions');
select app.attach_soft_delete_guard('descriptive_conclusions');

-- ---------------------------------------------------------------------------
-- Cierre de año.
--
-- El último nivel de logro registrado para una competencia en el año se convierte en su
-- nivel de cierre (5.1.2.2 p.3): un estudiante que estuvo en C en el bimestre 1 y en A en el
-- bimestre 4 cierra el año en A. year_final_situations luego cuenta niveles
-- por área bajo el cuadro de 5.1.3.A para determinar PRO/PER/RR.
-- ---------------------------------------------------------------------------

create table competency_year_snapshots (
  id                uuid primary key default gen_random_uuid(),
  tenant_id         uuid not null references tenants (id),
  student_id        uuid not null,
  competency_id     uuid not null,
  academic_year_id  uuid not null,
  scale_level_id    uuid not null,
  source_term_id    uuid,
  source_level_id   uuid not null,
  closed_at         timestamptz not null default now(),
  closed_by_id      uuid,
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now(),
  deleted_at        timestamptz,
  constraint cys_tenant_id_key unique (tenant_id, id),
  constraint cys_student_fk foreign key (tenant_id, student_id)
    references students (tenant_id, id),
  constraint cys_competency_fk foreign key (tenant_id, competency_id)
    references competencies (tenant_id, id),
  constraint cys_year_fk foreign key (tenant_id, academic_year_id)
    references academic_years (tenant_id, id),
  constraint cys_level_fk foreign key (tenant_id, scale_level_id)
    references grade_scale_levels (tenant_id, id),
  constraint cys_source_term_fk foreign key (tenant_id, source_term_id)
    references terms (tenant_id, id),
  constraint cys_source_level_fk foreign key (tenant_id, source_level_id)
    references competency_term_levels (tenant_id, id),
  constraint cys_closed_by_fk foreign key (tenant_id, closed_by_id)
    references teachers (tenant_id, id)
);

comment on table competency_year_snapshots is
  'DATOS PERSONALES DE MENORES (académico, oficial). El nivel de cierre de año, congelado, de una competencia, tomado del último periodo en que se trabajó (5.1.2.2 p.3). Inmutable una vez escrito: es a partir de esto que se emiten el Acta Oficial y el Certificado de Estudios.';
comment on column competency_year_snapshots.source_term_id is 'El último periodo en que se trabajó esta competencia — de donde se copió el nivel. Nulable: la fila de competency_term_levels de origen puede no llevar term (un nivel afirmado a partir de evidencia de recuperación), en cuyo caso no hay periodo regular que registrar aquí.';
comment on column competency_year_snapshots.source_level_id is 'La fila exacta de competency_term_levels copiada, para poder rastrear el snapshot hasta el docente que la afirmó.';

create unique index cys_key
  on competency_year_snapshots (student_id, competency_id, academic_year_id)
  where deleted_at is null;

create table year_final_situations (
  id                uuid primary key default gen_random_uuid(),
  tenant_id         uuid not null references tenants (id),
  student_id        uuid not null,
  academic_year_id  uuid not null,
  grade_level_id    uuid not null,
  situation         text not null check (situation in ('PRO', 'PER', 'RR')),
  stage             text not null default 'year_end'
                      check (stage in ('year_end', 'post_recuperacion')),
  breakdown         jsonb not null default '{}'::jsonb,
  closed_at         timestamptz not null default now(),
  closed_by_id      uuid,
  document_ref      text,
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now(),
  deleted_at        timestamptz,
  constraint yfs_tenant_id_key unique (tenant_id, id),
  constraint yfs_student_fk foreign key (tenant_id, student_id)
    references students (tenant_id, id),
  constraint yfs_year_fk foreign key (tenant_id, academic_year_id)
    references academic_years (tenant_id, id),
  constraint yfs_grade_level_fk foreign key (tenant_id, grade_level_id)
    references grade_levels (tenant_id, id),
  constraint yfs_closed_by_fk foreign key (tenant_id, closed_by_id)
    references teachers (tenant_id, id),
  constraint yfs_post_recuperacion_situation_check
    check (stage <> 'post_recuperacion' or situation in ('PRO', 'PER'))
);

comment on table year_final_situations is
  'DATOS PERSONALES DE MENORES (académico, oficial). La situación final que lleva el Acta Oficial: PRO (promovido), PER (permanece) o RR (requiere recuperación) — las siglas que la norma nombra en 5.1.2.1.c p.5. Inmutable una vez escrita.';
comment on column year_final_situations.grade_level_id is 'El grado en que estaba el estudiante, porque la regla misma depende de esto: 1.°, 3.° y 4.° promueven con "B en la mitad o más de cada área", mientras que 2.° y 5.° — los grados de fin de ciclo — requieren "A o AD en la mitad o más de tres áreas y B en el resto" (cuadro 5.1.3.A, 048-2024).';
comment on column year_final_situations.stage is
  '''year_end'': la situación al cierre del periodo lectivo, donde PRO/PER/RR son las tres posibles. ''post_recuperacion'': recalculada tras el acompañamiento o evaluación de recuperación, que la norma trata como una determinación aparte que produce su propia acta (5.2.1.A p.4-6) — ahí solo PRO o PER son situaciones legales, nunca RR de nuevo, y yfs_post_recuperacion_situation_check lo hace cumplir.';
comment on column year_final_situations.breakdown is
  'Los conteos por área a partir de los cuales se tomó la decisión, capturados como JSON: qué competencias se consideraron, en qué nivel, y qué áreas cumplieron la condición.';

create unique index yfs_key
  on year_final_situations (student_id, academic_year_id, stage)
  where deleted_at is null;

-- +goose StatementBegin
create or replace function app.forbid_year_close_mutation() returns trigger
  language plpgsql
  as $fn$
  begin
    if tg_table_name = 'competency_year_snapshots' then
      if new.scale_level_id is distinct from old.scale_level_id
         or new.student_id     is distinct from old.student_id
         or new.competency_id  is distinct from old.competency_id
         or new.academic_year_id is distinct from old.academic_year_id
         or new.source_term_id is distinct from old.source_term_id then
        raise exception 'competency year snapshot % is immutable', old.id
          using errcode = 'restrict_violation',
                hint = 'Reopening the year and re-closing it writes a new snapshot; it does not edit this one.';
      end if;
    else
      if new.situation is distinct from old.situation
         or new.student_id is distinct from old.student_id
         or new.academic_year_id is distinct from old.academic_year_id
         or new.stage is distinct from old.stage
         or new.breakdown is distinct from old.breakdown then
        raise exception 'year final situation % is immutable', old.id
          using errcode = 'restrict_violation',
                hint = 'The post-recuperacion determination is a separate row (stage), not an edit of the year-end one.';
      end if;
    end if;
    return new;
  end;
  $fn$;
-- +goose StatementEnd

create trigger forbid_mutation before update on competency_year_snapshots
  for each row execute function app.forbid_year_close_mutation();
create trigger forbid_mutation before update on year_final_situations
  for each row execute function app.forbid_year_close_mutation();

select app.enable_tenant_rls('competency_year_snapshots');
select app.attach_updated_at('competency_year_snapshots');
select app.attach_soft_delete_guard('competency_year_snapshots');

select app.enable_tenant_rls('year_final_situations');
select app.attach_updated_at('year_final_situations');
select app.attach_soft_delete_guard('year_final_situations');

-- ---------------------------------------------------------------------------
-- competency_exemptions
-- ---------------------------------------------------------------------------
-- Una exoneración autorizada por la UGEL de una competencia para un estudiante en un
-- año escolar, ej. Educación Física o Educación Religiosa. El cierre de
-- año excluye una competencia exonerada del conteo de PRO/PER/RR
-- en vez de leer su ausencia como una evaluación incompleta.
create table competency_exemptions (
  id               uuid primary key default gen_random_uuid(),
  tenant_id        uuid not null references tenants (id),
  student_id       uuid not null,
  competency_id    uuid not null,
  academic_year_id uuid not null,
  reason           text not null,
  document_ref     text,
  authorized_by_id uuid,
  authorized_at    timestamptz not null default now(),
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now(),
  deleted_at       timestamptz,
  constraint competency_exemptions_tenant_id_key unique (tenant_id, id),
  constraint competency_exemptions_student_fk foreign key (tenant_id, student_id)
    references students (tenant_id, id),
  constraint competency_exemptions_competency_fk foreign key (tenant_id, competency_id)
    references competencies (tenant_id, id),
  constraint competency_exemptions_year_fk foreign key (tenant_id, academic_year_id)
    references academic_years (tenant_id, id),
  constraint competency_exemptions_authorized_by_fk foreign key (tenant_id, authorized_by_id)
    references teachers (tenant_id, id)
);

comment on table competency_exemptions is
  'DATOS PERSONALES DE MENORES (académico, oficial). Una exoneración autorizada por la UGEL de una competencia para un estudiante en un año escolar (RVM 094-2020: exoneraciones de competencias asociadas a las áreas curriculares, ej. Educación Religiosa, Educación Física). El cierre de año lee esto para excluir el área del conteo de PRO/PER/RR en vez de tratarla como no evaluada.';
comment on column competency_exemptions.reason is 'Por qué se otorgó la exoneración, ej. "Objeción religiosa" o una excepción médica para Educación Física.';
comment on column competency_exemptions.document_ref is 'Referencia al documento de autorización de la UGEL, cuando el colegio conserva uno en archivo.';
comment on column competency_exemptions.authorized_by_id is 'El miembro del personal que registró la exoneración en Mawta. No es la autoridad de la UGEL en sí — document_ref es donde se rastrea esa autorización.';

create unique index competency_exemptions_key
  on competency_exemptions (student_id, competency_id, academic_year_id)
  where deleted_at is null;

select app.enable_tenant_rls('competency_exemptions');
select app.attach_updated_at('competency_exemptions');
select app.attach_soft_delete_guard('competency_exemptions');

-- ===========================================================================
-- Planeamiento por experiencias de aprendizaje
-- ===========================================================================
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
--   | Evidencias planificadas vs. assessments          | planned_evidences es la promesa de qué se observará, contra qué criterios y en qué escala se valorará; assessments es la evidencia valorable. El enlace es assessments.planned_evidence_id: cada evidencia aceptada se materializa como una assessment al planificar la experiencia. |
--   | Esquema de sesiones                             | session_outline_entries: a lo sumo una fila por (experiencia, fecha de clase). Un bloque doble es una sola sesión, así que la unicidad es por fecha y no por franja horaria. |
--   | Días no laborables                              | non_teaching_days por año escolar, cargados en onboarding, para excluir feriados/vacaciones/gestión del conteo de sesiones. |
--   | Procedencia de propuestas                       | proposed_by ('mawta'/'teacher') + accepted_at en criterios, evidencias planificadas y entradas de esquema: una propuesta queda pendiente hasta que el docente la acepta o edita. |
--   | Seguimiento entre periodos                      | Sin tabla resumen: se calcula con una consulta sobre learning_experiences + experience_competencies (decisión 9 del flujo). |
--   | Fuera de alcance (diferido por decisión)        | Ajustes por estudiante, sistema de diseño, vista "Hoy" y agente de detalle de sesión. No se modelan aquí. |
--
-- Nada aquí calcula ni sugiere un nivel de logro oficial: el nivel es el
-- juicio del docente (RVM 094-2020 / RVM 048-2024) y vive en
-- competency_term_levels.


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
  status            text not null default 'borrador'
                      check (status in ('borrador', 'planificada')),
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
  kind             text not null check (kind in ('produccion', 'actuacion')),
  value_scale      text not null default 'numeric' check (value_scale in ('numeric', 'ordinal')),
  max_score        numeric(8, 4) default 20 check (max_score > 0),
  session_entry_id uuid,
  proposed_by      text not null default 'teacher' check (proposed_by in ('mawta', 'teacher')),
  accepted_at      timestamptz,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now(),
  deleted_at       timestamptz,
  constraint planned_evidences_max_score_matches_scale
    check ((value_scale = 'numeric') = (max_score is not null)),
  constraint planned_evidences_tenant_id_key unique (tenant_id, id),
  constraint planned_evidences_experience_key unique (tenant_id, experience_id, id),
  constraint planned_evidences_experience_fk foreign key (tenant_id, experience_id)
    references learning_experiences (tenant_id, id)
);

comment on table planned_evidences is
  'Una evidencia planificada dentro de una experiencia: qué se va a observar (name), de qué tipo (kind) y contra qué criterios (planned_evidence_criteria). Es una PROMESA, no la evidencia real: la evidencia valorable es la assessment en la que se materializa al planificar la experiencia (assessments.planned_evidence_id).';
comment on column planned_evidences.kind is
  'Los dos tipos que nombra la norma: "Evidencias. Producciones y/o actuaciones realizadas por los estudiantes" (RVM 094-2020, glosario p.9). produccion: algo que los estudiantes elaboran (maqueta, informe, portafolio, una prueba escrita). actuacion: algo que hacen frente a otros (exposición, debate, demostración). Es el mismo vocabulario que assessments.kind, así que la evidencia planificada se materializa con su tipo sin traducirlo.';
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

-- ===========================================================================
-- Generaciones de los agentes
-- ===========================================================================
-- Generaciones de los agentes de Mawta (ticket 6). Mawta es un sistema de
-- varios agentes acotados — planificación primero, después sesiones y
-- conclusiones descriptivas — que comparten esta misma tabla: cada fila es un
-- pedido de "✦ Generar con Mawta" y su resultado.
--
-- El job encolado (tabla jobs) solo lleva el id de la generación: jobs no
-- tiene RLS ni columna de resultado, así que nunca se expone. La app consulta
-- esta tabla (GET /generations/{id}) hasta que la generación termina.

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

comment on column learning_experiences.status is
  'borrador: la experiencia se está armando y cada paso ya quedó guardado. planificada: el docente la confirmó en "Revisar y guardar". El solapamiento de fechas se exige en ambos estados, así que un borrador también reserva sus semanas.';
comment on column planned_evidences.value_scale is
  'Cómo se valorará esta evidencia cuando se materialice como assessment: numeric (nota sobre max_score) u ordinal (AD/A/B/C). Se elige al planificar, porque los criterios y la tarea se comunican a los estudiantes con anticipación.';
comment on column planned_evidences.max_score is
  'El máximo de la nota cuando value_scale = numeric (por defecto 20). Null cuando es ordinal.';

-- ---------------------------------------------------------------------------
-- El puente entre el planeamiento y la evaluación real
-- ---------------------------------------------------------------------------
-- Una evidencia planificada (planned_evidences) es una promesa; la evidencia
-- valorable es una assessment. Una experiencia planificada materializa cada
-- evidencia aceptada como una assessment (ver repo.SyncExperience). Esta
-- columna recuerda de cuál evidencia planificada viene, para que la
-- sincronización sea idempotente.
alter table assessments
  add column planned_evidence_id uuid;

alter table assessments
  add constraint assessments_planned_evidence_fk
    foreign key (tenant_id, planned_evidence_id)
    references planned_evidences (tenant_id, id);

comment on column assessments.planned_evidence_id is
  'La evidencia planificada de la que esta assessment se materializó al planificar la experiencia. Null para la evidencia registrada a mano. A lo sumo una assessment viva por evidencia planificada (assessments_planned_evidence_key).';

create unique index assessments_planned_evidence_key
  on assessments (planned_evidence_id)
  where planned_evidence_id is not null and deleted_at is null;

-- ---------------------------------------------------------------------------
-- Un solo periodo activo por nivel
-- ---------------------------------------------------------------------------
-- active: el periodo en curso de su nivel (a lo sumo uno por año y nivel).
-- planned: aún no empieza. closed: cerrado, solo lectura; se cierra a mano antes
-- de activar el siguiente. No tener ningún periodo activo es un estado válido
-- (entre dos periodos): la base no exige uno, solo prohíbe dos.
create unique index terms_one_active_key
  on terms (academic_year_id, coalesce(stage, ''))
  where status = 'active' and deleted_at is null;

comment on index terms_one_active_key is
  'A lo sumo un periodo activo por año y nivel (stage), la misma clave que terms_no_overlap. Es por nivel y no por tenant porque un colegio puede llevar calendarios distintos por nivel. No exige que haya uno: entre dos periodos puede no haber ninguno activo.';

-- +goose Down

drop table if exists agent_generations cascade;
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

drop table if exists competency_exemptions cascade;
drop table if exists year_final_situations cascade;
drop table if exists competency_year_snapshots cascade;
drop table if exists descriptive_conclusions cascade;
drop table if exists competency_term_levels cascade;
drop table if exists jobs cascade;
drop table if exists events cascade;
drop table if exists notifications cascade;
drop table if exists voice_notes cascade;
drop table if exists scores cascade;
drop table if exists assessment_criteria cascade;
drop table if exists assessments cascade;
drop table if exists grade_scale_levels cascade;
drop table if exists grade_scales cascade;
drop table if exists attendance_records cascade;
drop table if exists class_sessions cascade;
drop table if exists class_schedules cascade;
drop table if exists class_teachers cascade;
drop table if exists classes cascade;
drop table if exists section_memberships cascade;
drop table if exists students cascade;
drop table if exists sections cascade;
drop table if exists evaluation_criteria cascade;
drop table if exists capabilities cascade;
drop table if exists courses cascade;
drop table if exists competencies cascade;
drop table if exists subjects cascade;
drop table if exists grade_levels cascade;
drop table if exists terms cascade;
drop table if exists academic_years cascade;
drop table if exists user_sessions cascade;
drop table if exists teachers cascade;
drop table if exists memberships cascade;
drop table if exists users cascade;
drop table if exists tenants cascade;

-- Eliminar los esquemas con CASCADE remueve cada función/vista de app.* y
-- privacy.* en un solo paso (funciones de trigger, utilidades de DDL, las
-- vistas de privacy.*).
drop schema if exists privacy cascade;
drop schema if exists app cascade;

drop type if exists timerange cascade;

-- +goose StatementBegin
do $$
begin
  if exists (select 1 from pg_roles where rolname = 'mawta_app') then
    execute 'drop owned by mawta_app';
    execute 'drop role mawta_app';
  end if;
end
$$;
-- +goose StatementEnd
