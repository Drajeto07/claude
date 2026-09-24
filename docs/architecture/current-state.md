# Current state (Phase 0 baseline)

Snapshot of SmartDoc Formatter as of commit `e66d64a`, before the SaaS transformation described in `docs/architecture/target-state.md` begins. Condensed from a full file-by-file audit; see the published version for exhaustive detail: https://claude.ai/artifact/8WPTtt8SKCyG2hQbs9myTF

This document describes **what exists today**, including its real limitations — it is a baseline, not an aspiration. `README.md` and `docs/spec.md`'s own prose predate the persistence work and the full UI/UX overhaul and are stale in places; this file supersedes them for architecture questions until Phase 18's final audit replaces it in turn.

## Stack

- **Frontend**: Next.js 16 (App Router), TypeScript, Tailwind CSS 4, Tiptap 3/ProseMirror editor. No global state manager. Zero test files, zero test framework in `package.json`.
- **Backend**: FastAPI, Python 3.13, Pydantic. 179 passing pytest tests across 15 files.
- **Persistence**: none — a single `DocumentService()` instance (`backend/app/services/document_service.py`) holds every document in an in-memory `dict`, loaded once at process startup from `backend/app/services/persistence.py`, which writes one JSON file per document to `backend/data/documents/{id}.json` (atomic temp+rename writes). Not safe for more than one process/worker.
- **AI**: Anthropic Claude only, behind a 2-method `AIProvider` ABC (`backend/app/ai/base.py`). Three call sites, all with an identical retry(1)+fallback shape: structure analysis (unstructured prose only — DOCX/Markdown parse deterministically), instruction extraction (text → `FormattingRule`/operations), Style Analysis (read-only tone/consistency report). AI never writes `resolvedStyles` directly; everything it produces is validated then handed to the deterministic engine.
- **No auth, no database, no payments, no subscriptions, no admin panel, no deployment config of any kind** (no Dockerfile, no CI, no docker-compose). Confirmed by direct grep across `backend/app` and the frontend source — not an oversight in this document, an actual absence in the code.

## Document Model

`backend/app/models/document.py`, hand-mirrored 1:1 in `frontend/types/document.ts`. `Document { metadata, settings, sections[always 1], elements[], formattingRules[], revisions[], resolvedStyles }`. `Element` is a flat list (not a tree) with `type`/`inline`/`listItems`/`table`/`image`/`level`/`confidence`/`styleRef`. Images are base64 `data:` URIs embedded directly in the JSON — no separate asset storage. `MarkType` covers `bold|italic|strike|code|link` — no `underline` value exists at the character-run level (element-level underline via `FormattingProperty.UNDERLINE` works; the Toolbar's per-character underline does not survive a save, see Known Bugs).

## Formatting engine

Fully centralized in `backend/app/formatting/engine.py`. Priority model (lower number wins), 5 of 7 spec tiers actually have a producer: `PRIORITY_LIVE_OVERRIDE=1` (PropertiesPanel/PageSettingsPanel), `PRIORITY_INSTRUCTION=2` (AI instruction extraction — tier 3 "official uploaded rule" is collapsed into this, no separate producer), `PRIORITY_CUSTOM_TEMPLATE=4`, `PRIORITY_BUILTIN_TEMPLATE=5`, `PRIORITY_DEFAULT=7` (tier 6, AI style inference, was never asked for anywhere and was never built). `recompute_styles()` fully rebuilds `resolvedStyles`/`settings`/every `element.styleRef` from `formattingRules` on every mutation — this is the actual source of truth, not anything cached. `apply_formatting()` preserves priority-1 overrides across a re-format (the core "manual changes survive a reformat" guarantee). `detect_conflicts()` only flags a conflict where the resolved value would genuinely differ. 3 built-in templates (`academic-default`, `professional-cv`, `official-standard`) are hardcoded Python; custom templates via `POST /api/templates` are **in-memory only**, gone on restart.

## API surface

19 routes total under `/api/documents` (17) and `/api/templates` (2), plus `/api/health`. No versioning (`/api/v1` does not exist). No auth on any route — any client that knows a document's UUID can read/write/export it. Full list: create (paste/upload), get, format, undo, redo, set/clear element style, update content (autosave), add page, add element, rename, set/clear page setting, style-analysis, export docx/pdf, list/create templates. Notably **absent**: `DELETE /documents/{id}` — the backend function to delete a persisted document file exists (`persistence.py::delete_document_file`) but is never called from anywhere; confirmed via grep.

## Known, verified bugs and gaps (Phase 1 targets)

All confirmed by reading the actual code, not inferred:

1. **Character-level underline is silently dropped.** `frontend/editor/tiptapToDocument.ts`'s `_MARK_TYPES` list (and the backend `MarkType` enum itself) has no `underline` value — Toolbar underline renders live in the browser but vanishes the next time content reconciles/saves.
2. **Captions degrade to plain paragraphs.** Tiptap has no caption node; `tiptapToDocument.ts::deriveFromNode`'s `"paragraph"` case always returns `type: "paragraph"`, overwriting an original `Element.type: "caption"` the first time the document round-trips through the editor.
3. **Hyperlinks are captured on parse but lost on export.** Both `docx.py`/`markdown.py` extract `Mark(type=LINK, href=...)`, but neither `docx_export.py` nor `pdf_export.py` checks for `MarkType.LINK` — the exported file has plain text where a link was.
4. **No document deletion.** See API surface above.
5. **Upload size limit can silently no-op.** `api/documents.py`'s check is `if file.size is not None and file.size > max_bytes` — when a client doesn't report `Content-Length`, the cap is skipped entirely.
6. **Custom templates don't survive a restart.**
7. **DOCX upload does not detect**: page breaks (no run-level `w:br type="page"` check anywhere in `docx.py`'s block loop), or header/footer content (the parser never reads `docx_document.sections[0].header/footer`) — both are silently absent from the imported document, not merely unrepresented.
8. **Table colspan/rowspan fields exist in the model** (`TableCell.colspan/rowspan`) **but nothing ever sets them above 1** — a merged-cell source table imports as a flat grid.
9. **Deeply nested lists (3+ levels) don't fully round-trip** through DOCX export (Word's `List Bullet`/`List Number` styles only approximate nesting via `left_indent`).
10. **The undo/redo stack is a list of full, unbounded `Document.model_copy(deep=True)` snapshots** (`document_service.py::_push_undo_snapshot`) — for a document with embedded base64 images, every mutation duplicates every image's full payload in memory, with no cap on stack depth.

## Test coverage

179 backend tests (pytest), 15 files, all green. Genuine round-trip tests exist for export (`test_docx_export.py`/`test_pdf_export.py` build a `Document`, export it, re-open the output file, assert on real values). No test exercises a real uploaded DOCX all the way through edit→reformat→export→re-import. Zero frontend tests of any kind (no Jest/Vitest/Playwright/RTL in `package.json`).

## What's good and must not be broken by the transformation below

The AI/engine separation (AI never writes styles directly); the priority-resolution model; the graceful-degradation pattern shared by all three AI call sites; the two independent, `resolvedStyles`-driven DOCX/PDF exporters; atomic JSON writes; conflict detection's "only flag a real difference" precision. These pieces are correct and are being carried into the new architecture, not replaced.
