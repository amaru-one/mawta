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
grades and both grading schemes:

```sh
psql "$DATABASE_URL" -f seed/seed_demo_tenant.sql
```

## Quick sanity check

```sh
docker exec -it yanai-pg psql -U postgres -d yanai -c "
  set role yanai_app;
  set app.tenant_id = '11111111-1111-4111-8111-111111111111';
  select name from classes;"
```

Expected: `Inglés 5to B` and `Matemática 5to B`.

## Reset everything

```sh
docker rm -f yanai-pg
docker volume rm yanai-pgdata
```
