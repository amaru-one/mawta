"""The declarative base every table class inherits from.

The classes only describe the schema (for Alembic and for typed SQLAlchemy Core queries); the
application never uses an ORM Session.
"""

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

# Names for constraints and indexes declared without one, matching what Postgres itself would
# choose. Every object already in the schema has an explicit name; this only shapes new ones.
NAMING_CONVENTION = {
    "pk": "%(table_name)s_pkey",
    "uq": "%(table_name)s_%(column_0_N_name)s_key",
    "fk": "%(table_name)s_%(column_0_N_name)s_fkey",
    "ix": "%(table_name)s_%(column_0_N_name)s_idx",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
