# Local Postgres setup

The schema targets **PostgreSQL 16** and uses `btree_gist` and `pg_trgm`, both bundled with core
Postgres. The commands below use `pgvector/pgvector:pg16`, which is the image production runs.
pgvector itself is not used, so a plain `postgres:16` works too.

A database holds **one school**, so use one database per school you want to try.

## Start the container

```sh
docker run -d --name mawta-pg \
  -e POSTGRES_PASSWORD=mawta -e POSTGRES_DB=mawta \
  -p 55432:5432 -v mawta-pgdata:/var/lib/postgresql/data \
  pgvector/pgvector:pg16
docker exec mawta-pg pg_isready -U postgres
```

- The host port is **55432**, so it does not clash with a local Postgres on 5432.
- The named volume `mawta-pgdata` keeps the data across restarts. Leave the `-v` option out for a
  throwaway instance.

## The roles

| Role | Who uses it | Connection |
|---|---|---|
| `postgres` (owner) | Migrations, `onboard` and `useradd` | `MAWTA_MIGRATIONS_URL`, `ADMIN_DATABASE_URL` |
| `mawta_app` | The app, for every request and job | `DATABASE_URL` |
| `mawta_chat` | The chat's tools. **It has no login**: the app enters it with `SET LOCAL ROLE`, and inside it the tools can read only the `chat_api` views | none |
| `mawta_langgraph` | The chat's memory (LangGraph checkpoints), in schema `langgraph` of the same database | `LANGGRAPH_DATABASE_URL` |
| `mawta_chat_api` | Owns the `chat_api` views. It never logs in | none |

The migrations create these roles without passwords, because a password never goes in a
migration. Roles belong to the whole Postgres cluster, not to one database, so a password set once
serves every database of the container.

```sh
export MAWTA_MIGRATIONS_URL='postgres://postgres:mawta@localhost:55432/mawta'
export ADMIN_DATABASE_URL="$MAWTA_MIGRATIONS_URL"
export DATABASE_URL='postgres://mawta_app:app-local@localhost:55432/mawta'
export LANGGRAPH_DATABASE_URL='postgres://mawta_langgraph:lg-local@localhost:55432/mawta?options=-c%20search_path%3Dlanggraph'
```

The same values can go in `.env` (see `.env.example`).

## Migrate

```sh
uv run alembic upgrade head
docker exec mawta-pg psql -U postgres -d mawta \
  -c "alter role mawta_app password 'app-local'" \
  -c "alter role mawta_langgraph password 'lg-local'"
```

`uv run alembic downgrade -1` steps one migration back. `uv run alembic check` fails if the
models in `src/mawta_schema/` and the migrations disagree.

LangGraph creates its own tables in schema `langgraph` the first time the chat starts with a
model.

## Install a school

The database is empty until a school is installed from its JSON file
([school-onboarding.md](school-onboarding.md)):

```sh
uv run onboard -file colegio.json -dry-run    # validate, then roll back
uv run onboard -file colegio.json
```

Use `useradd` to add one account later, for example a director:

```sh
uv run useradd -username rquispe -role director -no-teacher-profile \
  -email director@colegio.edu.pe -given-name Rosa -family-name Quispe   # asks for the password
```

## Working inside the container

The container has its own `psql`, so you never need a local client:

```sh
docker exec -it mawta-pg psql -U postgres -d mawta                          # interactive
docker exec mawta-pg psql -U postgres -d mawta -c 'select count(*) from classes'
docker exec -i mawta-pg psql -U postgres -d mawta -v ON_ERROR_STOP=1 -f - < script.sql
```

Use `-it` only for an interactive shell. A script or CI has no terminal, and there `-it` fails
with "cannot attach stdin to a TTY-enabled container".

To see what the chat's tools see, become their role:

```sh
docker exec mawta-pg psql -U postgres -d mawta -c "
  set role mawta_chat;
  select section, count(*) from chat_api.students group by 1;"
```

As `mawta_chat`, a query on `public.students` fails with `permission denied`. That is the
boundary working, not a bug.

## Resetting the database

This is for development only. Never run it against a deployed stack.

```sh
docker exec mawta-pg psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
  -c 'drop database mawta with (force)' -c 'create database mawta'
uv run alembic upgrade head
```

The `-d postgres` option matters, because you cannot drop the database you are connected to.
`with (force)` closes any connection that still holds it open.

The roles and their passwords survive the drop, because they belong to the cluster. Migration
`0001` creates each role inside `exception when duplicate_object` and grants its privileges again,
so a fresh database picks them up as they are. Several databases can also migrate at the same time
this way, which is what the tests do.

To start over from nothing, also remove the container and the volume:
`docker rm -f mawta-pg && docker volume rm mawta-pgdata`.
