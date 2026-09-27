# AI continuation — SmartDoc production hardening

Resume with: **"Прочети docs/AI-CONTINUATION.md и продължи от next task."**

Read in this order: this file → `docs/session-state.json` → `python tools/tracker/tracker.py show --open --phase <current>`
→ the brief section for the current phase in `docs/implementation-brief.md` (§104 lists the phases).
Branch: `feature/smartdoc-production-hardening`. The tracker is `SmartDoc_Master_Implementation_Tracker.xlsx`
(repository root); update it with `tools/tracker/tracker.py` after every atomic task (see `tools/tracker/README.md`).

## CURRENT STATE

- Phase 0: DONE (commit `4da4ecb`).
- Phase 1 (editor integrity + content preservation): COMPLETE (every task DONE/VERIFIED; gate run 2026-09-27).
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
  - `phase-01f-editor-direct-formatting` (`53c84e4`): alignment typed with a shortcut or pasted, and a pasted picture's
    size, are saved as the element's own style (`reconcileWithIds` → `styles`, `PUT /content` `styles`, validated,
    no revision entry); a block split off one keeps its alignment (as Word); pasting into an empty paragraph keeps the
    pasted paragraphs' attributes (editor fix, `pasteIntoEmptyBlock.ts`); after each save the editor shows each block
    the look it was saved with. What the editor holds that the model can't keep (hsl colours, em sizes, nested
    alignment, differing cells, column widths) is named in the status bar and the Проверка panel ("While editing").
    Security (SEC-022, found on the way): rule values reached CSS as raw text — `center;background-image:url(…)` via
    the element-style/page-setting endpoints or an instruction; now `formatting/values.py` checks every value at every
    entry (422 / dropped) and at resolve (stored bad values skipped). FMT-005 done with it.
  - `phase-01g-phase-1-complete` (this commit):
    - link titles (tooltips) are kept from Word (ScreenTips, also the HYPERLINK field's switch) and Markdown, through the
      editor, and back into Word (`Mark.title`, EDIT-010);
    - a run's marks keep one order, MarkType's, on both sides, so opening a document saves nothing (EDIT-007);
    - Markdown pictures are named as left out with their description, and `---` becomes a rule (FID-006, found on the
      way);
    - EDIT-011 is resolved by naming: keeping per-cell alignment and column widths moves to DOCX-017;
    - TEST-010 verified;
    - the documentation tree is started (`docs/document-model`, `docs/architecture/fidelity.md`, `docs/docx`,
      `docs/formatting`, `docs/security`, `docs/testing`).
- Phase 2 (AI fidelity + destructive-operation review): in progress.
  - `phase-02a-ai-fidelity-check` (`78f5c8f`), AI-001..AI-004:
    - `app/fidelity/text_check.py::check_text` compares an AI answer with its source token by token, in order.
      Tokens are words, numbers with their sign, decimals, separators and percent sign, and every punctuation mark.
      Typographic variants and line-start list/heading marks don't count.
    - Differences are classified: number, unit, negation, sentence, duplicate, reordered, punctuation, words.
      Numbers and units are protected facts. `changed_numbers` covers text whose words may rightly change.
    - Structure analysis refuses any answer that alters its piece. It retries once, then splits that piece alone
      into paragraphs, and logs what changed without the text.
    - This replaces the 20%-unknown-words check (AUD-02).
  - `phase-02b-ai-proposals` (`5f67f5a`), AI-005..AI-007 and REV-001:
    - instruction operations are sorted by what they touch;
    - styles and page breaks apply at once (after the formatting pass, which used to drop a style set on one
      element);
    - inserting, deleting or moving text becomes a `ProposedChange` on `Document.proposals`, with what it would
      change;
    - the user accepts it (validated against the current document, one undoable step, 409 when it no longer fits)
      or rejects it;
    - the Instructions panel lists the proposals, and the status bar counts them;
    - the E2E server has a scripted AI (`backend/scripts/e2e_ai.py`) for two fixed instructions.
  - `phase-02c-ai-budget` (this commit), AI-008:
    - every job and every request that calls the AI gets an allowance: `AI_CALLS_PER_JOB` calls and
      `AI_SECONDS_PER_JOB` seconds (`ai/budget.py`);
    - past it, calls are refused at once, and a running call is cancelled at the deadline;
    - structure analysis then splits the rest into paragraphs, with a note in the import report;
    - retries are capped at 0–3.
  - **Tracker updates for AI-001..AI-008, REV-001, CORE-005, AUD-02 and AUD-05 are pending**: the workbook has been
    open in Excel on this machine since 10:55. When `~$SmartDoc_Master_Implementation_Tracker.xlsx` is gone, record
    them:
    - VERIFIED, with the evidence in the commit messages of `phase-02a-ai-fidelity-check` (`78f5c8f`),
      `phase-02b-ai-proposals` (`5f67f5a`) and `phase-02c-ai-budget`;
    - CORE-005 IN_PROGRESS (proposals are its first command);
    - the test runs (backend 799 then 805 / 1 skipped, Vitest 117, Playwright 20);
    - then DONE with those commits.
    - The session that queued them kept the exact commands in its scratchpad (`pending_tracker.sh`); a new session
      rebuilds them from this list.

## LAST VERIFIED

- 2026-09-27 — AI budget: backend 805 passed / 1 skipped (`tests/test_ai_budget.py`: 6).
- 2026-09-27 — AI proposals: backend 799 passed / 1 skipped; Vitest 117; Playwright 20 (new
  `e2e/proposals.spec.ts`: instruct → the deletion waits → accept → reload → reject → reload); tsc and eslint
  clean.
- 2026-09-27 — AI fidelity check: backend 789 passed / 1 skipped (`tests/test_ai_fidelity.py`: 36).

- 2026-09-27 — Phase 1 gate:
  - backend 754 passed / 1 skipped; Vitest 113; Playwright 19; tsc and eslint clean.
  - browser check in the throwaway stack:
    - a Markdown picture was named on import;
    - a pasted centred line, a 160 px picture and a titled link survived a reload (centred; width 24.9%; title
      kept);
    - an hsl colour was named "not kept" while editing and was gone after the reload.

- 2026-09-27 — editor direct formatting + rule values: backend 749 passed / 1 skipped; Vitest 109; Playwright 19
  (new `e2e/direct-formatting.spec.ts`: paste → reload keeps centred line and 50% picture; hsl colour named); tsc,
  eslint clean.
- 2026-09-27 — import detections: backend 713 passed / 1 skipped; Vitest 84; tsc and eslint clean. Probe confirmed the
  section-break bug before the fix (continuous → page break) and the new test pins Word's behaviour.
- 2026-09-27 — export report: backend 694 passed / 1 skipped; Vitest 84; Playwright 18; tsc and eslint clean.

## WHAT WAS CHANGED

- Backend:
  - `models/document.py`: `Mark.title`; `InlineRun` keeps a canonical mark order;
  - `parsers/docx_inline.py` + `docx.py`: tooltips and field ScreenTips;
  - `export/docx_export.py`: `w:tooltip`;
  - `parsers/markdown.py`: link titles; pictures named; rules imported;
  - `capabilities.py`: editor.link_title, text.markdown, text.markdown_images.
- Frontend: `editor/tiptapToDocument.ts` (link title, `MARK_ORDER`), `editor/documentToTiptap.ts` (link title).
- Tests:
  - `backend/tests/test_link_titles.py`;
  - `test_markdown_parser.py` (+2);
  - `test_document_nesting.py` (+1);
  - `test_capabilities.py`: the `markdown.` key prefix; no `not_detected` row is required any more;
  - `frontend/editor/directFormatting.test.ts` (+4).
- Docs: the tree listed above.

## WHAT PASSED

- Everything above.

## WHAT FAILED

- Nothing open.

## WHAT REMAINS

- Phase 2, from the tracker:
  - AI-001: comparator hardening (numbers, punctuation, structure);
  - AI-002: protected facts;
  - AI-003: structure analysis uses the comparator and falls back per piece;
  - AI-004: adversarial tests;
  - AI-005: classify AI operations;
  - REV-001: the change model;
  - AI-006: PLAN → VALIDATE → PREVIEW → ACCEPT → APPLY;
  - AI-007: the proposal review UI;
  - AI-008: budgets;
  - AI-009: prompt-injection review;
  - CORE-005: the command model.
- Phase 3 follow-ups recorded on the tasks:
  - DOCX-015: sections as a model concept;
  - DOCX-016: multilevel numbering, prefixes and suffixes;
  - DOCX-017: table engine, plus per-cell alignment and column widths from EDIT-011;
  - DOCX-012: custom properties need DOCX-010;
  - DOCX-026: autolink off by default;
  - SEC-014: a model-level href policy.
- Phases 3–18 as listed in the tracker.
- Needs Boril (never guess): Stripe account and prices, e-mail provider credentials, Anthropic API key for real-model
  checks, hosting/deployment target, SEC-021 (sensitivity-label metadata in `корекции.docx` in public history).

## NEXT ACTION

- If the tracker is closed, apply the pending updates (see CURRENT STATE).
- Phase 2, remaining work:
  - AI-009: a prompt-injection hardening review. Document content never becomes instructions; check output abuse.
    Review `ai/prompting.py` (the untrusted-document tag), every prompt builder, and output validation (values
    now checked by `formatting/values.py`; operations limited to listed element ids); then write hostile-document
    tests.
  - CORE-005: the general command model (P1), after AI-008/009.
- Then the Phase 2 gate: full suites, a browser check, docs, and commit.

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
