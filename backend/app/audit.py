"""Security-relevant events (корекции.docx §33 "structured audit logging"):
one structured line each on the "app.audit" logger, with the request id --
who did what to which thing, and from where. Never the content involved, a
password, or an email address in plain text (hashed when it identifies a
failed sign-in)."""

import logging

_logger = logging.getLogger("app.audit")


def audit(event: str, **fields: object) -> None:
    """e.g. audit("document.deleted", document_id=..., user_id=...). Field names
    must not be LogRecord attributes (name, filename, module, ...)."""
    _logger.info(event, extra={"event": event, **{key: value for key, value in fields.items() if value is not None}})
