# Resetting the Yanai database

This is **destructive** — it drops and recreates the `yanai` database on
whatever server `.env` points at, wiping all data. Use it deliberately: to
reset a dev/staging box, or to recover from the schema drift described in
Open Questions below. Never run it against a server with data you need,
without a backup first.

Run everything below as `deploy@<server>`, from `/srv/yanai`.

## 1. Back up first

```sh
set -a; source .env; set +a
docker compose --env-file .env -f deploy/docker-compose.prod.yml \
  exec -T postgres pg_dump -U postgres -d yanai --no-owner --no-privileges \
  > ~/yanai_backup_$(date +%Y%m%d_%H%M%S).sql
```

## 2. Stop the app and drop the database

```sh
docker compose --env-file .env -f deploy/docker-compose.prod.yml stop api

docker compose --env-file .env -f deploy/docker-compose.prod.yml \
  exec -T postgres psql -U postgres -d postgres -c "
    select pg_terminate_backend(pid) from pg_stat_activity
    where datname = 'yanai' and pid <> pg_backend_pid();"

docker compose --env-file .env -f deploy/docker-compose.prod.yml \
  exec -T postgres psql -U postgres -d postgres -c "drop database yanai;"

docker compose --env-file .env -f deploy/docker-compose.prod.yml \
  exec -T postgres psql -U postgres -d postgres -c "create database yanai;"
```

## 3. Re-apply the current migration

```sh
docker compose --env-file .env -f deploy/docker-compose.prod.yml \
  run --rm --entrypoint /usr/local/bin/goose api up
```

`yanai_app` itself is untouched by this (it's a cluster-wide role, not
per-database) — the migration's `create role ... exception when
duplicate_object/unique_violation` block just no-ops, and its password
(already set in Postgres from before) still matches `.env`'s
`YANAI_APP_PASSWORD`. Nothing to redo there.

## 4. Restart and smoke-test

```sh
docker compose --env-file .env -f deploy/docker-compose.prod.yml up -d api
curl -fsS https://$(grep ^DOMAIN .env | cut -d= -f2)/healthz
curl -s -o /dev/null -w '%{http_code}\n' https://$(grep ^DOMAIN .env | cut -d= -f2)/api/v1/me  # expect 401
```

## 5. Recreate a tenant and account

There is no seed. Create the tenant, then the first account with
`cmd/useradd` (see `yanai-server/cmd/useradd/SPEC.md`):

```sh
docker compose --env-file .env -f deploy/docker-compose.prod.yml \
  exec -T postgres psql -U postgres -d yanai \
  -c "insert into tenants (name) values ('Your School Name') returning id;"

docker compose --env-file .env -f deploy/docker-compose.prod.yml \
  run --rm --entrypoint /usr/local/bin/useradd api \
  -tenant '<tenant-uuid-from-above>' -username <username> \
  -email <email> -given-name <given> -family-name <family> \
  -role teacher -generate-password
```

`-generate-password` prints a one-time password to stderr — save it, it's
never stored in plaintext. Use `-password <value>` instead to set one
directly, or `-reset-password -username <u> -password <v>` to change an
existing account's password.
