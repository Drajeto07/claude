"""Security-relevant events (корекции.docx §33 "structured audit logging"):
one structured line each on the "app.audit" logger, with the request id --
who did what to which thing, and from where. Never the content involved, a
password, or an email address in plain text (hashed when it identifies a
failed sign-in)."""

import logging

from app.observability import SECURITY_EVENTS

_logger = logging.getLogger("app.audit")
# Events counted as refusals or failures (OBS-003): a rate or plan limit, a refused file, a failed
# sign-in ... Their reason label is the scope or entitlement -- code names, never free text (a
# refused file's reason is the error's message, so it isn't one).
_REFUSAL_SUFFIXES = ("_failed", "_refused", ".refused")


def audit(event: str, **fields: object) -> None:
    """e.g. audit("document.deleted", document_id=..., user_id=...). Field names
    must not be LogRecord attributes (name, filename, module, ...)."""
    _logger.info(event, extra={"event": event, **{key: value for key, value in fields.items() if value is not None}})
    if event.endswith(_REFUSAL_SUFFIXES):
        SECURITY_EVENTS.inc(event=event, reason=fields.get("scope") or fields.get("entitlement") or "-")
