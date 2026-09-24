# SmartDoc Formatter

Web app that turns raw pasted text or an uploaded TXT/DOCX/PDF file into a structured, editable document — deterministic parsers or a real AI module figure out the structure (headings, paragraphs, lists, tables, quotes, code blocks, ...), a separate deterministic engine will later apply formatting rules, and a WYSIWYG editor lets you review it before export.

Full requirements: [docs/spec.md](docs/spec.md).

## Status: Phase 0-1-2-3-4-5-6 (foundation + parsing + AI structure analysis + formatting engine + full editor: page preview/toolbar/outline/properties panel/undo-redo/conflict resolution + DOCX/PDF export) complete

Built so far: project scaffolding, the Document Model (shared shape between frontend and backend, now with rich inline formatting/lists/tables/code/images), paste-text and file-upload input, real TXT/DOCX/PDF/Markdown parsing, real AI-driven structure analysis for plain prose (via Anthropic), a deterministic formatting rules engine with built-in/custom templates and AI-assisted instruction extraction, a full editor (visually-paginated, a real rich-text toolbar, a clickable heading outline, a Properties panel for live per-element style overrides, a separate undo/redo history for formatting/structural changes, and the interactive Conflict Resolution modal from spec §7.10), and real DOCX/PDF export. See the roadmap in [docs/spec.md#23-development-roadmap](docs/spec.md#23-development-roadmap) for what's next.

**Not built yet** (later phases, on purpose — see [docs/spec.md §27](docs/spec.md#27-основни-принципи-за-ai-developer)): real multi-page *reflow* (content actually moving between fixed-height pages — the editor only looks paginated, see below), AI style *inference*, Table-of-Contents generation, and persistence/accounts.

## Project layout

```
backend/            FastAPI app
  app/
    main.py           FastAPI app, CORS, cross-site-write (Origin) check, 412 handler, router mount, GET /api/health
    config.py         env-based settings (backend/.env); normalizes a pasted Supabase DATABASE_URL
    api/
      deps.py            signed-in user from the session cookie; per-request DocumentService (If-Match -> expected revision)
      auth.py            POST /api/auth/register|login|logout, GET /api/auth/me
      documents.py       POST /api/documents, POST /api/documents/upload, GET /api/documents/{id}, POST .../format (409 on conflict), PATCH/DELETE .../elements/{id}/style, POST .../undo, POST .../redo, GET .../export/docx, GET .../export/pdf -- all signed-in, scoped to the user's workspaces
      assets.py          GET /api/assets/{id} (stored images, workspace members only)
      templates.py        /api/templates: list, get, create (blank, from a style system, or from a document), update (If-Match), delete, duplicate, versions + restore, workspace default, live preview -- signed-in
    db/                  SQLAlchemy models (14 tables) + async engine; schema changes go through alembic/ (see docs/architecture/migration-plan.md)
    repositories/document_repository.py   documents table access, user-scoped lookups
    repositories/template_repository.py   templates visible to a user, their versions, clearing a workspace default
    storage/             StorageProvider: local files (dev) or any S3-compatible service
    models/document.py   the canonical Document Model (Pydantic) -- rich inline/list/table/image content + formatting
    schemas/
      document.py          API request schema
      formatting.py         element-style and conflict-resolution request schemas
      templates.py          template request/response schemas (TemplateOut carries engine-computed preview styles)
    services/
      document_service.py    every document read/write for one signed-in user: upload dispatch + format_document() + style/content/page changes + undo()/redo(); optimistic concurrency (412 on a stale If-Match)
      version_history.py      persisted, bounded undo/redo (DocumentVersion rows; autosave bursts merge into one step)
      template_service.py      built-in + workspace templates for one signed-in user: access rules, versions, default template, preview
      auth_service.py          argon2id passwords, hashed session tokens, personal workspace on sign-up
      asset_service.py / image_assets.py   stored images (row + blob kept consistent); inline data: images moved into storage
      ingestion_service.py    routes each input to the right parser (see "How parsing works" below)
    parsers/
      detection.py      looks_like_markdown() heuristic
      markdown.py        deterministic Markdown -> Document Model (markdown-it-py)
      docx.py             deterministic DOCX -> Document Model (python-docx)
      pdf.py               PDF text extraction (pypdf, text-based PDFs only)
      plain_text.py         naive segmenter -- now only the AI-failure fallback
    ai/
      base.py            provider-agnostic interface (NFR-006) + complete_structured()
      anthropic_provider.py   Claude adapter, structured output via messages.parse()
      schemas.py           internal AI response schemas (structure analysis + instruction extraction)
      structure_analysis.py  prompt, retry/repair loop, text-fidelity check
      instruction_extraction.py  free-text formatting instructions -> FormattingRule[] (same retry/fallback shape)
    formatting/
      engine.py            priority-based rule resolution -> resolvedStyles + DocumentSettings (deterministic, no AI); set/clear_element_override() for live per-element overrides; detect_conflicts() for spec §7.10
      priorities.py         the seven resolution tiers as one enum
      style_system.py       StyleSystem (the product-level template model) <-> FormattingRules
      builtin_templates.json   the built-in templates, as StyleSystem data
      templates.py          loads and validates the built-ins
      units.py / colors.py   length/size unit conversion; the colour names every renderer understands
    export/
      docx_export.py        Document -> real editable .docx (python-docx), reading the same resolvedStyles the editor renders
      pdf_export.py           Document -> real .pdf (reportlab, independent of docx_export.py -- no LibreOffice on this machine, see below)
  scripts/verify_anthropic.py  manual-only connectivity check
  scripts/verify_database.py    manual-only DATABASE_URL check (connection, schema head, rolled-back round trip)
  scripts/migrate_json_documents.py   one-shot import of the old JSON document store into an account
  tests/                 pytest (parsers, AI logic via a hand-written fake, formatting engine, API round-trips)

frontend/            Next.js (App Router) + TypeScript + Tailwind
  app/page.tsx             Home
  app/new/page.tsx          paste-text + file-upload input screen
  app/documents/[id]/page.tsx  editor screen
  app/templates/page.tsx      template library
  app/templates/[id]/page.tsx  template editor (live preview, version history)
  components/
    PasteTextForm.tsx, FileUploadForm.tsx
    DocumentEditor.tsx        Tiptap-based editor, page-seam visual pagination, header/footer strip, outline+toolbar+properties layout
    FormattingPanel.tsx        template picker + instructions text/file input, calls /format; shows ConflictModal on a 409; formatting Undo/Redo buttons
    Toolbar.tsx                 direct Tiptap rich-text commands (bold/italic/font/size/align/lists/undo-redo), local only
    OutlinePanel.tsx             clickable heading list, scrolls via each node's data-element-id
    PropertiesPanel.tsx           edits the *selected* element's style, persisted via PATCH/DELETE .../style (spec §7.9 tier 1)
    ConflictModal.tsx              spec §7.10's Required/Current + Apply-recommended/Keep-current, per conflict
    ExportPanel.tsx                 plain <a href> downloads for GET .../export/docx and .../export/pdf
    TemplatesPanel.tsx               editor panel: pick a template, open the library, save the document's look as a template
    TemplatePreviewSample.tsx         miniature page in a template's real look (engine-computed styles)
    templates/                        TemplateLibrary, TemplateEditor, StyleSystemForm, StylePreviewPage, TemplateHistory, fields
  editor/
    documentToTiptap.ts      Document Model -> Tiptap JSON, all element types + inline marks + resolved styles + elementId
    extensions.ts             StarterKit + Table + Image + ConfidenceIndicator + AppliedStyle + ElementId + text/font extensions
    confidenceIndicator.ts     passive low-confidence visual marker (no interaction yet)
    appliedStyle.ts             renders Document.resolvedStyles as real inline CSS per node
    elementId.ts                 renders Element.id as data-element-id + getSelectedElementId() (selection -> Element)
    fontSize.ts                   custom textStyle-based font-size mark (Tiptap ships no official one)
    useEditorForceUpdate.ts        shared transaction/selection subscription hook (Toolbar + PropertiesPanel + DocumentEditor)
    pageGeometry.ts                 page sizes shared by the editor and the template preview
    cssStyle.ts                      engine CSS -> React style objects, for previews
  services/api.ts            fetch wrappers (create, upload, get, templates [list/get/create/update/delete/duplicate/default/versions/restore/preview], format [discriminated applied/conflicts result], set/clear element style, undo/redo formatting)
  types/document.ts           1:1 mirror of the backend Document Model

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

> A `.claude/launch.json` exists for Claude Code's own preview tooling, but starting servers *by that config's name* resolves against the wrong project folder in this workspace (a tooling quirk, not a project bug) — start both servers directly with the commands above instead, then open `http://localhost:3000` in a browser.

### Tests

```powershell
cd backend
.\venv\Scripts\python.exe -m pytest
```

Tests never touch the real database or `backend/data/`: each API test gets its own SQLite file and asset directory.

No test hits the real Anthropic API — AI-path tests use a hand-written `FakeAIProvider` (`backend/tests/fakes.py`) swapped in via FastAPI's dependency override, not by mocking the `anthropic` SDK's internals.

### Verifying the Anthropic adapter directly

Independent of the rest of the app:

```powershell
cd backend
.\venv\Scripts\python.exe -m scripts.verify_anthropic
```

## How parsing/structure-analysis works

Content is routed to the cheapest reliable method for what it actually is, reserving the LLM for genuinely ambiguous plain prose:

1. **`.docx` upload** → `parsers/docx.py` reads real Word paragraph styles, list numbering XML, and tables directly. Deterministic, `confidence=1.0`, **no AI call**.
2. **Everything else** (paste, `.txt` upload, `.pdf` upload) reduces to plain text first (PDF via `pypdf` text extraction), then:
   - If it **looks like Markdown** (`parsers/detection.py`'s tiered heuristic: an ATX heading/fenced code/table row alone is enough; bold+link+blockquote need two together; a lone list marker never counts) → `parsers/markdown.py` parses it deterministically (headings, nested/checklist lists, tables with alignment, blockquotes, fenced code, inline marks). `confidence=1.0`, **no AI call**.
   - Otherwise → `ai/structure_analysis.py` sends it to Claude via a schema-constrained `messages.parse()` call, with a text-fidelity check on top of schema validation (the AI must never alter the original text — spec §13) and one retry. If the AI call fails entirely (no API key, network error, refusal, or still-invalid output after retry) it **falls back to the naive `plain_text.py` segmenter** rather than erroring the request.

The editor (`editor/documentToTiptap.ts`) renders every element type this can now produce — headings, paragraphs with inline bold/italic/strike/code/links, nested bullet/ordered lists (checklist items shown with a ☑/☐ glyph — no `TaskItem` extension installed this phase), tables, blockquotes, fenced code blocks with language, and images (DOCX-embedded pictures are stored as assets and load from `/api/assets/{id}`; pictures inside table cells or list items, and non-web formats like EMF, are reported in the document's `unsupportedFeatures` instead). Elements below a confidence threshold (0.6, tunable) get a subtle left-border tint — passive only, no accept/reject UI yet (see Assumptions below for why).

## How the formatting engine works

The `Element.styleRef`/`Document.templateId`/`Document.formattingRules`/`Document.settings` fields existed as unused placeholders since Phase 0-1 — this phase gives them real behaviour via `POST /api/documents/{id}/format`:

1. **Pick a source of rules**: a built-in template (see `formatting/builtin_templates.json`), one of your workspace's own templates (see "How templates work" below), and/or free-text formatting instructions (typed directly, or extracted from an uploaded `.txt`/`.pdf` instructions file via `ai/instruction_extraction.py` — the same Claude `messages.parse()` + retry + graceful-fallback-to-no-rules shape as structure analysis, just producing `FormattingRule`s instead of `Element`s).
2. **Resolve deterministically**: `formatting/engine.py::resolve_styles()` merges every rule source by spec §7.9's priority order (lower number wins) and converts the winners into real CSS per element-type target (`"Heading 1"`, `"Paragraph"`, `"Table"`, `"Image"`, ...); page-level properties (page size, margins, header/footer/page numbers) resolve separately into `Document.settings` via `extract_settings()`, since no single element owns them. Fully deterministic (NFR-007) — the AI is only ever involved in turning *instructions* into rules, never in applying them.
3. **The editor renders the result**: `documentToTiptap.ts` looks up each element's resolved style by `styleRef` and attaches it as a real inline `style="..."` attribute (via the new `AppliedStyle` Tiptap extension); `DocumentEditor.tsx` applies `Document.settings`' page size/margins as CSS on the editor's container and shows header/footer/page-number as a single non-repeating strip.

## How templates work (SaaS Phase 7)

- **A template is a `StyleSystem`** (`formatting/style_system.py`, корекции.docx §19): the look of a document described the way people think about it, not as loose rules. It covers the page (size, orientation, margins), text everywhere (a document-wide font and colour), body text, headings 1-6, lists, tables, captions, quotes, footnotes, code blocks, images, and the header and footer. Any field can be left unset, meaning "not decided here". `FormattingRule` stays the engine's internal mechanism: `compile_rules()` turns a style system into rules, always the same rules for the same input, and `style_system_from_rules()` goes back the other way (used to save a document's current look as a template). Anything that can't be represented is reported, never silently dropped.
- **Priority tiers are one enum**, `formatting/priorities.py`: live override 1, instruction 2, imported requirement 3, custom template 4, built-in template 5, AI inference 6, default 7. Tiers 3 and 6 have no producer yet but are named, so no numbers are hard-coded anywhere.
- **Built-in templates are data**: `formatting/builtin_templates.json`, validated when the backend starts, so a typo stops startup instead of breaking later. The original three compile to exactly the rules they had before (regression-tested). Two new ones use more of the style system: Модерен доклад and Договор / юридически текст.
- **Your own templates live in the database**, per workspace. Each row holds the style system, the rules it compiled to when saved, a version number, who can see it (the whole workspace or only its creator), and the document it was saved from. Every save adds a `template_versions` row recording who saved and when. The last `TEMPLATE_HISTORY_MAX_VERSIONS` (default 50) are kept, and any of them can be restored; a restore is saved as a new version. Saves carry the version they started from (`If-Match`), so two tabs can't overwrite each other silently: the second gets a 412 and can reload or save over it.
- **Who can do what**: a template is visible to its workspace's members (a private one only to its creator). Its creator or the workspace owner can edit, rename or delete it; only the creator can change who sees it. Only the owner sets the workspace default, and only to a template the whole workspace can see. Built-ins are read-only; duplicate one to customize it.
- **The workspace default template** is preselected in the new-document wizard. Deleting a template clears it as the default. Documents formatted with a deleted template keep their formatting, because each document holds its own copy of the rules.
- **Screens**: `/templates` is the library (new, duplicate, make default, rename, delete). `/templates/{id}` is the editor: every style-system field, a live page preview resolved by the real engine (`POST /api/templates/preview`), and version history with restore. In the document editor, the Templates panel links to the library and can save the document's current look as a template; changes made to a single paragraph are not included.
- **Not yet**: importing a template from a DOCX file comes with Format by Example (Phase 8), which extracts a style system from a reference document. Choosing who sees a template has no UI yet, since every workspace has a single member until invitations exist.

## How the page preview / toolbar / outline work (Phase 5a)

- **Page preview** is a CSS-only visual approximation, not real pagination: `DocumentEditor.tsx` puts a `repeating-linear-gradient` shadow band on the paper `div`, sized so the repeat unit is exactly one page height in pixels (`pageSize`/`orientation` → mm → px at 96dpi) — this is what makes the seams land on exact multiples of the page height with no drift. A `ResizeObserver` tracks the rendered content's height to estimate a page count (`Page 1 of N`), shown in the footer strip when `settings.showPageNumbers` is on. Content still flows continuously underneath — nothing actually moves to a new page.
- **Toolbar** (`components/Toolbar.tsx`) calls Tiptap commands directly (`editor.chain().focus().toggleBold().run()`, etc.) — bold/italic/underline/strike, font family/size (via `editor/fontSize.ts`, a custom mark since Tiptap ships no official font-size extension), the four text alignments, bullet/ordered list, and undo/redo (exposing Tiptap's already-working text-edit history as buttons, not new capability). These edits stay **local to the browser only**, exactly like all editing so far — they are not turned into `FormattingRule`s or sent to the backend. (`PropertiesPanel.tsx`, below, is the *separate*, backend-persisted mechanism for that — the Toolbar itself still doesn't use it.)
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
- **The Conflict modal** (`components/ConflictModal.tsx`) is the full spec-literal §7.10 design (confirmed with Boril, not a lighter toast): a `/format` call first runs `formatting/engine.py::detect_conflicts()`, which compares the incoming template/instruction rules against every existing live override and reports one only where the *resolved value would actually differ* (a template that happens to agree with what's already set isn't a conflict). If any exist and the request didn't already include resolutions, the endpoint returns **409** with the conflict list and applies nothing; the frontend shows the modal (Required/Current values, "Apply recommended"/"Keep current" per conflict) and re-submits `/format` with the user's choices once every conflict has one. "Apply recommended" removes that one override so the incoming rule wins; "Keep current" is a no-op by construction — it's already what `apply_formatting` does by default.
- **No conflict-detection loop on the resubmit**: once resolutions are provided, the backend applies them directly rather than re-running `detect_conflicts()` — the intended UI flow can't produce a case where that would matter, and adding it would be real complexity for a scenario that can't occur.

## How DOCX/PDF export works (Phase 6)

Spec §7.17/§10/§22 asked for real, downloadable DOCX and PDF — the payoff for everything the Document Model + formatting engine built through Phase 5.

- **Two fully independent exporters, not a DOCX→PDF pipeline.** The obvious approach — build a DOCX, then shell out to LibreOffice (`soffice --headless --convert-to pdf`), the same technique this project's own `docx`/`xlsx` skills use for their own output verification — doesn't work on this machine: `soffice` isn't on `PATH` and isn't in either standard Windows install location (checked directly), and the skills' own `soffice.py` wrapper is explicitly Linux/sandboxed-VM-oriented (it shells out to a pre-existing `soffice` binary and its socket-shim detection references `socket.AF_UNIX`, which doesn't exist on Windows Python). Rather than add a heavy new system dependency for one feature, `docx_export.py` (`python-docx`, already a dependency) and `pdf_export.py` (`reportlab`, a new pure-Python pip package, zero system install) both read the same `document.resolvedStyles` the editor already renders, but draw independently through two unrelated libraries.
- **DOCX** (`build_docx`) walks `document.elements` in order: headings/paragraphs become real Word paragraphs with per-run bold/italic/strike/code from each `InlineRun`'s marks; lists use Word's built-in `"List Bullet"`/`"List Number"` styles (nesting approximated via `left_indent`, a flagged simplification — it doesn't fully round-trip beyond one or two levels); tables use `add_table` + `"Table Grid"`; images are read from asset storage (only assets the requesting user may access, so a foreign asset id planted in a document can't leak into an export) and inserted at a width derived from `resolvedStyles`; code blocks get a monospace font plus light shading via raw XML (python-docx has no high-level API for paragraph shading, same pattern already used for numbering XML in the parser). Page size/margins/orientation/header/footer come from `document.settings`; page numbers need a raw-XML `PAGE` field, again with no high-level API.
- **PDF** (`build_pdf`) uses `reportlab.platypus`'s flowable model (`SimpleDocTemplate` + `Paragraph`/`Table`/`Image`), walking the same element list a second time. A `ParagraphStyle` is built per element from its resolved CSS; header/footer/page-numbers use `SimpleDocTemplate`'s `onFirstPage`/`onLaterPages` canvas callbacks, since reportlab paginates for real (the one place PDF export needed something DOCX's single header/footer paragraph didn't). Lists are plain `Paragraph` flowables with a manually-computed bullet/number prefix rather than `reportlab.platypus.ListFlowable`/`ListItem` — those exist and were confirmed working, but were judged too much unverified API surface for the value versus a simple text prefix (the same "text glyph instead of native construct" choice already made for Tiptap checklist items).
- **Font-substitution gap, flagged rather than fixed**: reportlab ships only Helvetica/Times-Roman/Courier (plus bold/italic variants) without registering external `.ttf` files, which would be disproportionate to embed for an MVP. A small lookup maps common names this project's templates/toolbar/instructions can produce (Arial/Calibri→Helvetica, Times New Roman→Times-Roman, Courier New→Courier, anything unrecognized→Helvetica). This means PDF font *rendering* won't be pixel-identical to the live preview or the DOCX, even though the underlying *document* (same resolved styles) is consistent across all three.
- **API**: `GET /api/documents/{id}/export/docx` and `.../export/pdf` return raw bytes with a download-triggering `Content-Disposition` header — no request body needed, so `ExportPanel.tsx` is just two plain `<a href>` links, no fetch/blob JS. 404 for an unknown document, matching every other route.
- **Empty-document edge case**: `SimpleDocTemplate.build([])` with zero flowables silently produces a 0-page PDF — a genuinely broken file, not just an odd test result. `build_pdf` appends one blank paragraph when the element list is empty, guaranteeing at least one page.

## Assumptions made (flagged for confirmation before later phases build on them)

- **Document Model nesting**: list items and table cells are typed sub-fields *on* the `LIST`/`TABLE` element (with an `int` nesting `level` for lists), not separate nested `Element` records — `parentId` stays Section-only. Chosen over a fully recursive model both for simplicity and because Anthropic's structured-output mode doesn't support recursive schemas.
- **`confidence=1.0`** (not `null`) for everything the Markdown/DOCX parsers produce — reading explicit syntax/styles is a mechanical fact, not a probabilistic guess, so `1.0` is the honest value and keeps every `if confidence < threshold` check correct without a null-handling branch. Only the real AI path (and the naive-segmenter fallback, which still uses `null`) has anything other than `1.0`.
- **`documentType`** is only ever classified on the AI path; Markdown/DOCX documents stay `"general"` (classifying would need a second AI call, defeating the point of the deterministic paths).
- **Model default**: `ANTHROPIC_MODEL=claude-sonnet-5` (changed from Phase 0-1's `claude-opus-5`) — a better latency/cost fit for a bounded, well-specified extraction call fired on every document. Fully overridable via `.env`.
- **No `TaskList`/`TaskItem` Tiptap extension** — checklist items (`- [x]`) render as a regular list item with a ☑/☐ text glyph prefix rather than a real interactive checkbox node, to avoid adding a dependency beyond what this phase scoped.
- **Confidence UI is still passive-only** (a visual tint, no accept/reject interaction) — a Properties panel now exists, but it edits *style*, not structure/classification; there's still nothing to reconcile a "this heading level is wrong" correction into. Still deferred, now genuinely open-ended rather than pointing at a specific next phase.
- **DOCX simplifications**: table cell merges don't reconstruct real colspan/rowspan; footnotes are unsupported; a DOCX with no real styles applied (everything "Normal") never falls back to AI — re-paste the extracted text through the paste flow if AI analysis is wanted for such a file.
- **PDF scope**: text-based PDFs only, per spec TC-003 — no OCR, no scanned-document support.
- **Formatting priority tiers actually implemented**: spec §7.9 defines 7 tiers; as of Phase 5b, tiers 1 (live per-element override, via the Properties panel), 2/3 (instructions, collapsed into one implemented priority since Phase 4's UI can never supply both for the same document at once), 4 (custom template), 5 (built-in template), and 7 (default) are all real. Only tier 6 (AI style *inference*) is unbuilt — never asked for anywhere in the spec.
- **Custom templates now live in the database, per workspace** (see "How templates work"). The old JSON-file store under `backend/data/custom_templates/` is no longer read; everything in it was leftovers from test runs, so nothing was imported.
- **Instructions-file upload supports `.txt`/`.pdf` only** (not `.docx`) — narrower than document upload, since a plain-text DOCX extraction helper doesn't otherwise exist and an instructions file is the less common upload case; type manually or paste the text instead for now.
- **Page preview is a CSS visual approximation, chosen deliberately over real reflow**: a page-height-shaped shadow seam repeats down one continuous scroll container; content never actually moves between fixed-height pages. Building true live-reflowing pagination on Tiptap/ProseMirror (no library does this for free) is a separate, much larger engineering effort than an MVP needs right now — confirmed with Boril before starting Phase 5.
- **Page numbers**: the Модерен доклад and Договор built-ins, and any template with "Page numbers: On", turn them on. The page-count estimate (`Page 1 of N`) is real and tested (the seam/page-height math was verified via computed styles).
- **Toolbar edits are still local-only** — bold/italic/font/size/alignment/list toggles go straight through Tiptap/ProseMirror marks, never through the backend's `FormattingRule`/`resolvedStyles` system, and never enter the formatting undo/redo stack below. `PropertiesPanel.tsx` is the separate, backend-persisted mechanism (spec §7.9 tier 1); the Toolbar doesn't route through it.
- **Tiptap 3's `useEditorState` hook didn't work in this setup** — its snapshot's `editor` stayed `null` in the selector even once the outer `editor` instance was genuinely ready (confirmed live: `console.log`-ing showed `{editor: Editor, state: null}` on every render). `editor/useEditorForceUpdate.ts` uses the older, simpler pattern instead: subscribe to the editor's own `transaction`/`selectionUpdate` events and force a re-render, reading fresh editor state directly in the render body. Worth retrying `useEditorState` in a future Tiptap version rather than assuming this workaround is permanently required.
- **Uncontrolled inputs keyed for remount need a *precise* key, not a proxy** — `PropertiesPanel`'s fields originally re-keyed on `` `${element.id}-${document.revisions.length}` ``, and in one live sequence (set an override, then immediately apply a different template without any other interaction) the Color field showed blank even though the underlying data and the rendered document were both correct — a revision counter conflates *any* mutation with *this element's style* having changed. Fixed by keying on `` `${element.id}:${JSON.stringify(css)}` `` instead, i.e. the actual resolved style content. A fully-controlled (`useState`+`useEffect`-synced) version was tried first but rejected by ESLint's `react-hooks/set-state-in-effect` rule (calling `setState` synchronously inside an effect to derive state from props is the exact anti-pattern it flags) — the key-remount approach is also what React's own docs recommend for "reset state when a prop changes."
- **Live overrides reuse `FormattingRule.target` as an element id** — no schema change: `target` was already a plain string, so a rule scoped to one specific element just uses that element's own `id` instead of a coarse label like `"Paragraph"`. `formatting/engine.py::_recompute_styles()` tells the two apart by checking whether a rule's `target` matches a known element id.
- **Formatting undo/redo covers `/format` and the element-style endpoints only** — the complete set of backend-mutating formatting/structural operations that exist. Text content edits stay Tiptap-local (their own separate, already-working history) since there's still no endpoint that persists document *content* changes to the backend at all.
- **A resolved conflict's "Apply recommended" is implemented as dropping the override**, not as writing a new rule at some intermediate priority — once dropped, whatever the template/instructions/default layer already resolves to just applies naturally, with no new mechanism needed.
- **LibreOffice is confirmed unavailable on this machine** (no `soffice` on `PATH`, not in either standard install location) — this is why DOCX and PDF are two independent exporters instead of a DOCX→PDF conversion pipeline, and also why this project's `.docx`/`.xlsx` verification skills (which shell out to `soffice`) can't be used here either; their own read-only helpers (e.g. `pandoc`, `pdftoppm`) are also absent from this machine, so export verification this phase used a direct `python-docx`/`pypdf` re-read instead of a rendered-image check.
- **DOCX list nesting is approximate**: Word's built-in `"List Bullet"`/`"List Number"` styles don't nest cleanly through python-docx beyond `left_indent` scaling, so deeply nested lists lose some visual nesting on export (content and order are still correct).
- **PDF fonts are substituted, not embedded**: reportlab ships Helvetica/Times-Roman/Courier only; real `.ttf` embedding was judged disproportionate for an MVP. A document exported to both DOCX and PDF will match in structure/content but not necessarily in exact font rendering.
- **Export reflects the last applied template/formatting, not unsaved Toolbar text edits** — since text content edits are still Tiptap-local only (no content-persistence endpoint exists yet, see the Phase 5c note above), exporting a document whose text was edited directly in the browser after the last `/format` call exports the pre-edit content. Flagged to Boril in the editor UI itself (see `DocumentEditor.tsx`'s intro paragraph), not silently.
- Everything else from the Phase 0-1/2-3/4/5a/5b/5c README's assumptions (Tiptap as the editor library, Anthropic behind the `AIProvider` abstraction, no manual document-type/template *picker* UI, `confidence=1.0` for deterministic parses, `documentType` only classified on the AI path, CSS-approximated page preview) still holds.
