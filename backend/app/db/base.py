from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

# Explicit constraint-naming convention -- without it, SQLite/Postgres each
# pick their own auto-generated constraint names, so two Alembic autogenerate
# runs on different backends (or even the same backend twice) can produce
# spurious diffs. Recommended verbatim by the Alembic docs.
_NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=_NAMING_CONVENTION)
