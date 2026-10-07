# Deployment

How SmartDoc runs outside a developer's machine. Nothing is deployed from here or from CI: where it runs (the hosting
target), its domain, and the accounts it needs (database, storage, e-mail, Stripe, the Anthropic key) are the owner's
decisions. What is ready is below, and what has and hasn't been verified is said at the end.

## The pieces

| Piece | What | Image / command |
| --- | --- | --- |
| API | FastAPI under uvicorn (never `fastapi dev`), `--proxy-headers`, no access log (the app logs requests) | `backend/Dockerfile`, non-root `smartdoc`, health check on `/api/health` |
| Job worker | arq: imports, formatting, exports, translations, the hourly file sweep | the backend image, `arq app.worker.WorkerSettings` |
| Migrations | Alembic, a release step before the new API starts; never tables made at startup | the backend image, `alembic upgrade head` |
| Frontend | Next.js standalone server | `frontend/Dockerfile`, non-root `node`, health check on `/login` |
| PostgreSQL | documents, accounts, jobs, usage (`DATABASE_URL`; TLS required for any non-local host) | managed Postgres (Supabase in development) |
| Redis | the job queue and shared rate-limit counters (`REDIS_URL`) | |
| Object storage | pictures, uploads, export files: S3 or any S3-compatible service (`STORAGE_BACKEND=s3`, `S3_*`) | MinIO locally |

`docker compose up --build` (`docker-compose.yml`) starts all of it locally: postgres, redis, minio (with its bucket
made on start), migrate (once, before anything else), backend, worker and frontend at http://localhost:3000.

## Settings

Every setting is in `backend/.env.example` with what it does. For production, in short: `DATABASE_URL`,
`STORAGE_BACKEND=s3` with `S3_*`, `JOB_BACKEND=arq` with `REDIS_URL` and a worker, `RATE_LIMIT_BACKEND=redis`,
`CORS_ORIGINS` and `FRONTEND_URL` (the real frontend), `SESSION_COOKIE_SECURE` (on by default), `HSTS_SECONDS` when
served over HTTPS only, `FORWARDED_ALLOW_IPS` (the reverse proxy) and `WEB_CONCURRENCY`, `LOG_FORMAT=json` and
`LOG_REQUESTS=true`, `METRICS_TOKEN` for the metrics scraper, `ANTHROPIC_API_KEY`, `EMAIL_BACKEND=smtp` with `SMTP_*`
and `EMAIL_FROM`, the `STRIPE_*` settings once payments are switched on, and `OCR_PROVIDER` if an OCR engine is chosen.
The frontend is built with `NEXT_PUBLIC_API_BASE_URL` (the API as the browser sees it); `API_INTERNAL_URL` when its own
server reaches the API another way. Secrets are `SecretStr` settings and never printed.

Fonts: the backend image has Liberation and DejaVu (Latin and Cyrillic). A deployment that must draw Arabic,
Hebrew, Devanagari, Thai or CJK in PDFs needs the Noto fonts added (`fonts-noto-core`, `fonts-noto-cjk`;
[`docs/fonts`](../fonts/README.md)); otherwise those characters are reported as not drawn, never silently dropped.

## Releasing

1. CI on the change passed (`.github/workflows/ci.yml`): backend tests and the security suite, the migrations on a
   real PostgreSQL (up, `alembic check`, down, up), frontend lint, types, unit tests and build, the dependency audit,
   the end-to-end tests in Chromium, and on pull requests the performance gate against the base branch. On main,
   both production images are built and the compose file checked.
2. Take the images from that run.
3. Run `alembic upgrade head`; migrations are additive first, the code that needs them after
   ([`docs/architecture/migration-plan.md`](../architecture/migration-plan.md)).
4. Start the new API and worker. `GET /api/ready` answers 503, naming what is missing, until the database (and Redis,
   when used) answer: a load balancer holds traffic back until then. `GET /api/health` is liveness.
5. Old browser tabs keep working through the deploy: the unversioned `/api/...` paths answer as deprecated aliases of
   `/api/v1`.

## Running it

- Logs: one line per event, JSON with `LOG_FORMAT=json`, each with its request, operation and job ids; never a
  document's content. Metrics at `GET /api/metrics` for the `METRICS_TOKEN` bearer, per process.
  [`docs/operations`](../operations/README.md) lists them and what to alert on.
- Security: [`docs/security`](../security/README.md) (headers, rate limits, uploads, audit lines, the CSP).
- Jobs that lost their worker are recovered or failed on startup and by the sweep ([`docs/architecture/jobs.md`](../architecture/jobs.md)).

## Verified, and not

- Verified in CI and here: every test suite above; the compose file (`docker compose config`); the settings each
  service reads.
- **Not verified here: building and starting the images and the stack** (tracker INFRA-010). This machine can't run
  Docker (virtualization is off in its BIOS), so the images are built by CI on main only and the stack has never been
  started end to end by this project. Before the first real deployment, run `docker compose up --build` on a machine
  with Docker and check: the migrations finish, `/api/ready` turns 200, an upload, a formatted document and an export
  work through the worker, pictures land in MinIO.
- **Not done: a deployment.** It needs the owner's hosting target and accounts.
