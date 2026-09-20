# SmartDoc Formatter

Web app that turns raw pasted text or an uploaded TXT/DOCX/PDF file into a structured, editable document — deterministic parsers or a real AI module figure out the structure (headings, paragraphs, lists, tables, quotes, code blocks, ...), a separate deterministic engine will later apply formatting rules, and a WYSIWYG editor lets you review it before export.

Full requirements: [docs/spec.md](docs/spec.md).

## Status: Phase 0-1-2-3-4-5a (foundation + parsing + AI structure analysis + formatting engine + page preview/toolbar/outline) complete

Built so far: project scaffolding, the Document Model (shared shape between frontend and backend, now with rich inline formatting/lists/tables/code/images), paste-text and file-upload input, real TXT/DOCX/PDF/Markdown parsing, real AI-driven structure analysis for plain prose (via Anthropic), a deterministic formatting rules engine with built-in/custom templates and AI-assisted instruction extraction, and now a visually-paginated editor with a real rich-text toolbar and a clickable heading outline. See the roadmap in [docs/spec.md#23-development-roadmap](docs/spec.md#23-development-roadmap) for what's next.

**Not built yet** (later phases, on purpose — see [docs/spec.md §27](docs/spec.md#27-основни-принципи-за-ai-developer)): real multi-page *reflow* (content actually moving between fixed-height pages — this phase only looks paginated, see below), a Properties panel with live per-element style overrides, real undo/redo for formatting/structural changes (only text edits are undoable so far), the interactive Conflict Resolution modal, AI style *inference*, Table-of-Contents generation, DOCX/PDF export, and persistence/accounts.

## Project layout

```
backend/            FastAPI app
  app/
    main.py           FastAPI app, CORS, router mount, GET /api/health
    config.py         env-based settings
    api/
      documents.py       POST /api/documents, POST /api/documents/upload, GET /api/documents/{id}, POST /api/documents/{id}/format
      templates.py        GET/POST /api/templates
    models/document.py   the canonical Document Model (Pydantic) -- rich inline/list/table/image content + formatting
    schemas/
      document.py          API request schema
      formatting.py         template create/list request-response schemas
    services/
      document_service.py    in-memory store (no DB -- see spec §16) + upload dispatch + format_document()
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
      engine.py            priority-based rule resolution -> resolvedStyles + DocumentSettings (deterministic, no AI)
      templates.py          built-in template registry (academic/professional/official) + in-memory custom templates
  scripts/verify_anthropic.py  manual-only connectivity check
  tests/                 pytest (parsers, AI logic via a hand-written fake, formatting engine, API round-trips)

frontend/            Next.js (App Router) + TypeScript + Tailwind
  app/page.tsx             Home
  app/new/page.tsx          paste-text + file-upload input screen
  app/documents/[id]/page.tsx  editor screen
  components/
    PasteTextForm.tsx, FileUploadForm.tsx
    DocumentEditor.tsx        Tiptap-based editor, page-seam visual pagination, header/footer strip, outline+toolbar layout
    FormattingPanel.tsx        template picker + instructions text/file input, calls the /format endpoint
    Toolbar.tsx                 direct Tiptap rich-text commands (bold/italic/font/size/align/lists/undo-redo)
    OutlinePanel.tsx             clickable heading list, scrolls via each node's data-element-id
  editor/
    documentToTiptap.ts      Document Model -> Tiptap JSON, all element types + inline marks + resolved styles + elementId
    extensions.ts             StarterKit + Table + Image + ConfidenceIndicator + AppliedStyle + ElementId + text/font extensions
    confidenceIndicator.ts     passive low-confidence visual marker (no interaction yet)
    appliedStyle.ts             renders Document.resolvedStyles as real inline CSS per node
    elementId.ts                 renders Element.id as data-element-id (Outline's scroll target)
    fontSize.ts                   custom textStyle-based font-size mark (Tiptap ships no official one)
  services/api.ts            fetch wrappers (create, upload, get, list/create templates, format)
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

The editor (`editor/documentToTiptap.ts`) renders every element type this can now produce — headings, paragraphs with inline bold/italic/strike/code/links, nested bullet/ordered lists (checklist items shown with a ☑/☐ glyph — no `TaskItem` extension installed this phase), tables, blockquotes, fenced code blocks with language, and images (DOCX-embedded images become base64 `data:` URIs). Elements below a confidence threshold (0.6, tunable) get a subtle left-border tint — passive only, no accept/reject UI yet (see Assumptions below for why).

## How the formatting engine works

The `Element.styleRef`/`Document.templateId`/`Document.formattingRules`/`Document.settings` fields existed as unused placeholders since Phase 0-1 — this phase gives them real behaviour via `POST /api/documents/{id}/format`:

1. **Pick a source of rules**: a built-in template (`academic-default`, `professional-cv`, `official-standard` — see `formatting/templates.py`), a custom template created via `POST /api/templates`, and/or free-text formatting instructions (typed directly, or extracted from an uploaded `.txt`/`.pdf` instructions file via `ai/instruction_extraction.py` — the same Claude `messages.parse()` + retry + graceful-fallback-to-no-rules shape as structure analysis, just producing `FormattingRule`s instead of `Element`s).
2. **Resolve deterministically**: `formatting/engine.py::resolve_styles()` merges every rule source by spec §7.9's priority order (lower number wins) and converts the winners into real CSS per element-type target (`"Heading 1"`, `"Paragraph"`, `"Table"`, `"Image"`, ...); page-level properties (page size, margins, header/footer/page numbers) resolve separately into `Document.settings` via `extract_settings()`, since no single element owns them. Fully deterministic (NFR-007) — the AI is only ever involved in turning *instructions* into rules, never in applying them.
3. **The editor renders the result**: `documentToTiptap.ts` looks up each element's resolved style by `styleRef` and attaches it as a real inline `style="..."` attribute (via the new `AppliedStyle` Tiptap extension); `DocumentEditor.tsx` applies `Document.settings`' page size/margins as CSS on the editor's container and shows header/footer/page-number as a single non-repeating strip.

## How the page preview / toolbar / outline work (Phase 5a)

- **Page preview** is a CSS-only visual approximation, not real pagination: `DocumentEditor.tsx` puts a `repeating-linear-gradient` shadow band on the paper `div`, sized so the repeat unit is exactly one page height in pixels (`pageSize`/`orientation` → mm → px at 96dpi) — this is what makes the seams land on exact multiples of the page height with no drift. A `ResizeObserver` tracks the rendered content's height to estimate a page count (`Page 1 of N`), shown in the footer strip when `settings.showPageNumbers` is on. Content still flows continuously underneath — nothing actually moves to a new page.
- **Toolbar** (`components/Toolbar.tsx`) calls Tiptap commands directly (`editor.chain().focus().toggleBold().run()`, etc.) — bold/italic/underline/strike, font family/size (via `editor/fontSize.ts`, a custom mark since Tiptap ships no official font-size extension), the four text alignments, bullet/ordered list, and undo/redo (exposing Tiptap's already-working text-edit history as buttons, not new capability). These edits are **local to the browser only**, exactly like all editing in this phase — they are not turned into `FormattingRule`s or sent to the backend; doing that is the Properties-panel/live-override work of a later phase.
- **Outline** (`components/OutlinePanel.tsx`) lists every `heading` element indented by level; clicking one scrolls the matching node into view via `data-element-id` (rendered by the new `editor/elementId.ts` extension, from `Element.id` — also reusable later for mapping a click back to its source element). Hidden below the `lg` breakpoint rather than becoming a collapsible drawer.

## Assumptions made (flagged for confirmation before later phases build on them)

- **Document Model nesting**: list items and table cells are typed sub-fields *on* the `LIST`/`TABLE` element (with an `int` nesting `level` for lists), not separate nested `Element` records — `parentId` stays Section-only. Chosen over a fully recursive model both for simplicity and because Anthropic's structured-output mode doesn't support recursive schemas.
- **`confidence=1.0`** (not `null`) for everything the Markdown/DOCX parsers produce — reading explicit syntax/styles is a mechanical fact, not a probabilistic guess, so `1.0` is the honest value and keeps every `if confidence < threshold` check correct without a null-handling branch. Only the real AI path (and the naive-segmenter fallback, which still uses `null`) has anything other than `1.0`.
- **`documentType`** is only ever classified on the AI path; Markdown/DOCX documents stay `"general"` (classifying would need a second AI call, defeating the point of the deterministic paths).
- **Model default**: `ANTHROPIC_MODEL=claude-sonnet-5` (changed from Phase 0-1's `claude-opus-5`) — a better latency/cost fit for a bounded, well-specified extraction call fired on every document. Fully overridable via `.env`.
- **No `TaskList`/`TaskItem` Tiptap extension** — checklist items (`- [x]`) render as a regular list item with a ☑/☐ text glyph prefix rather than a real interactive checkbox node, to avoid adding a dependency beyond what this phase scoped.
- **Confidence UI is still passive-only** (a visual tint, no accept/reject interaction) — a formatting engine now exists, but there's still no Properties panel or live per-element override endpoint to reconcile a correction *into* (that's Phase 5b's job); building accept/reject now would still be dead-end UX.
- **DOCX simplifications**: table cell merges don't reconstruct real colspan/rowspan; footnotes are unsupported; a DOCX with no real styles applied (everything "Normal") never falls back to AI — re-paste the extracted text through the paste flow if AI analysis is wanted for such a file.
- **PDF scope**: text-based PDFs only, per spec TC-003 — no OCR, no scanned-document support.
- **Formatting priority tiers actually implemented**: spec §7.9 defines 7 tiers; tier 1 (live per-element user override) has no producer yet (no Properties panel/save endpoint), and tier 6 (AI style *inference*) was never asked for anywhere else in the spec, so neither is built. Tiers 2 (manually-typed instructions) and 3 (uploaded instructions file) are collapsed into one implemented priority — Phase 4's UI can never supply both for the same document, so a finer split would have no observable effect.
- **Custom templates are in-memory only**, same no-persistence MVP rule as documents (spec §16) — gone on server restart, and stored separately from built-in templates so a custom id can never shadow one.
- **Instructions-file upload supports `.txt`/`.pdf` only** (not `.docx`) — narrower than document upload, since a plain-text DOCX extraction helper doesn't otherwise exist and an instructions file is the less common upload case; type manually or paste the text instead for now.
- **Page preview is a CSS visual approximation, chosen deliberately over real reflow**: a page-height-shaped shadow seam repeats down one continuous scroll container; content never actually moves between fixed-height pages. Building true live-reflowing pagination on Tiptap/ProseMirror (no library does this for free) is a separate, much larger engineering effort than an MVP needs right now — confirmed with Boril before starting Phase 5.
- **None of the 3 built-in templates set `showPageNumbers`** — the page-count estimate (`Page 1 of N`) is real and tested (verified the seam/page-height math directly via computed styles), but there's currently no way to see it through the built-in templates alone; it only shows once something (a future template tweak, or an AI-extracted instruction) sets that setting to true.
- **Toolbar edits are local-only, same as all editing so far** — bold/italic/font/size/alignment/list toggles go straight through Tiptap/ProseMirror marks, never through the backend's `FormattingRule`/`resolvedStyles` system. Turning a manual toolbar edit into a persisted priority-1 `FormattingRule` (spec §7.9's "explicit current user change", the tier the formatting engine deliberately left unimplemented) is Phase 5b's Properties-panel work.
- **Tiptap 3's `useEditorState` hook didn't work in this setup** — its snapshot's `editor` stayed `null` in the selector even once the outer `editor` instance was genuinely ready (confirmed live: `console.log`-ing showed `{editor: Editor, state: null}` on every render). `components/Toolbar.tsx` uses the older, simpler pattern instead: subscribe to the editor's own `transaction`/`selectionUpdate` events and force a re-render, reading `editor.isActive(...)` fresh in the render body. Worth retrying `useEditorState` in a future Tiptap version rather than assuming this workaround is permanently required.
- Everything else from the Phase 0-1/2-3/4 README's assumptions (Tiptap as the editor library, Anthropic behind the `AIProvider` abstraction, no manual document-type/template *picker* UI, `confidence=1.0` for deterministic parses, `documentType` only classified on the AI path) still holds.
