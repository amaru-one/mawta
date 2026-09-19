-- Esquema completo de la aplicación Yanai, como una sola migración.

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
-- los roles BYPASSRLS las ignoran. El servicio en Go debe conectarse como yanai_app.

-- +goose StatementBegin
do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'yanai_app') then
    create role yanai_app nologin;
  end if;
end
$$;
-- +goose StatementEnd

grant usage on schema public, app, privacy to yanai_app;
alter default privileges in schema public grant select, insert, update, delete on tables to yanai_app;
alter default privileges in schema public grant usage, select on sequences to yanai_app;
alter default privileges in schema privacy grant select on tables to yanai_app;

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
  uses_internal_grading    boolean not null default true,
  status                   text not null default 'active' check (status in ('active', 'suspended', 'closed')),
  created_at               timestamptz not null default now(),
  updated_at               timestamptz not null default now(),
  deleted_at               timestamptz
);

comment on table tenants is 'Un colegio (institución educativa). Raíz de toda política RLS: app.current_tenant_id() resuelve a una fila aquí.';
comment on column tenants.modular_code is 'Código modular MINEDU de la institución educativa, cuando tiene uno. Null para colegios privados fuera del registro.';
comment on column tenants.timezone is 'Zona horaria IANA del colegio. Todos los timestamps se almacenan en UTC; este es el único lugar donde se define un día calendario local, y es contra el que se calcula "HOY".';
comment on column tenants.uses_internal_grading is
  'Si este colegio lleva su propio sistema de calificación numérica ponderada junto al registro oficial de MINEDU (el D.S. 009-2006-ED art. 37.4.f lo permite). True es el comportamiento histórico y sigue siendo el valor por defecto. False significa que el colegio solo registra niveles de logro: la interfaz deja de pedir una nota por cada evidencia y oculta computed_grades por completo. Esto nunca cambia cómo se produce el registro oficial, que en ambos casos es el juicio del docente sobre la evidencia frente a los criterios. Ningún valor de esta columna puede hacer que un número determine un nivel de logro: la RVM 048-2024 Anexo II convierte un nivel en un número, nunca al revés.';

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
  cycle       text check (cycle in ('ciclo_i', 'ciclo_ii')),
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

comment on table competencies is 'Una competencia MINEDU dentro de una asignatura, ej. "Se comunica oralmente en inglés como lengua extranjera". Las assessments enlazan aquí para que el logro pueda reportarse luego por competencia y no solo por componente.';
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
-- grading_schemes
-- ---------------------------------------------------------------------------
create table grading_schemes (
  id          uuid primary key default gen_random_uuid(),
  tenant_id   uuid not null references tenants (id),
  scale_id    uuid not null,
  code        text not null,
  name        text not null,
  description text,
  is_active   boolean not null default true,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  deleted_at  timestamptz,
  constraint grading_schemes_tenant_id_key unique (tenant_id, id),
  constraint grading_schemes_scale_fk foreign key (tenant_id, scale_id)
    references grade_scales (tenant_id, id)
);

comment on table grading_schemes is 'Una política de calificación con nombre, ej. "Evaluación MINEDU secundaria" o "Bachillerato 0-20". Identidad estable; las reglas viven en sus versiones.';

create unique index grading_schemes_tenant_code_key
  on grading_schemes (tenant_id, code) where deleted_at is null;

select app.enable_tenant_rls('grading_schemes');
select app.attach_updated_at('grading_schemes');
select app.attach_soft_delete_guard('grading_schemes');

-- ---------------------------------------------------------------------------
-- grading_components
-- ---------------------------------------------------------------------------
-- Deliberadamente depende del scheme y no de la versión. Una assessment creada
-- en abril apunta a "Examen final"; cuando el colegio re-versiona sus pesos en
-- junio, esa assessment debe seguir resolviendo al mismo componente bajo la nueva
-- versión. Si los componentes pertenecieran a las versiones, cada re-versión dejaría huérfana
-- a cada assessment existente.
create table grading_components (
  id          uuid primary key default gen_random_uuid(),
  tenant_id   uuid not null references tenants (id),
  scheme_id   uuid not null,
  code        text not null,
  name        text not null,
  description text,
  sort_order  smallint not null default 0,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  deleted_at  timestamptz,
  constraint grading_components_tenant_id_key unique (tenant_id, id),
  constraint grading_components_scheme_component_key unique (tenant_id, scheme_id, id),
  constraint grading_components_scheme_fk foreign key (tenant_id, scheme_id)
    references grading_schemes (tenant_id, id)
);

comment on table grading_components is 'Un balde ponderado dentro de un scheme: Participación, Quiz, Examen final. Se lista una fila por componente con su peso y el resultado del estudiante en él.';
comment on column grading_components.code is 'Clave estable para el sistema. El nombre puede reescribirse sin romper assessments ni computed grades históricos.';
comment on constraint grading_components_scheme_component_key on grading_components is 'Permite que assessments lleve una FK compuesta (tenant_id, scheme_id, component_id), lo que hace estructuralmente imposible registrar una assessment bajo un componente del scheme de otro colegio.';

create unique index grading_components_scheme_code_key
  on grading_components (tenant_id, scheme_id, code) where deleted_at is null;

select app.enable_tenant_rls('grading_components');
select app.attach_updated_at('grading_components');
select app.attach_soft_delete_guard('grading_components');

-- ---------------------------------------------------------------------------
-- grading_scheme_versions
-- ---------------------------------------------------------------------------
create table grading_scheme_versions (
  id                            uuid primary key default gen_random_uuid(),
  tenant_id                     uuid not null references tenants (id),
  scheme_id                     uuid not null,
  version                       integer not null check (version >= 1),
  effective_from                date not null,
  effective_to                  date,
  rounding_mode                 text not null default 'half_up'
                                  check (rounding_mode in ('half_up', 'half_even', 'floor', 'ceil', 'none')),
  rounding_decimals             smallint not null default 0 check (rounding_decimals between 0 and 4),
  absent_counts_as              text not null default 'zero'
                                  check (absent_counts_as in ('zero', 'excused')),
  late_penalty_pct_per_day      numeric(5, 4) not null default 0
                                  check (late_penalty_pct_per_day >= 0 and late_penalty_pct_per_day <= 1),
  retake_policy                 text not null default 'best'
                                  check (retake_policy in ('none', 'best', 'last', 'capped')),
  retake_cap_normalized         numeric(6, 5)
                                  check (retake_cap_normalized is null or (retake_cap_normalized >= 0 and retake_cap_normalized <= 1)),
  min_evaluated_weight_for_grade numeric(6, 5) not null default 0
                                  check (min_evaluated_weight_for_grade >= 0 and min_evaluated_weight_for_grade <= 1),
  notes                         text,
  published_at                  timestamptz,
  published_by_id               uuid,
  created_at                    timestamptz not null default now(),
  updated_at                    timestamptz not null default now(),
  deleted_at                    timestamptz,
  constraint grading_scheme_versions_tenant_id_key unique (tenant_id, id),
  constraint grading_scheme_versions_scheme_fk foreign key (tenant_id, scheme_id)
    references grading_schemes (tenant_id, id),
  constraint grading_scheme_versions_published_by_fk foreign key (tenant_id, published_by_id)
    references teachers (tenant_id, id),
  constraint grading_scheme_versions_range_valid
    check (effective_to is null or effective_to > effective_from),
  constraint grading_scheme_versions_capped_needs_cap
    check (retake_policy <> 'capped' or retake_cap_normalized is not null),
  constraint grading_scheme_versions_no_overlap
    exclude using gist (
      scheme_id with =,
      daterange(effective_from, effective_to, '[)') with &&
    ) where (published_at is not null and deleted_at is null)
);

comment on table grading_scheme_versions is 'Una fotografía inmutable de las reglas de un scheme durante un rango de fechas. Cambiar los pesos inserta una nueva versión y cierra la anterior con effective_to; nunca se edita una fila publicada. Cada computed grade registra la versión que la produjo, para que una libreta emitida en abril no pueda cambiar silenciosamente en junio.';
comment on column grading_scheme_versions.absent_counts_as is 'Cuánto vale una ausencia no justificada en una assessment. Esto es política, no dato: la fila de score solo registra que el estudiante estuvo ausente, y esto decide si eso se vuelve un cero o sale del denominador.';
comment on column grading_scheme_versions.late_penalty_pct_per_day is 'Fracción descontada por día de atraso. Se aplica al momento del cálculo a partir de scores.late_days — el score en crudo nunca se modifica, así que corregir esta política vuelve a calificar correctamente.';
comment on column grading_scheme_versions.retake_policy is 'Cómo se combinan varios intentos sobre una misma assessment: best, last, o best-capped. La recuperación peruana normalmente es capped. Nunca se resuelve descartando el intento anterior.';
comment on column grading_scheme_versions.min_evaluated_weight_for_grade is 'Proporción mínima del peso del term que debe estar evaluada antes de mostrar siquiera una nota parcial. Evita reportar "AD" a partir de un solo quiz con 5% de peso.';
comment on column grading_scheme_versions.published_at is 'Null mientras la versión es un borrador. Publicar la congela: después de esto, solo effective_to puede cambiar.';
comment on constraint grading_scheme_versions_no_overlap on grading_scheme_versions is 'Dos versiones publicadas de un mismo scheme no pueden estar vigentes en la misma fecha, así que "la política que aplica a esta assessment" es inequívoca. Los borradores se excluyen para poder redactar un reemplazo mientras el actual sigue vigente.';

create unique index grading_scheme_versions_scheme_version_key
  on grading_scheme_versions (scheme_id, version) where deleted_at is null;

select app.enable_tenant_rls('grading_scheme_versions');
select app.attach_updated_at('grading_scheme_versions');
select app.attach_soft_delete_guard('grading_scheme_versions');

-- ---------------------------------------------------------------------------
-- grading_scheme_component_weights
-- ---------------------------------------------------------------------------
create table grading_scheme_component_weights (
  id                 uuid primary key default gen_random_uuid(),
  tenant_id          uuid not null references tenants (id),
  scheme_version_id  uuid not null,
  component_id       uuid not null,
  weight             numeric(9, 6) not null check (weight > 0 and weight <= 1),
  drop_lowest_n      smallint not null default 0 check (drop_lowest_n >= 0),
  aggregation        text not null default 'weighted_mean'
                       check (aggregation in ('mean', 'weighted_mean', 'best', 'last', 'sum')),
  is_required        boolean not null default true,
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now(),
  deleted_at         timestamptz,
  constraint gscw_version_fk foreign key (tenant_id, scheme_version_id)
    references grading_scheme_versions (tenant_id, id),
  constraint gscw_component_fk foreign key (tenant_id, component_id)
    references grading_components (tenant_id, id)
);

comment on table grading_scheme_component_weights is 'Los pesos en sí, una fila por componente por versión. "Peso 20%" se muestra directamente desde weight. Los pesos dentro de una versión suman exactamente 1, forzado por un trigger de restricción diferido.';
comment on column grading_scheme_component_weights.drop_lowest_n is 'Descarta las N scores más bajas de este componente antes de agregar. Qué scores se descartaron se registra por estudiante en computed_grade_components, para que el docente pueda explicar el número.';
comment on column grading_scheme_component_weights.aggregation is 'Cómo se combinan varias assessments dentro de un componente. weighted_mean usa assessments.weight_within_component; sum es para schemes de acumulación de puntos donde el total del componente es el denominador.';
comment on column grading_scheme_component_weights.is_required is 'Si es false, el componente sale del denominador cuando no tiene ninguna score, en vez de contar como peso no evaluado.';

create unique index gscw_version_component_key
  on grading_scheme_component_weights (scheme_version_id, component_id) where deleted_at is null;
create index gscw_component_idx on grading_scheme_component_weights (component_id);

-- Los pesos deben sumar 1 por versión. Un CHECK a nivel de fila no puede ver filas hermanas,
-- así que esto es un trigger de restricción diferido: se dispara en el COMMIT, lo que permite
-- insertar o rebalancear toda una tabla de pesos en una sola transacción.
-- +goose StatementBegin
create or replace function app.check_component_weights_sum() returns trigger
  language plpgsql
  as $fn$
  declare
    v_version uuid;
    v_sum     numeric;
  begin
    -- NEW no está definido en un DELETE; referenciarlo ahí lanzaría un error.
    if tg_op = 'DELETE' then
      v_version := old.scheme_version_id;
    else
      v_version := new.scheme_version_id;
    end if;

    -- La versión pudo haberse eliminado en la misma transacción; no hay nada que verificar.
    if not exists (select 1 from grading_scheme_versions v
                    where v.id = v_version and v.deleted_at is null) then
      return null;
    end if;

    select coalesce(sum(weight), 0) into v_sum
      from grading_scheme_component_weights
     where scheme_version_id = v_version and deleted_at is null;

    if v_sum <> 1 then
      raise exception 'component weights for grading scheme version % sum to %, must sum to exactly 1', v_version, v_sum
        using errcode = 'check_violation',
              hint = 'For thirds use 0.333333 / 0.333333 / 0.333334 -- weights are exact numerics, not floats.';
    end if;
    return null;
  end;
  $fn$;
-- +goose StatementEnd

create constraint trigger check_weights_sum
  after insert or update or delete on grading_scheme_component_weights
  deferrable initially deferred
  for each row execute function app.check_component_weights_sum();

-- Una versión sin ninguna fila de peso nunca dispararía el trigger de arriba, así que
-- publicar también es un punto de control.
-- +goose StatementBegin
create or replace function app.check_version_publishable() returns trigger
  language plpgsql
  as $fn$
  declare
    v_sum numeric;
    v_cnt integer;
  begin
    if new.published_at is null then
      return new;
    end if;

    select count(*), coalesce(sum(weight), 0) into v_cnt, v_sum
      from grading_scheme_component_weights
     where scheme_version_id = new.id and deleted_at is null;

    if v_cnt = 0 then
      raise exception 'grading scheme version % has no components and cannot be published', new.id
        using errcode = 'check_violation';
    end if;
    if v_sum <> 1 then
      raise exception 'grading scheme version % has weights summing to %, must be exactly 1', new.id, v_sum
        using errcode = 'check_violation';
    end if;
    return new;
  end;
  $fn$;
-- +goose StatementEnd

create trigger check_publishable before insert or update of published_at on grading_scheme_versions
  for each row execute function app.check_version_publishable();

-- Las versiones publicadas son inmutables salvo por cerrarse con effective_to.
-- +goose StatementBegin
create or replace function app.forbid_published_version_mutation() returns trigger
  language plpgsql
  as $fn$
  begin
    if old.published_at is null then
      return new;
    end if;
    if new.scheme_id            is distinct from old.scheme_id
       or new.version           is distinct from old.version
       or new.effective_from    is distinct from old.effective_from
       or new.rounding_mode     is distinct from old.rounding_mode
       or new.rounding_decimals is distinct from old.rounding_decimals
       or new.absent_counts_as  is distinct from old.absent_counts_as
       or new.late_penalty_pct_per_day is distinct from old.late_penalty_pct_per_day
       or new.retake_policy            is distinct from old.retake_policy
       or new.retake_cap_normalized    is distinct from old.retake_cap_normalized
       or new.min_evaluated_weight_for_grade is distinct from old.min_evaluated_weight_for_grade
       or new.published_at             is distinct from old.published_at then
      raise exception 'grading scheme version % is published and immutable; insert a new version instead', old.id
        using errcode = 'restrict_violation',
              hint = 'Only effective_to may change on a published version, to close it off.';
    end if;
    return new;
  end;
  $fn$;
-- +goose StatementEnd

create trigger forbid_published_mutation before update on grading_scheme_versions
  for each row execute function app.forbid_published_version_mutation();

-- +goose StatementBegin
create or replace function app.forbid_published_weight_mutation() returns trigger
  language plpgsql
  as $fn$
  declare
    v_version   uuid;
    v_published timestamptz;
  begin
    -- NEW no está definido en un DELETE, así que la fila examinada depende de la operación.
    if tg_op = 'DELETE' then
      -- Un borrado autorizado (baja de un tenant, reversión de datos semilla) puede eliminar
      -- las filas directamente; el código normal de la aplicación no puede.
      if coalesce(nullif(current_setting('app.allow_hard_delete', true), ''), 'off') = 'on' then
        return old;
      end if;
      v_version := old.scheme_version_id;
    else
      v_version := new.scheme_version_id;
    end if;

    select published_at into v_published
      from grading_scheme_versions where id = v_version;

    if v_published is not null then
      raise exception 'weights of published grading scheme version % cannot be changed; insert a new version', v_version
        using errcode = 'restrict_violation';
    end if;

    if tg_op = 'DELETE' then
      return old;
    end if;
    return new;
  end;
  $fn$;
-- +goose StatementEnd

create trigger forbid_published_weight_mutation
  before update or delete on grading_scheme_component_weights
  for each row execute function app.forbid_published_weight_mutation();

select app.enable_tenant_rls('grading_scheme_component_weights');
select app.attach_updated_at('grading_scheme_component_weights');

-- ---------------------------------------------------------------------------
-- Resolución del scheme: default del tenant -> override de course -> override de class/term
-- ---------------------------------------------------------------------------
alter table tenants add column default_grading_scheme_id uuid;
alter table tenants add constraint tenants_default_scheme_fk
  foreign key (id, default_grading_scheme_id) references grading_schemes (tenant_id, id);
comment on column tenants.default_grading_scheme_id is 'Scheme de calificación de respaldo para todo el colegio. Se sobrescribe por course, luego por class y term.';

alter table courses add column grading_scheme_id uuid;
alter table courses add constraint courses_grading_scheme_fk
  foreign key (tenant_id, grading_scheme_id) references grading_schemes (tenant_id, id);
comment on column courses.grading_scheme_id is 'Override opcional por course, para un colegio donde Matemática pondera distinto que Inglés. Null recae en el default del tenant.';

-- El orden de resolución en un solo lugar, para que ningún código en Go lo reimplemente.
create view class_effective_grading_schemes as
select
  c.tenant_id,
  c.id                                            as class_id,
  t.id                                            as term_id,
  coalesce(co.grading_scheme_id, tn.default_grading_scheme_id) as scheme_id,
  case
    when co.grading_scheme_id is not null     then 'course'
    when tn.default_grading_scheme_id is not null then 'tenant'
  end                                             as resolved_from,
  v.id                                            as scheme_version_id
from classes c
join tenants tn on tn.id = c.tenant_id
join courses co on co.id = c.course_id and co.tenant_id = c.tenant_id
join grade_levels gl on gl.id = co.grade_level_id and gl.tenant_id = c.tenant_id
join terms   t  on t.tenant_id = c.tenant_id and t.academic_year_id = c.academic_year_id
                and (t.stage is null or t.stage = gl.stage)
left join lateral (
  select gv.id
    from grading_scheme_versions gv
   where gv.scheme_id = coalesce(co.grading_scheme_id, tn.default_grading_scheme_id)
     and gv.published_at is not null
     and gv.deleted_at is null
     and gv.effective_from <= t.starts_on
     and (gv.effective_to is null or gv.effective_to > t.starts_on)
   order by gv.effective_from desc
   limit 1
) v on true
where c.deleted_at is null;

comment on view class_effective_grading_schemes is 'Resuelve qué grading scheme, y qué versión publicada de este, rige una class en un term. La versión se elige por la fecha de inicio del term, así que re-versionar a mitad de año no cambia retroactivamente un term ya en curso. El join con terms se acota por stage (a través de grade_levels, vía courses) para que un colegio con calendarios mixtos no le asigne a una class de Primaria los bimestres de Secundaria, o viceversa; un term sin stage sigue aplicando a todas.';


-- ---------------------------------------------------------------------------
-- assessments
-- ---------------------------------------------------------------------------
create table assessments (
  id                        uuid primary key default gen_random_uuid(),
  tenant_id                 uuid not null references tenants (id),
  class_id                  uuid not null,
  term_id                   uuid,
  scheme_id                 uuid not null,
  component_id              uuid not null,
  session_id                uuid,
  title                     text not null,
  description               text,
  student_id                uuid,
  kind                      text not null default 'otro'
                              check (kind in ('examen', 'practica', 'tarea', 'proyecto',
                                              'exposicion', 'participacion', 'otro')),
  value_scale               text not null default 'numeric'
                              check (value_scale in ('numeric', 'rubric')),
  max_score                 numeric(8, 4) check (max_score > 0),
  counts_toward_internal    boolean not null default true,
  weight_within_component   numeric(9, 6) not null default 1 check (weight_within_component > 0),
  due_at                    timestamptz,
  status                    text not null default 'draft'
                              check (status in ('draft', 'published', 'closed', 'cancelled')),
  published_at              timestamptz,
  closed_at                 timestamptz,
  late_penalty_pct_per_day  numeric(5, 4) check (late_penalty_pct_per_day between 0 and 1),
  created_by_id             uuid,
  created_at                timestamptz not null default now(),
  updated_at                timestamptz not null default now(),
  deleted_at                timestamptz,
  constraint assessments_tenant_id_key unique (tenant_id, id),
  constraint assessments_class_fk foreign key (tenant_id, class_id)
    references classes (tenant_id, id),
  constraint assessments_term_fk foreign key (tenant_id, term_id)
    references terms (tenant_id, id),
  constraint assessments_component_fk foreign key (tenant_id, scheme_id, component_id)
    references grading_components (tenant_id, scheme_id, id),
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
    check ((value_scale = 'numeric') = (max_score is not null)),
  constraint assessments_rubric_not_internal
    check (value_scale <> 'rubric' or counts_toward_internal = false)
);

comment on table assessments is 'Un ítem calificado para una class: "Quiz 1", "Examen final", "Participación". Se listan bajo EVALUACIONES con el peso del componente junto a cada una. "Añadir evaluación" inserta aquí.';
comment on column assessments.scheme_id is 'Desnormalizado desde el componente para que la FK compuesta pueda probar que el componente pertenece al scheme previsto. Se establece a partir de la política de calificación resuelta de la class al crearse.';
comment on column assessments.term_id is 'El term al que pertenece esta evidencia. Nulable: una recuperación pedagógica o evaluación de subsanación suele ocurrir fuera del periodo lectivo regular, así que su evidencia queda registrada sin pertenecer al promedio ponderado de ningún term.';
comment on column assessments.student_id is 'Null significa que la assessment aplica a toda la class, que es el caso original y sigue siendo el más común. Si está definido, es evidencia solo para ese estudiante: una tarea de recuperación, un proyecto rehecho, una defensa oral que reemplaza una exposición grupal perdida. Toda consulta que expanda assessments sobre el roster debe filtrar (student_id is null or student_id = el estudiante), o la evidencia personal de un estudiante contará como faltante para todos los demás.';
comment on column assessments.value_scale is
  'Cómo se valora esta evidencia. ''numeric'': una nota en la escala vigesimal propia del colegio, con max_score como denominador y el valor en scores.raw_value. ''rubric'': evidencia puramente cualitativa, sin nota general — se valora solo a través de los niveles por criterio en criterion_scores, y max_score queda null. Ninguno de los dos casos es un nivel de logro: el nivel de una competencia se afirma en competency_term_levels por un docente que ha leído todo el periodo, y nada puede derivarlo de estos valores.';
comment on column assessments.max_score is 'El denominador sobre el que se mide cada score de esta assessment, ej. 20 para un quiz vigesimal. Solo aplica a value_scale = ''numeric''; null cuando value_scale = ''rubric'', que no tiene nota general.';
comment on column assessments.counts_toward_internal is
  'Si esta evidencia alimenta el promedio ponderado interno del colegio. Siempre alimenta el juicio oficial: un nivel de criterio registrado contra ella cuenta de todas formas, porque la norma no sabe nada de esta bandera. False existe para la tarea de recuperación dada a un solo estudiante (assessments.student_id definido). Esa tarea es evidencia legítima de la competencia, pero dejar que eleve solo el promedio interno de ese estudiante le da una oportunidad que el resto de la class nunca tuvo. Leído por worker/handlers/recompute.go, su único consumidor. assessments_rubric_not_internal fuerza este valor a false cuando value_scale es rubric: una rúbrica nunca tiene fila en scores (no hay raw_value/max_value que derivar), así que dejarla contar la marcaría como peso pendiente para siempre.';
comment on column assessments.weight_within_component is 'Peso relativo frente a otras assessments del mismo componente, usado cuando el componente agrega por weighted_mean. No es una porción de la nota final — ese es el peso del componente.';
comment on column assessments.due_at is 'Fecha límite. Determina scores.late_days, y define qué assessments cuentan en el denominador de "notas esperadas hasta ahora" detrás del indicador "Notas reg.".';
comment on column assessments.status is 'draft es invisible para el cálculo de notas. Una assessment debe publicarse antes de contribuir peso no evaluado al indicador "falta 40%".';
comment on column assessments.late_penalty_pct_per_day is 'Override por assessment de la política de atraso de la versión del scheme. Null hereda.';

-- Las assessments de este estudiante para esta class y term, en orden de componente.
-- Deliberadamente sin índice para counts_toward_internal: este índice se mantiene
-- no parcial porque la lista de evidencia, los conteos del dashboard y el recompute
-- leen todos las mismas filas (class_id, term_id, status), y solo el último de los
-- tres usa esa bandera. Acotar el índice compartido a ese único consumidor
-- dejaría a los otros dos sin índice para servir un filtro que descarta como mucho un
-- puñado de filas por class.
create index assessments_class_term_idx
  on assessments (class_id, term_id, status) where deleted_at is null;
-- Leer la propia evidencia de un estudiante para una class+term es el camino más frecuente.
create index assessments_student_idx
  on assessments (class_id, term_id, student_id)
  where student_id is not null and deleted_at is null;
-- "Notas reg." y "Pendientes": assessments publicadas ya vencidas.
create index assessments_due_idx
  on assessments (tenant_id, due_at)
  where status = 'published' and deleted_at is null;
create index assessments_component_idx on assessments (component_id) where deleted_at is null;
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
-- evidencia dada; si el trabajo del estudiante frente a ese criterio se valora
-- de forma independiente vive en criterion_scores más abajo.
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

comment on table assessment_criteria is 'A qué criterios de evaluación habla una evidencia, ej. un "Quiz 1" etiquetado contra dos criterios de "Resuelve problemas de cantidad". criterion_scores_rubric_item_fk (en criterion_scores) es compuesta sobre assessment_criteria_tenant_key, así que una marca por criterio solo puede existir para un par assessment+criterio que esta tabla realmente etiquetó.';
comment on constraint assessment_criteria_tenant_key on assessment_criteria is 'A diferencia del resto de esta migración, esta es una unique constraint completa, no parcial por deleted_at is null: Postgres solo permite que una FK apunte a una unique/primary key completa, nunca a un índice parcial, y esta es lo que hace posible criterion_scores_rubric_item_fk. Sin consecuencia práctica hoy — nada en Go borra una fila de assessment_criteria (linkAssessmentCriteria solo inserta) — pero si algún día se agrega un "destag", debe reactivar la fila existente en vez de insertar una nueva para el mismo par.';

create index assessment_criteria_criterion_idx on assessment_criteria (criterion_id);

select app.enable_tenant_rls('assessment_criteria');
select app.attach_updated_at('assessment_criteria');
select app.attach_soft_delete_guard('assessment_criteria');

-- ---------------------------------------------------------------------------
-- criterion_scores
-- ---------------------------------------------------------------------------
-- La valoración independiente de un estudiante contra un criterio dentro de una
-- assessment, ej. una rúbrica que califica "Plantea estrategias" y "Ejecuta el
-- plan" por separado dentro del mismo "Proyecto final". De solo inserción, con la misma
-- forma de reemplazo (supersede) que scores: una corrección inserta una fila nueva en vez de
-- actualizar en el lugar.
create table criterion_scores (
  id             uuid primary key default gen_random_uuid(),
  tenant_id      uuid not null references tenants (id),
  assessment_id  uuid not null,
  criterion_id   uuid not null,
  student_id     uuid not null,
  value_scale    text not null default 'numeric'
                   check (value_scale in ('numeric', 'ordinal')),
  raw_value      numeric(8, 4),
  max_value      numeric(8, 4),
  scale_level_id uuid,
  recorded_by_id uuid not null,
  recorded_at    timestamptz not null default now(),
  supersedes_id  uuid,
  superseded_at  timestamptz,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now(),
  deleted_at     timestamptz,
  constraint criterion_scores_tenant_id_key unique (tenant_id, id),
  constraint criterion_scores_rubric_item_fk foreign key (tenant_id, assessment_id, criterion_id)
    references assessment_criteria (tenant_id, assessment_id, criterion_id),
  constraint criterion_scores_student_fk foreign key (tenant_id, student_id)
    references students (tenant_id, id),
  constraint criterion_scores_recorded_by_fk foreign key (tenant_id, recorded_by_id)
    references teachers (tenant_id, id),
  constraint criterion_scores_supersedes_fk foreign key (tenant_id, supersedes_id)
    references criterion_scores (tenant_id, id),
  constraint criterion_scores_scale_level_fk foreign key (tenant_id, scale_level_id)
    references grade_scale_levels (tenant_id, id),
  constraint criterion_scores_max_value_positive
    check (max_value is null or max_value > 0),
  constraint criterion_scores_value_matches_scale
    check ((value_scale = 'numeric') = (raw_value is not null and max_value is not null)),
  constraint criterion_scores_level_matches_scale
    check ((value_scale = 'ordinal') = (scale_level_id is not null)),
  constraint criterion_scores_value_in_range
    check (raw_value is null or (max_value is not null and raw_value >= 0 and raw_value <= max_value))
);

comment on table criterion_scores is
  'DATOS PERSONALES DE MENORES (académico). La nota de un estudiante contra un criterio dentro de una assessment, ej. 3 de 4 en "Plantea estrategias" dentro de "Proyecto final", o un nivel para una fila de rúbrica valorada de forma descriptiva en vez de numérica. Una corrección reemplaza la fila anterior en vez de sobrescribirla, el mismo protocolo que usa scores. criterion_scores_rubric_item_fk es compuesta sobre (assessment_id, criterion_id) hacia assessment_criteria en vez de dos FKs simples hacia assessments y evaluation_criteria por separado — así una marca solo puede existir para un criterio que la assessment realmente etiquetó, nunca uno ajeno al instrumento.';
comment on column criterion_scores.value_scale is 'numeric: raw_value sobre max_value, heredado de assessments.max_score — requiere que la assessment tenga uno, así que no aplica a una assessment rubric (max_score null). ordinal: un nivel en scale_level_id (AD/A/B/C), sin esa restricción. Independiente de assessments.value_scale: una assessment numeric puede calificar algunos criterios por nivel, y una rubric solo admite calificarlos por nivel.';
comment on column criterion_scores.scale_level_id is 'El nivel que obtuvo este criterio, cuando value_scale es ordinal. No es un nivel de logro: el juicio oficial de una competencia se afirma por separado en competency_term_levels por un docente que ha leído todo el periodo, nunca se deriva de un valor aquí.';

create unique index criterion_scores_live_key
  on criterion_scores (assessment_id, criterion_id, student_id)
  where superseded_at is null and deleted_at is null;
create index criterion_scores_student_idx
  on criterion_scores (student_id) where superseded_at is null and deleted_at is null;

-- +goose StatementBegin
create or replace function app.forbid_criterion_score_mutation() returns trigger
  language plpgsql
  as $fn$
  begin
    if new.assessment_id  is distinct from old.assessment_id
       or new.criterion_id is distinct from old.criterion_id
       or new.student_id   is distinct from old.student_id
       or new.value_scale    is distinct from old.value_scale
       or new.raw_value      is distinct from old.raw_value
       or new.max_value      is distinct from old.max_value
       or new.scale_level_id is distinct from old.scale_level_id
       or new.recorded_by_id is distinct from old.recorded_by_id
       or new.recorded_at    is distinct from old.recorded_at then
      raise exception 'criterion_scores is append-only (row %); insert a superseding row instead of updating', old.id
        using errcode = 'restrict_violation',
              hint = 'Stamp superseded_at on this row FIRST, then insert the replacement with supersedes_id set.';
    end if;
    return new;
  end;
  $fn$;
-- +goose StatementEnd

create trigger forbid_mutation before update on criterion_scores
  for each row execute function app.forbid_criterion_score_mutation();

select app.enable_tenant_rls('criterion_scores');
select app.attach_updated_at('criterion_scores');
select app.attach_soft_delete_guard('criterion_scores');

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
  attempt_number            smallint not null default 1 check (attempt_number >= 1),
  attempt_kind              text not null default 'original'
                              check (attempt_kind in ('original', 'recuperacion', 'subsanacion', 'makeup')),
  status                    text not null default 'graded'
                              check (status in ('graded', 'excused', 'absent', 'not_submitted')),
  raw_value                 numeric(8, 4),
  max_value                 numeric(8, 4),
  late_days                 smallint not null default 0 check (late_days >= 0),
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
  constraint scores_max_value_positive
    check (max_value is null or max_value > 0),
  constraint scores_value_matches_status
    check ((status = 'graded') = (raw_value is not null)),
  constraint scores_value_in_range
    check (raw_value is null or (max_value is not null and raw_value >= 0 and raw_value <= max_value)),
  constraint scores_attempt_kind_consistent
    check ((attempt_number = 1) = (attempt_kind = 'original'))
);

comment on table scores is
  'DATOS PERSONALES DE MENORES (académico). De solo inserción. Contiene el valor en crudo y el máximo de la assessment y nada derivado — sin porcentaje, sin contribución ponderada, sin penalidad por atraso ya descontada. Corregir una score inserta una fila nueva que reemplaza a la anterior; una recuperación inserta un nuevo intento junto a ella. Nada aquí se actualiza en el lugar ni se borra físicamente.';

comment on column scores.attempt_number is 'El intento 1 es la sesión original. Una recuperación es el intento 2 sobre la misma assessment, nunca una sobrescritura.';
comment on column scores.attempt_kind is 'Qué instrumento legal produjo este intento. Restringido para coincidir con attempt_number, así que el intento 1 siempre es el original.';
comment on column scores.status is 'excused excluye la fila del denominador por completo; absent y not_submitted se califican según el absent_counts_as de la versión del scheme. Por eso una score excused es una fila y no una fila faltante — una fila faltante significa que el docente aún no ha calificado ("Sin evaluar").';
comment on column scores.raw_value is 'El número que escribió el docente, sobre max_value, ej. 15 sobre 20. Null salvo que status = graded.';
comment on column scores.max_value is 'Copiado de la assessment al momento de escribir y congelado, así que cambiar después el máximo de una assessment no puede reinterpretar notas ya ingresadas.';
comment on column scores.late_days is 'Días completos después de due_at. La penalidad se aplica al momento del cálculo según la política de la versión del scheme, nunca se hornea en raw_value, así que corregir la política de atraso vuelve a calificar correctamente.';
comment on column scores.supersedes_id is 'La fila que esta reemplaza tras una corrección. El enlace apunta solo hacia atrás: un superseded_by_id hacia adelante tendría que escribirse en el mismo momento que superseded_at, pero la fila de reemplazo no puede existir hasta que la anterior se cierre. Sigue supersedes_id hacia atrás para el historial completo de una nota.';
comment on column scores.superseded_at is 'Se establece cuando una fila más nueva reemplaza a esta. Una fila con superseded_at null y deleted_at null es el valor vigente. Se escribe antes de insertar el reemplazo — ver scores_live_attempt_key.';
comment on column scores.class_id is 'Desnormalizado desde la assessment. Se mantiene por trigger; permite que los agregados de cobertura de calificación por class se salten un join.';
comment on column scores.term_id is 'Desnormalizado desde la assessment. Nulable: una score de recuperación o subsanación puede registrarse contra una assessment sin term (ver assessments.term_id), en cuyo caso es evidencia real en el registro del estudiante pero queda fuera de todo agregado de notas acotado por term.';

-- Exactamente una fila vigente por (assessment, student, attempt). Corregir una score está
-- entonces ordenado: cerrar la fila anterior (fijar superseded_at), luego insertar el
-- reemplazo. Un índice parcial no puede ser DEFERRABLE, así que las dos no pueden solaparse.
create unique index scores_live_attempt_key
  on scores (assessment_id, student_id, attempt_number)
  where superseded_at is null and deleted_at is null;
-- "Pendientes · 3 alumnos": quién en esta assessment no tiene score vigente.
create index scores_assessment_idx
  on scores (assessment_id) where superseded_at is null and deleted_at is null;
-- Las scores vigentes de un estudiante para una class y term.
create index scores_student_term_idx
  on scores (student_id, term_id) where superseded_at is null and deleted_at is null;
-- Cobertura de "Notas reg.": scores vigentes de una class en un term.
create index scores_class_term_idx
  on scores (class_id, term_id) where superseded_at is null and deleted_at is null;
-- Estudiantes que alguna vez necesitaron una recuperación.
create index scores_retake_idx
  on scores (tenant_id, student_id) where attempt_number > 1 and deleted_at is null;
create index scores_supersedes_idx on scores (supersedes_id) where supersedes_id is not null;

-- Las columnas desnormalizadas se copian de la assessment, nunca se proveen. Las
-- verificaciones de term cerrado y assessment en borrador viven en esta misma función a
-- propósito: dependen de term_id, que no existe en la fila entrante.
-- Como triggers BEFORE INSERT separados se dispararían en orden alfabético, y una verificación
-- que corriera antes que esta leería silenciosamente un term null y pasaría.
-- +goose StatementBegin
create or replace function app.sync_score_denormalised() returns trigger
  language plpgsql
  as $fn$
  declare
    v_assessment_status text;
    v_term_status       text;
  begin
    select a.class_id, a.term_id, a.status, t.status
      into new.class_id, new.term_id, v_assessment_status, v_term_status
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

    -- Un term cerrado deja de aceptar notas. Esto es lo que hace que una libreta
    -- cerrada sea real y no solo una convención. Una assessment sin term (ej. una
    -- recuperación) no tiene term que cerrar, así que la verificación se omite.
    if v_term_status in ('closed', 'archived') then
      raise exception 'term % is closed; grades cannot be added or changed', new.term_id
        using errcode = 'restrict_violation',
              hint = 'Reopen the term explicitly, which is an audited action, or record the change as a subsanación in the current term.';
    end if;

    return new;
  end;
  $fn$;
-- +goose StatementEnd

create trigger sync_denormalised before insert on scores
  for each row execute function app.sync_score_denormalised();

-- Restricción 5: las notas son temporales. Una score nunca se actualiza en el lugar.
-- +goose StatementBegin
create or replace function app.forbid_score_mutation() returns trigger
  language plpgsql
  as $fn$
  begin
    if new.assessment_id  is distinct from old.assessment_id
       or new.student_id  is distinct from old.student_id
       or new.attempt_number is distinct from old.attempt_number
       or new.attempt_kind   is distinct from old.attempt_kind
       or new.status         is distinct from old.status
       or new.raw_value      is distinct from old.raw_value
       or new.max_value      is distinct from old.max_value
       or new.late_days      is distinct from old.late_days
       or new.recorded_by_id is distinct from old.recorded_by_id
       or new.recorded_at    is distinct from old.recorded_at then
      raise exception 'scores are append-only (score %); insert a superseding row instead of updating', old.id
        using errcode = 'restrict_violation',
              hint = 'Stamp superseded_at on this row FIRST, then insert the replacement with supersedes_id set. scores_live_attempt_key is a partial unique index and cannot be deferred, so two live rows for one attempt never coexist, even briefly.';
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
-- computed_grades
-- ---------------------------------------------------------------------------
create table computed_grades (
  id                        uuid primary key default gen_random_uuid(),
  tenant_id                 uuid not null references tenants (id),
  student_id                uuid not null,
  class_id                  uuid not null,
  term_id                   uuid not null,
  scheme_version_id         uuid not null,
  scale_id                  uuid not null,
  scope                     text not null default 'term_partial'
                              check (scope in ('term_partial', 'term_final')),

  normalized_value          numeric(6, 5) not null check (normalized_value between 0 and 1),
  normalization_method      text not null
                              check (normalization_method in ('ratio_of_evaluated', 'linear_min_max',
                                                              'band_midpoint', 'identity')),
  scale_level_id            uuid,
  display_value             text,

  total_weight              numeric(9, 6) not null check (total_weight > 0),
  evaluated_weight          numeric(9, 6) not null check (evaluated_weight >= 0),

  previous_scale_level_id   uuid,
  previous_normalized_value numeric(6, 5) check (previous_normalized_value between 0 and 1),
  trend                     text check (trend in ('up', 'down', 'flat')),

  scores_counted            integer not null default 0 check (scores_counted >= 0),
  inputs_digest             text,
  computed_by_job_id        bigint,
  supersedes_id             uuid,
  superseded_at             timestamptz,
  created_at                timestamptz not null default now(),
  updated_at                timestamptz not null default now(),
  deleted_at                timestamptz,

  constraint computed_grades_tenant_id_key unique (tenant_id, id),
  constraint computed_grades_student_fk foreign key (tenant_id, student_id)
    references students (tenant_id, id),
  constraint computed_grades_class_fk foreign key (tenant_id, class_id)
    references classes (tenant_id, id),
  constraint computed_grades_term_fk foreign key (tenant_id, term_id)
    references terms (tenant_id, id),
  constraint computed_grades_version_fk foreign key (tenant_id, scheme_version_id)
    references grading_scheme_versions (tenant_id, id),
  constraint computed_grades_scale_fk foreign key (tenant_id, scale_id)
    references grade_scales (tenant_id, id),
  constraint computed_grades_level_fk foreign key (tenant_id, scale_level_id)
    references grade_scale_levels (tenant_id, id),
  constraint computed_grades_prev_level_fk foreign key (tenant_id, previous_scale_level_id)
    references grade_scale_levels (tenant_id, id),
  constraint computed_grades_supersedes_fk foreign key (tenant_id, supersedes_id)
    references computed_grades (tenant_id, id),
  constraint computed_grades_evaluated_within_total
    check (evaluated_weight <= total_weight),
  constraint computed_grades_trend_needs_previous
    check ((trend is null) or (previous_normalized_value is not null))
);

comment on table computed_grades is
  'DATOS PERSONALES DE MENORES (académico, derivado). NO es el registro oficial. El sistema ponderado interno propio del colegio (el D.S. 009-2006-ED art. 37.4.f permite que una IE privada lleve uno), mantenido para colegios que quieren una nota numérica junto a la norma. La RVM 094-2020 determina el logro por competencia a partir del juicio del docente frente a los criterios (ver competency_term_levels, que es el registro oficial y nunca se deriva de esta tabla). Una fila por estudiante por class por term, reescrita como una fila nueva cada vez que el resultado cambia.';

comment on column computed_grades.normalized_value is 'La nota en un eje 0-1, comparable entre toda escala y todo tenant. Esta es la columna sobre la que se entrenan modelos con un simple SELECT. Para un term parcial es el logro solo sobre la parte evaluada: "83% de lo evaluado" es 0.83333.';
comment on column computed_grades.normalization_method is 'Cómo se convirtió el resultado en crudo en un número 0-1. ratio_of_evaluated es el caso de term parcial; band_midpoint es la vía con pérdida usada cuando el origen es un juicio ordinal sin número subyacente. Se almacena porque el método cambia lo que significa el valor.';
comment on column computed_grades.scale_level_id is 'La banda en la que cae el valor normalizado: la "A" que se muestra, y la clave de agrupación detrás de "Distribución de logros". Null cuando evaluated_weight está por debajo del mínimo de la versión para mostrar una nota.';
comment on column computed_grades.display_value is 'Qué imprimir: "A" para una escala ordinal, "15.4" para vigesimal. Se calcula una sola vez aquí en vez de en cada cliente.';
comment on column computed_grades.total_weight is 'Suma de los pesos de los componentes en juego para este term. Normalmente 1; menos si se descartó un componente opcional por no tener assessments.';
comment on column computed_grades.evaluated_weight is 'Porción de total_weight ya evaluada. "60% del curso evaluado · falta 40%" es esto sobre total_weight.';
comment on column computed_grades.previous_scale_level_id is
  'Nivel del cálculo anterior, para el sistema ponderado interno propio del colegio. Se conserva para poder mostrar un cambio de posición sin recalcular el historial. Solo lo lee ese sistema: el nivel de logro oficial lo afirma un docente y nunca se deriva de estas filas.';
comment on column computed_grades.trend is
  'Dirección del último cambio, para el sistema ponderado interno propio del colegio. Se puede derivar de previous_normalized_value, se cachea porque un dashboard de class lo lee para toda una section a la vez.';
comment on column computed_grades.inputs_digest is 'Hash de las filas de score que alimentaron este cálculo. Permite que el job de recompute se salte escribir una fila nueva cuando nada material cambió, que es lo que evita que esta tabla crezca con cada tecla presionada.';
comment on column computed_grades.superseded_at is 'Se establece cuando un cálculo más nuevo reemplaza esta fila. Null significa vigente. Se escribe antes de insertar el reemplazo, ya que computed_grades_current_key admite solo una fila vigente por estudiante, class y term.';
comment on column computed_grades.supersedes_id is 'El cálculo que esta fila reemplaza. Apunta solo hacia atrás, por la misma razón que scores.supersedes_id: un puntero hacia adelante nunca podría escribirse, porque el sucesor no existe en el momento en que el predecesor debe cerrarse.';
comment on column computed_grades.computed_by_job_id is 'La fila de jobs que produjo este cálculo, cuando vino de la cola en vez de un guardado interactivo. Intencionalmente no es una FK: los jobs terminados se depuran, y una nota no debe volverse imposible de escribir porque su fila de job envejeció.';

-- Una fila vigente por estudiante, class y term.
create unique index computed_grades_current_key
  on computed_grades (student_id, class_id, term_id)
  where superseded_at is null and deleted_at is null;
-- "Distribución de logros": cuenta las notas vigentes por nivel para una class.
create index computed_grades_class_level_idx
  on computed_grades (class_id, term_id, scale_level_id)
  where superseded_at is null and deleted_at is null;
-- El roster con el nivel y la tendencia vigentes de cada estudiante.
create index computed_grades_class_term_idx
  on computed_grades (class_id, term_id)
  where superseded_at is null and deleted_at is null;
-- El historial de notas de un estudiante, más reciente primero.
create index computed_grades_student_history_idx
  on computed_grades (student_id, class_id, created_at desc) where deleted_at is null;
-- Entrenamiento de modelos: extraer notas normalizadas entre todos los tenants para un periodo.
create index computed_grades_training_idx
  on computed_grades (created_at) where superseded_at is null and deleted_at is null;

select app.enable_tenant_rls('computed_grades');
select app.attach_updated_at('computed_grades');
select app.attach_soft_delete_guard('computed_grades');

-- ---------------------------------------------------------------------------
-- computed_grade_components
-- ---------------------------------------------------------------------------
create table computed_grade_components (
  id                  uuid primary key default gen_random_uuid(),
  tenant_id           uuid not null references tenants (id),
  computed_grade_id   uuid not null,
  component_id        uuid not null,
  weight_applied      numeric(9, 6) not null check (weight_applied >= 0),
  is_evaluated        boolean not null default false,
  normalized_value    numeric(6, 5) check (normalized_value between 0 and 1),
  display_value       text,
  assessments_counted integer not null default 0 check (assessments_counted >= 0),
  counted_score_ids   uuid[] not null default '{}',
  dropped_score_ids   uuid[] not null default '{}',
  excused_score_ids   uuid[] not null default '{}',
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now(),
  deleted_at          timestamptz,
  constraint cgc_grade_fk foreign key (tenant_id, computed_grade_id)
    references computed_grades (tenant_id, id) on delete cascade,
  constraint cgc_component_fk foreign key (tenant_id, component_id)
    references grading_components (tenant_id, id),
  constraint cgc_evaluated_has_value
    check (is_evaluated = (normalized_value is not null))
);

comment on table computed_grade_components is 'El desglose por componente detrás de un computed grade. La lista de EVALUACIONES lee weight_applied y normalized_value de aquí, y la fila "Sin evaluar" es un componente con is_evaluated = false.';
comment on column computed_grade_components.counted_score_ids is 'Exactamente qué filas de score alimentaron este número. Hace que una nota sea explicable a un padre sin volver a ejecutar el cálculo.';
comment on column computed_grade_components.dropped_score_ids is 'Scores removidas por drop-lowest-N. Se conservan para que el docente pueda responder con precisión "por qué mi peor quiz no cuenta".';
comment on column computed_grade_components.excused_score_ids is 'Scores excluidas del denominador por haber sido excused. Distinto de dropped: excused fue una decisión sobre el estudiante, dropped fue una regla sobre los números.';

create unique index cgc_key on computed_grade_components (computed_grade_id, component_id)
  where deleted_at is null;
create index cgc_component_idx on computed_grade_components (component_id);

select app.enable_tenant_rls('computed_grade_components');
select app.attach_updated_at('computed_grade_components');

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
  'La cola de trabajo, en Postgres. La recomputación de notas y la transcripción de notas de voz pasan por aquí. Se reclama con SELECT ... FOR UPDATE SKIP LOCKED, que es la única razón por la que una cola en la base de datos primaria es viable a esta escala.';

comment on column jobs.tenant_id is 'Nulable: el trabajo de mantenimiento entre tenants no tiene tenant. Por eso jobs no lleva política RLS — un worker legítimamente abarca varios tenants y establece app.tenant_id por cada job.';
comment on column jobs.kind is
  'Qué handler ejecuta el job. Dos tipos están vigentes: ''grade.recompute'' (recalcula la nota ponderada interna opcional del colegio para una class/term) y ''voice_note.transcribe'' (transcripción de voz a texto en español para una nota grabada). Texto libre sin CHECK: las filas de tipos retirados fallan como ''unknown job kind'' en vez de reescribirse.';
comment on column jobs.priority is 'El menor corre primero. La transcripción de una nota que el docente está viendo tiene prioridad sobre un recompute nocturno.';
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

create table practice_scores (
  id             uuid primary key default gen_random_uuid(),
  tenant_id      uuid not null references tenants (id),
  student_id     uuid not null,
  class_id       uuid not null,
  term_id        uuid not null,
  title          text not null,
  kind           text not null default 'otro'
                   check (kind in ('examen', 'practica', 'tarea', 'proyecto',
                                    'exposicion', 'participacion', 'otro')),
  raw_value      numeric(8, 4) not null,
  max_value      numeric(8, 4) not null check (max_value > 0),
  note           text,
  recorded_by_id uuid not null,
  recorded_at    timestamptz not null default now(),
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now(),
  deleted_at     timestamptz,
  constraint practice_scores_tenant_id_key unique (tenant_id, id),
  constraint practice_scores_student_fk foreign key (tenant_id, student_id)
    references students (tenant_id, id),
  constraint practice_scores_class_fk foreign key (tenant_id, class_id)
    references classes (tenant_id, id),
  constraint practice_scores_term_fk foreign key (tenant_id, term_id)
    references terms (tenant_id, id),
  constraint practice_scores_recorded_by_fk foreign key (tenant_id, recorded_by_id)
    references teachers (tenant_id, id)
);

comment on table practice_scores is
  'Un registro personal y no oficial de un docente, creado con "Añadir evaluación" en la pantalla de notas del estudiante. Explícitamente no es una assessment: no lleva componente ni peso, internal/grading nunca lo lee, y nunca llega a computed_grades. Para qué se usa (un quiz de práctica, un repaso, lo que sea) depende enteramente del docente.';
comment on column practice_scores.kind is 'El mismo vocabulario que assessments.kind, por consistencia de etiquetas con la lista oficial de EVALUACIONES — no es una FK, ya que estas no están atadas a ningún grading scheme.';
comment on column practice_scores.note is 'Texto libre opcional que el docente adjunta a la score.';

-- Las scores personales de un estudiante para una class/term, más reciente primero.
create index practice_scores_student_idx
  on practice_scores (student_id, class_id, term_id, recorded_at desc) where deleted_at is null;

select app.enable_tenant_rls('practice_scores');
select app.attach_updated_at('practice_scores');
select app.attach_soft_delete_guard('practice_scores');


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
  suggested_level_id uuid,
  computed_grade_id  uuid,
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
  constraint ctl_suggested_level_fk foreign key (tenant_id, suggested_level_id)
    references grade_scale_levels (tenant_id, id),
  constraint ctl_computed_grade_fk foreign key (tenant_id, computed_grade_id)
    references computed_grades (tenant_id, id),
  constraint ctl_asserted_by_fk foreign key (tenant_id, asserted_by_id)
    references teachers (tenant_id, id),
  constraint ctl_supersedes_fk foreign key (tenant_id, supersedes_id)
    references competency_term_levels (tenant_id, id)
);

comment on table competency_term_levels is
  'DATOS PERSONALES DE MENORES (académico, oficial). El nivel de logro de una competencia para un estudiante en un periodo — la fila que va a SIAGIE y, al cierre del año, decide la situación final. Escrito por el juicio de un docente sobre la evidencia del periodo (5.1.1.3 p.2-3), nunca por un cálculo: internal/grading solo completa suggested_level_id. Una competencia no desarrollada ni evaluada explícitamente en el periodo simplemente no tiene fila (5.1.2.2 p.1) — la ausencia es significativa y no debe leerse como C.';
comment on column competency_term_levels.scale_level_id is 'El nivel afirmado, como una fila de grade_scale_levels (AD/A/B/C en la escala ordinal MINEDU). El único valor que es oficial.';
comment on column competency_term_levels.suggested_level_id is 'Lo que Yanai propuso a partir de las scores ponderadas antes de que el docente decidiera. Null cuando no se calculó nada. Se conserva para medir con qué frecuencia se anula la sugerencia — no tiene ningún valor normativo.';
comment on column competency_term_levels.computed_grade_id is 'La fila de computed_grades de la que vino la sugerencia, para trazabilidad. Null cuando el docente afirmó sin ningún insumo calculado.';
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
comment on column competency_exemptions.authorized_by_id is 'El miembro del personal que registró la exoneración en Yanai. No es la autoridad de la UGEL en sí — document_ref es donde se rastrea esa autorización.';

create unique index competency_exemptions_key
  on competency_exemptions (student_id, competency_id, academic_year_id)
  where deleted_at is null;

select app.enable_tenant_rls('competency_exemptions');
select app.attach_updated_at('competency_exemptions');
select app.attach_soft_delete_guard('competency_exemptions');

-- +goose Down

drop view if exists class_effective_grading_schemes;

drop table if exists competency_exemptions cascade;
drop table if exists year_final_situations cascade;
drop table if exists competency_year_snapshots cascade;
drop table if exists descriptive_conclusions cascade;
drop table if exists competency_term_levels cascade;
drop table if exists practice_scores cascade;
drop table if exists jobs cascade;
drop table if exists events cascade;
drop table if exists notifications cascade;
drop table if exists voice_notes cascade;
drop table if exists computed_grade_components cascade;
drop table if exists computed_grades cascade;
drop table if exists criterion_scores cascade;
drop table if exists scores cascade;
drop table if exists assessment_criteria cascade;
drop table if exists assessments cascade;
drop table if exists grading_scheme_component_weights cascade;
drop table if exists grading_scheme_versions cascade;
drop table if exists grading_components cascade;
drop table if exists grading_schemes cascade;
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
  if exists (select 1 from pg_roles where rolname = 'yanai_app') then
    execute 'drop owned by yanai_app';
    execute 'drop role yanai_app';
  end if;
end
$$;
-- +goose StatementEnd
