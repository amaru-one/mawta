# Local Postgres setup

The schema targets **PostgreSQL 16** and requires the `pgvector` extension
(`voice_notes.embedding`), plus `btree_gist` and `pg_trgm` (bundled with core
Postgres). The `pgvector/pgvector:pg16` image ships all three.

## Start the container

```sh
docker run -d \
  --name yanai-pg \
  -e POSTGRES_PASSWORD=yanai \
  -e POSTGRES_DB=yanai \
  -p 55432:5432 \
  -v yanai-pgdata:/var/lib/postgresql/data \
  pgvector/pgvector:pg16
```

- Host port is **55432** to avoid clashing with any local Postgres on 5432.
- The named volume `yanai-pgdata` persists data across container restarts.
  Drop `-v yanai-pgdata:...` if you want a fully throwaway instance.

Wait until it accepts connections:

```sh
docker exec yanai-pg pg_isready -U postgres
```

## Connection strings

Two roles, two purposes. `ADMIN_DATABASE_URL` connects as the `postgres`
superuser: it owns every table, so it's what runs migrations and what
`cmd/useradd` uses to seed the very first account in an empty tenant (see
`internal/db.WithSystemTx`). `DATABASE_URL` connects as the non-owner
`yanai_app` role (created by migration `00001`): it's what `cmd/api` runs as
for every real request, RLS-scoped to whatever tenant the request resolves to.

```sh
export ADMIN_DATABASE_URL='postgres://postgres:yanai@localhost:55432/yanai?sslmode=disable'
export DATABASE_URL='postgres://yanai_app:yanai_app@localhost:55432/yanai?sslmode=disable'
```

## Run the migrations

```sh
goose -dir migrations postgres "$ADMIN_DATABASE_URL" up
```

Roll back / re-apply:

```sh
goose -dir migrations postgres "$ADMIN_DATABASE_URL" down   # one migration
goose -dir migrations postgres "$ADMIN_DATABASE_URL" reset  # all the way down
```

`00001` creates `yanai_app` with `login` but no password — it needs one
before `DATABASE_URL` above can connect as it:

```sh
docker exec yanai-pg psql -U postgres -d yanai -c "alter role yanai_app login password 'yanai_app';"
```

## Connecting as the application

RLS is **forced** on every tenant table. `cmd/api`'s own pool connects
directly as the non-owner role `yanai_app` (`DATABASE_URL`); `internal/db`'s
`WithTenantTx`/`WithAuthTx` still set the tenant per transaction on top of
that:

```sql
set local app.tenant_id = '<tenant uuid>';
set local app.actor_id  = '<user uuid>';
```

Queries without `app.tenant_id` set return **zero rows** — that's the isolation
working, not a bug. This applies to psql sessions and backfill scripts too;
from a `psql` session connected as `postgres`, reach the same RLS scope with
`set role yanai_app;` first.

There is no seed any more. Create a tenant row by hand (or with a script of
your own), then create the first account with `cmd/useradd` — it hashes a
real password, so it has to be Go rather than a SQL file:

```sh
psql "$DATABASE_URL" -c "insert into tenants (name) values ('I.E. Cristo Rey') returning id;"
go run ./cmd/useradd -tenant '<tenant-uuid-from-above>' -username jquispe \
  -email janice.quispe@cristorey.edu.pe -given-name Janice -family-name Quispe \
  -role teacher -password 'a real password, 10+ chars'
```

`useradd` creates only the account (users + memberships + teachers rows) —
not an academic year, terms, competencias or classes. See
`cmd/useradd/SPEC.md`.

No local `psql` client? Pipe commands into the container's own — see
[Working inside the container](#working-inside-the-container).

## Working inside the container

The container ships its own `psql`, so you never need a local client. For an
interactive shell (`-it` gives you the terminal; `\dt`, `\d+ <table>`, `\q`
all work as usual):

```sh
docker exec -it yanai-pg psql -U postgres -d yanai
```

For one-off commands, drop the `-it` — with `-c` there's nothing to attach a
terminal to, and passing `-it` from a script or CI fails with *"cannot attach
stdin to a TTY-enabled container"*:

```sh
docker exec yanai-pg psql -U postgres -d yanai -c 'select count(*) from classes;'
```

To pipe a whole file in from the host, use `-i` (stdin, no TTY) with `-f -`:

```sh
docker exec -i yanai-pg psql -U postgres -d yanai -v ON_ERROR_STOP=1 -f - < some_script.sql
```

## Quick sanity check

```sh
docker exec yanai-pg psql -U postgres -d yanai -c "
  set role yanai_app;
  set app.tenant_id = '<tenant-uuid>';
  select name from classes;"
```

Expected: whatever classes you've loaded against that tenant.

## Resetting the database

While the project is in development this is a routine operation, not an
emergency one: there is no hard-delete rule in the schema to work around, and
there is no seed to worry about losing. **Dev only** — see the warning at the
end before running any of this against a deployed stack.

### Drop and recreate the database (the usual way)

This stays entirely inside the running container — the container, the volume
and the `yanai_app` role all survive, so it's much faster than rebuilding the
cluster. `with (force)` terminates any connection still holding the database
open (the API, a stray `psql`), which is what otherwise makes `drop database`
fail:

```sh
docker exec yanai-pg psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
  -c 'drop database yanai with (force);' \
  -c 'create database yanai;'
```

Note the `-d postgres`: you cannot drop the database you're connected to, so
this connects to the default `postgres` maintenance database instead.

Then re-apply the schema and recreate your account (see above):

```sh
goose -dir migrations postgres "$ADMIN_DATABASE_URL" up
go run ./cmd/useradd -tenant '<tenant-uuid>' -username jquispe -password '...' ...
```

`yanai_app` is a **cluster-wide** role, so both it and its password outlive
the database they were created for. That's fine: migration `00001` creates
the role only `if not exists` and re-grants its privileges on every `up`, so
re-migrating a freshly created database picks it back up cleanly — no need to
set the password again.

### Rebuild the container from scratch

Only needed when the cluster itself is the problem — a corrupt volume, a
changed image tag, or a Postgres version bump:

```sh
docker rm -f yanai-pg
docker volume rm yanai-pgdata

docker run -d --name yanai-pg -e POSTGRES_PASSWORD=yanai -e POSTGRES_DB=yanai \
  -p 55432:5432 -v yanai-pgdata:/var/lib/postgresql/data pgvector/pgvector:pg16
docker exec yanai-pg pg_isready -U postgres
goose -dir migrations postgres "$ADMIN_DATABASE_URL" up
docker exec yanai-pg psql -U postgres -d yanai -c "alter role yanai_app login password 'yanai_app';"
go run ./cmd/useradd -tenant '<tenant-uuid>' -username jquispe -password '...' ...
```

### Not on the deployed stack

Everything above targets the local `yanai-pg` container. The deployed stack
(`deploy/docker-compose.prod.yml`) names the service `postgres`, keeps its
data in the `pgdata` volume, and publishes no host port — you'd reach it as
`docker compose -f docker-compose.prod.yml exec postgres psql -U postgres …`.
Dropping that database destroys real school data with no backup path in this
repo. Migrate it (`DEPLOY.md`), don't reset it.
