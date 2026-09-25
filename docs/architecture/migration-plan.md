# Migration plan

How SmartDoc Formatter gets from `current-state.md` to `target-state.md`. Full phase detail lives in the working plan (`C:\Users\speed\.claude\plans\inherited-chasing-pizza.md` at planning time; superseded here as the durable repo record). Tracked task-by-task in `saas-transformation-tracker.xlsx`.

## Guiding rules (from `корекции.docx` §87/§89/§90, non-negotiable)

- **No big-bang refactor.** One phase at a time; a phase isn't done until its own tests pass *and* the full existing suite still passes.
- **Adapters and migration scripts, not destructive rewrites**, whenever an existing subsystem is being replaced (see the three call-outs below).
- **Never delete**: the formatting engine, templates, conflict resolution, the 179 backend tests — carry them forward, refactor around them.
- **Never**: AI writing `resolvedStyles` directly, secrets in the frontend, auth tokens in `localStorage`, silent data loss, fake progress, claiming "supported" without a round-trip test.

## Phase sequence

| # | Phase | Depends on | One-line goal |
|---|---|---|---|
| 0 | Audit & baseline | — | This doc set + confirmed 179-green baseline |
| 1 | Fix content-loss bugs | 0 | Close the 10 verified gaps in `current-state.md`, each with a regression test first |
| 2 | Document Model hardening | 1 | `schema_version`, generated frontend types, preservation layer scaffolding |
| 3 | Database + persistence | 2 | PostgreSQL/SQLAlchemy/Alembic; retire the in-memory singleton |
| 4 | Asset storage | 3 | `DocumentAsset` + `StorageProvider`; retire base64-in-JSON |
| 5 | Authentication + workspace | 3 | Sessions, ownership, per-request authorization |
| 6 | Revisions & concurrency | 3, 5 | Bounded persisted version history; optimistic concurrency |
| 7 | Formatting engine refactor | 3 | `StyleSystem`; persisted templates |
| 8 | Format by Example | 7 | Reference-document style extraction + application |
| 9 | DOCX fidelity expansion | 2 | Header/footer/page-break import, colspan/rowspan, deep lists |
| 10 | Export reliability | 9 | Shared render spec; PDF font embedding |
| 11 | Background jobs | 3 | `arq`/Redis; move AI/parsing/export off the request thread |
| 12 | Frontend refactor | 5, 11 | Split `DocumentEditor.tsx`; TanStack Query; typed API client |
| 13 | Dashboard & document management | 5, 12 | Post-auth home; Document Health; before/after |
| 14 | Billing | 5 | Stripe + Entitlements: built; the Stripe account and real prices **need Boril** |
| 15 | Security hardening | 5, 11 | Everything not already closed by auth/jobs work: done (uploads by content, limits, audit, headers, AI prompt safety) |
| 16 | Testing | all prior | Vitest/RTL, Playwright, golden-document fixtures |
| 17 | Docker + CI/CD | 3, 4, 11 | Compose stack, GitHub Actions, production ASGI |
| 18 | Final audit | all | `final-audit.md` |

Numbering matches the tracker's phase groups exactly.

## The three riskiest migrations (called out explicitly in `корекции.docx` §89) — adapter strategy for each

### JSON files → PostgreSQL (Phase 3)
1. ✅ Done. Postgres models (`app/db/models/`, all 14 tables from doc §5) and `app/repositories/document_repository.py`.
2. ✅ Done. `scripts/migrate_json_documents.py --owner-email you@example.com`: imports every `backend/data/documents/*.json` into that (already registered) account's personal workspace, moving inline base64 images into asset storage on the way, and prints a report (counts, any file skipped and why). **Never modifies the source JSON files.** Idempotent (an id already in the DB is skipped) and supports `--dry-run`. Not yet run against Boril's real documents — that needs his account on the Supabase database first.
3. ✅ Done (landed with Phase 5, as planned). `DocumentService` is built per request for the signed-in user on top of `DocumentRepository`; the in-memory dict and JSON write-through are gone from the request path. Undo/redo history is still process-local until Phase 6.

**Where Postgres lives: Supabase** (managed Postgres 17, project `smartdoc-formatter`, ref `edmmjmsynjziahwtjuke`, Frankfurt). Alembic stays the single source of truth for the schema. Each revision is applied to Supabase from Alembic's own offline-rendered SQL (`alembic upgrade <from>:<to> --sql`), one Supabase migration per Alembic revision, so the database's `alembic_version` always equals the code head and a backend-run `alembic upgrade head` is a no-op. Current head: `85211092fe4c` (Phase 14: `subscriptions.cancel_at_period_end`, and indexes on the Stripe customer and subscription ids for the billing webhooks). Before it, `ee14c191e210` (Phase 13: `documents.formatted_at`, backfilled for documents already formatted, and an index on (workspace_id, updated_at) for the document list), and `5f5c3a367f6f` (Phase 11: `processing_jobs` gets the job's creator, stage, progress, payload, stored input, result and attempt count; the never-used `export_jobs` table is dropped, since an export is one kind of processing job), applied after checking both tables were empty.

**Supabase-specific rule for every future migration:** Supabase serves everything in the `public` schema over its REST/GraphQL Data API, and grants its public `anon` role access by default. Revision `4cbc55236361` therefore enables RLS (no policies = deny all) on every table. The backend connects as the table owner, which bypasses RLS. **A migration that creates a table must enable RLS on it too**; `tests/test_db_migration.py::test_every_table_gets_rls_enabled_on_postgres` fails otherwise.

**How the backend connects:** as a dedicated role, `smartdoc_app`. It can read and write the app's tables (read-only on `alembic_version`), and default privileges extend that to tables `postgres` creates later. It bypasses RLS like the table owner, and has no DDL rights and no access to Supabase's other schemas. So **schema changes are applied as `postgres` through the workflow above, never by the running app.** Connection: Supavisor session pooler (`aws-0-eu-central-1.pooler.supabase.com:5432`, user `smartdoc_app.<project-ref>`, TLS required), set as `DATABASE_URL` in the gitignored `backend/.env`. Verified end to end with `python -m scripts.verify_database`: asyncpg through the pooler, schema head check, and a rolled-back repository round trip.

**Checking a migration before it is applied:** `tests/test_db_migration.py::test_upgrade_head_matches_the_models_column_for_column` upgrades a scratch SQLite database to head and compares it with the models the way `alembic revision --autogenerate` does, so a migration that misses a column, index or foreign key fails the suite. Migrations that alter or drop constraints use `op.batch_alter_table`, which is a plain `ALTER TABLE` on Postgres and a table rebuild on SQLite.

### JSON-file custom templates → workspace templates in PostgreSQL (Phase 7)
1. ✅ Done. Revision `74e891504d93` turns `templates` into workspace-owned rows (style system, compiled rules, version counter, visibility, source document), adds the author to `template_versions`, gives `workspaces` a `default_template_id`, and drops the never-used `documents.template_id` (the applied template stays `data.templateId`; each document keeps its own copy of the rules, so a template can be deleted without touching documents). Applied while `templates` was empty everywhere; its new NOT NULL columns would stop the upgrade rather than invent values otherwise.
2. ✅ Nothing to import: every file in the old `backend/data/custom_templates/` store was left over from test runs (the tests wrote there until this phase). The store is no longer read, and the files were left in place.
3. ✅ Built-in templates stay in code, now as data (`formatting/builtin_templates.json`); they are not database rows, so they can't be edited or deleted and need no seeding.

### base64-in-JSON images → `DocumentAsset` + object storage (Phase 4)
1. ✅ Done. `app/storage/` (`StorageProvider` + Local + S3-compatible, factory on `STORAGE_BACKEND`) and `services/asset_service.py` (row + blob kept consistent). `services/image_assets.externalize_inline_images` moves every inline `data:` image into an asset wherever a document enters or is saved: creation, editor autosave, and migration. `ImageContent.assetId` references it, and `GET /api/assets/{id}` serves it to workspace members only. Asset *deletion* is a sweep, never part of a document write (deleting a blob inside a transaction that later rolls back would lose data, and undo can bring back an element that points at an "unused" asset): ✅ done in Phase 11, `services/asset_cleanup.py`, daily. An asset goes once no document of its workspace refers to it, in its current content or its undo history, and it is more than a day old; the row is committed away before the blob is deleted. Deleting a document leaves its assets to the sweep, since an image copied into another document of the workspace still points at them. Not covered yet: a blob whose row was never committed (the storage providers can't list their contents).
2. ✅ Done. The backfill is built into `migrate_json_documents.py` (see above).
3. ⬜ Deliberately kept for now: exporters and the editor still accept inline `data:` images through one resolver (`app/export/images.py`). Remove that path only once every stored document has been migrated.

### Hand-mirrored TypeScript types → generated types (Phase 2, finished in Phase 12)
1. ✅ Done (Phase 2). OpenAPI-schema type generation (`openapi-typescript`) into a separate file, `frontend/types/generated/api.ts`. Since Phase 12 it reads a committed schema file, `frontend/types/generated/openapi.json`, written by `backend/scripts/export_openapi.py`, so no server has to run; `tests/test_openapi_contract.py` fails while that file is out of date.
2. ✅ Done (Phase 12). The generated types are now what the frontend compiles against: `types/document.ts` no longer describes anything itself, it only names the generated types (the adapter step), so the files importing it (32 now) kept their imports and every mismatch surfaced as a type error (there were five, fixed). For the generated response types to be exact, the API's models share a base (`app/models/base.py`) that marks every always-sent field as required in response schemas, and job results and the error body are part of the schema.
3. ⬜ Deliberately not done: `types/document.ts` stays as the naming layer (it also holds the few frontend-only types). It holds no hand-written copy of an API type any more.

## Rollback posture

Every phase that touches persisted data (3, 4, 6) keeps the previous storage mechanism readable until the new path has real-use verification, per the adapter strategy above — a failed migration is a matter of pointing back at the old path, not data loss. Every phase that touches the deterministic engine (7, 9, 10) is required to keep the full backend test suite green throughout, not just at the end of the phase.
