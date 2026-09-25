# SmartDoc Formatter

Web app that turns raw pasted text or an uploaded TXT/DOCX/PDF file into a structured, editable document — deterministic parsers or a real AI module figure out the structure (headings, paragraphs, lists, tables, quotes, code blocks, ...), a separate deterministic engine will later apply formatting rules, and a WYSIWYG editor lets you review it before export.

Full requirements: [docs/spec.md](docs/spec.md).

## Status

The original MVP roadmap (docs/spec.md, phases 0-6) is complete. On top of it, the SaaS transformation from `корекции.docx` is under way: its phases 0-8 are done (Postgres with accounts and workspaces, private asset storage, persisted undo, StyleSystem templates, Format by Example, a much more faithful DOCX import and export, real editor pages). Progress per task: `saas-transformation-tracker.xlsx`; the plan: [docs/architecture/migration-plan.md](docs/architecture/migration-plan.md).

Built so far: project scaffolding, the Document Model (shared shape between frontend and backend, now with rich inline formatting/lists/tables/code/images), paste-text and file-upload input, real TXT/DOCX/PDF/Markdown parsing, real AI-driven structure analysis for plain prose (via Anthropic), a deterministic formatting rules engine with built-in/custom templates and AI-assisted instruction extraction, a full editor (visually-paginated, a real rich-text toolbar, a clickable heading outline, a Properties panel for live per-element style overrides, a separate undo/redo history for formatting/structural changes, and the interactive Conflict Resolution modal from spec §7.10), and real DOCX/PDF export. See the roadmap in [docs/spec.md#23-development-roadmap](docs/spec.md#23-development-roadmap) for what's next.

**Not built yet**: AI style *inference*, Table-of-Contents generation, and the SaaS phases still ahead (background jobs, dashboard, billing, security hardening, frontend tests, Docker and CI).

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
      templates.py        /api/templates: list, get, create (blank, from a style system, or from a document), update (If-Match), delete, duplicate, versions + restore, workspace default, live preview, read the style of a reference .docx (Format by Example) -- signed-in
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
      reference_service.py     Format by Example: a reference .docx in, the StyleSystem it uses out (nothing stored)
      auth_service.py          argon2id passwords, hashed session tokens, personal workspace on sign-up
      asset_service.py / image_assets.py   stored images (row + blob kept consistent); inline data: images moved into storage
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
      structure_analysis.py  prompt, retry/repair loop, text-fidelity check
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
    export/
      docx_export.py        Document -> real editable .docx (python-docx), reading the same resolvedStyles the editor renders
      pdf_export.py           Document -> real .pdf (reportlab, independent of docx_export.py -- no LibreOffice on this machine, see below)
      fonts.py                 the TrueType fonts a PDF embeds (PDF_FONT_DIRS, then the system font folders)
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
    DocumentEditor.tsx        Tiptap-based editor on real pages (one sheet per page, header/footer on each), fit-to-column zoom, outline+toolbar+properties layout
    FormattingPanel.tsx        template picker + instructions text/file input, calls /format; shows ConflictModal on a 409; formatting Undo/Redo buttons
    Toolbar.tsx                 rich-text toolbar: character formatting saved with the text, alignment saved as the element's style, lists and checklists
    OutlinePanel.tsx             clickable heading list, scrolls via each node's data-element-id
    PropertiesPanel.tsx           edits the *selected* element's style, persisted via PATCH/DELETE .../style (spec §7.9 tier 1)
    ConflictModal.tsx              spec §7.10's Required/Current + Apply-recommended/Keep-current, per conflict
    ExportPanel.tsx                 plain <a href> downloads for GET .../export/docx and .../export/pdf
    TemplatesPanel.tsx               editor panel: match another document (Format by Example), pick a template, open the library, save the document's look as a template
    ReferenceStyleSummary.tsx         what Format by Example read from a reference: main styles in words, a sample page, notes
    TemplatePreviewSample.tsx         miniature page in a template's real look (engine-computed styles)
    templates/                        TemplateLibrary, TemplateEditor, StyleSystemForm, StylePreviewPage, TemplateHistory, fields
  editor/
    documentToTiptap.ts      Document Model -> Tiptap JSON, all element types + inline marks + resolved styles + elementId
    extensions.ts             StarterKit + Table + Image + TaskList/TaskItem + ConfidenceIndicator + AppliedStyle + ElementId + text/font/colour/super-/subscript extensions
    pagination.ts              lays the document out on pages: a block that doesn't fit moves to the next page; reports the page count
    fontStack.ts                font name -> CSS font stack with a fallback of the same kind
    tableCellBackground.ts       table cell shading
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
- **The Conflict modal** (`components/ConflictModal.tsx`) is the full spec-literal §7.10 design (confirmed with Boril, not a lighter toast): a `/format` call first runs `formatting/engine.py::detect_conflicts()`, which compares the incoming template/instruction rules against every existing live override and reports one only where the *resolved value would actually differ* (a template that happens to agree with what's already set isn't a conflict). If any exist and the request didn't already include resolutions, the endpoint returns **409** with the conflict list and applies nothing; the frontend shows the modal (Required/Current values, "Apply recommended"/"Keep current" per conflict) and re-submits `/format` with the user's choices once every conflict has one. "Apply recommended" removes that one override so the incoming rule wins; "Keep current" is a no-op by construction — it's already what `apply_formatting` does by default.
- **No conflict-detection loop on the resubmit**: once resolutions are provided, the backend applies them directly rather than re-running `detect_conflicts()` — the intended UI flow can't produce a case where that would matter, and adding it would be real complexity for a scenario that can't occur.

## How DOCX/PDF export works (Phase 6)

Spec §7.17/§10/§22 asked for real, downloadable DOCX and PDF — the payoff for everything the Document Model + formatting engine built through Phase 5.

- **Two fully independent exporters, not a DOCX→PDF pipeline.** The obvious approach — build a DOCX, then shell out to LibreOffice (`soffice --headless --convert-to pdf`), the same technique this project's own `docx`/`xlsx` skills use for their own output verification — doesn't work on this machine: `soffice` isn't on `PATH` and isn't in either standard Windows install location (checked directly), and the skills' own `soffice.py` wrapper is explicitly Linux/sandboxed-VM-oriented (it shells out to a pre-existing `soffice` binary and its socket-shim detection references `socket.AF_UNIX`, which doesn't exist on Windows Python). Rather than add a heavy new system dependency for one feature, `docx_export.py` (`python-docx`, already a dependency) and `pdf_export.py` (`reportlab`, a new pure-Python pip package, zero system install) both read the same `document.resolvedStyles` the editor already renders, but draw independently through two unrelated libraries.
- **DOCX** (`build_docx`) first writes the look of each kind of block as a Word style (Normal, Heading 1-6, Quote, Caption, List Bullet/Number/Paragraph, and added Table Text, Code and Footnote Text styles), set explicitly from the resolved type-level styles, so the file has real styles (change Heading 1 in Word and every heading follows) and nothing of python-docx's own template leaks in (its headings are blue Calibri Light). Then it walks `document.elements` in order: a paragraph carries direct formatting only where it differs from its kind (a manual change, a paragraph the source file set apart), plus each run's bold/italic/underline/strike/code, font, size, colour, highlight (Word's own highlight colour when one matches, shading otherwise), superscript/subscript and real hyperlinks; lists keep Word's built-in `"List Bullet"`/`"List Number"` styles and each list gets its own multi-level numbering, so levels nest as they do in Word (Tab/Shift+Tab work, and a re-import keeps them) and every numbered list starts at 1 (python-docx's template only has single-level lists, all sharing one counter); checklists get real Word checkboxes (content controls that can be ticked in Word); tables use `"Table Grid"` with merged cells, cell shading and column alignment; images are read from asset storage (only assets the requesting user may access, so a foreign asset id planted in a document can't leak into an export) and inserted at a width derived from `resolvedStyles`; code blocks use the Code style (monospace, light grey shading); horizontal rules are a paragraph border. Page size/margins/orientation/header/footer come from `document.settings`, with `{PAGE}`/`{NUMPAGES}` written as real Word fields.
- **PDF** (`build_pdf`) uses `reportlab.platypus`'s flowable model, walking the same element list a second time. A `ParagraphStyle` is built per element from its resolved CSS (font, size, colour, alignment, line spacing, space before/after, indents), and each run's formatting becomes reportlab markup (fonts, sizes, colours, highlights, superscript/subscript, links, line breaks). Headers and footers are drawn once the page count is known, so `{NUMPAGES}` is right on every page. Lists are plain `Paragraph` flowables with a computed bullet/number prefix; checklist items get a drawn checkbox; tables keep merged cells and shading; code blocks keep their line breaks and indentation.
- **Real fonts, embedded** (`export/fonts.py`): reportlab's built-in Helvetica/Times/Courier have no Cyrillic, so a Bulgarian document used to come out as black boxes. PDF export embeds TrueType fonts found on the server: the document's own font when it's installed (Arial, Times New Roman, Calibri, Cambria, Georgia, Verdana, Tahoma, Segoe UI, Consolas, Courier New, Garamond, Book Antiqua, Liberation, DejaVu), otherwise an installed font of the same kind (sans-serif, serif or monospace). It looks in `PDF_FONT_DIRS` first, then the system font folders. A Linux server needs a font package such as `fonts-dejavu` or `fonts-liberation`; with no TrueType font at all, export falls back to the built-in fonts and logs a warning.
- **API**: `GET /api/documents/{id}/export/docx` and `.../export/pdf` return raw bytes with a download-triggering `Content-Disposition` header — no request body needed, so `ExportPanel.tsx` is just two plain `<a href>` links, no fetch/blob JS. 404 for an unknown document, matching every other route.
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
- **Export reads the saved document**: typing is saved a moment after you stop (and when the editor loses focus), and an export includes it once it's saved.
- Everything else from the Phase 0-1/2-3/4/5a/5b/5c README's assumptions (Tiptap as the editor library, Anthropic behind the `AIProvider` abstraction, no manual document-type/template *picker* UI, `confidence=1.0` for deterministic parses, `documentType` only classified on the AI path) still holds.
