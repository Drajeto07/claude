# Background jobs

Heavy work (imports, AI formatting, exports, reading a reference document) runs as a job: the API answers `202`
with the job, the client polls `GET /api/v1/jobs/{id}` for its real stage and progress. Every job is one
`processing_jobs` row (`backend/app/db/models/jobs.py`). Where it runs (`JOB_BACKEND`): in the API process
(`background`), in an arq worker over Redis (`arq`, production), or inside the request (`eager`, tests). All three
run the same `JobRunner` (`app/jobs/runner.py`). Job safety (JOB-001) is the part below.

## Statuses

`pending` → `running` → `succeeded` | `failed` | `cancelled`. A job waiting for a retry is `pending` with stage
`retrying`. `JobOut` also carries `retryCount` and `deadLetter`.

## Idempotency keys

Every job-creating POST (`import-text`, `import-file`, `format`, `export`, `extract-reference`) takes an optional
`Idempotency-Key` header. It exists so a client that retries after a timeout or a dropped connection never gets a
second job (a second document, a second export).

- **Scope: per user.** One key is one job *for that user*; two users may use the same key.
- **Format:** 1 to 128 characters from `A-Z a-z 0-9 . _ : -` (a UUID fits). Anything else is `422` with code
  `invalid_idempotency_key`, through the error envelope, and no job is made.
- **Same key, same request:** the job already made is returned (`202`, same body), nothing runs again. "Same
  request" is a hash of the job type, document, options and the uploaded file's bytes
  (`request_fingerprint`).
- **Same key, different request:** `422`, code `idempotency_key_reused`. It is never answered with the other
  request's job. (422 rather than 409: nothing is wrong with the state of the job, the request is the problem.)
- **The same key on a failed job** returns that failed job; it is not run again. A client that wants another try
  uses a new key.
- **A repeat is not a new job**, so the plan checks (documents allowed, file size, AI operations, export format)
  are asked only for the first request; a repeat is answered with its job whatever the plan says now.
- **Memory:** a key lives as long as its job row: `JOB_RETENTION_DAYS` (7 by default), then the sweep removes the
  job and the key is free. A dead letter keeps its key.
- **Enforced in the database:** a unique index on `(created_by, idempotency_key)`
  (`uq_processing_jobs_created_by_idempotency_key`). Two requests that arrive together both pass the lookup, the
  index lets one insert, and the other catches the `IntegrityError` and answers with the winner's job. Rows
  without a key (NULL) never collide.

## Retries, with backoff, for transient errors only

A job is started at most `JOB_MAX_ATTEMPTS` times (3). After a failed attempt that is transient it goes back to
`pending` (stage `retrying`, `retry_count + 1`) and runs again after `JOB_RETRY_BASE_SECONDS * 2^retries`
(5 s, 10 s, 20 s ..., at most `JOB_RETRY_MAX_SECONDS`, 300 s). The runner returns the wait; the queue does the
waiting: an `asyncio.sleep` in process, `arq.Retry(defer=...)` in the worker. A retry keeps the job's upload and
text input; they go when the job is finished. A delete that failed then (a storage hiccup) is tried again by the
hourly `sweep_job_files` for as long as the job records the upload, dead letters included (STOR-001; the table of
stored files is in `docs/security/README.md`).

What counts as **transient** (`app/jobs/policy.py::TRANSIENT_ERRORS`): `ConnectionError`, `TimeoutError` raised by
the work (not the job's own deadline), database `OperationalError` / `InterfaceError`, the Anthropic client's
connection and timeout errors, rate limits and server errors, and botocore connection and timeout errors.

**Never retried:** the user's file or text and anything else that would fail the same way again: `DocxParseError`,
`PdfParseError`, `UnsafeFileError`, `UnsupportedFileTypeError`, `JobError`, `PlanLimitError`, and every
exception not on the list above (a bug is not made better by running it three times). `PERMANENT_ERRORS` wins if
an exception is both.

## A timeout per job type

`JOB_TIMEOUTS` (seconds): import of pasted text 300, import of a file 600, formatting 600, export 300, reference
document 300. A job past its time is stopped and fails with "This import took longer than 5 minutes, so it was
stopped. Please try again; if it keeps happening, try a smaller document." It is **not** retried: the same input
would take as long again. `failure_reason` is `timeout`. A thread already started (an export's rendering) can't be
stopped from outside; its result is no longer waited for.

## Cancellation

`POST /api/v1/jobs/{job_id}/cancel`, the job's owner only; another user's job and a missing one both answer the
same `404` as the other job routes. Idempotent:

- `pending`: becomes `cancelled`; it never runs; its upload and text input go at once.
- `running`: becomes `cancelled`; the job notices at its next check (`JobContext.report`, every stage boundary,
  where progress is written with one statement that refuses a cancelled job) and stops without writing a result.
  The steps between two checks (one AI call, one rendering) finish first; their result is dropped. If the work
  was already past its last check, the result is dropped when it would be written, and an export's file is
  removed. A document an import had already created by then stays in the user's list.
- `cancelled`, `succeeded`, `failed`: **not an error.** `200` with the job as it is. A late or repeated cancel is
  harmless, and the client reads `status` to see whether it took. (The alternative, `409` for a finished job,
  would turn a harmless race into an error the client has to special-case.)

AI calls a cancelled job already made are still counted in usage.

## Stuck jobs

A job still `running` after its type's timeout **plus 60 seconds** (`STUCK_GRACE_SECONDS`) has lost its worker (a
crash, a deploy): its own timeout can't have fired. Rule (`app/jobs/recovery.py`):

- attempts left: back to `pending` (stage `retrying`, `retry_count + 1`, `failure_reason = stuck`) and queued
  again at once;
- no attempts left: `failed` as a dead letter, `failure_reason = stuck`, its upload deleted.

The sweep runs every minute: the `recover` cron job in the arq worker (`app/worker.py`), `recover_in_process` in the
API for `JOB_BACKEND=background`. If queueing again fails (Redis down) the job is put back as running, so the next
sweep tries again. A worker that retries a crashed job on its own (arq does) takes it only when it is past the
same deadline, and a job is taken by compare-and-set on its attempt count, so two workers never run one job.
Jobs interrupted by an API restart (`background` only) are still failed at startup, `failure_reason = restart`.

## Dead letters

A job that failed after its last attempt (transient errors that never cleared, or a stuck run on the last attempt)
has `dead_letter = true` and `failure_reason` (a short code for operators such as `transient:ConnectionError`,
never text from the document). The user's `error` says it gave up: "This couldn't be finished after 3 tries.
Please try again in a few minutes."

- **Queryable:** `GET /api/v1/jobs?dead_letter=true` (the user's own); `SELECT ... WHERE dead_letter` for operators.
- **Never swept:** `sweep_job_files` removes jobs past `JOB_RETENTION_DAYS` but not dead letters. Someone removes a
  dead letter after looking at it.
- **No copy of the user's text is kept**, as for any finished job: the payload's text is dropped and the upload
  deleted. The row keeps the job's type, document, timestamps and reason.

`failure_reason` is set on every failure: `user:<ErrorName>`, `timeout`, `transient:<ErrorName>`,
`unexpected:<ErrorName>`, `stuck`, `restart`, `queue_unavailable`.

## With the real arq queue

Not tested here (no Redis in the tests); what the code does for it: `run_job` raises `arq.Retry(defer=wait)` after
a transient failure; `WorkerSettings.max_tries` is `JOB_MAX_ATTEMPTS + 3` (arq counts its own crash retries too, and
the runner is the one that gives up); `job_timeout` is the longest job type plus the grace, so the job's own
timeout, with its message, fires first; a stuck job is queued again under a new arq job id
(`{id}:retry{n}`), because the first id's key may still be in Redis.
