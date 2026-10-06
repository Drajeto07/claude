import json
import re
from typing import Any

from sqlalchemy import JSON, Integer
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql.functions import FunctionElement

# JSONB on Postgres (indexable, binary-stored), plain JSON on every other
# dialect -- lets the same model run against SQLite in tests and Postgres in
# production without two separate column definitions.
JSONVariant = JSON().with_variant(JSONB(), "postgresql")

_SURROGATE = re.compile("[\ud800-\udfff]")


def dump_json(value: Any) -> str:
    """The engines' json_serializer (PERF-006): what SQLAlchemy does by default
    (json.dumps), but with the letters as they are instead of \\uXXXX escapes --
    Cyrillic takes two bytes a letter, not six. Rows written with escapes read the
    same way (json.loads takes both)."""
    text = json.dumps(value, ensure_ascii=False)
    if _SURROGATE.search(text):
        # An unpaired surrogate can't be written as UTF-8; its escape can.
        return json.dumps(value)
    return text


class octet_length(FunctionElement):  # noqa: N801 -- named as the SQL function it is
    """The bytes a text or binary value takes, the same on both databases (PLAN-005):
    PostgreSQL's octet_length; on SQLite length() of the value as a BLOB (SQLite's
    own octet_length only came with 3.43). length() of text counts characters on
    both, so a Cyrillic letter would count once instead of twice."""

    type = Integer()
    inherit_cache = True


@compiles(octet_length)
def _octet_length(element, compiler, **kw):
    return f"octet_length({compiler.process(element.clauses, **kw)})"


@compiles(octet_length, "sqlite")
def _octet_length_sqlite(element, compiler, **kw):
    return f"length(CAST({compiler.process(element.clauses, **kw)} AS BLOB))"
