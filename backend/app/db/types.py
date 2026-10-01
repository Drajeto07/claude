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


_PIECE = 200
_SCAN = 1 << 20


def dumps_in_pieces(data: Any, **options: Any) -> str:
    """json.dumps(data, **options), the same text, made a few hundred list items at a
    time instead of in one call (PERF-008). One json.dumps of a big document is a
    single C call that keeps the interpreter's lock for its whole length -- a tenth of
    a second at ten thousand blocks -- so the event loop, which needs the lock too,
    can't run beside a save's thread; between small calls it can. Only the top level
    and its long lists are cut, the way a document is (its `elements`); anything else
    is dumped whole. `options`: ensure_ascii and separators."""
    if not isinstance(data, dict) or not set(options) <= {"ensure_ascii", "separators"} or not all(type(name) is str for name in data):
        return json.dumps(data, **options)
    item, key = options.get("separators") or (", ", ": ")
    members = []
    for name, value in data.items():
        if isinstance(value, list) and len(value) > _PIECE:
            pieces = (json.dumps(value[start : start + _PIECE], **options)[1:-1] for start in range(0, len(value), _PIECE))
            text = "[" + item.join(pieces) + "]"
        else:
            text = json.dumps(value, **options)
        members.append(json.dumps(name, **options) + key + text)
    return "{" + item.join(members) + "}"


class EncodedJSON(dict):
    """A JSON object with its `dump_json` text already made (PERF-008): a save works the
    text out in a thread, so the flush that writes the row doesn't spend the event
    loop's time on a document-sized json.dumps. `dump_json` hands the text on as it is.
    The object itself is still the dict, for whoever reads it; it is never changed
    after the text was made (changing the top level raises), or text and dict would
    differ."""

    __slots__ = ("text",)

    def __init__(self, data: dict) -> None:
        super().__init__(data)
        self.text = dump_json(data, in_pieces=True)

    def _refuse(self, *args: Any, **kwargs: Any) -> Any:
        raise TypeError("An EncodedJSON is not changed: its text was made from what it held.")

    __setitem__ = __delitem__ = __ior__ = clear = pop = popitem = setdefault = update = _refuse


def _has_surrogate(text: str, in_pieces: bool) -> bool:
    if not in_pieces:
        return _SURROGATE.search(text) is not None
    # A regex scan of ten megabytes is one call too: a megabyte at a time.
    return any(_SURROGATE.search(text, start, start + _SCAN) for start in range(0, len(text), _SCAN))


def dump_json(value: Any, *, in_pieces: bool = False) -> str:
    """The engines' json_serializer (PERF-006): what SQLAlchemy does by default
    (json.dumps), but with the letters as they are instead of \\uXXXX escapes --
    Cyrillic takes two bytes a letter, not six. Rows written with escapes read the
    same way (json.loads takes both). `in_pieces`: the same text, made by dumps_in_pieces."""
    if isinstance(value, EncodedJSON):
        return value.text
    dump = dumps_in_pieces if in_pieces else json.dumps
    text = dump(value, ensure_ascii=False)
    if _has_surrogate(text, in_pieces):
        # An unpaired surrogate can't be written as UTF-8; its escape can.
        return dump(value)
    return text
