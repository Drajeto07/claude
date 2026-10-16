# Operations: logs, ids and metrics

What the backend tells whoever runs it, and what it never does: nothing of a document -- its
text, its title, a file name, an address someone typed -- goes into a log line or a metric.

## Ids on every log line (OBS-002)

- **request_id**: the request a line belongs to (`X-Request-ID`, sent back on every response;
  a client may send its own). Set by the request middleware (`app/main.py`).
- **operation_id**: one thing a user asked for -- the request that started it and every job it
  queued. A job stores the operation that queued it (`payload.operationId`), so a worker's lines
  (the arq worker has no request of its own) lead back to that request. Outside a job it is the
  request id.
- **job_id**: the job a worker is running, on every line it logs (`app/jobs/runner.py`); a line
  that names a job itself keeps its own.

They come from context variables (`app/observability.py`, `ContextFilter`) and are written as
fields: `LOG_FORMAT=json` gives one JSON object per line with `request_id`, `operation_id` and
`job_id`; the text format shows the request id in brackets and the others as `key=value`.

## Metrics (OBS-001)

`GET /api/metrics` serves the process' metrics in Prometheus' text format -- only when
`METRICS_TOKEN` is set, to `Authorization: Bearer <METRICS_TOKEN>` (404 when unset, 401 for a
wrong token). Each process keeps its own (each API worker, the job worker); scrape them all.

| Metric | Labels | What |
| --- | --- | --- |
| `smartdoc_http_requests_total` | method, route, status (`2xx`...) | API requests; failure rate = 5xx (and 4xx) over all |
| `smartdoc_http_request_duration_seconds` | method, route | latency histogram |
| `smartdoc_jobs_total` | type, outcome | jobs finished: `succeeded`, `cancelled`, `retry`, `interrupted`, `failed:<how>` |
| `smartdoc_job_duration_seconds` | type | how long jobs ran |
| `smartdoc_ai_calls_total` | outcome | AI calls: `ok`, `refused` (the allowance), `timeout`, or the error's type |
| `smartdoc_ai_call_duration_seconds` | | AI latency |
| `smartdoc_exports_total` | format, path (`job`/`direct`), outcome | exports made and failed |
| `smartdoc_security_events_total` | event, reason (scope or entitlement, else `-`) | refused and failed audit events: rate and plan limits, refused files, failed sign-ins, cross-site writes, a wrong admin token |

`route` is the route's template (`/api/v1/documents/{document_id}`), never the path with its ids;
a path no route matches is `unmatched`. Label values keep to a short safe alphabet.

Worth alerting on: a rising 5xx share, p95 latency of the document routes, `failed:*` and
`failed:dead_letter` jobs, AI calls other than `ok`, export failures, a jump in `smartdoc_security_events_total`.

## Operations data (OBS-003)

`GET /api/v1/admin/operations?hours=24` answers what the per-process metrics can't, across every
workspace, from the database -- only when `ADMIN_TOKEN` is set, to `Authorization: Bearer <ADMIN_TOKEN>`
(404 when unset, 401 for a wrong token, which is counted as `admin.token_refused`). There is no admin
role: a signed-in user gets nothing from it. `hours` is the window, 1 to 744 (31 days).

| Section | What |
| --- | --- |
| `jobs` | jobs created in the window by type and status; failed ones by type and failure code; dead letters (all time); ids of stuck jobs (running past their deadline); how long the oldest pending job has waited; the 20 latest failures (id, workspace, type, code, attempts, when) |
| `processing`, `exports` | finished and failed in the window: imports, formatting, reference reading, translation; export jobs |
| `usage_spikes` | a workspace's metric (exports, AI operations ...) at least 3x the window before and at least 20 |
| `storage` | documents, their JSON, kept versions and assets in bytes; the 10 largest workspaces |
| `abuse` | accounts made in the window, the 10 workspaces that queued the most jobs, and this process' refusals (`smartdoc_security_events_total`) |
| `this_process` | this process' job, AI-call and export counters since it started |

Only counts, ids, types, codes and times: never a title, a file name, an address, a job's error
message or anything else from a document or an account. The `abuse.refusals` and `this_process`
counts are the answering API process' own; the metrics scrape has every process'.
