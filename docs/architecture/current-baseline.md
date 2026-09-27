# Current baseline — before production hardening

Measured on 2026-09-27 on branch `feature/smartdoc-production-hardening` at `ea69829` (the state `main` was left in after
the SaaS transformation), before any production code changed. Every run below is also a row on the `TESTING` sheet of
`SmartDoc_Master_Implementation_Tracker.xlsx` (RUN-0001..RUN-0011). The known risks are the 20 findings of the
2026-09-26 audit, tracked as AUD-01..AUD-20 on `CRITICAL_FIXES`.

## Stack

| Part | Version |
|---|---|
| Backend | Python 3.13, FastAPI 0.141, SQLAlchemy 2.0 (async), Alembic 1.20, python-docx 1.2, lxml 6.1, reportlab 5.0, pypdf 6.19, Pillow 12.3, arq 0.28, anthropic 1.7 |
| Frontend | Next.js 16.3, React 19.2, Tiptap 3.31, TanStack Query 5 |
| Database | PostgreSQL 17 on Supabase (project `edmmjmsynjziahwtjuke`); SQLite only in tests |
| Jobs | arq worker over Redis (`arq app.worker.WorkerSettings`) or in-process |
| Storage | `local` provider (default) or S3-compatible (`s3`) |
| Document model | `schemaVersion` 1 |

## Test and check results

| Check | Command | Result |
|---|---|---|
| Backend tests | `cd backend && venv/Scripts/python -m pytest -q -p no:cacheprovider` | **643 passed, 1 skipped, 0 failed** in 88 s. The skip is the optional real-Word check (`SMARTDOC_REAL_DOCX`). 1 deprecation warning from starlette/anyio. |
| Coverage | (audit venv, 2026-09-26) | 93% line coverage |
| Frontend lint | `npm run lint` | 0 problems (53 s) |
| Frontend types | `npx tsc --noEmit` | 0 errors (7 s) |
| Frontend unit tests | `npm test` | **46 passed** in 6 files (30 s): `editorRoundTrip`, `client`, `format`, `BillingPage`, `ConfirmDialog`, `PlanLimitBanner` |
| Frontend build | `npm run build` | Succeeds; 11 routes |
| End-to-end | `npm run test:e2e` (Edge) | **16 passed, 0 failed** in 67 s — sign up/in/out, wrong password, redirect, other user's document refused, paste + structure review, autosave survives reload, template apply + undo/redo, export DOCX + PDF, delete, own template, Format by Example, uploads (link, pictures, captions, everything), visual snapshot |
| Migrations | `alembic upgrade head && alembic check && alembic downgrade base && alembic upgrade head` (scratch SQLite) | Clean; "No new upgrade operations detected" |
| PostgreSQL SQL | `alembic upgrade head --sql` | Generates; 14 tables at head (`export_jobs` is created and later dropped), RLS enabled on every table |
| Supabase | MCP `list_migrations`, `list_tables`, `get_advisors` | 8/8 migrations applied (head `85211092fe4c`); 14 tables, RLS on all. Advisors: INFO only — 14 × RLS enabled without policies (by design: the API connects as the owner; PostgREST roles see nothing), 8 × unused index (low traffic) |
| Python dependencies | `uvx pip-audit --disable-pip -r backend/requirements.lock` (and `requirements-dev.lock`) | No known vulnerabilities |
| JavaScript dependencies | `npm audit` / `npm audit --omit=dev` | 0 vulnerabilities in 633 dependencies |
| Docker | `docker compose config --quiet` | Valid; 8 services (postgres, redis, minio, minio-bucket, migrate, worker, backend, frontend). **Images not built here** — the Docker daemon is not running on this machine; CI builds them on `main`. Never deployed. |

## Database

Alembic chain (8 revisions): `361677e33e9c` initial schema → `4cbc55236361` RLS on all tables → `e7958c683f5b` foreign-key
indexes → `e68923f36278` revisions and version history → `74e891504d93` template persistence → `5f5c3a367f6f` job
progress payload → `ee14c191e210` documents `formatted_at` → `85211092fe4c` subscription cancel flag and Stripe indexes.
Live data is tiny (1 user, 8 documents, 35 versions, 6 assets).

Tests never reach the real database: `backend/tests/conftest.py` replaces `get_engine` with a function that raises, and
every test uses the SQLite fixtures.

## Fixtures

- `backend/tests/fixtures/documents/`: 12 DOCX files (`01-simple` … `12-complex`) generated with python-docx, plus
  `backend/tests/fixtures/sample.pdf`. None is Word-authored, so none carries the OOXML that Word writes (numbering
  definitions, sections, themes, content controls, fields, custom properties).
- The audit's 17 Word-authored fixtures (a01–a12 by feature, r01–r05 realistic documents) exist outside the repository;
  bringing them in with expected-loss manifests is TEST-020/TEST-021.

## Performance (from the 2026-09-26 audit)

Also on the `PERFORMANCE` sheet (BENCH-001..013), where new measurements are compared with these.

| Scenario | Baseline |
|---|---|
| DOCX export, table 500×8 | 321 s (quadratic: 400 cells 3.8 s, 1,600 cells 53.7 s) |
| PDF export, same table | 1.4 s |
| Import / DOCX export / PDF export, 300-page text document | 0.33 s / 0.67 s / 1.8 s |
| PDF export, 39 KB DOCX holding a 12000×12000 PNG | +1,382 MB memory (14000×14000 crashes the export) |
| Editor, 20 keystrokes at 12,196 elements | 9.4 s (~470 ms per key) |
| Autosave request, 300-page document / 1M-character paste | 2.77 MB / 5.99 MB |
| Stored history, one 300-page document, 50 steps | ~140 MB |

## Not verified by this baseline

- Docker image build and start (daemon not running) — INFRA-010.
- A real AI model: no Anthropic API key is configured; AI paths are tested with fakes.
- Stripe, e-mail delivery, hosting: need Boril's accounts and decisions.
- Word-authored documents in CI (see Fixtures).

## Where this leaves the work

Everything that exists passes its own tests. The gaps are the ones the audit found — silent content loss in the editor
save, weak AI fidelity checks, import/export fidelity, resource limits, account basics — and those are the phases that
follow (tracker phases 1–18).
