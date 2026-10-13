"""Error reporting (RELEASE, app/monitoring.py): off without SENTRY_DSN; with it, an unhandled error
reaches Sentry with nothing of a document or a person in it -- no body, cookies, session or
Authorization headers, query string, local variables or user."""

import sentry_sdk
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import monitoring
from app.config import Settings

SECRET = "Confidential merger text 9917"


def _settings(**values) -> Settings:
    return Settings(_env_file=None, **values)


def test_off_without_a_dsn():
    assert monitoring.init_monitoring(_settings()) is False


def test_an_error_is_reported_with_nothing_of_the_document_or_the_person(monkeypatch):
    sent: list[dict] = []
    real_init = sentry_sdk.init

    def capturing_init(**options):
        # The real SDK, its events kept here instead of sent.
        return real_init(**options, transport=lambda envelope_or_event: sent.append(envelope_or_event))

    monkeypatch.setattr(sentry_sdk, "init", capturing_init)
    assert monitoring.init_monitoring(_settings(sentry_dsn="https://public@o1.ingest.de.sentry.io/1")) is True

    app = FastAPI()

    @app.post("/api/v1/boom")
    async def boom(payload: dict) -> dict:
        document_text = payload["text"]  # a local variable holding the document
        raise RuntimeError("formatting failed")

    client = TestClient(app, raise_server_exceptions=False)
    response = client.post(
        f"/api/v1/boom?q={SECRET}",
        json={"text": SECRET},
        headers={"Cookie": f"smartdoc_session={SECRET}", "Authorization": f"Bearer {SECRET}", "X-Request-ID": "req-42"},
    )
    sentry_sdk.flush()

    assert response.status_code == 500
    assert sent, "the error was reported"
    report = str([envelope if isinstance(envelope, dict) else envelope.serialize() for envelope in sent])
    assert "formatting failed" in report and "req-42" in report  # the bug and the request id, to find its log lines
    assert SECRET not in report  # not in the body, the cookie, the Authorization header, the query or a local variable
    sentry_sdk.init(dsn=None)  # off again for the other tests


def test_scrub_keeps_how_a_request_came_and_drops_who_and_what():
    event = {
        "request": {
            "url": f"https://smartdoc.vercel.app/api/v1/documents?token={SECRET}",
            "headers": {"Content-Type": "application/json", "Cookie": SECRET, "Authorization": SECRET, "X-Request-ID": "r1"},
            "data": {"text": SECRET},
            "cookies": {"smartdoc_session": SECRET},
            "query_string": f"token={SECRET}",
        },
        "user": {"email": "someone@example.com", "ip_address": "203.0.113.9"},
        "exception": {"values": [{"stacktrace": {"frames": [{"function": "f", "vars": {"text": SECRET}}]}}]},
        "breadcrumbs": {"values": [{"message": "query", "data": {"params": SECRET}}]},
    }

    scrubbed = monitoring.scrub(event)

    assert scrubbed["request"] == {"url": "https://smartdoc.vercel.app/api/v1/documents", "headers": {"Content-Type": "application/json", "X-Request-ID": "r1"}}
    assert "user" not in scrubbed and SECRET not in str(scrubbed)
