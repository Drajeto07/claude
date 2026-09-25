"""Logs as the server writes them (корекции.docx §51): one line per event, with
the request it belongs to (request_id), as JSON for a log collector
(LOG_FORMAT=json) or as readable text. Log calls pass ids, sizes, counts and
durations as fields (`extra=`), never a document's content (§81): documents
can be sensitive."""

import json
import logging
import sys
from datetime import datetime, timezone

from pydantic import ValidationError

from app.api.errors import current_request_id

# LogRecord's own attributes; anything else on a record came in through extra=.
_RECORD_FIELDS = set(logging.makeLogRecord({}).__dict__) | {"message", "asctime", "request_id", "taskName"}


def _fields(record: logging.LogRecord) -> dict:
    return {key: value for key, value in record.__dict__.items() if key not in _RECORD_FIELDS and not key.startswith("_")}


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if getattr(record, "request_id", None) is None:
            record.request_id = current_request_id.get()
        return True


def _stamp_request_ids() -> None:
    """Every record gets the request id when it is made, whichever handlers
    write it (another library may replace the root handlers, as Alembic's
    logging config does)."""
    make_record = logging.getLogRecordFactory()
    if getattr(make_record, "_stamps_request_id", False):
        return

    def factory(*args, **kwargs) -> logging.LogRecord:
        record = make_record(*args, **kwargs)
        record.request_id = current_request_id.get()
        return record

    factory._stamps_request_id = True  # type: ignore[attr-defined]
    logging.setLogRecordFactory(factory)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "time": datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if getattr(record, "request_id", None):
            entry["request_id"] = record.request_id
        entry.update(_fields(record))
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str, ensure_ascii=False)


class TextFormatter(logging.Formatter):
    """12:00:01 INFO app.audit [4f0c1a2b] document.deleted document_id=… user_id=…"""

    def format(self, record: logging.LogRecord) -> str:
        time = datetime.fromtimestamp(record.created).strftime("%H:%M:%S")
        request = f" [{record.request_id[:8]}]" if getattr(record, "request_id", None) else ""
        fields = " ".join(f"{key}={value}" for key, value in _fields(record).items())
        line = f"{time} {record.levelname} {record.name}{request} {record.getMessage()}" + (f" {fields}" if fields else "")
        if record.exc_info:
            line += "\n" + self.formatException(record.exc_info)
        return line


_HANDLER_MARK = "_smartdoc_handler"


def configure_logging(level: str = "INFO", log_format: str = "text") -> None:
    """The app's loggers ("app.*") at `level`, written through one handler on
    the root logger (so other libraries' warnings come out the same way).
    Safe to call again: the handler is replaced, never doubled."""
    _stamp_request_ids()
    handler = logging.StreamHandler(sys.stderr)
    setattr(handler, _HANDLER_MARK, True)
    handler.addFilter(RequestIdFilter())
    handler.setFormatter(JsonFormatter() if log_format == "json" else TextFormatter())
    root = logging.getLogger()
    root.handlers = [existing for existing in root.handlers if not getattr(existing, _HANDLER_MARK, False)] + [handler]
    logging.getLogger("app").setLevel(level.upper())


def describe_error(exc: BaseException) -> str:
    """An exception for a log line, without the data it may quote: a validation
    error says where it failed, not the values (an AI's answer quotes the
    document), and any other message is cut short."""
    if isinstance(exc, ValidationError):
        places = ", ".join(".".join(str(part) for part in error["loc"]) or "(root)" for error in exc.errors()[:5])
        return f"ValidationError ({exc.error_count()} error(s) at {places})"
    message = str(exc)
    return f"{type(exc).__name__}: {message[:200]}" if message else type(exc).__name__
