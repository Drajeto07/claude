"""Operations data without anything of the documents (brief §51/§98, tracker OBS-001/002).

Ids (OBS-002): every log line carries the request it belongs to (request_id, set by the
request middleware), the operation -- one thing a user asked for: the request that started it
and any job it queued, so a worker's lines lead back to that request -- and the job a worker is
running. `ContextFilter` puts operation_id and job_id on each record; a record that names a job
itself (extra={"job_id": ...}) keeps its own.

Metrics (OBS-001): counters and histograms kept in this process and written in Prometheus' text
format at GET /api/metrics (only with METRICS_TOKEN set, and its bearer token). Labels are route
templates, types, formats and outcomes -- never a path with ids in it, a file name or any text --
so nothing of a document can reach the metrics. Each process (an API worker, the job worker)
keeps its own, as Prometheus scrapes them."""

import logging
import re
import threading
from bisect import bisect_left
from contextvars import ContextVar

current_operation_id: ContextVar[str | None] = ContextVar("current_operation_id", default=None)
current_job_id: ContextVar[str | None] = ContextVar("current_job_id", default=None)


class ContextFilter(logging.Filter):
    """Puts the operation and job a record belongs to on it, unless it names them itself."""

    def filter(self, record: logging.LogRecord) -> bool:
        for name, var in (("operation_id", current_operation_id), ("job_id", current_job_id)):
            if getattr(record, name, None) is None and (value := var.get()) is not None:
                setattr(record, name, value)
        return True


# --- metrics ---------------------------------------------------------------------------------------

_LABEL_VALUE = re.compile(r"[^A-Za-z0-9_./{}:\-]")
_LATENCY_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120, 300)


def _label(value: object) -> str:
    """A label value kept to a safe, short alphabet: route templates and enum-like values pass
    unchanged, anything else can't smuggle text in."""
    return _LABEL_VALUE.sub("_", str(value))[:100]


class _Metric:
    def __init__(self, name: str, help: str, labels: tuple[str, ...]) -> None:
        self.name, self.help, self.labels = name, help, labels
        self._lock = threading.Lock()

    def _key(self, values: dict[str, object]) -> tuple[str, ...]:
        if set(values) != set(self.labels):
            raise ValueError(f"{self.name} takes the labels {self.labels}")
        return tuple(_label(values[name]) for name in self.labels)

    def _labels(self, key: tuple[str, ...], extra: str = "") -> str:
        parts = [f'{name}="{value}"' for name, value in zip(self.labels, key, strict=True)]
        if extra:
            parts.append(extra)
        return "{" + ",".join(parts) + "}" if parts else ""


class Counter(_Metric):
    def __init__(self, name: str, help: str, labels: tuple[str, ...] = ()) -> None:
        super().__init__(name, help, labels)
        self._values: dict[tuple[str, ...], float] = {}

    def inc(self, amount: float = 1, **labels: object) -> None:
        key = self._key(labels)
        with self._lock:
            self._values[key] = self._values.get(key, 0) + amount

    def value(self, **labels: object) -> float:
        return self._values.get(self._key(labels), 0)

    def render(self) -> list[str]:
        lines = [f"# HELP {self.name} {self.help}", f"# TYPE {self.name} counter"]
        with self._lock:
            lines += [f"{self.name}{self._labels(key)} {value:g}" for key, value in sorted(self._values.items())]
        return lines


class Histogram(_Metric):
    def __init__(self, name: str, help: str, labels: tuple[str, ...] = (), buckets: tuple[float, ...] = _LATENCY_BUCKETS) -> None:
        super().__init__(name, help, labels)
        self.buckets = buckets
        self._values: dict[tuple[str, ...], tuple[list[int], list[float]]] = {}  # counts per bucket (+Inf last), [sum, count]

    def observe(self, value: float, **labels: object) -> None:
        key = self._key(labels)
        with self._lock:
            counts, total = self._values.setdefault(key, ([0] * (len(self.buckets) + 1), [0.0, 0]))
            counts[bisect_left(self.buckets, value)] += 1
            total[0] += value
            total[1] += 1

    def count(self, **labels: object) -> int:
        found = self._values.get(self._key(labels))
        return int(found[1][1]) if found else 0

    def render(self) -> list[str]:
        lines = [f"# HELP {self.name} {self.help}", f"# TYPE {self.name} histogram"]
        with self._lock:
            for key, (counts, (total, count)) in sorted(self._values.items()):
                running = 0
                for bound, bucket in zip([*self.buckets, float("inf")], counts, strict=True):
                    running += bucket
                    le = "+Inf" if bound == float("inf") else f"{bound:g}"
                    bucket_labels = self._labels(key, 'le="' + le + '"')
                    lines.append(f"{self.name}_bucket{bucket_labels} {running}")
                lines.append(f"{self.name}_sum{self._labels(key)} {total:g}")
                lines.append(f"{self.name}_count{self._labels(key)} {int(count)}")
        return lines


HTTP_REQUESTS = Counter("smartdoc_http_requests_total", "API requests by route template, method and status class.", ("method", "route", "status"))
HTTP_LATENCY = Histogram("smartdoc_http_request_duration_seconds", "API request latency by route template and method.", ("method", "route"))
JOBS = Counter("smartdoc_jobs_total", "Jobs finished, by type and outcome.", ("type", "outcome"))
JOB_DURATION = Histogram("smartdoc_job_duration_seconds", "How long a job ran, by type.", ("type",))
AI_CALLS = Counter("smartdoc_ai_calls_total", "AI calls by outcome (ok, refused by the allowance, or the error's type).", ("outcome",))
AI_LATENCY = Histogram("smartdoc_ai_call_duration_seconds", "AI call latency.")
EXPORTS = Counter("smartdoc_exports_total", "Exports by format, path (job or direct) and outcome.", ("format", "path", "outcome"))
METRICS = (HTTP_REQUESTS, HTTP_LATENCY, JOBS, JOB_DURATION, AI_CALLS, AI_LATENCY, EXPORTS)


def route_template(scope: dict) -> str:
    """The matched route as a template ("/api/v1/documents/{document_id}/export/docx"): each path
    segment that is a path parameter's value put back as its name. A path no route matched is
    "unmatched" -- never itself, or anyone could fill the metrics with made-up paths."""
    if scope.get("route") is None:
        return "unmatched"
    names = {str(value): name for name, value in (scope.get("path_params") or {}).items()}
    return "/".join("{" + names[segment] + "}" if segment in names else segment for segment in str(scope.get("path", "")).split("/"))


def status_class(status: int) -> str:
    return f"{status // 100}xx"


def render() -> str:
    return "\n".join(line for metric in METRICS for line in metric.render()) + "\n"
