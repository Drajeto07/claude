# INTEGRATION: Phase 5 branches and CI gates (INFRA-011, TEST-031, PERF-007)

Branch `cloud/integration-phase5`, from `feature/smartdoc-production-hardening` at 15c319d.

## Summary

- Merged, in this order, with merge commits: PERF-002/006 (PR #4), PERF-001 (PR #5), JOB-001 (PR #6), PERF-004 (PR #3).
  Everything of both sides is kept: PERF-003's delta autosave, PLAN-003's plan holds and ACCT-001..004 from the base,
  and the four branches' work.
- One Alembic head: `... 85211092fe4c -> 1da599e1913f -> 0417f0f393fc -> c3a91f7d2b64 (JOB-001) -> b8534d3c4256 (PERF-004)`.
  Up / check / down / up on SQLite and on the throwaway PostgreSQL. The PostgreSQL SQL for production is below.
- PERF-004 with PERF-003 and PERF-006: a PATCH /content records its undo step only through the compressed copy, and
  storage metering counts it (new test). PERF-006's tests and the benchmark read `document_versions.data`, which is
  NULL for new rows since PERF-004; both fixed.
- Export benchmark after PERF-001: the 500x8 table's Word export takes **706 ms** (best of 3), against 247 s in the
  baseline (`docs/performance/after-perf-001/`).
- CI (INFRA-011): `npx next typegen` before `tsc`; a dependency audit job (pip-audit on both locks, npm audit on the
  production dependencies); the migrations job runs the new `postgres`-marked tests (TEST-031).
- npm audit failed today on `next` 16.3.5 (critical, GHSA-vcvr-r3jv-pc5j); bumped next and eslint-config-next to
  16.3.8 (patch level, through npm). pip-audit: nothing found in either lock.
- PERF-007: the Limits table's "Background jobs" row states JOB-001's real numbers.

## Commits

| Commit | What |
|---|---|
| 37c9466 | merge PERF-002/006 (#4) |
| d144387 | merge PERF-001 (#5) |
| a6a93d8 | export benchmark after PERF-001 |
| f83fcef | merge JOB-001 (#6) |
| bf34023 | one Alembic head: JOB-001 after the account migrations |
| 41b638d | merge PERF-004 (#3), with the interplay fixes |
| 1ca4545 | TEST-031: PostgreSQL fixture and marker, the race on both engines |
| 7fddc99 | INFRA-011: CI typegen, audit job, PostgreSQL tests; next 16.3.8 |
| b077b99 | PERF-007: Background jobs limits |

## Merge conflicts and how each was resolved

| Merge | File | Conflict | Resolution |
|---|---|---|---|
| PERF-002/006 | -- | none | `app/db/session.py` (`make_engine`, `json_serializer=dump_json`) and `tests/conftest.py` merged cleanly. |
| PERF-001 | `docs/performance/README.md` | add/add (both created it) | Every section kept: Benchmarks (PERF-002), UTF-8 JSON storage (PERF-006), Table export (PERF-001). |
| JOB-001 | `docs/security/README.md` | the base's E-mail, Account tokens, Changing a password (ACCT-001..004) and JOB-001's Background jobs at the same place | Both kept, base sections first. |
| PERF-004 | `docs/performance/README.md` | add/add | Every section kept; Version history storage (PERF-004) last. |
| PERF-004 | `backend/tests/test_db_migration.py` | JOB-001's and PERF-004's migration tests at the same place | Both kept; each one's "before" revision is its new parent (`0417f0f393fc`, `c3a91f7d2b64`). |

Merged without a textual conflict, checked by hand:

- `backend/app/services/document_service.py`: `update_content` -> `_take_elements` and `patch_content` (PERF-003),
  `check_new_document(..., hold=True)` in `create` and `check_storage(..., hold=True)` in `_take_elements` (PLAN-003),
  and PERF-004's `_move_inline_images` / `needs_base` in `_write` are all there. `patch_content` saves through `_write`,
  which records the step with `VersionHistory.record`; every write there (new step, merged autosave, base step) sets
  `DocumentVersion.data`, the property that writes `compressed_data` and clears `legacy_data`. Nothing in `app/` or
  `scripts/` writes `legacy_data` or the `data` column of `document_versions` directly (grep).
- `backend/app/services/usage_service.py::storage_bytes` adds `DocumentVersion.stored_bytes` (PERF-004), and
  PLAN-003's `check_storage` calls `storage_bytes`, so the plan's storage counts version bytes as stored.
- `backend/tests/test_security_suite.py::_REQUESTS` holds `PATCH /documents/{id}/content` (PERF-003) and
  `POST /jobs/{id}/cancel` (JOB-001).
- `backend/app/api/jobs.py` (JOB-001 + PLAN-003): the base's job routes never passed `hold=True`; their plan checks
  are the early refusals PLAN-003 describes ("earlier checks that only refuse early don't hold anything"). The hold
  is in `DocumentService.create`, which the job runner uses for both imports, so it is unchanged by JOB-001's
  reordering (the idempotency replay lookup now comes before the early checks; `import-file` reads the upload before
  the document-count check). `PlanLimitError` is in JOB-001's never-retried list.
- `frontend/types/generated/*`: taken as merged, then regenerated (`scripts.export_openapi`, `npm run generate-types`):
  no difference.

Interplay fixes in the PERF-004 merge commit:

- `tests/test_utf8_json_storage.py` (PERF-006) read `SELECT data FROM document_versions`, NULL for new rows now: it
  reads `compressed_data`, decompresses, and checks the title's letters are there and no `\u04` escape (stricter than
  before). Its legacy-row test wrote escaped JSON into `data` while `compressed_data` was set, which the check
  constraint refuses; it now writes a real legacy row (`data` set, `compressed_data` NULL) and also reads it back
  through `GET /versions/1`. Mutation: `pack_snapshot` with `ensure_ascii=True` -> 1 failed.
- `scripts/benchmark.py::stored_bytes` summed `length(data)` of the versions, 0 for compressed rows: it counts whichever
  copy a row holds. `test_benchmark_script.py` asserts `version_bytes > 0`. Mutation: the old query -> 1 failed.
- New `tests/test_content_patch.py::test_a_patch_s_undo_steps_are_stored_compressed_and_count_as_storage`: two PATCH
  saves (a new step, then a merged one); every version row has `data` NULL and `compressed_data` set, the merged step
  holds the second text, and `GET /usage`'s `storageBytes` is the document plus the compressed bytes. Mutations: the
  merged step written to `legacy_data` -> 1 failed; `storage_bytes` without the versions -> 1 failed.

## Migration chain

| Revision | down_revision | Change |
|---|---|---|
| 1da599e1913f | 85211092fe4c | account tokens (base, in production, untouched) |
| 0417f0f393fc | 1da599e1913f | users.email_verified_at (base, in production, untouched) |
| c3a91f7d2b64 | **0417f0f393fc** (was 85211092fe4c) | JOB-001: processing_jobs retry_count, dead_letter, failure_reason, idempotency_key, request_fingerprint, unique index |
| b8534d3c4256 | **c3a91f7d2b64** (was 85211092fe4c) | PERF-004: document_versions.compressed_data, data nullable, check constraint |

Docstrings' "Revises:" updated too. `alembic heads`: `b8534d3c4256 (head)`, one head.

Tested:
- SQLite (`ALEMBIC_DATABASE_URL=sqlite+aiosqlite:///<scratch file>`): `upgrade head`, `check` ("No new upgrade operations
  detected."), `downgrade base`, `upgrade head`.
- PostgreSQL 16 (`postgresql+asyncpg://smartdoc_w0:...@127.0.0.1:55432/smartdoc_w0`): the same four, same result.
- `tests/test_db_migration.py`: all green (JOB-001's test from 0417f0f393fc, PERF-004's from c3a91f7d2b64, with data,
  both ways).

### SQL for production (PostgreSQL, 0417f0f393fc to head)

`ALEMBIC_DATABASE_URL=postgresql+asyncpg://<dummy> alembic upgrade 0417f0f393fc:head --sql`. Upgrade steps only; no
secret in it.

```sql
BEGIN;

-- Running upgrade 0417f0f393fc -> c3a91f7d2b64

ALTER TABLE processing_jobs ADD COLUMN retry_count INTEGER DEFAULT '0' NOT NULL;

ALTER TABLE processing_jobs ADD COLUMN dead_letter BOOLEAN DEFAULT false NOT NULL;

ALTER TABLE processing_jobs ADD COLUMN failure_reason VARCHAR(200);

ALTER TABLE processing_jobs ADD COLUMN idempotency_key VARCHAR(128);

ALTER TABLE processing_jobs ADD COLUMN request_fingerprint VARCHAR(64);

CREATE UNIQUE INDEX uq_processing_jobs_created_by_idempotency_key ON processing_jobs (created_by, idempotency_key);

UPDATE alembic_version SET version_num='c3a91f7d2b64' WHERE alembic_version.version_num = '0417f0f393fc';

-- Running upgrade c3a91f7d2b64 -> b8534d3c4256

ALTER TABLE document_versions ADD COLUMN compressed_data BYTEA;

ALTER TABLE document_versions ALTER COLUMN data DROP NOT NULL;

ALTER TABLE document_versions ADD CONSTRAINT ck_document_versions_one_copy CHECK ((data IS NULL) <> (compressed_data IS NULL));

UPDATE alembic_version SET version_num='b8534d3c4256' WHERE alembic_version.version_num = 'c3a91f7d2b64';

COMMIT;
```

The downgrade of b8534d3c4256 can't be rendered with `--sql`: it decompresses every compressed version back into
`data` before dropping the column, which needs a live connection, and it says so
(`RuntimeError: This downgrade decompresses stored versions, so it needs a database connection (not --sql).`). Run a
rollback of it with `alembic downgrade c3a91f7d2b64` against the database, not as SQL. The upgrade has no data step:
existing version rows stay uncompressed and are read as they are.

## Benchmark after PERF-001

`cd backend && python -m scripts.benchmark --only export --timeout 900`, run early, on d144387 (PERF-002/006 and PERF-001
merged), on this shared container (Xeon reporting 2.10 GHz, 4 cores, 15.7 GiB; other workers ran at the same time).

| Document | Word | PDF |
|---|---:|---:|
| 500 blocks | 268 ms (273 baseline) | 236 ms (245) |
| 2000 blocks | 824 ms (882) | 901 ms (946) |
| 5000 blocks | 2.71 s (2.44 s) | 1.93 s (2.27 s) |
| table 500x8 | **706 ms (247 s)**, 11.8 MiB | 831 ms (1.03 s) |
| 50 pictures | 258 ms (338) | 808 ms (993) |

Written to `docs/performance/after-perf-001/benchmarks.{md,json}`, not over `docs/performance/benchmarks.{md,json}`: the
script writes only what it ran, so `--only export` there would have erased the baseline's import, save and load
numbers, and the baseline ran on a machine reporting 2.80 GHz. This follows the PERF-006 run (`after-perf-006/`);
`docs/performance/README.md` points at both. (While the run was going, a JOB-001 merge was started in this worktree
and aborted within seconds; the files it touches are not on the export path, and the run's commit says d144387 clean.)

## CI changes (`.github/workflows/ci.yml`)

- **frontend**: `npx next typegen` before `npx tsc --noEmit`. Locally: `tsc` alone, 5 errors (PageProps/LayoutProps);
  after `next typegen`, 0.
- **audit** (new job): `pip install pip-audit`, then `pip-audit -r requirements.lock --require-hashes --disable-pip`
  and the same for `requirements-dev.lock` (both locks are hashed, so they are audited as pinned without installing or
  resolving anything; pip-audit is a CI tool, not an app dependency); in `frontend`, `npm audit --omit=dev
  --audit-level=high`. The `images` job on main also waits for it.
- **migrations** (TEST-031): installs `requirements-dev.lock` (cache keyed on it); after the last `alembic upgrade head`,
  `python -m pytest -m postgres -q -p no:cacheprovider` with
  `SMARTDOC_TEST_POSTGRES_URL=postgresql+asyncpg://smartdoc:smartdoc@localhost:5432/smartdoc` (the service container).
- The backend job is unchanged: it runs `-m security` and `-m "not security"`; the postgres-marked cases skip there.

## Audit results (run locally first)

- `pip-audit` 2.10.1 (in a throwaway venv, not the app's): `requirements.lock` 79 packages, `requirements-dev.lock` 90,
  **no known vulnerabilities**.
- `npm audit --omit=dev --audit-level=high`: **failed** on `next` 16.3.5: GHSA-vcvr-r3jv-pc5j, critical, "Remote Code
  Execution in next/og ImageResponse", affects 16.2.0 - 16.3.5, fixed in 16.3.8. The app does not import `next/og`
  (grep), but the gate was not weakened: `npm install --save-exact next@16.3.8 eslint-config-next@16.3.8` (patch level;
  the lock changes only next, @next/env, @next/swc-*, eslint-config-next and @next/eslint-plugin-next, all 16.3.5 ->
  16.3.8). After it, `npm audit --omit=dev --audit-level=high` and a full `npm audit`: 0 vulnerabilities. Lint, tsc,
  Vitest, build and Playwright below ran on 16.3.8.

## TEST-031

- `backend/pytest.ini`: marker `postgres` registered.
- `backend/tests/conftest.py::postgres_sessions`: an `async_sessionmaker` on `SMARTDOC_TEST_POSTGRES_URL`, built with
  `app.db.session.make_engine` (NullPool). Skipped when the variable is unset. `local_postgres_url` refuses, with a
  failure, any driver but `postgresql+asyncpg` and any host but `localhost`/`127.0.0.1` (no host, a socket, too),
  before a connection is made.
- **Schema decision**: the migrated schema, which must be at head (else the test fails, saying to run `alembic
  upgrade head`): these tests are there to run on what production runs, and CI migrates first. Only a database with
  no tables at all gets `Base.metadata.create_all`, for a quick local run; one with tables but no `alembic_version` is
  refused. CI's `alembic check` keeps the models and the migrations equal.
- Every table of the current schema except `alembic_version` is emptied before and after each test
  (`TRUNCATE ... RESTART IDENTITY CASCADE`); the database is never dropped. Before as well as after, so a run that
  was killed can't leave a user behind that the next run's sign-up would collide with.
- `tests/test_plan_limits_atomic.py`: the race (documents, templates, storage) is parametrized on `sqlite` and
  `postgres` (the second marked `postgres`) through a sync `race_database` fixture (an async fixture can't set up
  another async fixture from inside the running loop). Its SQLite engine now goes through `make_engine` as well.
- `tests/test_postgres_fixture.py` (8): the URL guard, without a database.
- Results: default run, `test_plan_limits_atomic.py`: 4 passed, 3 skipped (the postgres cases). Against my PostgreSQL:
  `SMARTDOC_TEST_POSTGRES_URL=postgresql+asyncpg://smartdoc_w0:...@127.0.0.1:55432/smartdoc_w0 python -m pytest -m postgres`:
  **3 passed**; afterwards `users` and `workspaces` hold 0 rows, `alembic_version` is still b8534d3c4256. With a
  non-local host in the variable: 3 errors, the fixture's message, no connection.

Mutation checks:

| Mutation | Result |
|---|---|
| `hold_workspace` returns at once (no row lock) | `-m postgres`: 3 failed |
| the host check in `local_postgres_url` removed | `test_postgres_fixture.py`: 4 failed |

## PERF-007

`docs/security/README.md`, Limits, "Background jobs": the time per job type (import of text 300 s, of a file 600 s,
formatting 600 s, export 300 s, reading a reference document 300 s; not retried), 3 attempts (`JOB_MAX_ATTEMPTS`),
retried only on transient errors (network, database connection, the AI provider's connection, rate limit and 5xx,
the storage's connection and timeouts; never the user's file, text or plan, or a bug) after 5 s doubling up to 300 s,
the owner's cancel (a waiting job never runs, a running one stops at its next stage and writes nothing), and the
stuck rule (60 s past its time, swept every minute, started again while attempts remain, else a dead letter). From
`app/jobs/policy.py`, `app/config.py` and `app/worker.py`.

## Test results

All on this branch at b077b99 (the code; the report commit after it changes only this file), on the shared container.

- Backend, full suite (no `SMARTDOC_TEST_POSTGRES_URL`): **1908 passed, 4 skipped, 2 warnings in 305 s**. The skips
  are the base's 1 and the 3 PostgreSQL race cases; the 2 warnings are the existing Pillow decompression-bomb ones.
  (Base 1795 passed / 1 skipped; the rest is the four branches' new tests plus this branch's 1 + 8 + 3 parametrized.)
- Backend, `-m postgres` against the throwaway PostgreSQL: **3 passed**.
- Areas after each merge: PERF-002/006 36 + 24 passed; PERF-001 43 + 55 passed; JOB-001 (migration, job safety, jobs,
  security suite, entitlements, plan limits, OpenAPI contract) 232 passed; PERF-004 (UTF-8 storage, benchmark,
  versioning, version history storage, migrations, content patch, usage, plan limits, job safety, pictures, OpenAPI)
  178 passed after the fixes (2 failed before them, described above).
- Frontend (next 16.3.8): `npm ci` ok; `npm run lint` clean; `npx next typegen && npx tsc --noEmit` 0 errors (5 without
  typegen); `npx vitest run` **241 passed** (30 files; base 240 + JOB-001's 1); `npm run build` ok.
- Playwright, the whole suite through `/tmp/e2e.lock` with the container's Chromium: **33 passed, 1 skipped**
  (`visual.spec.ts`, which skips itself off Windows: its baseline is of Windows' fonts) in 2.2 min.

## Risks

- PERF-004's downgrade needs a live connection (above). Its data path (decompress back) was tested on SQLite by
  `test_db_migration.py`; on PostgreSQL the downgrade ran only on empty tables (here and in CI).
- `next` 16.3.8 is a new patch release in the app; lint, types, unit tests, the build and the E2E suite pass on it.
- The postgres-marked tests are only the three races today; other PostgreSQL-only behaviour (jsonb, RLS, TOAST sizes in
  `stored_bytes`) is still covered only by `alembic check` and the migration round trip.
- Benchmarks come from a shared container; compare runs from the same machine only.

## Decisions for the owner

1. Apply the SQL above to production (or `alembic upgrade head`), after merging. It adds columns and a constraint, no
   table rewrite; existing version rows stay as they are.
2. Whether to keep the `next` 16.3.8 bump in this PR or take it separately (it is what makes the new audit gate green).
3. Whether `docs/performance/benchmarks.{md,json}` should be re-run in full on one machine (about 10 minutes now that
   the table export is fast) to replace the 370ed49 baseline and the two partial `after-*` runs.

## Commands run

- `git merge --no-ff origin/cloud/<branch>` x4, conflicts resolved as above.
- `python -m pytest` on the touched areas after each merge; the full suite at the end.
- `alembic heads`, `upgrade head`, `check`, `downgrade base`, `upgrade head` on SQLite and PostgreSQL;
  `alembic upgrade 0417f0f393fc:head --sql`; `alembic downgrade b8534d3c4256:c3a91f7d2b64 --sql` (refused, as designed).
- `python -m scripts.benchmark --only export --timeout 900 --out-dir <scratch>`.
- `python -m scripts.export_openapi`, `npm run generate-types` (no change).
- `pip-audit -r <lock> --require-hashes --disable-pip` x2; `npm audit --omit=dev --audit-level=high`;
  `npm install --save-exact next@16.3.8 eslint-config-next@16.3.8`.
- `npm ci`, `npm run lint`, `npx next typegen && npx tsc --noEmit`, `npx vitest run`, `npm run build`,
  `flock /tmp/e2e.lock npx playwright test --config playwright.local.config.ts`.
- The secret check on the branch diff before each push.
