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
  - `phase-01b-fidelity-report` (this commit): the Document Fidelity Report. `backend/app/fidelity/`: report model
    (FidelityItem: feature, policy class per brief §90, element ids, source/new state, confidence, count,
    contentChanged), `compare_words` (the content check: source words vs document words, in order; verified only
    when identical), `docx_source.py` (reads a DOCX's text independently of the importer, mirroring only its open
    representation choices: accepted revisions, field results, linear math, drop caps, text boxes after their
    paragraph, note labels), Markdown/PDF sources, `imports.py`. Every import path attaches `Document.importReport`.
    The editor shows it (Проверка panel + status-bar verdict: "No content changes" only when proven and nothing else
    lost content).
  - `phase-01c-export-report`: exports report what they approximate or leave out and re-read the file (DOCX: exactly
    the document's words; PDF: every word in order, its own numbers/headers allowed); shown under Download.
- Still open in Phase 1: CORE-004 (capability matrix), FID-002 (explicit importer detections beyond the content
  check), EDIT-007..011 (attribute-level editor fidelity), TEST-010.

## LAST VERIFIED

- 2026-09-27 — export report: backend 694 passed / 1 skipped; Vitest 84; Playwright 18; tsc and eslint clean.
- 2026-09-27 — backend 688 passed / 1 skipped; Vitest 80; Playwright 18; tsc and eslint clean. Browser check in the
  throwaway stack with the audit fixtures a03 (differences shown: heading numbers baked into text) and a05 (header
  variants left out).

## WHAT WAS CHANGED

- Backend: `app/fidelity/` (new), `models/document.py` (`importReport`), `parsers/docx.py` + `docx_inline.py` (notes
  carry feature/policy/content flag), `services/ingestion_service.py` (reports on every import);
  `tests/test_fidelity_report.py`.
- Frontend: `editor/panels/FidelityPanel.tsx` (+ test), `EditorStatusBar.tsx`, `DocumentEditorShell.tsx`, types;
  `e2e/fidelity.spec.ts`; `e2e/nested.spec.ts` made deterministic; `.next-preview` ignored by git/eslint/vitest.
- Tools: `tools/dev/throwaway-backend.ps1`, `throwaway-frontend.ps1`; `.claude/launch.json` throwaway entries.

## WHAT PASSED

- Everything above.

## WHAT FAILED

- Nothing open. One full E2E run failed in `nested.spec.ts` (paste landed at the document start: the caret wasn't
  placed yet); the test now asserts focus and moves to the end first — 3/3 and the full suite pass.

## WHAT REMAINS

- Phase 1: CORE-004, FID-002 detections (hidden text, caps, underline variants, numbering formats/continuation/start,
  sections, content controls, custom properties, dropped links, crop/rotation, table geometry, bullets in cells,
  empty paragraphs, autolinks, SmartArt/charts), EDIT-007..011, TEST-010.
- Phases 2–18 as listed in the tracker.
- Needs Boril (never guess): Stripe account and prices, e-mail provider credentials, Anthropic API key for real-model
  checks, hosting/deployment target, SEC-021 (sensitivity-label metadata in `корекции.docx` in public history).

## NEXT ACTION

- CORE-004: the capability matrix as data (`backend/app/capabilities.py`: per format and feature, import / edit /
  export / round_trip and the policy class), served at `GET /api/v1/capabilities`; a test that every fidelity
  feature key used in the code is in the matrix. Write `backend/tests/test_capabilities.py` first.

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
- The resume reminder is a session-only cron job (hourly at :23, expires after 7 days); it only fires while this session is
  open and idle. Delete it (CronList + CronDelete) when the brief is finished or only Boril-input items remain.
