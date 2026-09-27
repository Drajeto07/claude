# AI continuation — SmartDoc production hardening

Resume with: **"Прочети docs/AI-CONTINUATION.md и продължи от next task."**

Read in this order: this file → `docs/session-state.json` → `python tools/tracker/tracker.py show --open --phase <current>`
→ the brief section for the current phase in `docs/implementation-brief.md` (§104 lists the phases).
Branch: `feature/smartdoc-production-hardening`. The tracker is `SmartDoc_Master_Implementation_Tracker.xlsx`
(repository root); update it with `tools/tracker/tracker.py` after every atomic task (see `tools/tracker/README.md`).

## CURRENT STATE

- Phase 0: DONE (commit `4da4ecb`).
- Phase 1 (editor integrity + content preservation), first half committed as `phase-01a-editor-integrity`:
  - model: `TableCell.blocks`, `ListItem.blocks`, `Element.children` hold nested blocks as Elements (authoritative when
    set; `inline` keeps plain text), `Element.numbering` {start, format}; nesting capped at 8 (422 beyond);
    `walk_elements()` / `inline_runs()` for every reader;
  - editor: `tiptapToDocument.ts` maps every node of the schema recursively (a test checks the whole
    `getSchema(editorExtensions)`); unknown nodes/marks throw `UnsupportedContentError` → autosave status
    "Not saved – …", nothing sent, last saved version kept; `documentToTiptap.ts` renders it all back;
  - backend: nested pasted pictures validated + stored as assets; exports fetch nested assets; health links see
    list items/cells/nested blocks;
  - exports: DOCX and PDF render nested blocks in reading order, list start/format, DOCX picture alt text.
- Still open in Phase 1: FID-001..005 (fidelity report), CORE-004 (capability matrix), EDIT-007..011
  (attribute-level editor fidelity), TEST-010 (consolidate).

## LAST VERIFIED

- 2026-09-27 — backend 659 passed / 1 skipped; Vitest 77 passed (the new nested suite: 26 of 28 fail against the
  pre-fix mapping); Playwright 17 passed incl. `e2e/nested.spec.ts` (real paste event, autosave, reload); tsc, eslint clean.

## WHAT WAS CHANGED

- Backend: `models/document.py`, `services/image_assets.py`, `services/document_service.py`, `formatting/health.py`,
  `export/docx_export.py` (adders write into a `_Place`: body or cell), `export/pdf_export.py`; tests
  `test_document_nesting.py`, `test_nested_blocks_api.py`, `test_health.py`.
- Frontend: `editor/tiptapToDocument.ts`, `editor/documentToTiptap.ts`, `editor/useAutoSave.ts`,
  `editor/EditorStatusBar.tsx`, `editor/DocumentEditorShell.tsx`, `types/document.ts`, regenerated `types/generated/*`;
  tests `editor/nestedBlocks.test.ts`, `editor/useAutoSave.test.tsx`, `e2e/nested.spec.ts`.
- Tracker tool: retries the atomic replace (transient Windows file locks).

## WHAT PASSED

- Everything above. Phase 0 baseline checks unchanged.

## WHAT FAILED

- Nothing open. (A first E2E run failed at `next build`'s type check because of a mock's typing in
  `useAutoSave.test.tsx`; fixed.)

## WHAT REMAINS

- Phase 1: FID-001 structured report model (FidelityItem: element, feature, source state, new state, confidence,
  reason, policy class) + FID-005 policy classes; content verification (source DOCX/PDF words vs model words) so
  "No content changes" is shown only when proven; FID-002 importer detections (hidden text, caps, numbering
  formats/continuation/start, sections, header variants, content controls, custom properties, links, crop/rotation,
  table geometry, bullets in cells, empty paragraphs, autolinks, SmartArt/charts); FID-003 export report; FID-004 UI;
  CORE-004 capability matrix; EDIT-007..011.
- Phases 2–18 as listed in the tracker.
- Needs Boril (never guess): Stripe account and prices, e-mail provider credentials, Anthropic API key for real-model
  checks, hosting/deployment target, SEC-021 (sensitivity-label metadata in `корекции.docx` in public history).

## NEXT ACTION

- FID-001: add `backend/app/fidelity/` (report model + word-level comparator), write
  `backend/tests/test_fidelity_report.py` first; then wire the import path to build and store the report.

## IMPORTANT WARNINGS

- Never mark a task VERIFIED/DONE without evidence and tests (the tool refuses anyway). DONE also needs the commit.
- The repository is PUBLIC (github.com/Drajeto07/claude). Run the secret scan before every push (it also flags MSIP
  sensitivity labels now; `корекции.docx` is the known hit, SEC-021). Never commit `backend/.env`, the user's
  stress-test DOCX, Office lock files, or any password the user pasted in chat.
- Excel/Word on this machine stamp `MSIP_Label_*` (organisation tenant ID) into Office files on save: the tracker
  tools strip them; scrub any Word fixture before committing.
- Tests must never touch the real Supabase database (`backend/.env` points at it); the test suite enforces this.
- `next build` (and so the E2E web server) type-checks test files too: run `npx tsc --noEmit` before E2E.
- The FastAPI dev server's auto-reload silently does nothing: restart it after backend edits.
- Close the tracker in Excel before running `tracker.py` (it refuses to write while `~$` lock files exist).
  `excel_recalc.py` needs a Python with pywin32 (e.g. `%TEMP%\sda\Scripts\python.exe`, the audit venv).
- The resume reminder is a session-only cron job (hourly at :23, expires after 7 days); it only fires while this session is
  open and idle. Delete it (CronList + CronDelete) when the brief is finished or only Boril-input items remain.
