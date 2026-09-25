# SmartDoc Formatter

Web app that turns raw pasted text or an uploaded TXT/DOCX/PDF file into a structured, editable document — deterministic parsers or a real AI module figure out the structure (headings, paragraphs, lists, tables, quotes, code blocks, ...), a separate deterministic engine will later apply formatting rules, and a WYSIWYG editor lets you review it before export.

Full requirements: [docs/spec.md](docs/spec.md).

## Status

The original MVP roadmap (docs/spec.md, phases 0-6) is complete. On top of it, the SaaS transformation from `корекции.docx` is under way: its phases 0-16 are done (Postgres with accounts and workspaces, private asset storage, persisted undo, StyleSystem templates, Format by Example, a much more faithful DOCX import and export, one render specification for the editor and both exports, real editor pages, background jobs with real progress, a restructured frontend — typed API client, server state in TanStack Query, the editor split into focused parts, status-aware autosave — a dashboard with the document list, version history with before/after comparison, Document Health and usage metering, plans whose limits the backend enforces, with Stripe subscriptions ready to switch on, and security hardening: uploads checked by what they really are, rate limits, audit logs, secure headers, and AI prompts that keep documents apart from instructions; frontend unit tests, end-to-end tests in a real browser and golden Word documents that must survive import, editing, formatting and export). Progress per task: `saas-transformation-tracker.xlsx`; the plan: [docs/architecture/migration-plan.md](docs/architecture/migration-plan.md).

Built so far: project scaffolding, the Document Model (shared shape between frontend and backend, now with rich inline formatting/lists/tables/code/images), paste-text and file-upload input, real TXT/DOCX/PDF/Markdown parsing, real AI-driven structure analysis for plain prose (via Anthropic), a deterministic formatting rules engine with built-in/custom templates and AI-assisted instruction extraction, a full editor (visually-paginated, a real rich-text toolbar, a clickable heading outline, a Properties panel for live per-element style overrides, a separate undo/redo history for formatting/structural changes, and the interactive Conflict Resolution modal from spec §7.10), and real DOCX/PDF export. See the roadmap in [docs/spec.md#23-development-roadmap](docs/spec.md#23-development-roadmap) for what's next.

**Not built yet**: AI style *inference*, Table-of-Contents generation, and the SaaS phases still ahead (Docker and CI, and the final audit). Payments need Boril's Stripe account and prices first (see "Plans and billing" below).

## Project layout

```
backend/            FastAPI app
  app/
    main.py           FastAPI app, CORS, cross-site-write (Origin) check, request ids, error handlers, router mount, GET /api/health
    config.py         env-based settings (backend/.env); normalizes a pasted Supabase DATABASE_URL
    api/
      errors.py          one body for every error, {code, message, details, request_id}; X-Request-ID on every response; the OpenAPI schema documents it
      deps.py            signed-in user from the session cookie; their workspace; per-request DocumentService (If-Match -> expected revision); the plan checks; the metered AI provider
      auth.py            POST /api/auth/register|login|logout, GET /api/auth/me
      documents.py       GET /api/documents (the list: search, sort, pages), POST /api/documents, POST /api/documents/upload, GET/DELETE /api/documents/{id}, .../versions (list, one, restore), .../compare (before/after), .../health, POST .../format (409 on conflict), PATCH/DELETE .../elements/{id}/style, POST .../undo, POST .../redo, GET .../export/docx, GET .../export/pdf -- all signed-in, scoped to the user's workspaces
      usage.py           GET /api/usage: this month's usage of the workspace, and what it stores
      billing.py         GET /api/billing (plan, usage against its limits, the plans), POST /api/billing/checkout|portal (Stripe pages), POST /api/billing/webhook (Stripe's signed events)
      assets.py          GET /api/assets/{id} (stored images, workspace members only)
      templates.py        /api/templates: list, get, create (blank, from a style system, or from a document), update (If-Match), delete, duplicate, versions + restore, workspace default, live preview, read the style of a reference .docx (Format by Example) -- signed-in
      jobs.py             /api/jobs: import-text, import-file, format, export, extract-reference (each answers 202 with a background job), GET /api/jobs/{id} (its stage, progress, result), GET /api/jobs/{id}/file (a finished export)
      uploads.py          the upload checks every endpoint shares: allowed types, a hard size limit while reading, instructions files
    security/            files.py (what an upload really is: signatures, ZIP limits, safe XML), rate_limit.py (memory or Redis counters), http.py (request-size cap, security headers)
    logging_setup.py     structured logs (text or JSON) with the request id; describe_error() keeps content out of log lines
    audit.py             audit events on the app.audit logger: who did what to which thing, never the content
    billing/             plans.json (the plans and their entitlements), plans.py (loaded and validated at startup), stripe_gateway.py (the few Stripe calls, signature checks), errors.py
    jobs/                background jobs: runner.py (what each kind of job does, and the runner recording its stages), queue.py (in-process, arq or eager), files.py (uploads, export files and old jobs: when each goes)
    worker.py            the arq worker (`arq app.worker.WorkerSettings`): runs jobs, sweeps job files hourly
    db/                  SQLAlchemy models (14 tables) + async engine; schema changes go through alembic/ (see docs/architecture/migration-plan.md)
    repositories/document_repository.py   documents table access, user-scoped lookups
    repositories/template_repository.py   templates visible to a user, their versions, clearing a workspace default
    storage/             StorageProvider: local files (dev) or any S3-compatible service
    models/document.py   the canonical Document Model (Pydantic) -- rich inline/list/table/image content + formatting
    models/base.py       ApiModel, the base of everything the API sends or receives (response fields always sent are required in the schema)
    schemas/
      document.py          API request schema
      formatting.py         element-style and conflict-resolution request schemas
      templates.py          template request/response schemas (TemplateOut carries engine-computed preview styles)
      jobs.py               a job as the client polls it, and the result each kind of job produces
    services/
      document_service.py    every document read/write for one signed-in user: upload dispatch + format_document() + style/content/page changes + undo()/redo(); optimistic concurrency (412 on a stale If-Match)
      version_history.py      persisted, bounded undo/redo (DocumentVersion rows; autosave bursts merge into one step)
      template_service.py      built-in + workspace templates for one signed-in user: access rules, versions, default template, preview
      reference_service.py     Format by Example: a reference .docx in, the StyleSystem it uses out (nothing stored)
      job_service.py           the signed-in user's jobs: queue one, read it back, the latest ones, its export file
      usage_service.py         usage metering: an event per document created, job, export and completed AI call, per workspace and month
      entitlements_service.py   a workspace's plan and every limit check (402 plan_limit); never a plan's name
      billing_service.py        the billing page's summary, Stripe Checkout and portal, webhooks -> the workspace's subscription row
      auth_service.py          argon2id passwords, hashed session tokens, personal workspace on sign-up
      asset_service.py / image_assets.py   stored images (row + blob kept consistent); inline data: images moved into storage
      asset_cleanup.py         the daily sweep of images no document of the workspace uses any more (undo history included)
      ingestion_service.py    routes each input to the right parser (see "How parsing works" below)
    parsers/
      detection.py      looks_like_markdown() heuristic
      markdown.py        deterministic Markdown -> Document Model (markdown-it-py)
      docx.py             deterministic DOCX -> Document Model (python-docx plus the raw XML it doesn't cover)
      docx_styles.py       Word styles (inheritance, theme fonts), numbering, page setup, header/footer -> a StyleSystem
      docx_inline.py        the text inside a paragraph: run formatting, fields, links, notes, checkboxes, tracked changes
      pdf.py               PDF text extraction (pypdf, text-based PDFs only)
      plain_text.py         naive segmenter -- now only the AI-failure fallback
    ai/
      base.py            provider-agnostic interface (NFR-006) + complete_structured()
      anthropic_provider.py   Claude adapter, structured output via messages.parse()
      schemas.py           internal AI response schemas (structure analysis + instruction extraction)
      prompting.py        the rule and the per-call tag that keep a document apart from the instructions (корекции.docx §22)
      structure_analysis.py  prompt, retry/repair loop, text-fidelity check; long text a piece at a time
      instruction_extraction.py  free-text formatting instructions -> FormattingRule[] (same retry/fallback shape)
      semantic_labeling.py   Format by Example: which paragraphs of a reference are headings (labels only, never formatting)
    formatting/
      engine.py            priority-based rule resolution -> resolvedStyles + DocumentSettings (deterministic, no AI); set/clear_element_override() for live per-element overrides; detect_conflicts() for spec §7.10
      priorities.py         the eight resolution tiers as one enum
      style_system.py       StyleSystem (the product-level template model) <-> FormattingRules
      reference_style.py    Format by Example: the StyleSystem a reference document really uses (majority of its text)
      builtin_templates.json   the built-in templates, as StyleSystem data
      templates.py          loads and validates the built-ins
      units.py / colors.py   length/size unit conversion; the colour names every renderer understands
      render_spec.py        the Document Render Specification: page sizes, each block's base look, what inherits from body text, Word's line height
      health.py             Document Health: deterministic checks of a document's formatting, each naming its elements, and a score from them
      compare.py            what changed between two versions: elements added/removed/moved/retyped/edited, style and page-setting changes
    export/
      docx_export.py        Document -> real editable .docx (python-docx), reading the same resolvedStyles the editor renders
      pdf_export.py           Document -> real .pdf (reportlab, independent of docx_export.py -- no LibreOffice on this machine, see below)
      fonts.py                 the TrueType fonts a PDF embeds (PDF_FONT_DIRS, then the system font folders)
      filenames.py              a document title as a safe download name
  scripts/verify_anthropic.py  manual-only connectivity check
  scripts/verify_database.py    manual-only DATABASE_URL check (connection, schema head, rolled-back round trip)
  scripts/migrate_json_documents.py   one-shot import of the old JSON document store into an account
  scripts/export_openapi.py   writes the API's OpenAPI schema to frontend/types/generated/openapi.json (the frontend's types come from it)
  tests/                 pytest (parsers, AI logic via a hand-written fake, formatting engine, API round-trips, the OpenAPI contract, security)
  tests/fixtures/documents/  the golden Word documents (01-simple ... 12-complex), built by scripts/make_golden_documents.py
  scripts/e2e_server.py      a throwaway backend (fresh SQLite, no AI, no Stripe) for the end-to-end tests
  scripts/export_golden_json.py  the golden documents as the editor receives them, for the frontend's tests

frontend/            Next.js (App Router) + TypeScript + Tailwind + TanStack Query
  app/layout.tsx, providers.tsx   root layout; the query client every page shares
  app/page.tsx             Home: the dashboard when signed in, the landing page otherwise
  app/new/page.tsx          the new-document wizard (?mode=upload, ?template=<id>, ?reference=1 preselect)
  app/documents/page.tsx    all documents: search, sort, pages, delete
  app/documents/[id]/page.tsx  editor screen (the document is fetched on the server, then held by the editor)
  app/documents/[id]/compare/page.tsx  before/after: two versions side by side, changes marked and listed
  app/templates/page.tsx      template library
  app/templates/[id]/page.tsx  template editor (live preview, version history)
  app/settings/billing/page.tsx  plan and billing: usage against the limits, the plans, Stripe Checkout and portal
  components/                app-wide pieces
    CreateDocumentWizard.tsx  template -> paste or upload -> formatting; its processing screen shows each job's real steps
    dashboard/Dashboard.tsx   quick actions, recent documents, templates, usage, recent exports
    documents/                DocumentList, CompareView (before/after), DocumentPreview (a version read-only, changes marked)
    billing/BillingPage.tsx   the plan, its status, usage meters, plan cards; waits for Stripe after checkout
    PlanLimitBanner.tsx       offers the billing page whenever the plan refuses something (any 402 plan_limit)
    Landing.tsx, ConfirmDialog.tsx
    AppHeader.tsx, AccountMenu.tsx, AuthForm.tsx, SidePanel.tsx (icon rail + flyout; over the content below 1100 px)
    JobProgressBar.tsx              a background job's real stage and percentage
    ReferenceStyleSummary.tsx         what Format by Example read from a reference: main styles in words, a sample page, notes
    TemplatePreviewSample.tsx         miniature page in a template's real look (engine-computed styles)
    templates/                        TemplateLibrary, TemplateEditor, StyleSystemForm, StylePreviewPage, TemplateHistory, fields
  editor/                    the document editor (see "How the frontend is organized" below)
    DocumentEditorShell.tsx   lays the editor out and wires its parts together
    EditorState.tsx           what the panels share (document, editor, selection) and `change`, the one way a change reaches the document
    EditorCanvas.tsx          the pages: one sheet per page, header/footer on each, the editor over them
    EditorToolbar.tsx, RichTextToolbar.tsx   the toolbar row: character formatting saved with the text, alignment saved as the element's style, lists and checklists
    EditorActionBar.tsx, EditorStatusBar.tsx, EditableTitle.tsx, ExportMenu.tsx, AddElementMenu.tsx, ConflictModal.tsx, StyleAnalysisModal.tsx
    useDocument.ts            the document as server state (query cache), and whether it changed elsewhere
    useAutoSave.ts            debounced, one-at-a-time saving of typing, with its status (Saving/Saved/Failed/Offline/Conflict)
    useFormatting.ts, useHistory.ts, useSelection.ts, useExport.ts, usePageSettings.ts   formatting jobs, undo/redo, what is selected, export jobs, page geometry and zoom
    panels/                   TemplatesPanel, InstructionsPanel, PageSettingsPanel, StructurePanel, HistoryPanel, HealthPanel, PropertiesPanel + PropertiesSidebar (a column, or over the pages below 1100 px)
    changeHighlight.ts        marks the blocks that changed between two versions (a decoration, for the before/after previews)
    documentToTiptap.ts      Document Model -> Tiptap JSON, all element types + inline marks + resolved styles + elementId
    tiptapToDocument.ts      the editor's content back to elements, keeping each element's id
    extensions.ts             StarterKit + Table + Image + TaskList/TaskItem + ConfidenceIndicator + AppliedStyle + ElementId + text/font/colour/super-/subscript extensions
    pagination.ts              lays the document out on pages: a block that doesn't fit moves to the next page; reports the page count
    fontStack.ts                font name -> CSS font stack with a fallback of the same kind
    tableCellBackground.ts       table cell shading
    confidenceIndicator.ts     passive low-confidence visual marker (no interaction yet)
    appliedStyle.ts             renders Document.resolvedStyles as real inline CSS per node
    elementId.ts                 renders Element.id as data-element-id + getSelectedElementId() (selection -> Element)
    fontSize.ts                   custom textStyle-based font-size mark (Tiptap ships no official one)
    useEditorForceUpdate.ts        shared transaction/selection subscription hook (toolbar and selection)
    pageGeometry.ts                 CSS pixels per millimetre (page sizes come from the backend's render specification)
    cssStyle.ts                      engine CSS -> React style objects, for previews
  services/api/              the typed API client: client.ts (HTTP, ApiError/NetworkError, request ids), auth, documents (write queue + revisions), jobs (polled by waitForJob), templates, assets, usage, billing
  services/queries.ts        TanStack Query keys and hooks: signed-in user, templates and their versions, style previews, the document list, versions, comparisons, health, usage, billing (polled after checkout), recent exports
  lib/                       useDebouncedValue, useMediaQuery, format (dates, sizes, source types)
  types/generated/           openapi.json (from backend/scripts/export_openapi.py) and api.ts (npm run generate-types)
  types/document.ts           the names the app uses for the generated API types, plus frontend-only ones
  *.test.ts(x), tests/        Vitest + React Testing Library (npm test); tests/fixtures/golden holds the golden documents as JSON
  e2e/                        Playwright end-to-end tests (npm run test:e2e), with the approved editor screenshot

docs/spec.md          full spec, kept in-repo
roadmap-tracker.xlsx  phase/acceptance-criteria checklist
```

## Setup

### Backend

```powershell
cd backend
py -3 -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
```

`.env` already exists locally (gitignored) with `ANTHROPIC_API_KEY` blank. Fill in your own key to exercise the real AI structure-analysis path — see [.env.example](backend/.env.example) for the shape. **Without a key, the app still works**: anything that would need AI (plain unstructured prose) automatically falls back to the naive segmenter instead of erroring.

**A database is required.** Documents, accounts and image assets live in PostgreSQL (the project's database is on Supabase). `backend/.env` (gitignored) holds it as `DATABASE_URL=...`: a Supabase **session pooler** connection string, not the port-6543 transaction pooler, which breaks the async driver. The backend switches a pasted `postgres://`/`postgresql://` string to the async driver and enforces TLS. The backend logs in as a dedicated role that can read and write data but not change the schema; schema changes are applied separately (see [docs/architecture/migration-plan.md](docs/architecture/migration-plan.md)). Check the connection:

```powershell
.\venv\Scripts\python.exe -m scripts.verify_database   # connection, schema version, a rolled-back round trip
```

Every page except the landing page needs an account: register at `http://localhost:3000/register`. Documents from the old pre-database JSON store (`backend/data/documents/`) can be imported into your account once you've registered — `.\venv\Scripts\python.exe -m scripts.migrate_json_documents --owner-email you@example.com` (add `--dry-run` first to preview; the JSON files are never modified).

Run the dev server:

```powershell
.\venv\Scripts\fastapi.exe dev app\main.py
```

Runs on `http://localhost:8000`.

> **Reload quirk found this session**: uvicorn's `--reload` (via WatchFiles) sometimes doesn't pick up every edit during a long, heavy editing session — a live request kept hitting pre-edit code with no new "Started server process" line in the log after the reload trigger fired. If behavior doesn't match what you just changed, stop the task and start the dev server fresh rather than trusting the auto-reload.

### Frontend

```powershell
cd frontend
npm install
npm run dev
```

Runs on `http://localhost:3000`. `.env.local` already exists locally pointing at the backend above.

The API types are generated from the backend. After changing the API, regenerate them (no server needed), then check the frontend still compiles:

```powershell
cd backend; .\venv\Scripts\python.exe -m scripts.export_openapi
cd ..\frontend; npm run generate-types; npx tsc --noEmit
```

> A `.claude/launch.json` exists for Claude Code's own preview tooling, but starting servers *by that config's name* resolves against the wrong project folder in this workspace (a tooling quirk, not a project bug) — start both servers directly with the commands above instead, then open `http://localhost:3000` in a browser.

### Tests

```powershell
cd backend
.\venv\Scripts\python.exe -m pytest          # backend: unit, API, golden documents, security
cd ..\frontend
npm test                                     # frontend: Vitest + React Testing Library
npm run test:e2e                             # end to end: Playwright, a real browser, the whole app
```

Tests never touch the real database or `backend/data/`: each API test gets its own SQLite file and asset directory, and the end-to-end run starts its own backend over a fresh SQLite database (see "Testing" below).

No test hits the real Anthropic API — AI-path tests use a hand-written `FakeAIProvider` (`backend/tests/fakes.py`) swapped in via FastAPI's dependency override, not by mocking the `anthropic` SDK's internals.

### Verifying the Anthropic adapter directly

Independent of the rest of the app:

```powershell
cd backend
.\venv\Scripts\python.exe -m scripts.verify_anthropic
```

## How parsing/structure-analysis works

Content is routed to the cheapest reliable method for what it actually is, reserving the LLM for genuinely ambiguous plain prose:

1. **`.docx` upload** → `parsers/docx.py` reads the file's own structure and formatting directly (see "How DOCX import works" below). Deterministic, `confidence=1.0`, **no AI call**.
2. **Everything else** (paste, `.txt` upload, `.pdf` upload) reduces to plain text first (PDF via `pypdf` text extraction), then:
   - If it **looks like Markdown** (`parsers/detection.py`'s tiered heuristic: an ATX heading/fenced code/table row alone is enough; bold+link+blockquote need two together; a lone list marker never counts) → `parsers/markdown.py` parses it deterministically (headings, nested/checklist lists, tables with alignment, blockquotes, fenced code, inline marks). `confidence=1.0`, **no AI call**.
   - Otherwise → `ai/structure_analysis.py` sends it to Claude via a schema-constrained `messages.parse()` call, with a text-fidelity check on top of schema validation (the AI must never alter the original text — spec §13) and one retry. If the AI call fails entirely (no API key, network error, refusal, or still-invalid output after retry) it **falls back to the naive `plain_text.py` segmenter** rather than erroring the request.

The editor (`editor/documentToTiptap.ts`) renders every element type this can now produce — headings, paragraphs with inline bold/italic/underline/strike/code/links, superscript/subscript, fonts, sizes, colours and highlights, nested bullet/ordered lists, checklists with real checkboxes (Tiptap's `TaskList`/`TaskItem`), tables with merged cells and cell shading, blockquotes, fenced code blocks with language, horizontal rules, and images (DOCX-embedded pictures are stored as assets and load from `/api/assets/{id}`; pictures inside table cells or list items, and non-web formats like EMF, are reported in the document's `unsupportedFeatures` instead). Elements below a confidence threshold (0.6, tunable) get a subtle left-border tint — passive only, no accept/reject UI yet (see Assumptions below for why).

## How DOCX import works (SaaS Phase 9)

- **The document keeps its own look.** Its Word styles, with their inheritance (`basedOn`) and theme fonts, become a style system at their own priority tier, *source document* (6): above the defaults and below every template, so an imported document looks like the original and applying a template still restyles it. A paragraph that differs from its style (a centred line, a larger title, another font) gets its own rule at the same tier. Formatting that is the same across a whole paragraph is lifted to the paragraph; formatting that varies inside it stays on the text as marks (font, size, colour, highlight, superscript/subscript, code).
- **What comes across**: headings (by style or outline level), bulleted and numbered lists from Word's numbering (including numbering defined by a style, and nesting), checklists (paragraphs starting with a checkbox: a Word checkbox control, a Wingdings box or a ☐/☒ character), tables with merged cells, cell shading and column alignment, images with their size and alignment, captions ("Фигура 1: …", "Table 2. …"), quotes, code (paragraphs set in a monospace font), page breaks, horizontal rules, hyperlinks and e-mail links (http/https/mailto/tel/ftp only), footnotes and endnotes (moved to the end of the document with their numbers), page size, orientation and margins, and the header and footer, whose page-number fields become `{PAGE}`/`{NUMPAGES}`. The title comes from the file's properties when it has one.
- **Kept for Word, not shown in the editor** (the preservation layer, корекции.docx §11): equations show as linear text, Word fields (dates, cross-references) as the text they last had, links to bookmarks as plain text, and bookmarks and comments not at all. Each is kept with its paragraph in `Element.preservedAttributes["ooxml"]`, together with where its text sits, and the DOCX export puts it back: the original equation (OMML), the real field, the bookmark, the internal link, the comment with its author and date. The export looks for each one's text in the paragraph as it is now, so edits elsewhere in the paragraph don't matter; if that text itself was changed, the piece is dropped and the edited text stays. Everything in `preservedAttributes` comes back from the browser on each autosave, so the export validates it and leaves out anything malformed. Inside lists, tables, footnotes and code these pieces are kept only as text, with a note (`tests/test_docx_preservation.py`).
- **What doesn't, and says so**: everything the importer can't keep is listed in the document's `unsupportedFeatures`, never dropped silently: several columns (shown as one), floating pictures (placed in line with the text), drop caps (normal text), text boxes (ordinary paragraphs), tracked changes (imported as accepted), a table of contents (plain text), watermarks and first-page/even-page headers (left out), embedded objects and charts, old-format (VML) pictures, symbol-font characters, and images inside table cells or list items.
- **Tests**: `tests/test_docx_fidelity.py` covers each of the above with a small generated document, and `tests/test_export_round_trip.py` exports documents to DOCX and imports them again (structure, character formatting, checklists, nested list levels, table spans and shading, page setup and footer fields) and checks the PDF's Cyrillic text and page numbers. A real Word stress-test document (headings 1–6, every character format, nested lists, complex tables, images, captions, notes, fields, columns, a checklist) was also checked by hand: exported to DOCX and imported again, it gives the same elements and text. That file isn't in the repository.

## How the formatting engine works

The `Element.styleRef`/`Document.templateId`/`Document.formattingRules`/`Document.settings` fields existed as unused placeholders since Phase 0-1 — this phase gives them real behaviour via `POST /api/documents/{id}/format`:

1. **Pick a source of rules**: a built-in template (see `formatting/builtin_templates.json`), one of your workspace's own templates (see "How templates work" below), and/or free-text formatting instructions (typed directly, or extracted from an uploaded `.txt`/`.pdf` instructions file via `ai/instruction_extraction.py` — the same Claude `messages.parse()` + retry + graceful-fallback-to-no-rules shape as structure analysis, just producing `FormattingRule`s instead of `Element`s).
2. **Resolve deterministically**: `formatting/engine.py::resolve_styles()` merges every rule source by spec §7.9's priority order (lower number wins) and converts the winners into real CSS per element-type target (`"Heading 1"`, `"Paragraph"`, `"Table"`, `"Image"`, ...); page-level properties (page size, margins, header/footer/page numbers) resolve separately into `Document.settings` via `extract_settings()`, since no single element owns them. Fully deterministic (NFR-007) — the AI is only ever involved in turning *instructions* into rules, never in applying them.
3. **The editor renders the result**: `documentToTiptap.ts` looks up each element's resolved style by `styleRef` and attaches it as a real inline `style="..."` attribute (via the new `AppliedStyle` Tiptap extension); `DocumentEditor.tsx` lays the document out on pages of `Document.settings`' size and margins, with the header, footer and page number on every page (see "How the pages / toolbar / outline work" below).

## How templates work (SaaS Phase 7)

- **A template is a `StyleSystem`** (`formatting/style_system.py`, корекции.docx §19): the look of a document described the way people think about it, not as loose rules. It covers the page (size, orientation, margins), text everywhere (a document-wide font and colour), body text, headings 1-6, lists, tables, captions, quotes, footnotes, code blocks, images, and the header and footer. Any field can be left unset, meaning "not decided here". `FormattingRule` stays the engine's internal mechanism: `compile_rules()` turns a style system into rules, always the same rules for the same input, and `style_system_from_rules()` goes back the other way (used to save a document's current look as a template). Anything that can't be represented is reported, never silently dropped.
- **Priority tiers are one enum**, `formatting/priorities.py`: live override 1, instruction 2, imported requirement 3, custom template 4, built-in template 5, source document 6 (an uploaded file's own formatting), AI inference 7, default 8. Tiers 3 and 7 have no producer yet but are named, so no numbers are hard-coded anywhere.
- **Built-in templates are data**: `formatting/builtin_templates.json`, validated when the backend starts, so a typo stops startup instead of breaking later. The original three compile to exactly the rules they had before (regression-tested). Two new ones use more of the style system: Модерен доклад and Договор / юридически текст.
- **Your own templates live in the database**, per workspace. Each row holds the style system, the rules it compiled to when saved, a version number, who can see it (the whole workspace or only its creator), and the document it was saved from. Every save adds a `template_versions` row recording who saved and when. The last `TEMPLATE_HISTORY_MAX_VERSIONS` (default 50) are kept, and any of them can be restored; a restore is saved as a new version. Saves carry the version they started from (`If-Match`), so two tabs can't overwrite each other silently: the second gets a 412 and can reload or save over it.
- **Who can do what**: a template is visible to its workspace's members (a private one only to its creator). Its creator or the workspace owner can edit, rename or delete it; only the creator can change who sees it. Only the owner sets the workspace default, and only to a template the whole workspace can see. Built-ins are read-only; duplicate one to customize it.
- **The workspace default template** is preselected in the new-document wizard. Deleting a template clears it as the default. Documents formatted with a deleted template keep their formatting, because each document holds its own copy of the rules.
- **Screens**: `/templates` is the library (new, duplicate, make default, rename, delete). `/templates/{id}` is the editor: every style-system field, a live page preview resolved by the real engine (`POST /api/templates/preview`), and version history with restore. In the document editor, the Templates panel links to the library and can save the document's current look as a template; changes made to a single paragraph are not included.
- **Import from Word**: the library's "Import from Word" reads a .docx with Format by Example (below), shows what it read, and saves it as a template to review in the editor.
- **Not yet**: choosing who sees a template has no UI, since every workspace has a single member until invitations exist.

## How Format by Example works (SaaS Phase 8)

корекции.docx §17: "make my document look like that one". You give a reference Word document; its look becomes a StyleSystem, and the deterministic engine applies it to your document. Your text never changes.

- **Reading the reference** (`POST /api/templates/extract`, `formatting/reference_style.py`): the reference goes through the normal DOCX importer, then for each kind of text (body, headings 1-6, lists, tables, captions, quotes, footnotes, code) every property takes the value that most of that text has, weighted by length. Formatting applied by hand therefore counts as much as Word's styles: a reference whose Normal style says Calibri 11 but whose paragraphs are all set in Times New Roman 12 gives Times New Roman 12. Kinds of text the reference doesn't use keep its style definitions. Page size, orientation and margins come along, and so does a footer or header that holds page numbers (`{PAGE}`/`{NUMPAGES}`). Other header or footer text belongs to the reference's own content, so it isn't copied; a note says so. Picture alignment is taken when most pictures share it, and a width only when most pictures have the same width.
- **Headings without heading styles**: many documents make headings by hand, as bold or larger Normal paragraphs. When the reference uses no heading styles at all, the short paragraphs that stand out from the body text (at least 1 pt larger, or bold where the body isn't) become headings, levelled by size. When an AI provider is configured, it is asked instead (`ai/semantic_labeling.py`): it only labels paragraphs as heading (with a level), body or caption, and its answer is thrown away if it names a paragraph that doesn't exist, gives no level, or calls most paragraphs headings. Either way, how the headings look is read from the document. The AI is never asked when the reference uses heading styles.
- **Nothing is stored until you choose**: the extract call returns the style system, a preview (the engine's own resolved styles), a plain-language summary and notes. Applying it saves it as a template first (named after the file, numbered if the name is taken), then formats with that template, so it re-applies, edits and reuses like any other and survives a later reformat.
- **Where**: the editor's Templates panel ("Match another document": review, then apply or only save), the new-document wizard ("Match a reference document", applied when the document is created), and the template library ("Import from Word", opens the saved template in the editor).
- **Tests**: `tests/test_reference_style.py` (styles, majority look, headings by look and by a fake AI, AI answers that aren't trusted, header/footer, pictures) and the extract tests in `tests/test_templates_api.py` (read, save, format, a unique name, wrong files). Checked live: a hand-formatted reference (no heading styles) applied from the editor panel, the wizard and the library.

## The Document Render Specification (SaaS Phase 10)

корекции.docx §23: the editor preview, the DOCX export and the PDF export draw from one specification, `formatting/render_spec.py`, instead of three copies of page sizes and heading spacing.

- **Page sizes**: one table with Word's exact sizes (A4 210x297 mm, Letter 8.5x11 in, Legal 8.5x14 in). Both exporters and the DOCX importer's size detection use it, and the editor reads a document's page size from `DocumentSettings.pageWidthMm`/`pageHeightMm` (computed from the table), so the frontend keeps no table of its own.
- **The base look of every kind of block**: body text (Arial 11 pt, 8 pt after), headings 1-6 (20/16/14/12/11/11 pt, bold, their own spacing), lists, tables, quotes (italic, 1 cm indent), captions (9 pt italic), footnotes (9 pt) and code (Courier New 10 pt). These are the engine's lowest-priority rules. They are always resolved after a document's own rules, so documents saved before a default existed get it too.
- **Inheritance from body text**, as Word styles are based on Normal: headings take the body font and colour unless they set their own; lists and quotes also take its size, line spacing and alignment; tables, captions and footnotes take what fits them. So a template that only sets the body font gets it everywhere.
- **Line spacing as Word counts it**: Word's single spacing is a font's own line height, about 1.15x its size. A line spacing of N is written into the resolved style as `line-height: N x 1.15` for the editor and the PDF, and as `--line-spacing: N` for the DOCX export and the Properties panel, so all three put the same number of lines on a page.
- **Resolved styles are derived, never trusted from storage**: they are worked out again whenever a document is created or read, so a change to the specification reaches every document, in the editor and in both exports.
- **Editor CSS** now defers to the resolved styles: no spacing of its own for paragraphs, list items, cells and quotes, and code in the same light grey box both exports draw.
- **Tests**: `tests/test_render_spec.py`, the native-styles tests in `tests/test_docx_export.py`, and an API test that a pasted document comes back with the full look. A DOCX export and re-import of Boril's stress-test document gives the same look per kind and per paragraph (apart from an explicit "left" on headings), and every export passes the OOXML schema check.

## How background jobs work (SaaS Phase 11)

корекции.docx §52/§53: parsing, AI calls and rendering don't run inside the request any more, and the app shows what is really happening instead of a spinner that either finishes or times out.

- **Every heavy action is a job** (`api/jobs.py`): importing pasted text or a file, formatting (template and/or instructions), exporting DOCX/PDF and reading a reference document (Format by Example). The endpoint checks what it can at once (file type and size, access to the document), stores an uploaded file, and answers `202` with the job. `GET /api/jobs/{id}` then gives its status (pending, running, succeeded, failed), its stage (queued, uploading, parsing, analyzing, formatting, rendering, finalizing, complete) and its progress, both written only as real steps finish, and finally its result: the new document's id, the formatting outcome (applied, or the conflicts to resolve), the export to download from `GET /api/jobs/{id}/file`, or the reference's style. A job is its starter's alone. A failure the user can act on keeps its reason ("not a valid .docx file", "changed in another tab"); anything unexpected is logged on the server and reported as a generic message.
- **Where jobs run** (`JOB_BACKEND`, `jobs/queue.py`): `background` (the default) runs them in the API process right after the request, for development; a restart fails whatever was running, so nobody polls it forever. `arq` hands them to a separate worker through Redis, for production: set `REDIS_URL` and run `arq app.worker.WorkerSettings` next to the API. A worker that dies mid-job is retried (up to 3 tries, 10 minutes each), and a finished job never runs again. If a job can't be handed to Redis, it fails at once with a 503 instead of waiting forever. Tests run jobs inside the request (`eager`). All three use the same `JobRunner` and the same `processing_jobs` rows, so the API and the frontend can't tell them apart.
- **In the app**: `services/api.ts` polls a job (every 300 ms at first, slowing to 1.5 s) and reports each stage. The new-document wizard lists the steps of the import and of the formatting as they happen; the formatting panels, the conflict dialog, Format by Example, the template library's import and the export menu show a progress bar where the action was started. While formatting runs the pages are read-only, since its result replaces them, and the formatting job holds the document's write queue, so an autosave waits for it and then goes out with the new revision instead of failing. An export first saves any typing not yet saved, so the file has what is on screen.
- **What jobs leave behind** (`jobs/files.py`): an upload is deleted once its job has run. An export's file is kept for `JOB_FILE_TTL_HOURS` (default 24), and goes at once when its document is deleted. A finished job keeps no copy of pasted text or instructions. Job records are kept for `JOB_RETENTION_DAYS` (default 7). An hourly sweep does the timed part, in the worker or, with in-process jobs, in the API.
- **Images nobody uses** (`services/asset_cleanup.py`, the half of Phase 4's asset storage that waited for a sweep): once a day, an image goes when no document of its workspace refers to it, neither in its content nor in its undo history, and it is more than a day old. Deleting a document leaves its images to this sweep, because an image copied into another document of the workspace still points at them. The database row goes first and the file after, so a failure in between leaves an unused file, never a missing image.
- **The earlier synchronous endpoints stay** (`POST /api/documents`, `.../upload`, `.../format`, `GET .../export/docx|pdf`) for API clients and tests; the app itself uses jobs.
- **Tests**: `tests/test_jobs.py` (every kind of job over the API, conflicts, failures with and without a reason, expiry, deleting a document, no text kept, a queue that can't be reached, the sweep, restart handling, the in-process queue and the arq worker) and `tests/test_asset_cleanup.py` (images in use, in the undo history, copied into another document, too new, or used only from another workspace).

## How the frontend is organized (SaaS Phase 12)

корекции.docx §27 (editor architecture), §28 (server state), §29 (autosave) and §49 (API client).

- **A typed API client** (`services/api/`): one module per part of the API over one `apiFetch`, which sends the session cookie, sends a signed-out user to /login and back, and turns every failure into an `ApiError` carrying the backend's error body -- `message` (written for people, shown as it is), `code`, `details` and `requestId` -- or a `NetworkError` when no answer came. The backend sends that one body for every error (`app/api/errors.py`): validation errors name the fields but never echo what was sent, and an unexpected failure is a plain 500 whose detail goes to the log under its request id. Every response carries `X-Request-ID`, the caller's own when it sends a sane one.
- **Types come from the backend.** `types/document.ts` only names the types generated from the backend's OpenAPI schema (`types/generated/api.ts`), so the Pydantic models are their one source of truth. Response schemas mark every field the backend always sends as required (`app/models/base.py`), and job results and the error body are described too. The schema is a committed file: after changing the API, run `.\venv\Scripts\python.exe -m scripts.export_openapi` in backend/ and `npm run generate-types` in frontend/; `tests/test_openapi_contract.py` fails until then.
- **Server state in TanStack Query** (`app/providers.tsx`, `services/queries.ts`): the signed-in user, the templates (fetched again when the tab regains focus, since the library often sits in another tab), a template and its versions, and style previews (keyed by the style, so one seen before comes back at once) live in the query cache, and a change invalidates what it affects. The document being edited is there too (`editor/useDocument.ts`), starting from the version the page was rendered with and replaced by each change's response; what the editor holds while you type stays local to it. No other state library.
- **The editor in parts** (`editor/`): `DocumentEditorShell` only lays out and wires; `useDocument`, `useAutoSave`, `useFormatting`, `useHistory`, `useSelection`, `useExport` and `usePageSettings` each own one concern; `EditorCanvas` draws the pages; the panels read what they need from `EditorState` rather than through long prop lists. Every change to the document goes through `change`: typing not yet saved goes first (and a failed save stops the change instead of letting it overwrite the typing), then the change, then its result replaces the editor's content with the cursor kept where it was.
- **Autosave** (`editor/useAutoSave.ts`): one request a moment (1.2 s) after typing stops, never one per key, and one at a time; `flush()` resolves only once everything typed before it is saved. The status bar says Saving…, Saved, Failed to save (retried after 5 s, 15 s and 60 s, or at once with Retry), Offline (retried when the connection is back) or Conflict (changed elsewhere: nothing more is sent until a reload, which the banner offers). Leaving the page with something unsaved asks first; leaving the editor for another page of the app saves what is pending.
- **Narrow screens**: below 1100 px the side panels and the Properties sidebar open over the pages instead of squeezing them (the toolbar gets a Properties button), and the Templates panel starts closed.
- **Checked live**: typing (23 keystrokes, one save), a template applied (the pages read-only meanwhile), a Properties override undone and redone, page margins, a new page and paragraph, renaming, an export that included typing done just before it, a write from "another tab" (Conflict; further changes refused without a request), the backend stopped while typing (Failed to save, retried, saved once it was back), Format by Example, the template editor (save, history, restore, delete, live preview) and the narrow layout. Frontend tests come in Phase 16.

## Dashboard, documents, versions and Document Health (SaaS Phase 13)

корекции.docx §64 (dashboard), §32 (deleting), §31 (versions), §39 (before/after), §38 (Document Health) and §36 (usage).

- **Dashboard**: signed in, `/` shows quick actions (paste, upload, match a document, templates), the latest documents with their status, templates (each can start a new document, `/new?template=<id>`), this month's usage and the recent exports with their downloads while they last. Signed out, it is the landing page.
- **All documents** (`/documents`, `GET /api/documents`): title, when it last changed, where it came from, and its status -- Draft, or Formatted with the template's name (`documents.formatted_at`, set whenever a template or instructions are applied; migration `ee14c191e210`, which also marked the documents already formatted). Search by title (case-insensitive, `%` and `_` taken literally), sort by last change, creation or title, 20 per page; the list reads a few fields, never whole documents. Deleting asks first and is for good: the document, its version history and its export files go at once, its images with the next unused-image sweep.
- **Versions** (the editor's History panel, `.../versions`): every kept version says what it did ("Created from pasted text", "Applied formatting (template: …)", "Renamed to …", "Edited the text", "Restored version 2"), who and when, and which one the document shows now. The original is never trimmed, whatever `DOCUMENT_HISTORY_MAX_STEPS` says, so it can always be compared with and restored. Restoring is saved as a new change, so it can itself be undone.
- **Before and after** (`/documents/{id}/compare`, `.../compare?from=&to=`): two versions side by side, drawn exactly as the editor draws them, with the blocks that changed marked (added, removed, edited, moved, changed kind), and beside them what changed: content, formatting per kind of text and per block formatted on its own (as the settings people change: line spacing rather than the line height it produces, a picture's alignment rather than its margins), and page setup. By default the original against now; any two versions can be picked, and the "before" one restored.
- **Document Health** (the editor's Health panel, `.../health`): eleven deterministic checks of the saved document -- structure (headings in long text, skipped levels), fonts, heading sizes, spacing (including empty paragraphs used as space), direct formatting, numbering (hand-numbered headings with gaps, numbered lists with typed numbers), alignment, tables, captions, page breaks and links (checked as written, not visited). The score comes from them alone, weighted, a warning counting half; checks that don't apply are left out. Each issue can show its blocks in the editor. No AI is involved (§38: an AI may later explain, never score).
- **Usage** (`GET /api/usage`, `services/usage_service.py`): documents created, processing jobs, exports and completed AI calls are counted on the backend as they happen, one `usage_records` row per event and calendar month (UTC); storage is measured when asked. A job's AI calls and export count even if the job fails later. Phase 14's plan limits read the same rows. Counting started with this phase, so earlier activity isn't in it.
- **Tests**: `tests/test_document_management.py` (list, search, sort, pages, privacy, versions, restore with If-Match, before/after, delete), `tests/test_compare.py`, `tests/test_health.py` (every check, the score, the endpoint), `tests/test_usage.py`. Checked live against Boril's account with a throwaway document (deleted afterwards): the dashboard, the list and its Cyrillic search, History (rename, restore), Health (a numbering gap found and shown), before/after with content and formatting changes, and deleting from the list. Checked live against the real database with the in-process backend: paste and DOCX import, formatting with and without instructions, a conflict resolved in the dialog, exports, Format by Example from the editor, the wizard and the library, and a broken file's error.

## Plans and billing (SaaS Phase 14)

корекции.docx §35 (billing through entitlements, never `if plan == "pro"`) and §36 (limits checked on the backend).

- **Plans are data** (`backend/app/billing/plans.json`, validated when the backend starts): Free, Pro and Business, each with its entitlements: DOCX and PDF export, how many documents, the largest file, AI operations per calendar month (UTC), templates of your own, storage, and priority processing. `null` means unlimited. **The limits and prices in it are placeholders**: what each plan costs and allows is Boril's decision. Edit the file and restart the backend; nothing else changes, because no code checks a plan's name.
- **Enforced on the backend, before the work** (`services/entitlements_service.py`): a new document (however it is made: paste, upload, background job or direct endpoint), a file's size, an export's format, a new template, stored images (storage), and AI work. A refusal is a `402` with code `plan_limit`, `details` (the entitlement, its limit, what is used) and a message saying how to go on. Work that is all AI (instructions, style analysis) is refused up front once the month's AI operations are used up; where the AI only helps (the structure of pasted prose, which paragraphs of a reference are headings) it falls back exactly as when no AI is configured. The allowance counts the calls a request or job has already made, so a retry can't go over it. No plan takes a file over the server's own cap, `MAX_UPLOAD_SIZE_MB` (default 10): raise it for plans that promise more.
- **A workspace's plan** comes from its `subscriptions` row (one per workspace): the row's plan while its status is active, trialing or past_due; otherwise, and without a row, Free.
- **Stripe** (`services/billing_service.py`, `billing/stripe_gateway.py`, `api/billing.py`): `POST /api/billing/checkout` opens Stripe Checkout for a paid plan (the workspace's id goes on the checkout and on the subscription it creates), `POST /api/billing/portal` opens Stripe's billing portal (change plan, card, invoices, cancel), and `POST /api/billing/webhook` takes Stripe's events. An event is refused unless its `Stripe-Signature` checks out. The subscription it is about is then fetched from Stripe as it is now, since events can arrive late, twice or out of order, and written to the workspace's row: the plan (from the price id), status, period end, and whether it ends there. News about a subscription the workspace has since replaced is ignored. The plan changes only when Stripe says so, never when the checkout page opens.
- **Priority processing**: with the arq worker, a job of a plan that includes it is queued as if it had already waited ten minutes, so it goes ahead of the jobs queued since (arq takes the oldest first). In-process jobs never wait, so there it changes nothing.
- **In the app**: `/settings/billing` (the card icon in the header, or the plan link on the dashboard) shows the plan, its status and when it renews or ends, usage against each limit, and the plans, with Upgrade (Stripe Checkout) or "Change in billing portal". Back from Checkout it waits for Stripe's webhook to switch the plan. Wherever the plan refuses something, a notice offers the billing page.
- **To switch payments on** (needs Boril): in Stripe, create a product with a recurring price for each paid plan and turn on the customer portal; add a webhook endpoint at `<backend URL>/api/billing/webhook` for `checkout.session.completed` and `customer.subscription.*`. Then set `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_PRICE_PRO`, `STRIPE_PRICE_BUSINESS` and `FRONTEND_URL` in `backend/.env`, and each paid plan's `priceLabel` in plans.json. For local testing, `stripe listen --forward-to localhost:8000/api/billing/webhook` prints a webhook secret. Until then everyone is on Free, and the billing page says paid plans aren't available yet.
- **Not yet**: plans apply to a user's own workspace; shared workspaces (invitations) don't exist yet.
- **Tests**: `tests/test_entitlements.py` (each limit on every way in, AI fallbacks and the in-request count, subscription states, priority queueing) and `tests/test_billing.py` (the summary, checkout, the portal, and webhooks through the real Stripe signature check with Stripe's API stood in for: a completed checkout, plan changes, cancellation, replays, stale and unrelated events). Migration `85211092fe4c` adds `subscriptions.cancel_at_period_end` and indexes for the webhooks' lookups. Checked live: the billing page on Boril's account (Free, real usage) at phone and desktop widths, and the limit notice.

## Security and observability (SaaS Phase 15)

корекции.docx §33 (security), §34, §76 (rate limiting), §20-22 (AI limits and prompt safety), §51 (observability) and §81 (privacy).

- **Uploads are judged by their bytes** (`security/files.py`), not their name or the type the browser declares: a .docx has to be a ZIP package with `[Content_Types].xml`, a .pdf has to start as one, a .txt must not be binary, and a declared type that contradicts the extension is refused. Old .doc and password-protected Word files are named as such. The browser's type is replaced by the real one before a job stores the file. A refusal is `400 invalid_file`, before anything is queued or parsed.
- **Zip bombs and hostile XML**: before python-docx opens a package, its entries are counted (at most 1,000), each XML part capped at 50 MB unpacked, the whole at 200 MB, and any entry unpacking to more than 100 times its size refused; entries with absolute or `..` paths, or encrypted, are refused too. Python's zipfile never unpacks past an entry's declared size, so the declared sizes are what's checked. The raw XML the importer parses itself goes through a parser that resolves no entities and loads no DTDs (no XXE, no "billion laughs"). A PDF may have up to 1,000 pages, and anything a malformed one makes pypdf throw is a refusal, never a crash. Images (pasted, or from a Word file) are stored only if their bytes are the kind of image their type says, and never SVG.
- **Size**: no request body over `MAX_REQUEST_SIZE_MB` (default 25) is taken in at all: refused by its Content-Length, or as soon as the bytes received pass the cap when it sends none, so nothing oversized is spooled to disk. Files stay capped at `MAX_UPLOAD_SIZE_MB` and by the plan. Pasted text: 2,000,000 characters.
- **Rate limits** (`security/rate_limit.py`, all configurable): signing in (per address, and per account against password guessing), registering (per address), AI work, uploads and exports (per user), and a generous overall allowance per session or address against floods. A refusal is `429 rate_limited` with `Retry-After`, and nothing of the request is done. The counters are in memory by default; with several API processes, `RATE_LIMIT_BACKEND=redis` shares them. If Redis is down, requests go through and the failure is logged.
- **Headers**: every API response carries `nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer` and a CSP that lets nothing run (`default-src 'none'; sandbox`); `HSTS_SECONDS` adds Strict-Transport-Security for HTTPS-only deployments. The frontend sends a Content-Security-Policy (scripts and styles from the site itself, data and images from the API, no framing, no plugins), `nosniff`, `DENY`, a strict referrer policy and a Permissions-Policy, and no `X-Powered-By`. CORS allows the configured origins only (never `*`, refused at startup), the methods the app uses, and only the `Content-Type`, `If-Match` and `X-Request-ID` headers.
- **Audit and logs** (`audit.py`, `logging_setup.py`): sign-ups, sign-ins (a failed one with a hash of the address, never the address), sign-outs, documents created, exported, restored and deleted, templates created and deleted, billing actions and webhooks, and every refusal (plan limit, rate limit, file, cross-site request) are one structured line each on the `app.audit` logger. Every log line carries its request id; background jobs keep the id of the request that started them. Each job logs its type, outcome, duration and AI calls; each AI call its task, duration, tokens and how it ended. `LOG_FORMAT=json` writes JSON lines, and `LOG_REQUESTS=true` adds a line per request with its status and duration. No log line holds a document's content: an AI answer that fails validation is logged as where it failed, not what it said.
- **Secrets** are `SecretStr` settings (the Anthropic key, the S3 secret, the Stripe keys), so printing the settings shows asterisks.
- **AI** (`ai/prompting.py`): each task's rules go in a system prompt, and the document goes in the message between tags with a random name made for that call. The document can't close a tag it can't guess, so text in it that looks like instructions stays data, and nothing in it has to be changed. Every call has a timeout (`AI_TIMEOUT_SECONDS`, default 180) and the SDK's own retries. Long pasted text is analysed a piece of about 8,000 characters at a time, cut between paragraphs. Each piece is shown the headings found before it, so levels carry on, and a piece whose answer can't be trusted falls back alone. Past about 160,000 characters the rest is split into paragraphs without the AI, and the document says so. Instructions see at most 400 listed elements, and style analysis reads the first 300.
- **Privacy in the app**: the landing page and the new-document wizard say what happens to your text: it's private to your account, the AI only reads what a task needs and never rewrites it, and deleting a document removes it with its history. The wizard shows the plan's real file-size limit.
- **Tests**: `tests/test_security.py` (file checks, zip bombs, XXE, PDF limits, renamed and disguised files over the API, the size cap, every rate limit, Redis counting and outage, headers, CORS, unsafe settings, hidden secrets) and `tests/test_observability.py` (audit events, no content in any log line, JSON lines, prompt separation against a hostile document, chunking with a failing piece, the piece cap, AI call timeouts and telemetry). Checked live: the headers on both servers, and the editor with a picture-heavy document under the new CSP (images from the API, hot reload, no violations).

## Testing (SaaS Phase 16)

корекции.docx §43 (strategy), §44 (golden documents), §45 (the critical round trip) and §46 (frontend and end-to-end tests).

- **Golden Word documents** (`backend/tests/fixtures/documents/`, built by `scripts/make_golden_documents.py`): 01-simple, 02-rich-text, 03-tables, 04-images, 05-links, 06-lists, 07-headings, 08-caption, 09-sections, 10-header-footer, 11-page-breaks and 12-complex. `tests/test_golden_documents.py` checks what each imports as, then imports it, formats it with a template, exports it to Word, imports the export and compares everything: every element's kind and text, heading levels, list items with their levels and checkboxes, table cells with their spans and shading, pictures, each run's formatting and links, the page setup and header/footer, and the warnings. Exported without a template, the document's own look comes back too.
- **The critical round trip** (§45), through the API: a real Word document is uploaded, saved the way the editor saves it (with an edit typed in), formatted, exported and imported again, and must come back identical apart from the edit, pictures included. `SMARTDOC_REAL_DOCX=<path>` puts any real document through the same test without committing it; Boril's stress-test document passes.
- **What the golden documents found**, now fixed: Word's "List Bullet 2/3" and "List Number 2" styles came in as separate flat lists instead of one nested list; an exported footnote came back as a paragraph; the editor saved a table's summary differently from the backend, rewrote a page break, turned a footnote into a paragraph, and could add an empty paragraph at the end -- each a change made just by opening and saving a document.
- **Frontend tests** (Vitest + React Testing Library, `npm test`): the golden documents as the importer reads them (`frontend/tests/fixtures/golden/`, written by `scripts/export_golden_json.py`; a backend test fails when they go stale) go through the real editor and must come back unchanged, and an edit must change only itself; the API client (errors, request ids, the plan-limit notice, sign-in redirects, If-Match); the confirmation dialog, the plan-limit notice and the billing page (plan, meters, Stripe Checkout and portal, the wait after checkout); date and size formatting.
- **End to end** (Playwright, `npm run test:e2e`): the run starts its own backend on :8100 (`scripts/e2e_server.py`: a fresh SQLite database and asset folder, no AI key, no Stripe, no rate limits, never the real database) and a production build of the app on :3100 (built into `.next-e2e`, so the dev server and the real build are left alone), then drives Edge (installed with Windows; Playwright's Chromium elsewhere). The workflows: sign up, sign out and in, a wrong password, being sent to sign in and back, someone else's document refused; create from pasted text with the structure review; typing saved on its own and kept after a reload; choosing and applying a template with undo and redo; exporting DOCX and PDF; deleting from the list; uploading Word documents with links, pictures and captions, and one with everything; creating a template; Format by Example. The end-to-end run found that the header kept showing "Sign in" after signing in (fixed: signing in now clears the old session's cache and knows the user at once).
- **Visual regression**: one approved screenshot of the editor's first page for a formatted document with everything in it (`e2e/visual.spec.ts`); Windows only, since screenshots depend on the system's fonts. After an intended change: `npx playwright test e2e/visual.spec.ts --update-snapshots`.

## How the pages / toolbar / outline work

- **Real pages, like Word's page view** (`editor/pagination.ts`): a ProseMirror plugin measures every top-level block, and every item of a top-level list, and when one doesn't fit on the current page it inserts a spacer before it, so it starts at the top of the next page; a page break starts a new page too. Each page is drawn as its own sheet behind the text: a white page with a border and shadow on a grey background, a gap between pages, and the header, footer and page number (with `{PAGE}`/`{NUMPAGES}` filled in) in each page's top and bottom margins. The page count in the status bar is the real one. The layout runs again after every change, when an image finishes loading, and when the page size, margins or zoom change. Page geometry comes from the page container's `data-*` attributes, so the editor is never recreated for it.
- **Zoom**: until you pick one, pages shrink to fit the editor column (they never enlarge), so a page's edges are always in view; the zoom buttons and "Fit width" take over from there.
- **Toolbar** (`components/Toolbar.tsx`): undo/redo, bold/italic/underline/strikethrough, superscript/subscript, font and size, text colour and highlight, clear formatting, alignment, and bullet/numbered/check lists. Character formatting is saved with the text as marks, by the same autosave as typing. Alignment is the whole paragraph's formatting: outside tables it's saved as that element's own style, exactly like the Properties panel; inside a table it's saved per column.
- **Outline** (`components/OutlinePanel.tsx`) lists every `heading` element indented by level; clicking one scrolls the matching node into view via `data-element-id` (rendered by the new `editor/elementId.ts` extension, from `Element.id` — also reusable later for mapping a click back to its source element). Hidden below the `lg` breakpoint rather than becoming a collapsible drawer.

## How live per-element overrides work (Phase 5b)

Spec §7.9's priority tier 1 ("explicit current user change") is the one tier the Phase 4 formatting engine deliberately left unbuilt — this phase gives it a real producer: `components/PropertiesPanel.tsx`.

1. **Selecting an element**: clicking anywhere in the editor updates `DocumentEditor.tsx`'s `selectedElementId` via `editor/elementId.ts`'s `getSelectedElementId()`, which walks up from the current selection looking for the nearest ancestor node carrying a `data-element-id` (a click inside a table cell resolves to the whole table, matching `resolvedStyles`' existing table-level granularity).
2. **Editing it**: `PropertiesPanel` shows the selected element's *current resolved style* (reading `Document.resolvedStyles[element.styleRef]`, reverse-mapped back to form values) and lets you change font family/size/color/bold/italic/underline/alignment/line-spacing/paragraph-spacing/first-line-indent (or width/alignment for images). Each change calls `PATCH /api/documents/{id}/elements/{id}/style`; each field's "reset" link calls the matching `DELETE`.
3. **No schema change needed**: a live override just uses the element's own `id` as the `FormattingRule.target` instead of a coarse type-level label like `"Paragraph"` — `target` was already a plain string. `formatting/engine.py`'s `_recompute_styles()` merges the coarse target's rules with that one element's override rules and stores the result at `resolvedStyles[element.id]`, pointing that element's `styleRef` at its own id instead of the coarse target. The frontend's existing `resolvedStyles[el.styleRef ?? targetForElement(el)]` lookup (built in Phase 4) needed **no changes at all** to pick this up.
4. **Surviving a reformat**: `apply_formatting` (the `/format` endpoint) now preserves existing priority-1 rules when rebuilding the template/instruction layer from scratch, instead of wiping everything — this is NFR-008 ("manual changes take precedence over automatic suggestions") holding across a *re*-format, not just within one. Verified live: set one paragraph's color, apply a totally different template, and only that paragraph keeps its manual color while everything else (including its own font/size/spacing) picks up the new template.

## How formatting undo/redo and the Conflict modal work (Phase 5c)

- **Formatting undo/redo is a separate history track from Tiptap's own text-edit undo** (the Toolbar's ↺/↻, client-side and untouched by this). It is stored in the database (`services/version_history.py`): every change becomes a `DocumentVersion` step holding the full document state, `POST .../undo` and `POST .../redo` move a pointer between steps, and any new change after an undo drops the steps above it (standard semantics). The history survives server restarts, keeps the last `DOCUMENT_HISTORY_MAX_STEPS` steps per document (default 50), and merges a burst of autosaved typing (within a minute) into one step. Images are stored assets, so a step never duplicates image bytes. "Undo formatting"/"Redo formatting" are explicit text buttons, deliberately not bare icons, so they're never confused with the Toolbar's ↺/↻.
- **Two tabs editing the same document can't silently overwrite each other.** Every document carries a `revision`; the frontend sends it back as `If-Match` on each change and gets `412` if the document changed elsewhere in the meantime (the editor then shows a reload banner). Writes from one tab are queued, so a tab never conflicts with itself.
- **The Conflict modal** (`components/ConflictModal.tsx`) is the full spec-literal §7.10 design (confirmed with Boril, not a lighter toast): formatting first runs `formatting/engine.py::detect_conflicts()`, which compares the incoming template/instruction rules against every existing live override and reports one only where the *resolved value would actually differ* (a template that happens to agree with what's already set isn't a conflict). If any exist and the request didn't already include resolutions, nothing is applied: `/format` returns **409** with the conflict list, and a formatting job (what the app uses) finishes with the conflicts as its result. The frontend shows the modal (Required/Current values, "Apply recommended"/"Keep current" per conflict) and formats again with the user's choices once every conflict has one, showing that job's progress in the modal. "Apply recommended" removes that one override so the incoming rule wins; "Keep current" is a no-op by construction — it's already what `apply_formatting` does by default.
- **No conflict-detection loop on the resubmit**: once resolutions are provided, the backend applies them directly rather than re-running `detect_conflicts()` — the intended UI flow can't produce a case where that would matter, and adding it would be real complexity for a scenario that can't occur.

## How DOCX/PDF export works (Phase 6)

Spec §7.17/§10/§22 asked for real, downloadable DOCX and PDF — the payoff for everything the Document Model + formatting engine built through Phase 5.

- **Two fully independent exporters, not a DOCX→PDF pipeline.** The obvious approach — build a DOCX, then shell out to LibreOffice (`soffice --headless --convert-to pdf`), the same technique this project's own `docx`/`xlsx` skills use for their own output verification — doesn't work on this machine: `soffice` isn't on `PATH` and isn't in either standard Windows install location (checked directly), and the skills' own `soffice.py` wrapper is explicitly Linux/sandboxed-VM-oriented (it shells out to a pre-existing `soffice` binary and its socket-shim detection references `socket.AF_UNIX`, which doesn't exist on Windows Python). Rather than add a heavy new system dependency for one feature, `docx_export.py` (`python-docx`, already a dependency) and `pdf_export.py` (`reportlab`, a new pure-Python pip package, zero system install) both read the same `document.resolvedStyles` the editor already renders, but draw independently through two unrelated libraries.
- **DOCX** (`build_docx`) first writes the look of each kind of block as a Word style (Normal, Heading 1-6, Quote, Caption, List Bullet/Number/Paragraph, and added Table Text, Code and Footnote Text styles), set explicitly from the resolved type-level styles, so the file has real styles (change Heading 1 in Word and every heading follows) and nothing of python-docx's own template leaks in (its headings are blue Calibri Light). Then it walks `document.elements` in order: a paragraph carries direct formatting only where it differs from its kind (a manual change, a paragraph the source file set apart), plus each run's bold/italic/underline/strike/code, font, size, colour, highlight (Word's own highlight colour when one matches, shading otherwise), superscript/subscript and real hyperlinks; lists keep Word's built-in `"List Bullet"`/`"List Number"` styles and each list gets its own multi-level numbering, so levels nest as they do in Word (Tab/Shift+Tab work, and a re-import keeps them) and every numbered list starts at 1 (python-docx's template only has single-level lists, all sharing one counter); checklists get real Word checkboxes (content controls that can be ticked in Word); tables use `"Table Grid"` with merged cells, cell shading and column alignment; images are read from asset storage (only assets the requesting user may access, so a foreign asset id planted in a document can't leak into an export) and inserted at a width derived from `resolvedStyles`; code blocks use the Code style (monospace, light grey shading); horizontal rules are a paragraph border. Page size/margins/orientation/header/footer come from `document.settings`, with `{PAGE}`/`{NUMPAGES}` written as real Word fields.
- **PDF** (`build_pdf`) uses `reportlab.platypus`'s flowable model, walking the same element list a second time. A `ParagraphStyle` is built per element from its resolved CSS (font, size, colour, alignment, line spacing, space before/after, indents), and each run's formatting becomes reportlab markup (fonts, sizes, colours, highlights, superscript/subscript, links, line breaks). Headers and footers are drawn once the page count is known, so `{NUMPAGES}` is right on every page. Lists are plain `Paragraph` flowables with a computed bullet/number prefix; checklist items get a drawn checkbox; tables keep merged cells and shading; code blocks keep their line breaks and indentation.
- **Real fonts, embedded** (`export/fonts.py`): reportlab's built-in Helvetica/Times/Courier have no Cyrillic, so a Bulgarian document used to come out as black boxes. PDF export embeds TrueType fonts found on the server: the document's own font when it's installed (Arial, Times New Roman, Calibri, Cambria, Georgia, Verdana, Tahoma, Segoe UI, Consolas, Courier New, Garamond, Book Antiqua, Liberation, DejaVu), otherwise an installed font of the same kind (sans-serif, serif or monospace). It looks in `PDF_FONT_DIRS` first, then the system font folders. A Linux server needs a font package such as `fonts-dejavu` or `fonts-liberation`; with no TrueType font at all, export falls back to the built-in fonts and logs a warning.
- **API**: the app renders exports in a background job (`POST /api/jobs/export`, then `GET /api/jobs/{id}/file`, see "How background jobs work"); `GET /api/documents/{id}/export/docx` and `.../export/pdf` still return the file directly. Both answer with a download-triggering `Content-Disposition` header, and 404 for an unknown document, matching every other route.
- **Empty-document edge case**: `SimpleDocTemplate.build([])` with zero flowables silently produces a 0-page PDF — a genuinely broken file, not just an odd test result. `build_pdf` appends one blank paragraph when the element list is empty, guaranteeing at least one page.

## Assumptions made (flagged for confirmation before later phases build on them)

- **Document Model nesting**: list items and table cells are typed sub-fields *on* the `LIST`/`TABLE` element (with an `int` nesting `level` for lists), not separate nested `Element` records — `parentId` stays Section-only. Chosen over a fully recursive model both for simplicity and because Anthropic's structured-output mode doesn't support recursive schemas.
- **`confidence=1.0`** (not `null`) for everything the Markdown/DOCX parsers produce — reading explicit syntax/styles is a mechanical fact, not a probabilistic guess, so `1.0` is the honest value and keeps every `if confidence < threshold` check correct without a null-handling branch. Only the real AI path (and the naive-segmenter fallback, which still uses `null`) has anything other than `1.0`.
- **`documentType`** is only ever classified on the AI path; Markdown/DOCX documents stay `"general"` (classifying would need a second AI call, defeating the point of the deterministic paths).
- **Model default**: `ANTHROPIC_MODEL=claude-sonnet-5` (changed from Phase 0-1's `claude-opus-5`) — a better latency/cost fit for a bounded, well-specified extraction call fired on every document. Fully overridable via `.env`.
- **Checklists use Tiptap's `TaskList`/`TaskItem`**: real checkboxes that can be ticked, saved with the document and exported as Word checkboxes. A list is shown as a checklist when any of its items has a checkbox.
- **Confidence UI is still passive-only** (a visual tint, no accept/reject interaction) — a Properties panel now exists, but it edits *style*, not structure/classification; there's still nothing to reconcile a "this heading level is wrong" correction into. Still deferred, now genuinely open-ended rather than pointing at a specific next phase.
- **DOCX simplifications**: everything the importer approximates or leaves out is listed under "How DOCX import works" and reported in each document's `unsupportedFeatures`; a DOCX with no real styles applied (everything "Normal") never falls back to AI — re-paste the extracted text through the paste flow if AI analysis is wanted for such a file.
- **PDF scope**: text-based PDFs only, per spec TC-003 — no OCR, no scanned-document support.
- **Formatting priority tiers actually implemented**: spec §7.9 defines 7 tiers; as of Phase 5b, tiers 1 (live per-element override, via the Properties panel), 2/3 (instructions, collapsed into one implemented priority since Phase 4's UI can never supply both for the same document at once), 4 (custom template), 5 (built-in template), and 7 (default) are all real. Only tier 6 (AI style *inference*) is unbuilt — never asked for anywhere in the spec.
- **Custom templates now live in the database, per workspace** (see "How templates work"). The old JSON-file store under `backend/data/custom_templates/` is no longer read; everything in it was leftovers from test runs, so nothing was imported.
- **Instructions-file upload supports `.txt`/`.pdf` only** (not `.docx`) — narrower than document upload, since a plain-text DOCX extraction helper doesn't otherwise exist and an instructions file is the less common upload case; type manually or paste the text instead for now.
- **The editor's pages move whole blocks, never split one**: a paragraph, table or list item that doesn't fit moves to the next page, where Word would split a long paragraph or table across the break. A page can therefore end a little earlier than in Word, and a single block taller than a page runs past its bottom margin. The DOCX and PDF exports paginate for real.
- **Page numbers**: the Модерен доклад and Договор built-ins, and any template with "Page numbers: On", turn them on. Header and footer text can also contain `{PAGE}` and `{NUMPAGES}`: filled in on every page in the editor, and written as page-number fields in DOCX and PDF.
- **Toolbar formatting is saved with the text**: bold, fonts, colours and the like are marks on the text, saved by autosave like typing; they don't become `FormattingRule`s, so a template never overrides them. Alignment is the exception: it's the paragraph's own style, saved as a live override (spec §7.9 tier 1) like the Properties panel's.
- **Tiptap 3's `useEditorState` hook didn't work in this setup** — its snapshot's `editor` stayed `null` in the selector even once the outer `editor` instance was genuinely ready (confirmed live: `console.log`-ing showed `{editor: Editor, state: null}` on every render). `editor/useEditorForceUpdate.ts` uses the older, simpler pattern instead: subscribe to the editor's own `transaction`/`selectionUpdate` events and force a re-render, reading fresh editor state directly in the render body. Worth retrying `useEditorState` in a future Tiptap version rather than assuming this workaround is permanently required.
- **Uncontrolled inputs keyed for remount need a *precise* key, not a proxy** — `PropertiesPanel`'s fields originally re-keyed on `` `${element.id}-${document.revisions.length}` ``, and in one live sequence (set an override, then immediately apply a different template without any other interaction) the Color field showed blank even though the underlying data and the rendered document were both correct — a revision counter conflates *any* mutation with *this element's style* having changed. Fixed by keying on `` `${element.id}:${JSON.stringify(css)}` `` instead, i.e. the actual resolved style content. A fully-controlled (`useState`+`useEffect`-synced) version was tried first but rejected by ESLint's `react-hooks/set-state-in-effect` rule (calling `setState` synchronously inside an effect to derive state from props is the exact anti-pattern it flags) — the key-remount approach is also what React's own docs recommend for "reset state when a prop changes."
- **Live overrides reuse `FormattingRule.target` as an element id** — no schema change: `target` was already a plain string, so a rule scoped to one specific element just uses that element's own `id` instead of a coarse label like `"Paragraph"`. `formatting/engine.py::_recompute_styles()` tells the two apart by checking whether a rule's `target` matches a known element id.
- **Formatting undo/redo covers every saved change**: `/format`, the element-style and page-setting endpoints, and autosaved text (a burst of typing merges into one step). The Toolbar's ↺/↻ is the editor's own, finer-grained text history.
- **A resolved conflict's "Apply recommended" is implemented as dropping the override**, not as writing a new rule at some intermediate priority — once dropped, whatever the template/instructions/default layer already resolves to just applies naturally, with no new mechanism needed.
- **LibreOffice is confirmed unavailable on this machine** (no `soffice` on `PATH`, not in either standard install location) — this is why DOCX and PDF are two independent exporters instead of a DOCX→PDF conversion pipeline, and also why this project's `.docx`/`.xlsx` verification skills (which shell out to `soffice`) can't be used here either; their own read-only helpers (e.g. `pandoc`, `pdftoppm`) are also absent from this machine, so export verification this phase used a direct `python-docx`/`pypdf` re-read instead of a rendered-image check.
- **PDF fonts come from the server's installed fonts** (see the export section): a font the server doesn't have is replaced by an installed one of the same kind, so a PDF can differ from the DOCX in its font, never in its content.
- **Export saves first**: typing is saved a moment after you stop (and when the editor loses focus); the export menu also saves anything still pending before the export job starts, so the file matches the screen.
- Everything else from the Phase 0-1/2-3/4/5a/5b/5c README's assumptions (Tiptap as the editor library, Anthropic behind the `AIProvider` abstraction, no manual document-type/template *picker* UI, `confidence=1.0` for deterministic parses, `documentType` only classified on the AI path) still holds.
