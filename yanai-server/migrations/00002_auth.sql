-- Real authentication. Before this, internal/httpapi.tenantAuth trusted
-- client-supplied X-Tenant-ID / X-Actor-ID headers outright — anyone who
-- knew a user's UUID was that user. See migrations/SPEC.md's "00002_auth.sql"
-- section for the full reasoning behind every non-obvious choice below,
-- especially the login_lookup policy and why a security definer function
-- was rejected in favour of it.

-- +goose Up

-- ---------------------------------------------------------------------------
-- users: the credential
-- ---------------------------------------------------------------------------
alter table users
  add column username            text,
  add column password_hash       text,
  add column password_changed_at timestamptz,
  add column last_login_at       timestamptz,
  add column failed_login_count  smallint not null default 0,
  add column locked_until        timestamptz;

alter table users
  add constraint users_credential_complete
    check ((username is null) = (password_hash is null)),
  add constraint users_username_shape
    check (username is null or username ~ '^[a-z0-9._-]{3,64}$'),
  add constraint users_failed_login_count_nonneg
    check (failed_login_count >= 0);

create unique index users_username_key on users (lower(username))
  where username is not null and deleted_at is null;

comment on column users.username is
  'PII (adult): the login identifier. Globally unique on lower(username), like email and for the same reason — one person, one credential, one school (see memberships_one_school_per_user). Lowercased on write; users_username_shape restricts it to [a-z0-9._-]{3,64} so lower() is a true identity. Email stays contact data and is never a login.';
comment on column users.password_hash is
  'bcrypt hash (cost from BCRYPT_COST, default 12) of the account password. Never logged, never returned by any endpoint, read only by internal/repo/auth.go. Null means the account has no password and cannot log in; users_credential_complete keeps that paired with a null username.';
comment on column users.password_changed_at is
  'When the password was last set. Every user_sessions row for the user is revoked (reason = ''password_change'') when it changes.';
comment on column users.last_login_at is
  'Last successful login. Re-added by this migration; a column of this name was dropped on 2026-09-11 as dead schema when nothing wrote it. It has a writer now — repo.RecordLoginSuccess — and must not be dropped again for the same reason.';
comment on column users.failed_login_count is
  'Consecutive failed logins since the last success. Reset to 0 on success. At LOGIN_MAX_FAILURES the account locks via locked_until, whatever the password on the next attempt.';
comment on column users.locked_until is
  'Lockout expiry. While in the future, every login attempt for this account is refused with account_locked regardless of the password.';

-- ---------------------------------------------------------------------------
-- users, memberships: the pre-tenant login-lookup policy
-- ---------------------------------------------------------------------------
-- Permissive policies OR together, so this widens nothing while a tenant is
-- set — it only ever applies inside internal/db.WithAuthTx, the one
-- transaction mode with no tenant and this GUC on.
--
-- Needed on BOTH tables: resolving a login means reading the matching users
-- row (FindLoginCandidate) AND then the user's membership (ResolveMembership,
-- to learn which tenant/role to open a real session in) — and memberships
-- is tenant-scoped RLS same as any other table via app.enable_tenant_rls,
-- so without this second policy a tenant-less transaction reads zero
-- membership rows no matter what the query's WHERE clause says.
create policy login_lookup on users
  using      (app.current_tenant_id() is null and current_setting('app.auth_lookup', true) = 'on')
  with check (app.current_tenant_id() is null and current_setting('app.auth_lookup', true) = 'on');

create policy login_lookup on memberships
  using      (app.current_tenant_id() is null and current_setting('app.auth_lookup', true) = 'on')
  with check (app.current_tenant_id() is null and current_setting('app.auth_lookup', true) = 'on');

comment on policy login_lookup on memberships is
  'The same pre-tenant exception as users.login_lookup, for the same reason: ResolveMembership must read a membership before its tenant is known, to learn which tenant to open a real session in. Narrow for the same reasons — see users.login_lookup''s comment.';

comment on policy login_lookup on users is
  'The ordering exception. At login, and at every session-cookie validation, there is no tenant yet — the tenant is the RESULT of resolving a credential or a session token — so tenant_isolation can never match. This policy opens users to a transaction that has explicitly set app.auth_lookup=''on'' AND has no tenant, which only internal/db.WithAuthTx does. Every other table''s policy still evaluates tenant_id = NULL in that transaction and returns nothing, so the blast radius of a bug on this path is this one table. Deliberately NOT solved with a security definer function or with WithSystemTx: FORCE ROW LEVEL SECURITY binds the table owner too, so either would need a superuser (or BYPASSRLS) owner and would confer a full RLS bypass rather than reduce privilege — see migrations/SPEC.md.';

-- ---------------------------------------------------------------------------
-- users: why it is still not tenant-scoped (comment only, no shape change)
-- ---------------------------------------------------------------------------
comment on table users is
  'PII (adult). Authentication principals: the four membership roles (teacher, student, supervisor, admin). Carries the credential (username + password_hash) since this migration. Not tenant-scoped: isolation runs through memberships instead, via the tenant_isolation policy below, which is what login_lookup narrowly complements. Holds no minor data — students are not users and have no login: memberships.role may say ''student'', but no students row ever links to a users row, and only role=''teacher'' may complete a login today (see memberships.role below).';

-- ---------------------------------------------------------------------------
-- memberships: one person, one school
-- ---------------------------------------------------------------------------
create unique index memberships_one_school_per_user
  on memberships (user_id) where deleted_at is null and status <> 'revoked';

comment on index memberships_one_school_per_user is
  'A user holds at most one active-or-invited membership at a time. Revoked memberships are excluded on purpose: leaving one school must not block joining another. This is what makes the login path''s "which membership" question unreachable rather than merely unhandled — there is never more than one to choose from.';

-- ---------------------------------------------------------------------------
-- memberships: the role vocabulary
-- ---------------------------------------------------------------------------
-- Lossy on purpose: nothing in Go or the UI ever wrote 'coordinator',
-- 'director' or 'support', and the deleted demo seed only wrote 'teacher',
-- so these are expected to affect zero rows everywhere but exist so the
-- CHECK swap below cannot fail on a database that somehow has them.
update memberships set role = 'supervisor' where role in ('coordinator', 'director');
update memberships set role = 'admin'      where role = 'support';

alter table memberships drop constraint memberships_role_check;
alter table memberships add constraint memberships_role_check
  check (role in ('teacher', 'student', 'supervisor', 'admin'));

comment on table memberships is
  'Which user acts in which school, and in what role. The join that makes a users row visible under RLS, and the row a login resolves to. Four roles: ''teacher'' (the only one that may complete a login today), ''student'', ''supervisor'', ''admin''. The other three are modelled — permission checks are written generically against role — so they can be enabled later purely by widening domain.LoginEnabledRoles; a login attempt by one of them today is refused with role_not_enabled. memberships_one_school_per_user holds a user to exactly one active membership, so the login path never has to choose between several.';

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
  'Server-side sessions. The browser holds an opaque 256-bit token in an HttpOnly cookie; only its sha256 is stored here, so reading this table cannot impersonate anyone. Deliberately carries NO RLS policy, for the same reason jobs.tenant_id does not: a row here must be readable before app.current_tenant_id() can be set, since resolving it IS how the tenant becomes known. Isolation is structural instead: the only reader is internal/repo/auth.go, always by exact token_hash, and the composite FK to memberships (tenant_id, membership_id) makes a cross-tenant session row impossible to insert.';
comment on column user_sessions.token_hash is
  'sha256 of the raw token. The raw token exists only in the Set-Cookie header and the browser''s cookie jar — never stored, logged or returned again. sha256 rather than bcrypt on purpose: the input is 256 bits of crypto/rand, already unguessable, so it needs no work factor, and this is read on every request.';
comment on column user_sessions.tenant_id is
  'Denormalised from the membership so one pre-tenant read resolves the whole RLS context, without a second query through memberships once the tenant is still unknown.';
comment on column user_sessions.role is
  'Copied from the membership at login and re-checked against the live membership on every request (internal/httpapi.sessionAuth), so a role revoked or downgraded after login takes effect immediately rather than at session expiry.';
comment on column user_sessions.expires_at is
  'Absolute expiry, set at login from SESSION_TTL. Never extended. Idle expiry is a separate check, computed in Go from last_seen_at against SESSION_IDLE_TIMEOUT.';
comment on column user_sessions.last_seen_at is
  'Updated at most once an hour per session (repo.TouchSession), not on every request — a write per request would turn every GET into a read-write transaction.';
comment on column user_sessions.revoked_reason is
  'logout (user-initiated), expired/idle (lazily revoked at validation time — there is no scheduler in this codebase, see internal/worker/SPEC.md, so nothing prunes proactively), password_change (every session for the user, on a password change), admin (reserved for a future admin-initiated revoke).';

create unique index user_sessions_token_hash_key on user_sessions (token_hash);
create index user_sessions_user_idx   on user_sessions (user_id)    where revoked_at is null;
create index user_sessions_expiry_idx on user_sessions (expires_at) where revoked_at is null;

-- +goose Down

drop table if exists user_sessions;

drop policy if exists login_lookup on users;
drop policy if exists login_lookup on memberships;

alter table memberships drop constraint memberships_role_check;
-- Lossy in reverse: 'student' has no pre-existing equivalent, and
-- supervisor -> coordinator loses whether the row had been a director.
-- +goose StatementBegin
do $$
begin
  if exists (select 1 from memberships where role = 'student') then
    raise exception 'cannot roll back 00002_auth: memberships holds role=''student'', which the old CHECK has no value for';
  end if;
  update memberships set role = 'coordinator' where role = 'supervisor';
end
$$;
-- +goose StatementEnd
alter table memberships add constraint memberships_role_check
  check (role in ('teacher', 'coordinator', 'director', 'admin', 'support'));

comment on table memberships is 'Which user acts in which school, and in what role. The join that makes a users row visible under RLS.';

drop index if exists memberships_one_school_per_user;

drop index if exists users_username_key;
alter table users
  drop constraint if exists users_credential_complete,
  drop constraint if exists users_username_shape,
  drop constraint if exists users_failed_login_count_nonneg;
alter table users
  drop column if exists locked_until,
  drop column if exists failed_login_count,
  drop column if exists last_login_at,
  drop column if exists password_changed_at,
  drop column if exists password_hash,
  drop column if exists username;

comment on table users is 'PII (adult). Authentication principals: teachers, coordinators, directors, admins. Holds no minor data — students are not users in v1 and have no login.';
