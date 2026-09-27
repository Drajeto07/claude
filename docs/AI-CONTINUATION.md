# AI continuation — SmartDoc production hardening

Resume with: **"Прочети docs/AI-CONTINUATION.md и продължи от next task."**

Read in this order: this file → `docs/session-state.json` → `python tools/tracker/tracker.py show --open --phase <current>`
→ the brief section for the current phase in `docs/implementation-brief.md` (§104 lists the phases).
Branch: `feature/smartdoc-production-hardening`. The tracker is `SmartDoc_Master_Implementation_Tracker.xlsx`
(repository root); update it with `tools/tracker/tracker.py` after every atomic task (see `tools/tracker/README.md`).

## CURRENT STATE

- Phase 0: DONE (commit `4da4ecb`).
- Phase 1 (editor integrity + content preservation):
  - `phase-01a-editor-integrity` (`1fe27a9`, DONE): nested blocks in cells/list items/quotes survive the editor, the
    backend and both exports; list start/format; unknown content stops the save visibly.
  - `phase-01b-fidelity-report`: the Document Fidelity Report (`backend/app/fidelity/`): report model (policy class per
    brief §90), the content check (`compare_words`: "No content changes" only when the source's words and the
    document's are identical), an independent DOCX text reader, every import attaches `Document.importReport`, shown in
    the Проверка panel and the status bar.
  - `phase-01c-export-report`: exports report what they approximate or leave out and re-read the file.
  - `phase-01d-capability-matrix`: `backend/app/capabilities.py` (import/edit/export/round-trip per feature, policy,
    report keys, tests), `GET /api/v1/capabilities`, `tests/test_capabilities.py` ties it to the code both ways.
  - `phase-01e-import-detections` (`622d9c1`, FID-002 DONE): the import report names everything the importer changes
    without keeping it. `app/fidelity/docx_detect.py` reads the file itself (styles included) for hidden text, caps,
    underline variants, content controls, custom properties/sensitivity labels (never their values), crop/rotation,
    table geometry, bullets in cells, RTL, autolinks, charts/SmartArt, and per-section differences (page setup, odd/even
    breaks, page numbering, page borders, line numbers, vertical alignment). The importer itself notes empty spacing
    paragraphs, links with unsafe addresses (kept as text), empty numbered items, numbered headings, custom and
    multi-level list labels, shapes. Kept now instead of lost: list number format/start/continuation (Element.numbering,
    back into Word and PDF) and the file's core properties (`DocumentMetadata.sourceProperties`, back into Word instead
    of python-docx's "python-docx"/2013 stamps; author/subject into PDF). Bug fixed: section breaks broke the page by
    the ending section's type; Word uses the next section's (continuous breaks became page breaks). The golden JSON
    export is deterministic now (stable ids and times).
  - `phase-01f-editor-direct-formatting` (this commit): alignment typed with a shortcut or pasted, and a pasted picture's
    size, are saved as the element's own style (`reconcileWithIds` → `styles`, `PUT /content` `styles`, validated,
    no revision entry); a block split off one keeps its alignment (as Word); pasting into an empty paragraph keeps the
    pasted paragraphs' attributes (editor fix, `pasteIntoEmptyBlock.ts`); after each save the editor shows each block
    the look it was saved with. What the editor holds that the model can't keep (hsl colours, em sizes, nested
    alignment, differing cells, column widths) is named in the status bar and the Проверка panel ("While editing").
    Security (SEC-022, found on the way): rule values reached CSS as raw text — `center;background-image:url(…)` via
    the element-style/page-setting endpoints or an instruction; now `formatting/values.py` checks every value at every
    entry (422 / dropped) and at resolve (stored bad values skipped). FMT-005 done with it.
- Still open in Phase 1: EDIT-010 (link title), EDIT-011 (per-cell alignment and column widths kept, not only named),
  EDIT-007 (canonical mark order), TEST-010 consolidation, then the Phase 1 gate.

## LAST VERIFIED

- 2026-09-27 — editor direct formatting + rule values: backend 749 passed / 1 skipped; Vitest 109; Playwright 19
  (new `e2e/direct-formatting.spec.ts`: paste → reload keeps centred line and 50% picture; hsl colour named); tsc,
  eslint clean.
- 2026-09-27 — import detections: backend 713 passed / 1 skipped; Vitest 84; tsc and eslint clean. Probe confirmed the
  section-break bug before the fix (continuous → page break) and the new test pins Word's behaviour.
- 2026-09-27 — export report: backend 694 passed / 1 skipped; Vitest 84; Playwright 18; tsc and eslint clean.

## WHAT WAS CHANGED

- Backend: `app/formatting/values.py` (new: what a rule value may be, per property), `formatting/engine.py` (`_usable`
  at resolve, `set_direct_styles`, operations checked), `schemas/formatting.py` (`RuleValue`), `schemas/document.py`
  (`DirectStyle`, `UpdateContentRequest.styles`), `services/document_service.py` + `api/documents.py` (content save
  applies them), `ai/instruction_extraction.py` (values checked), `capabilities.py` (editor rows).
- Frontend: `editor/tiptapToDocument.ts` (direct styles, `NOT_KEPT` notes, `widthPercent`, cell `align`),
  `editor/documentToTiptap.ts` (`appliedStyle`, own alignment as `textAlign`), `editor/useAutoSave.ts` (sends styles,
  `notKept`, `syncAppliedStyles`), `editor/pasteIntoEmptyBlock.ts` (new) + `extensions.ts`, `EditorStatusBar.tsx`,
  `EditorState.tsx`, `DocumentEditorShell.tsx`, `panels/FidelityPanel.tsx` ("While editing"), `services/api/documents.ts`.
- Tests: `backend/tests/test_rule_values.py` (34), `backend/tests/test_editor_direct_styles.py` (2),
  `frontend/editor/directFormatting.test.ts` (9), `useAutoSave.test.tsx` (+3), `editorRoundTrip.test.ts` (+12),
  `FidelityPanel.test.tsx` (+1), `frontend/e2e/direct-formatting.spec.ts`.

## WHAT PASSED

- Everything above.

## WHAT FAILED

- Nothing open.

## WHAT REMAINS

- Phase 1: EDIT-010 (link title), EDIT-011 (per-cell alignment and column widths: kept, not only named — or left to
  DOCX-017), EDIT-007 (canonical mark order), TEST-010 consolidation, then the Phase 1 gate.
- Phase 3 follow-ups recorded on the tasks: DOCX-015 (sections as a model concept), DOCX-016 (multilevel numbering,
  prefixes/suffixes), DOCX-012 (custom properties need DOCX-010), DOCX-026 (autolink off by default).
- Phases 2–18 as listed in the tracker.
- Needs Boril (never guess): Stripe account and prices, e-mail provider credentials, Anthropic API key for real-model
  checks, hosting/deployment target, SEC-021 (sensitivity-label metadata in `корекции.docx` in public history).

## NEXT ACTION

- EDIT-010: link titles (tooltips) kept — `Mark.title` in the model (backend + generated types), editor link mark
  `title` ↔ Mark, DOCX import (`w:hyperlink/@w:tooltip`) and export (tooltip), PDF ignores it (matrix note). Then
  EDIT-011 (decide: model fields for per-cell alignment and column widths now, or leave to DOCX-017 with the report),
  EDIT-007, TEST-010, Phase 1 gate (full suites + browser check in the throwaway stack).

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
- Browser checks: use the throwaway stack (preview configs `smartdoc-backend-throwaway` / `smartdoc-frontend-throwaway`,
  or `tools/dev/throwaway-*.ps1`) — never the `backend` config, which uses the real database. Stop them before E2E
  (same ports 8100/3100). The browser pane may be hidden: `find`/`form_input`/`get_page_text` work, clicks may not.
- Close the tracker in Excel before running `tracker.py` (it refuses to write while `~$` lock files exist).
  `excel_recalc.py` needs a Python with pywin32 (e.g. `%TEMP%\sda\Scripts\python.exe`, the audit venv).
- After changing the importer, regenerate `python -m scripts.export_golden_json` (backend) — the output is stable, so
  the diff shows only real changes.
- The resume reminder is a session-only cron job (hourly at :23, expires after 7 days); it only fires while this session is
  open and idle. Delete it (CronList + CronDelete) when the brief is finished or only Boril-input items remain.
