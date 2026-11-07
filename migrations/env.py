"""Alembic environment: the models in mawta_schema plus the Postgres objects from alembic_utils."""

import os
import re
from logging.config import fileConfig

from alembic import context
from alembic_utils.pg_function import PGFunction
from alembic_utils.pg_policy import PGPolicy
from alembic_utils.pg_trigger import PGTrigger
from alembic_utils.pg_view import PGView
from alembic_utils.replaceable_entity import register_entities
from sqlalchemy import Connection, create_engine, pool

from mawta_schema import entities
from mawta_schema.base import Base
from mawta_schema.tables import __all__ as _tables  # noqa: F401  (registers every table)

config = context.config
if config.config_file_name is not None and not config.attributes.get("skip_logging"):
    # Keep the loggers that already exist (the app's, when migrations run inside a process).
    fileConfig(config.config_file_name, disable_existing_loggers=False)

SCHEMAS = {None, "public", "chat"}
# Monthly partitions of events (events_2026_01 ... and events_default) are created by the
# migrations and by app.ensure_events_partition, not declared as models.
PARTITION = re.compile(r"events_(\d{4}_\d{2}|default)")

# Only these kinds are compared. Grants and extensions are written by hand in the migrations
# (see 0001_baseline): alembic_utils would otherwise offer to revoke every grant that came from
# ALTER DEFAULT PRIVILEGES and to drop btree_gist and pg_trgm.
register_entities(
    entities.ALL,
    schemas=list(entities.SCHEMAS),
    entity_types=[PGFunction, PGTrigger, PGView, PGPolicy],
)

# Every function of ours lives in schema app. alembic_utils would otherwise also read public,
# where Postgres keeps the internal constructor functions of the timerange type, which it
# cannot parse.
_list_functions = PGFunction.from_database.__func__


def _app_functions(cls, sess, schema="%"):
    return _list_functions(cls, sess, schema="app") if schema in ("app", "%") else []


PGFunction.from_database = classmethod(_app_functions)  # pyright: ignore[reportAttributeAccessIssue]

# Postgres clones the row triggers of events onto each partition by itself; only the parent's
# trigger is declared.
_list_triggers = PGTrigger.from_database.__func__


def _parent_triggers(cls, sess, schema="%"):
    return [
        t
        for t in _list_triggers(cls, sess, schema=schema)
        if not PARTITION.fullmatch(t.on_entity.rpartition(".")[2])
    ]


PGTrigger.from_database = classmethod(_parent_triggers)  # pyright: ignore[reportAttributeAccessIssue]


def database_url() -> str:
    url = os.environ.get("MAWTA_MIGRATIONS_URL") or os.environ.get("ADMIN_DATABASE_URL")
    if not url:
        raise SystemExit("set MAWTA_MIGRATIONS_URL (or ADMIN_DATABASE_URL) to run migrations")
    return re.sub(r"^postgres(ql)?://", "postgresql+psycopg://", url)


def include_name(name, type_, parent_names):
    if type_ == "schema":
        return name in SCHEMAS
    if type_ == "table":
        return not PARTITION.fullmatch(name or "")
    return True


def configure(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=Base.metadata,
        include_schemas=True,
        include_name=include_name,
        compare_type=True,
        compare_server_default=True,
    )


def run_migrations_offline() -> None:
    context.configure(
        url=database_url(),
        target_metadata=Base.metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # Tests (pytest-alembic) hand over their own engine or connection.
    given = config.attributes.get("connection")
    if isinstance(given, Connection):
        configure(given)
        with context.begin_transaction():
            context.run_migrations()
        return
    engine = given or create_engine(database_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        configure(connection)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
