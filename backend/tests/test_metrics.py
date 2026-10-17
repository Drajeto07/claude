"""Operations data (tracker OBS-001/002): every log line names its request, its operation and its
job -- a worker's lines lead back to the request that queued the job -- and the process' metrics
(latency, failures, jobs, AI calls, exports) are served to a token holder, with nothing of any
document in them."""

import json
import logging

import pytest
from fastapi.testclient import TestClient

from app import main, observability
from app.ai.base import AIStructuredOutputError
from app.ai.factory import get_ai_provider
from app.logging_setup import JsonFormatter, RequestIdFilter
from app.observability import ContextFilter, Counter, Histogram, current_job_id, current_operation_id
from tests.fakes import FakeAIProvider

client = TestClient(main.app, base_url="https://testserver")
SECRET_TEXT = "Quarterly figures nobody may read 7731"


class Capture(logging.Handler):
    """Records as the app's handler sees them: with its filters."""

    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []
        self.addFilter(RequestIdFilter())
        self.addFilter(ContextFilter())

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture
def captured():
    handler = Capture()
    root = logging.getLogger()
    root.addHandler(handler)
    previous = logging.getLogger("app").level
    logging.getLogger("app").setLevel(logging.INFO)
    yield handler.records
    root.removeHandler(handler)
    logging.getLogger("app").setLevel(previous)


def test_log_lines_carry_the_operation_and_the_job_and_a_line_naming_its_job_keeps_it():
    record = logging.makeLogRecord({"name": "app.jobs.runner", "levelno": logging.INFO, "levelname": "INFO", "msg": "job.step"})
    named = logging.makeLogRecord({"name": "app.jobs.runner", "levelno": logging.INFO, "levelname": "INFO", "msg": "x", "job_id": "other-job"})
    operation, job = current_operation_id.set("op-1"), current_job_id.set("job-1")
    try:
        ContextFilter().filter(record)
        ContextFilter().filter(named)
    finally:
        current_job_id.reset(job)
        current_operation_id.reset(operation)
    line = json.loads(JsonFormatter().format(record))
    assert (line["operation_id"], line["job_id"]) == ("op-1", "job-1")
    assert (named.job_id, named.operation_id) == ("other-job", "op-1")


@pytest.fixture
def signed_in(api_db):
    client.cookies.clear()
    main.app.dependency_overrides[get_ai_provider] = lambda: FakeAIProvider([AIStructuredOutputError("no AI in tests")] * 9)
    assert client.post("/api/v1/auth/register", json={"email": "metrics@example.com", "password": "long enough password"}).status_code == 201
    yield
    client.cookies.clear()
    main.app.dependency_overrides.pop(get_ai_provider, None)


def test_a_jobs_lines_lead_back_to_the_request_that_queued_it(signed_in, captured):
    started = client.post("/api/v1/jobs/import-text", json={"text": f"# Title\n\n{SECRET_TEXT}", "title": "Report"})
    request_id = started.headers["X-Request-ID"]
    finished = [record for record in captured if record.getMessage() == "job.finished"]
    assert finished and finished[-1].job_id == started.json()["id"]
    assert finished[-1].operation_id == request_id
    created = [record for record in captured if record.getMessage() == "document.created"]
    assert created and created[-1].operation_id == request_id and created[-1].job_id == started.json()["id"]


def _scrape(token: str | None = "scrape-secret") -> "object":
    return client.get("/api/metrics", headers={"Authorization": f"Bearer {token}"} if token else {})


def test_metrics_are_only_for_the_token_holder(monkeypatch):
    monkeypatch.setattr(main.settings, "metrics_token", None)
    assert _scrape().status_code == 404  # off unless configured
    monkeypatch.setattr(main.settings, "metrics_token", "scrape-secret")
    assert _scrape(None).status_code == 401 and _scrape("wrong").status_code == 401
    assert _scrape().status_code == 200


def test_latency_failures_jobs_ai_and_exports_are_measured_without_any_content(signed_in, monkeypatch):
    monkeypatch.setattr(main.settings, "metrics_token", "scrape-secret")
    route = "/api/v1/documents/{document_id}"
    before = {
        "get": observability.HTTP_REQUESTS.value(method="GET", route=route, status="2xx"),
        "missing": observability.HTTP_REQUESTS.value(method="GET", route=route, status="4xx"),
        "jobs": observability.JOBS.value(type="import_text", outcome="succeeded"),
        "ai": sum(observability.AI_CALLS.value(outcome=outcome) for outcome in ("AIStructuredOutputError", "ok")),
        "exports": observability.EXPORTS.value(format="docx", path="direct", outcome="ok"),
        "unmatched": observability.HTTP_REQUESTS.value(method="GET", route="unmatched", status="4xx"),
    }

    job = client.post("/api/v1/jobs/import-text", json={"text": f"# Title\n\n{SECRET_TEXT}", "title": "Secret title 4410"}).json()
    document_id = job["result"]["documentId"]
    assert client.get(f"/api/v1/documents/{document_id}").status_code == 200
    assert client.get("/api/v1/documents/no-such-document").status_code == 404
    assert client.get("/api/v1/made-up-path-5521").status_code == 404
    client.post(f"/api/v1/documents/{document_id}/format", data={"instructionsText": "make it bold"})
    assert client.get(f"/api/v1/documents/{document_id}/export/docx").status_code == 200

    assert observability.HTTP_REQUESTS.value(method="GET", route=route, status="2xx") == before["get"] + 1
    assert observability.HTTP_REQUESTS.value(method="GET", route=route, status="4xx") == before["missing"] + 1
    assert observability.HTTP_LATENCY.count(method="GET", route=route) >= 2
    assert observability.HTTP_REQUESTS.value(method="GET", route="unmatched", status="4xx") == before["unmatched"] + 1
    assert observability.JOBS.value(type="import_text", outcome="succeeded") == before["jobs"] + 1
    assert sum(observability.AI_CALLS.value(outcome=outcome) for outcome in ("AIStructuredOutputError", "ok")) > before["ai"]
    assert observability.EXPORTS.value(format="docx", path="direct", outcome="ok") == before["exports"] + 1

    body = _scrape().text
    assert 'smartdoc_http_requests_total{method="GET",route="/api/v1/documents/{document_id}",status="2xx"}' in body
    assert "smartdoc_job_duration_seconds_bucket" in body and "smartdoc_ai_calls_total" in body
    for leaked in (document_id, SECRET_TEXT, "Secret title 4410", "metrics@example.com", "no-such-document", "made-up-path-5521"):
        assert leaked not in body


def test_histograms_count_cumulatively_and_labels_keep_to_a_safe_alphabet():
    histogram = Histogram("t_seconds", "test", ("kind",), buckets=(0.1, 1))
    for value in (0.05, 0.5, 0.5, 3):
        histogram.observe(value, kind="a")
    lines = histogram.render()
    assert 't_seconds_bucket{kind="a",le="0.1"} 1' in lines and 't_seconds_bucket{kind="a",le="1"} 3' in lines
    assert 't_seconds_bucket{kind="a",le="+Inf"} 4' in lines and 't_seconds_count{kind="a"} 4' in lines
    counter = Counter("t_total", "test", ("outcome",))
    counter.inc(outcome='bad"}\nvalue with spaces')
    assert counter.render()[-1] == 't_total{outcome="bad_}_value_with_spaces"} 1'  # no quote, no line break
    with pytest.raises(ValueError):
        counter.inc(other="x")
