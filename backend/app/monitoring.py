"""Error reporting to Sentry (RELEASE): unhandled errors and error log lines of the API, so a failure in
production is seen without waiting for someone to report it. Only with SENTRY_DSN set; off in
development and in the tests.

What a report may carry is kept to what helps find a bug and never what a user wrote or who they
are: no request bodies (documents, passwords), no cookies or Authorization/session headers, no
query strings, no local variables in stack frames, no user identity or IP address; the request id
is kept, to find the matching log lines. Anything else Sentry would attach is dropped by `scrub`.
"""

from __future__ import annotations

import os
from typing import Any

from app.config import Settings

# Request headers worth keeping: they say how the request came, never who sent it.
_KEPT_HEADERS = {"content-type", "content-length", "user-agent", "x-request-id", "accept"}


def scrub(event: dict[str, Any], _hint: dict[str, Any] | None = None) -> dict[str, Any]:
    """An event with nothing of a document or a person left in it."""
    request = event.get("request")
    if isinstance(request, dict):
        headers = request.get("headers") or {}
        if isinstance(headers, dict):
            request["headers"] = {key: value for key, value in headers.items() if key.lower() in _KEPT_HEADERS}
        for field in ("data", "cookies", "query_string", "env"):
            request.pop(field, None)
        url = request.get("url")
        if isinstance(url, str):
            request["url"] = url.split("?", 1)[0]
    event.pop("user", None)
    for exception in (event.get("exception") or {}).get("values") or []:
        for frame in (exception.get("stacktrace") or {}).get("frames") or []:
            frame.pop("vars", None)
    for breadcrumb in (event.get("breadcrumbs") or {}).get("values") or []:
        breadcrumb.pop("data", None)
    return event


def init_monitoring(settings: Settings) -> bool:
    """Starts error reporting when SENTRY_DSN is set; whether it did."""
    dsn = settings.sentry_dsn.strip()
    if not dsn:
        return False
    import sentry_sdk

    sentry_sdk.init(
        dsn=dsn,
        environment=settings.sentry_environment or os.environ.get("VERCEL_ENV") or "production",
        release=os.environ.get("VERCEL_GIT_COMMIT_SHA") or None,
        send_default_pii=False,
        max_request_body_size="never",
        include_local_variables=False,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        before_send=scrub,
        before_send_transaction=scrub,
    )
    return True
