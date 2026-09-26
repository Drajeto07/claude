# Final audit (SaaS Phase 18)

корекции.docx §92 asks for a final audit once every phase is done. This is that audit. It was written on 2026-09-26 against the Phase 17 code (commit `85a9e2a`) and committed with Phase 18.

- It replaces [current-state.md](current-state.md) as the description of the system as it is. That file stays as the Phase 0 baseline it always was.
- How each part works: the README, one section per phase.
- The path taken: [migration-plan.md](migration-plan.md).
- Per task: `saas-transformation-tracker.xlsx`.

**The rule it is measured against (§93).** SmartDoc Formatter is not a clone of Microsoft Word but an AI-assisted document transformation engine: *"You have the content; we take over the tedious professional formatting"*, or more exactly, *"give us a document, an example or template, and instructions; we apply the style consistently without changing the content."* Sections D, E and I are written with that in mind.

## The Definition of Done (§88), area by area

| Area | §88 asks for | State | Evidence, and what is missing |
|---|---|---|---|
| Architecture | no global document singleton, PostgreSQL, migrations, storage abstraction, ownership | Done | `DocumentService` is built per request on repositories; PostgreSQL 17 on Supabase; 8 Alembic revisions; `app/storage/` (local disk or any S3-compatible store); user → workspace → documents, templates, images, jobs |
| Security | authentication, authorization, workspace isolation, secure uploads, rate limiting | Done | Sessions in HTTP-only cookies, argon2, a cross-site write check; every endpoint does authenticate → authorize → fetch; the Phase 15 hardening. **Missing:** password reset and e-mail verification (E) |
| Document | versioned model, strong fidelity, no silent content loss | Done | `Document.schemaVersion`; 12 golden Word documents; every imported feature is supported, preserved for Word, or reported in `unsupportedFeatures` |
| Formatting | deterministic engine, StyleSystem, priorities, conflict handling, templates | Done | One `Priority` enum with 8 tiers, two of them without a producer yet (E); `StyleSystem`; the Conflict modal; built-in and workspace templates with versions |
| AI | structured outputs, validation, provider abstraction, chunking, usage controls, graceful fallback | Done, **not yet run against the real model** | Schema-constrained calls plus checks that the text was not altered; `AIProvider`, with Anthropic as the only implementation; chunked structure analysis; AI operations per plan and rate limits; every task has a fallback. No API key was configured during the transformation, so every AI path ran against the test double (F, G) |
| Editor | modular architecture, autosave, stable undo/redo, conflict awareness | Done | A shell and one hook per concern; autosave that reports its status; text undo in the editor and formatting history on the server; `If-Match`/412 with a reload banner |
| Export | reliable DOCX and PDF, hyperlinks, images, tables, lists, captions, page settings | Done | Round-trip and golden tests; the PDF embeds TrueType fonts, so Cyrillic text renders |
| Product | dashboard, templates, format-by-example, document health, before/after | Done | Phases 7, 8 and 13 |
| SaaS | billing, usage, plans, workspace | Built, **payments off** | The Stripe code is complete and tested against a stand-in for Stripe's API. It switches on with Boril's Stripe account and prices; the plans have placeholder limits until then. One personal workspace per user, and no invitations |
| Infra | Docker, CI, production startup, health/readiness, migrations | Done, **verified by CI only** | Dockerfiles, a compose stack and GitHub Actions. This machine cannot run Docker, and nothing is deployed yet |
| Testing | backend, frontend, E2E, round-trip document tests, golden fixtures | Done | 643 backend tests (plus 1 optional), 46 Vitest tests, 16 Playwright tests, 12 golden documents (G) |

**The deliverables (§91)** all exist:

- a working application, with updated architecture docs (this folder and the README);
- database migrations, a storage implementation, authentication and workspace ownership;
- strong document fidelity, a refactored formatting engine, persistent templates and Format by Example;
- an improved editor, reliable exporters and background processing;
- a billing architecture and a usage system;
- security hardening and a full testing strategy;
- Docker, CI and production deployment documentation: the README's "Deployment" section, `backend/.env.example` and `frontend/.env.example`.

Three of them are complete in code but not yet in operation:

- **Billing:** there is no Stripe account yet.
- **Docker and CI:** neither has run on this machine. CI results are visible only to the repository's owner.
- **Deployment:** no production deployment exists.

## A. What changed

**Before** (Phase 0), the app had these problems:

- one FastAPI process kept every document in a dictionary and wrote it to JSON files;
- there were no accounts, so anyone who knew a document's UUID could read and change it;
- images were stored as base64 inside the document;
- the undo stack was unbounded and held full copies in memory;
- custom templates were lost on restart;
- AI calls, parsing and exports ran inside the request;
- ten content-loss bugs had been verified;
- there were 179 backend tests and no frontend tests;
- there was no Docker, no CI and no API versioning.

**Now:**

- **Data** (Phase 3): PostgreSQL (Supabase, Postgres 17) through async SQLAlchemy 2 and Alembic, with 13 tables. That is §5's list, with the separate export-jobs table folded into processing jobs. Repositories and services are built per request, and the in-memory singleton and the JSON store are gone from the request path.
- **Accounts and tenancy** (Phase 5):
  - registration, sign-in and sign-out;
  - server-side sessions in HTTP-only cookies that expire (30 days) and can be revoked;
  - argon2 password hashes and a check against cross-site writes;
  - a personal workspace for each user.

  Every document, template, image and job belongs to a workspace, and every endpoint does authenticate → authorize → fetch.
- **Images** (Phases 4 and 11): `document_assets` rows backed by a storage provider (local disk or any S3-compatible store). Images are served only to members of the workspace, and a daily sweep removes images no document uses.
- **History and concurrency** (Phases 6 and 13): the version history is stored in the database and bounded (50 steps by default, and the original is always kept). It supports undo, redo and restore, and each step describes what it did. Each document has a revision number, and a stale write from another tab gets 412 instead of overwriting.
- **Formatting** (Phases 7, 8 and 10):
  - One priority enum: live override, instruction, imported requirement, custom template, built-in template, source document, AI inference, default.
  - `StyleSystem` is what templates are made of. The five built-ins are validated data.
  - Workspace templates have versions, visibility and a default, and a template editor shows a live preview.
  - Format by Example.
  - One render specification is shared by the editor and both exports.
- **Fidelity** (Phases 1, 2 and 9):
  - The ten bugs were fixed, each with a regression test.
  - Documents gained `schemaVersion`, the frontend types are generated, and a preservation layer was added.
  - The DOCX importer was rewritten: Word's styles become the source-document tier, and numbering with nesting, merged cells, headers and footers with page numbers, page breaks, footnotes, checklists and captions now come across.
  - The exporters were rewritten: native Word styles, multi-level numbering per list, Word checkboxes, hyperlinks and fonts embedded in the PDF.
  - Equations, fields, bookmarks and comments go back into Word on export.
- **Processing** (Phase 11): imports, AI work, formatting, exports and reading a reference document run as jobs with real stages and progress. In development they run in the API process; in production they run on an arq worker over Redis.
- **Frontend** (Phases 12 to 14):
  - the editor shows real pages, like Word's page view;
  - the editor is split into a shell and one hook per concern;
  - a typed API client is generated from the backend's schema, and TanStack Query holds server state;
  - autosave says what it is doing;
  - new screens: the dashboard, the document list, version history, before/after, Document Health and the billing page.
- **Business** (Phases 13 and 14):
  - plans are data;
  - the backend checks entitlements before the work (402 `plan_limit`);
  - usage is metered;
  - Stripe Checkout, the billing portal and webhooks with a checked signature are in place.
- **Security and observability** (Phase 15):
  - uploads are judged by their bytes;
  - ZIP, XML and PDF limits, and a cap on request size;
  - rate limits, security headers, a CSP and a restricted CORS policy;
  - secrets are hidden in the settings;
  - audit lines carry request ids, and no log line holds document content;
  - AI prompts keep documents apart from instructions, AI calls have timeouts and telemetry, and long text is analysed in pieces.
- **Tests** (Phase 16): golden documents, the §45 round trip, Vitest and Playwright.
- **Delivery** (Phase 17):
  - the API is `/api/v1`, and the old paths remain as deprecated aliases;
  - health and readiness probes;
  - hashed lockfiles;
  - Dockerfiles, a compose stack and CI.

## B. What was preserved

- **The rule that AI never formats.** The AI returns structured, validated data (elements, rules, labels), and only the deterministic engine produces styles. Every AI use added since follows the rule; Format by Example's AI, for instance, only labels which paragraphs are headings. The AI never rewrites content: structure analysis checks that the text came back unchanged.
- **The priority model** and its guarantee that manual changes survive a reformat. Conflict detection still flags only real differences, and the Conflict modal is unchanged.
- **Graceful degradation.** Every AI call site still has its fallback (the naive segmenter, no rules, no report). The fallback now also applies when the plan's AI allowance is used up.
- **Two independent exporters** driven by the resolved styles (python-docx and reportlab), with no LibreOffice.
- **The original three built-in templates** compile to exactly the rules they had, as `test_original_builtins_compile_to_exactly_the_rules_they_had` checks.
- **The original tests.** 166 of the 176 original test functions are still in the suite under their names, adapted to accounts, the database and `/api/v1` where they call the API. The other ten tested the in-memory template store and the document singleton, both retired. Tests of the new stores replaced them in the same commits (`5f2bf9e` and `ae36024`).
- **Everything users could do before:**
  - paste text, or upload a .txt, .docx or .pdf, with Markdown detected;
  - the editor's toolbar, outline and Properties panel;
  - formatting undo and redo, formatting instructions and style analysis;
  - DOCX and PDF export.

  The synchronous endpoints remain for API clients, next to the jobs.
- **The old data and addresses.** `backend/data/documents/*.json` was imported and never changed. The unversioned `/api` paths still answer.

## C. Migrations

### Schema

Each Alembic revision was applied to Supabase as one migration, in order:

| Revision | Phase | Change |
|---|---|---|
| `361677e33e9c` | 3 | Initial schema: the tables of §5 |
| `4cbc55236361` | 3 | RLS enabled on every table. Supabase's public Data API gets nothing, and the backend's role bypasses RLS |
| `e7958c683f5b` | 3 | Indexes on foreign-key columns |
| `e68923f36278` | 6 | Document revisions and version history |
| `74e891504d93` | 7 | Templates become workspace rows: style system, rules, versions, visibility, source document. Also adds the version's author and the workspace default template, and drops the unused `documents.template_id` |
| `5f5c3a367f6f` | 11 | Processing jobs gain their creator, stage, progress, payload, stored input, result and attempt count. The unused `export_jobs` table is dropped |
| `ee14c191e210` | 13 | `documents.formatted_at` (backfilled) and the index for the document list |
| `85211092fe4c` | 14 | `subscriptions.cancel_at_period_end`, and indexes on the Stripe ids |

**Head: `85211092fe4c`, the same in code and on Supabase.** Checked again on 2026-09-26: Supabase lists the same eight migrations.

- Its security advisor reports only the expected notice, "RLS enabled, no policy". That is deliberate: RLS denies Supabase's public API, and the backend's role bypasses it.
- Its performance advisor reports only indexes that have not been used yet. So far the only traffic is one account.

**How a revision is made and applied:**

1. It is generated against a scratch SQLite database.
2. It is rendered to SQL offline.
3. It is applied as `postgres`. The app's own role, `smartdoc_app`, cannot change the schema.

Two checks keep the models and the migrations from drifting apart:

- `test_upgrade_head_matches_the_models_column_for_column`;
- CI's PostgreSQL job, which upgrades, runs `alembic check`, downgrades to base and upgrades again.

### Data

- **JSON documents to PostgreSQL:** `scripts/migrate_json_documents.py`. It has a dry run, can be run twice without harm, and never modifies its sources. It was run on 2026-09-24 for Boril's account and imported his two documents.
- **Inline base64 images to assets:** done in the same script, and also on every write (`externalize_inline_images`).
- **Custom templates from the JSON store:** nothing to import, since every file was left over from tests. The built-ins moved from Python code to `builtin_templates.json`.
- **`formatted_at`:** backfilled for documents formatted before Phase 13.
- **TypeScript types:** no longer written by hand; they are generated from the committed OpenAPI schema.
- **Python dependencies:** `requirements.txt` became `pyproject.toml` plus hashed lockfiles.
- **API paths:** `/api/...` became `/api/v1/...`. The old paths remain as deprecated aliases.

### Still open

- The exporters and the editor still accept inline `data:` images. Remove that path once every stored document is known to be migrated.
- `formatting_profiles`, from §5's list, has never been used; Format by Example saves templates instead. Drop it in a migration or give it a purpose.

## D. What is really supported now

"Supported" means implemented, with a test that proves it (§90).

| Capability | What exactly | Proved by |
|---|---|---|
| Accounts and isolation | Registration, sign-in and sign-out; sessions that expire and can be revoked. Nobody reaches another workspace's documents, templates, images or jobs | `test_auth_api.py`, `test_auth_service.py`, `test_document_authorization.py`, `test_template_access.py`, `test_image_assets_api.py`; e2e `auth.spec.ts` |
| Input | Pasted text: Markdown is parsed as Markdown, and plain prose goes to the AI, with a fallback. Also .txt, .docx and text-based .pdf files | `test_markdown_detection.py`, `test_markdown_parser.py`, `test_ai_structure_analysis.py`, `test_plain_text_segmenter.py`, `test_pdf_parser.py`, `test_docx_parser.py`; e2e `documents.spec.ts`, `uploads.spec.ts` |
| Word import | Everything under the README's "What comes across": headings; lists with nesting and numbering; checklists; tables with merged cells and shading; images; captions; quotes; code; page breaks; rules; hyperlinks; footnotes and endnotes; page setup; header and footer with page numbers | `test_docx_fidelity.py`, `test_golden_documents.py` (12 documents) |
| Kept for Word | Equations, fields, bookmarks with their internal links, and comments. The editor does not show them, and the DOCX export puts them back | `test_docx_preservation.py` |
| Editing | All of the above survives opening and saving in the editor unchanged. Also toolbar formatting, Properties overrides, autosave, and conflicts between tabs | `editorRoundTrip.test.ts`, `test_versioning.py`, `client.test.ts`; e2e `documents.spec.ts` |
| Formatting | Five built-in templates. Workspace templates with versions, restore, a default and `If-Match`. Instructions turned into rules. Conflicts. Undo and redo | `test_formatting_engine.py`, `test_style_system.py`, `test_templates.py`, `test_templates_api.py`, `test_instruction_extraction.py`; e2e `documents.spec.ts`, `templates.spec.ts` |
| Format by Example | A reference .docx becomes a style system, applied as a template | `test_reference_style.py`, `test_templates_api.py`; e2e `templates.spec.ts` |
| Export | DOCX with native styles, numbering, checkboxes, links, images, tables, captions, footnotes, header and footer fields, and the preserved pieces. PDF with embedded fonts (Cyrillic included), page numbers, links and tables | `test_docx_export.py`, `test_pdf_export.py`, `test_export_round_trip.py`, `test_golden_documents.py`; e2e `documents.spec.ts` |
| Document management | The dashboard; the document list with search, sort and delete; version history and restore; before/after; Document Health; usage | `test_document_management.py`, `test_compare.py`, `test_health.py`, `test_usage.py`; e2e `documents.spec.ts` |
| Plans and billing | Limits enforced before the work. Stripe Checkout, the portal and webhooks, with the signature checked for real and Stripe's API stood in for | `test_entitlements.py`, `test_billing.py`, `BillingPage.test.tsx`, `PlanLimitBanner.test.tsx` |
| Jobs | Every heavy action runs as a job with stages. In-process jobs are tested for real; arq is tested against a stand-in for its Redis pool | `test_jobs.py`, `test_asset_cleanup.py` |
| Security | Everything in the Phase 15 list | `test_security.py`, `test_observability.py` |
| API | `/api/v1` with its deprecated aliases, the probes, and one error body for every error | `test_api_versioning.py`, `test_api_errors.py`, `test_openapi_contract.py` |

## E. What is still not supported

**Accounts and teams**

- **Password reset, e-mail verification, changing a password or e-mail address, and deleting an account.** None of these exist, and the app sends no e-mail at all.
- **Teams.** Each user has one personal workspace, and there are no invitations or other members. The owner/member roles and template visibility exist in the data but have no UI.
- **Other sign-in methods:** signing in with Google or Microsoft, and two-factor authentication.
- **A back office** for administration or support.

**Documents**

- **Scanned or image-only PDFs** (there is no OCR). From any PDF only the text comes across, not its layout, tables or pictures.
- **Other file formats:** .doc is refused with a message saying so; .odt, .rtf, HTML and Google Docs are not accepted.
- **The Word features that imports report in `unsupportedFeatures`.** They are listed in the README under "What doesn't, and says so":
  - several columns, floating pictures, drop caps and text boxes;
  - tracked changes, which are accepted on import;
  - tables of contents, which become plain text;
  - watermarks and first-page or even-page headers;
  - embedded objects and charts, VML pictures and symbol-font characters;
  - pictures inside table cells or list items.
- **Editing equations or comments.** They are kept for Word but not shown.
- **Generating a table of contents.**
- **Instructions from a .docx file.** Instructions can be typed or come from a .txt or .pdf file only.
- **Export to formats other than DOCX and PDF.**
- **Editing together in real time.** When two tabs change the same document, the conflict is detected but never merged. This is deliberate, per §93.

**Formatting and AI**

- **Two priority tiers without a producer:** AI style inference (tier 7) and imported requirements (tier 3). Both are named in the priorities, but nothing produces them yet.
- **Correcting the AI's structure.** Low-confidence elements are only tinted; there is no way to accept or reject them.
- **Any AI provider but Anthropic.** The abstraction is there, with one implementation.

**Business**

- **Taking payments.** There is no Stripe account, product, price or webhook yet. The plan limits and prices are placeholders.
- **Plans for shared workspaces**, since shared workspaces don't exist.

**Operations**

- **A production deployment.** Nothing is hosted. CI builds the images but deploys nothing.
- **Error tracking, metrics, dashboards and alerts.** There are only the structured logs.
- **Backups** beyond what the Supabase plan includes. Nothing backs up the asset store.

## F. Known limitations

These work, within a boundary.

**Documents and exports**

- **Pagination in the editor.** Pages move whole blocks and never split one. A paragraph or table taller than a page runs past the margin, and the editor's page count can differ from Word's. The exports paginate for real.
- **PDF fonts.** The PDF uses the document's font only if the server has it installed, and otherwise a font of the same kind. A PDF can differ from the DOCX in its font, never in its content.
- **Preserved Word pieces** (equations, fields, bookmarks, comments) are left out of the export if their own text was edited; the edit wins. Inside lists, tables, footnotes and code they are kept as text only.
- **Size limits:**
  - files: `MAX_UPLOAD_SIZE_MB` (10 MB by default) and the plan's limit;
  - request bodies: 25 MB;
  - pasted text: 2,000,000 characters;
  - Word packages: 1,000 entries and 200 MB unpacked;
  - PDFs: 1,000 pages.
- **How much text the AI reads:**
  - structure analysis: the first 160,000 characters or so; the rest is split into paragraphs without the AI, and the document says so;
  - instructions: at most 400 listed elements;
  - style analysis: the first 300 elements.

**Untested in real conditions**

- **The real AI model.** During the transformation the AI paths ran only against the test double, because no API key was set. The Phase 15 prompts, the chunking and Format by Example's labelling have not yet met the real model.
- **Redis, the arq worker, S3 storage and Docker** have never run on this machine. Their code is tested against stand-ins (a fake pool and Redis client, and moto for S3), and CI builds the images.
- **When Redis is down,** rate limits let requests through; the failure is logged.

**Behaviour to be aware of**

- **Rate limits** count per process unless `RATE_LIMIT_BACKEND=redis`.
- **Priority processing** only matters with the arq worker.
- **Usage** is counted from Phase 13 on, and plans apply to personal workspaces.

**Housekeeping gaps**

- Expired and revoked sessions are never deleted. They are refused when used, but the table keeps growing.
- A stored file whose database row was never committed is never swept.
- `formatting_profiles` is unused, and the inline-image path is still open (see C).

**Testing and interface**

- **Browsers:** the end-to-end tests run in Chromium and Edge only.
- **Screenshots:** there is one visual baseline, on Windows.
- **Accessibility:** nothing checks it automatically.
- **Language:** the interface is in English, with no translation layer. The built-in templates have Bulgarian names, and documents can be in any language.

**Hosting and CI**

- **Supabase's Free plan** pauses a project after about a week without activity.
- **CI results** are visible only in the repository's Actions tab, since the repository is private, and the runs use the account's Actions minutes.

## G. What was tested

All suites were run on 2026-09-26, and all passed.

- **Backend:** 643 passed and 1 skipped, in 48 files. The skipped test is the optional run on a private document, `SMARTDOC_REAL_DOCX`. The suite covers:
  - unit tests of the engine, the style system, the render specification, the parsers, Health and the comparison;
  - the API: every router, workspace isolation, errors and versioning;
  - the database: migrations against the models, and the RLS rule;
  - the golden documents and the §45 round trip;
  - jobs, billing and entitlements;
  - security and observability.

  No test touches the real database: each gets its own SQLite file and folder.
- **Frontend:**
  - 46 Vitest tests in 6 files: the golden documents through the real editor, the API client, the confirmation dialog, the plan-limit notice, the billing page and the formatting helpers;
  - `tsc` and ESLint pass without errors;
  - the production build succeeds.
- **End to end:** 16 Playwright tests, run against a production build and a throwaway backend:
  - 15 walk through the workflows of §46: accounts, documents, uploads, templates and Format by Example;
  - 1 compares a screenshot.
- **In CI:** the same suites, plus the migrations on a real PostgreSQL 17 and both images built. The workflow is defined, but only the repository's owner can see its results.
- **By hand, in every phase:** in the browser, against the real Supabase database, on Boril's account, with throwaway data deleted afterwards. Boril's stress-test Word document also passes the §45 round trip.
- **Not tested:**
  - payments in Stripe's test mode;
  - the worker with a real Redis;
  - a real S3 bucket;
  - the Docker images running;
  - the real AI model;
  - load;
  - Firefox and Safari;
  - accessibility.

## H. What to watch in production

These are the signals the app already gives (log lines and endpoints), and what to look for in each.

- **Availability:**
  - Watch `GET /api/ready` and `GET /api/health`, and alert when either fails.
  - When `/api/ready` returns 503, it names the failing check: the database or Redis.
- **Errors:**
  - Watch the rate of 5xx responses. `LOG_REQUESTS=true` logs every request with its status and duration.
  - Each error carries a request id that ties it to its log lines.
- **Jobs** (`job.finished` lines, with type, outcome, duration, AI calls and attempt):
  - the failure rate per type, and how long imports and exports take;
  - attempts above 1, which mean a worker stopped in the middle of a job (a crash or a restart);
  - jobs failed by a restart, and how long jobs wait in the queue;
  - the hourly and daily sweep lines. If they stop appearing, the worker's scheduled jobs aren't running.
- **AI** (`ai.call` lines, with task, duration, tokens and outcome):
  - Watch timeouts, errors and latency.
  - Watch how often a task falls back. The user doesn't see a fallback; they just get a plainer structure.
  - Compare tokens per workspace with what the plan earns.
- **Limits** (the audit events `plan_limit` and `rate_limited`):
  - Which entitlement stops people? That is a pricing signal.
  - Do the rate limits hit real users, or only abuse?
- **Security** (audit events):
  - failed sign-ins, per account and per address;
  - `invalid_file` refusals, cross-site refusals and oversized requests.
- **Billing:**
  - refused webhooks (bad signature) and failed ones;
  - subscriptions in `past_due`;
  - `subscriptions` rows that don't match Stripe's dashboard.
- **Storage:**
  - the size of the asset store per workspace, compared with the plans' storage limits;
  - the images the sweep deletes, and the export files that expire.
- **Database:**
  - connections through the pooler; session mode caps them;
  - slow queries;
  - table growth: `document_versions` (by default 50 steps per document, each a full copy, plus the original), `sessions`, `processing_jobs` (kept 7 days) and `usage_records`;
  - Supabase's advisors, after every migration.
- **Fonts:** the PDF export logs a warning when the server has no TrueType font. It then falls back to the built-in fonts, which have no Cyrillic.
- **Deprecated paths:** requests to `/api/...` without `v1` show up in the request log. Remove the aliases once there are none.
- **Missing signals.** Nothing counts which Word features imports report as unsupported, and nothing reports autosave failures or CSP violations from browsers. Add them before launch: they show what to build next, and when users are about to lose work.

## I. The next most logical product improvements

Per §93, deepen the transformation: a document plus an example or template plus instructions should give a consistent style with the content untouched. Don't grow toward a Word clone.

**Before launch.** These are needed to run the product as a SaaS; they are not features.

1. **The basics of an account:** password reset and e-mail verification, which need an e-mail service; changing a password; and deleting an account together with all its data (§81).
2. **Payments on:** Boril's Stripe account and the real plan limits and prices, both his decision. Then one purchase end to end in Stripe's test mode.
3. **A first deployment:**
   - hosting for the API, the worker and the frontend;
   - a managed Redis and an S3-compatible bucket;
   - Supabase on a paid plan;
   - error tracking, with alerts on the signals in H;
   - a real Anthropic key, and a round of real documents through every AI path.
4. **Housekeeping:** a sweep for expired sessions; drop `formatting_profiles` or give it a use; retire the inline-image path.

**Product, in order of value:**

5. **Review before formatting.** Let people confirm or correct what the AI decided where its confidence is low: heading levels, captions, lists. Today low confidence is only a passive tint. Trust in the structure is what the rest of the promise rests on.
6. **Official requirements as an input of their own** (the unused tier 3). Many people receive a university's or an institution's formatting rules as a document.
   - Read those rules once into a template.
   - Show which rules were understood and which weren't.
   - Reuse the template: "document + requirements → done".
7. **Fixes from Document Health.** Offer deterministic one-click fixes for what Health finds: spacing made of empty paragraphs, hand-typed numbering, stray direct formatting. Add AI explanations of the issues; §38 lets the AI explain, never score.
8. **A table of contents** built from the headings and exported as a real Word field. Nearly every academic and official document needs one.
9. **Batch formatting:** one template or reference applied to many documents at once. It fits the Business plan naturally.
10. **Teams:** invitations, roles, shared templates, and a workspace default for everyone. The data already has visibility and the default. This is what gives the Business plan its meaning.
11. **A Format by Example preview** on the person's own document before anything is saved. Before/after already exists and can be reused here.
12. **Fidelity where people need it.** Count what imports report in `unsupportedFeatures` to decide what to support next. Likely candidates: pictures in tables and lists, text boxes, several columns.
13. **A Bulgarian interface.** The people, the built-in templates and the documents are largely Bulgarian.

**Not next:** Word-clone features such as drawing, free page layout or real-time co-editing. The editor should stay a place to review and adjust, not to typeset by hand.
