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

## Connection string

```
postgres://postgres:yanai@localhost:55432/yanai?sslmode=disable
```

Export it for goose and the app:

```sh
export DATABASE_URL='postgres://postgres:yanai@localhost:55432/yanai?sslmode=disable'
```

## Run the migrations

```sh
goose -dir migrations postgres "$DATABASE_URL" up
```

Roll back / re-apply:

```sh
goose -dir migrations postgres "$DATABASE_URL" down   # one migration
goose -dir migrations postgres "$DATABASE_URL" reset  # all the way down
```

## Connecting as the application

RLS is **forced** on every tenant table, so the app must connect as the
non-owner role `yanai_app` (created by migration `00001`) and set the tenant
per transaction:

```sql
set local role yanai_app;
set local app.tenant_id = '<tenant uuid>';
set local app.actor_id  = '<user uuid>';
```

Queries without `app.tenant_id` set return **zero rows** — that's the isolation
working, not a bug. This applies to psql sessions and backfill scripts too.

`seed/seed_demo_tenant.sql` (not a goose migration — run it directly, see
`seed/README.md`) creates the demo tenant
`11111111-1111-4111-8111-111111111111` (I.E. Cristo Rey) with teacher, roster,
sessions, published assessments and both grading schemes:

```sh
psql "$DATABASE_URL" -f seed/seed_demo_tenant.sql
```

No local `psql` client? Pipe the file into the container's own — see
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
docker exec -i yanai-pg psql -U postgres -d yanai -v ON_ERROR_STOP=1 -f - < seed/seed_demo_tenant.sql
```

## Quick sanity check

```sh
docker exec yanai-pg psql -U postgres -d yanai -c "
  set role yanai_app;
  set app.tenant_id = '11111111-1111-4111-8111-111111111111';
  select name from classes;"
```

Expected: `Inglés 5to B` and `Matemática 5to B`.

## Resetting the database

While the project is in development this is a routine operation, not an
emergency one: there is no hard-delete rule in the schema to work around, and
the seed is the only source of data worth keeping. **Dev only** — see the
warning at the end before running any of this against a deployed stack.

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

Then re-apply the schema and the seed:

```sh
goose -dir migrations postgres "$DATABASE_URL" up
docker exec -i yanai-pg psql -U postgres -d yanai -v ON_ERROR_STOP=1 -f - < seed/seed_demo_tenant.sql
```

`seed_demo_tenant.sql` is one file containing all four dataset blocks
(the base tenant plus `Inglés 5to A`, `Historia 4to A`, `Arte 3ro A`), applied
in dependency order inside it — nothing else to run. `../seed/README.md`
covers what each block contains, and how to dry-run or undo it.

`yanai_app` is a **cluster-wide** role, so it outlives the database it was
created for. That's fine: migration `00001` creates it only `if not exists`
and re-grants its privileges on every `up`, so re-migrating a freshly created
database picks it back up cleanly.

### Rebuild the container from scratch

Only needed when the cluster itself is the problem — a corrupt volume, a
changed image tag, or a Postgres version bump:

```sh
docker rm -f yanai-pg
docker volume rm yanai-pgdata

docker run -d --name yanai-pg -e POSTGRES_PASSWORD=yanai -e POSTGRES_DB=yanai \
  -p 55432:5432 -v yanai-pgdata:/var/lib/postgresql/data pgvector/pgvector:pg16
docker exec yanai-pg pg_isready -U postgres
goose -dir migrations postgres "$DATABASE_URL" up
docker exec -i yanai-pg psql -U postgres -d yanai -v ON_ERROR_STOP=1 -f - < seed/seed_demo_tenant.sql
```

### Not on the deployed stack

Everything above targets the local `yanai-pg` container. The deployed stack
(`deploy/docker-compose.prod.yml`) names the service `postgres`, keeps its
data in the `pgdata` volume, and publishes no host port — you'd reach it as
`docker compose -f docker-compose.prod.yml exec postgres psql -U postgres …`.
Dropping that database destroys real school data with no backup path in this
repo. Migrate it (`DEPLOY.md`), don't reset it.
