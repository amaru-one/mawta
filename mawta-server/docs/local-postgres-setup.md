# Local Postgres setup

The schema targets **PostgreSQL 16** and requires `btree_gist` and `pg_trgm`,
both bundled with core Postgres. A plain `postgres:16` image is enough.

The commands below use `pgvector/pgvector:pg16`, which is also what
`deploy/docker-compose.prod.yml` runs, so a local container matches production
exactly. pgvector itself is **not** required and is not used: there is no
`vector` extension and no embedding column anywhere in the schema. An earlier
version of this page said `voice_notes.embedding` needed it; that column does
not exist.

## Start the container

```sh
docker run -d \
  --name mawta-pg \
  -e POSTGRES_PASSWORD=mawta \
  -e POSTGRES_DB=mawta \
  -p 55432:5432 \
  -v mawta-pgdata:/var/lib/postgresql/data \
  pgvector/pgvector:pg16
```

- Host port is **55432** to avoid clashing with any local Postgres on 5432.
- The named volume `mawta-pgdata` persists data across container restarts.
  Drop `-v mawta-pgdata:...` if you want a fully throwaway instance.

Wait until it accepts connections:

```sh
docker exec mawta-pg pg_isready -U postgres
```

## Connection strings

Two roles, two purposes. `ADMIN_DATABASE_URL` connects as the `postgres`
superuser: it owns every table, so it's what runs migrations and what
`cmd/useradd` uses to seed the very first account in an empty tenant (see
`internal/db.WithSystemTx`). `DATABASE_URL` connects as the non-owner
`mawta_app` role (created by migration `00001`): it's what `cmd/api` runs as
for every real request, RLS-scoped to whatever tenant the request resolves to.

```sh
export ADMIN_DATABASE_URL='postgres://postgres:mawta@localhost:55432/mawta?sslmode=disable'
export DATABASE_URL='postgres://mawta_app:mawta_app@localhost:55432/mawta?sslmode=disable'
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

`00001` creates `mawta_app` with `login` but no password — it needs one
before `DATABASE_URL` above can connect as it:

```sh
docker exec mawta-pg psql -U postgres -d mawta -c "alter role mawta_app login password 'mawta_app';"
```

## Connecting as the application

RLS is **forced** on every tenant table. `cmd/api`'s own pool connects
directly as the non-owner role `mawta_app` (`DATABASE_URL`); `internal/db`'s
`WithTenantTx`/`WithAuthTx` still set the tenant per transaction on top of
that:

```sql
set local app.tenant_id = '<tenant uuid>';
set local app.actor_id  = '<user uuid>';
```

Queries without `app.tenant_id` set return **zero rows** — that's the isolation
working, not a bug. This applies to psql sessions and backfill scripts too;
from a `psql` session connected as `postgres`, reach the same RLS scope with
`set role mawta_app;` first.

There is no seed any more. Create a tenant row by hand (or with a script of
your own), then create the first account with `cmd/useradd` — it hashes a
real password, so it has to be Go rather than a SQL file:

Create the tenant through **`ADMIN_DATABASE_URL`**, not `DATABASE_URL`:
`tenants` is FORCE RLS with `with check (id = app.current_tenant_id())`, and
there is no tenant set yet, so the insert as `mawta_app` is rejected. (This
page previously showed `$DATABASE_URL` here, which cannot work;
`DEPLOY.md` has it right.)

```sh
psql "$ADMIN_DATABASE_URL" -c "insert into tenants (name) values ('I.E. Cristo Rey') returning id;"
go run ./cmd/useradd -tenant '<tenant-uuid-from-above>' -username jquispe \
  -email janice.quispe@cristorey.edu.pe -given-name Janice -family-name Quispe \
  -role teacher -password 'a real password, 10+ chars'
```

`useradd` creates only the account (users + memberships + teachers rows) —
not an academic year, terms, competencies or classes. See
`cmd/useradd/SPEC.md`.

No local `psql` client? Pipe commands into the container's own — see
[Working inside the container](#working-inside-the-container).

## Working inside the container

The container ships its own `psql`, so you never need a local client. For an
interactive shell (`-it` gives you the terminal; `\dt`, `\d+ <table>`, `\q`
all work as usual):

```sh
docker exec -it mawta-pg psql -U postgres -d mawta
```

For one-off commands, drop the `-it` — with `-c` there's nothing to attach a
terminal to, and passing `-it` from a script or CI fails with *"cannot attach
stdin to a TTY-enabled container"*:

```sh
docker exec mawta-pg psql -U postgres -d mawta -c 'select count(*) from classes;'
```

To pipe a whole file in from the host, use `-i` (stdin, no TTY) with `-f -`:

```sh
docker exec -i mawta-pg psql -U postgres -d mawta -v ON_ERROR_STOP=1 -f - < some_script.sql
```

## Quick sanity check

```sh
docker exec mawta-pg psql -U postgres -d mawta -c "
  set role mawta_app;
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
and the `mawta_app` role all survive, so it's much faster than rebuilding the
cluster. `with (force)` terminates any connection still holding the database
open (the API, a stray `psql`), which is what otherwise makes `drop database`
fail:

```sh
docker exec mawta-pg psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
  -c 'drop database mawta with (force);' \
  -c 'create database mawta;'
```

Note the `-d postgres`: you cannot drop the database you're connected to, so
this connects to the default `postgres` maintenance database instead.

Then re-apply the schema and recreate your account (see above):

```sh
goose -dir migrations postgres "$ADMIN_DATABASE_URL" up
go run ./cmd/useradd -tenant '<tenant-uuid>' -username jquispe -password '...' ...
```

`mawta_app` is a **cluster-wide** role, so both it and its password outlive
the database they were created for. That's fine: migration `00001` wraps
`create role mawta_app login` in `exception when duplicate_object or
unique_violation then null` (not an `if not exists` check — that check-then-
create race is what broke CI when `dbtest` migrates several throwaway
databases concurrently, see `migrations/SPEC.md`) and re-grants its
privileges on every `up`, so re-migrating a freshly created database picks it
back up cleanly — no need to set the password again.

### Rebuild the container from scratch

Only needed when the cluster itself is the problem — a corrupt volume, a
changed image tag, or a Postgres version bump:

```sh
docker rm -f mawta-pg
docker volume rm mawta-pgdata

docker run -d --name mawta-pg -e POSTGRES_PASSWORD=mawta -e POSTGRES_DB=mawta \
  -p 55432:5432 -v mawta-pgdata:/var/lib/postgresql/data pgvector/pgvector:pg16
docker exec mawta-pg pg_isready -U postgres
goose -dir migrations postgres "$ADMIN_DATABASE_URL" up
docker exec mawta-pg psql -U postgres -d mawta -c "alter role mawta_app login password 'mawta_app';"
go run ./cmd/useradd -tenant '<tenant-uuid>' -username jquispe -password '...' ...
```
