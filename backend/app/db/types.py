import json
import re
from typing import Any

from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB

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
