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
- Phase 3 (DOCX/OOXML preservation): in progress.
  - `phase-03a-source-package` (`de23961`), DOCX-010, DOCX-011, DOCX-012 and TEST-023:
    - an uploaded Word file is kept as it was: `Document.sourcePackage` points at a checksummed asset;
    - a Word export of it is written into that file: only the body is regenerated, and styles, headers and footers
      of every kind, the last section's properties, custom properties, the sensitivity label and the theme are the
      original's;
    - styles and the main header or footer are rewritten only where the document changed them;
    - the import report says what the Word export keeps, and a PDF export says what it doesn't;
    - `app/export/package_check.py` independently validates every Word export's package;
    - kept originals count toward plan storage (a decision for Boril whether they should).
  - `phase-03b-original-blocks` (`c8c2d27`), DOCX-028: unchanged blocks keep their original XML in Word exports.
    - The importer records each top-level element's body children (`Element.sourceBlocks`). An upload whose file is
      kept stamps each element's fingerprint (`Element.sourceHash`, `app/export/provenance.py`). The fingerprint
      covers content and look: own, kind's, body's and nested blocks' resolved styles. A page break has none.
    - The copy plan (`docx_export.py::_copy_plan`) groups elements with their children, and uncovered children join
      the group before them. A group is copied when:
      - every element in it is unchanged;
      - it is together and in its original order;
      - its children are contiguous;
      - its XML is self-contained: no tracked changes, no note references, and balanced fields, bookmarks and
        comment ranges.
      Everything else is written anew.
    - Provenance is the server's: `PUT /content` keeps stored values by id (`keep_provenance`).
    - Earlier sections come back with their ending paragraph. Page setup now runs after the body, so:
      - changed sizes and margins reach every section (orientation kept, landscape pages turned);
      - a changed main header is rewritten where Word shows it (link to previous);
      - page numbers left out, or asked for, apply to every section.
    - Reports:
      - the export names a section lost with a changed paragraph (`export.docx.section_lost`, LOSSY);
      - the import report says earlier sections' setup and headers are kept while their ending paragraph is
        unchanged;
      - a PDF export names them as Word-only.
    - Golden set: `13-kept-blocks.docx` (field, content control, double underline, bookmark, landscape section).
      Every golden document stamped and exported into its original is copied, is a sound package and passes the
      content check. `12-complex` rewrites only the footnote paragraph and the note, by design.
    - E2E `e2e/kept-blocks.spec.ts`: after an edit in the real editor, the untouched paragraphs keep their content
      control, double underline and landscape section. So the editor's round trip matches the fingerprints.
  - `phase-03c-hidden-text` (this commit), DOCX-025: Word's hidden text stays hidden.
    - `MarkType.HIDDEN` (appended, so no existing mark order changes). The importer resolves `w:vanish` as Word does:
      the run, its character style, its paragraph's style (the default one when none), the defaults. `webHidden`
      stays visible.
    - The detector uses the default paragraph style the same way. It names hidden text as kept hidden
      (DETECTED_PRESERVED, not a content change).
    - The editor has a non-inclusive `hidden` mark (`editor/hiddenText.ts`, also parsed from Word's display:none paste).
      CSS hides it unless the page has `show-hidden`, and the status bar's "Show hidden text (N words)" toggles it and
      re-paginates. The Structure panel leaves hidden text out of headings.
    - Word export: `w:vanish`. PDF: hidden runs aren't printed, `export.pdf.hidden_text` says how many words, and
      the PDF content check compares visible words (`document_words(visible_only=True)`).
    - Golden `02-rich-text.docx` gained a hidden sentence (round trip through the editor in Vitest; E2E
      `e2e/hidden-text.spec.ts`).
  - Next in Phase 3: DOCX-013 (character formatting), then DOCX-014..027, FMT-004 and TEST-020..022.
- Phase 2 (AI fidelity + destructive-operation review): COMPLETE (gate 2026-09-27; CORE-005 deferred with reason).
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
  - `phase-02c-ai-budget` (`03f6a44`), AI-008:
    - every job and every request that calls the AI gets an allowance: `AI_CALLS_PER_JOB` calls and
      `AI_SECONDS_PER_JOB` seconds (`ai/budget.py`);
    - past it, calls are refused at once, and a running call is cancelled at the deadline;
    - structure analysis then splits the rest into paragraphs, with a note in the import report;
    - retries are capped at 0–3.
  - `phase-02d-prompt-injection` (`8253a6a`), AI-009 and SEC-018:
    - every AI task fences the document in a per-call tag, marked as data;
    - every AI answer field that reaches a document is bounded (`ai/schemas.py`) — before, a structure answer could
      store any document type, a heading level 99 or a code language with quotes;
    - `tests/test_prompt_injection.py` covers hostile documents.
  - Phase 2 gate (`76c50ee`, docs only):
    - suites: backend 817 / 1 skipped, Vitest 117, Playwright 20;
    - browser check in the throwaway stack:
      - "make the title red and delete “This draft paragraph”" made the title red at once;
      - the paragraph was kept and listed under Changes to review, with the notice and the status-bar count;
      - Accept removed it, and a reload kept it removed with nothing pending;
    - CORE-005 (the general command model) is DEFERRED: proposals implement validate, preview, apply and undo;
      the shared abstraction waits for a second kind (translation, repair, batch).
  - Tracker: up to date (the Phase 2 and 3a updates queued while the workbook was open in Excel were applied).

## LAST VERIFIED

- 2026-09-27 — hidden text (DOCX-025): backend 876 passed, 1 skipped; Vitest 125; Playwright 22 (new
  `e2e/hidden-text.spec.ts`); tsc and eslint clean.
- 2026-09-27 — original blocks (DOCX-028): backend 869 passed, 1 skipped; Vitest 119; Playwright 21 (new
  `e2e/kept-blocks.spec.ts`); tsc and eslint clean; all 13 golden documents copied into sound packages.
- 2026-09-27 — source package + patch writer: backend 838+ / 1 skipped; Vitest 117; Playwright 20; every golden
  export (fresh and into its original) passes the package check.
- 2026-09-27 — Phase 2 gate: backend 817 / 1 skipped, Vitest 117, Playwright 20; browser check of Changes to review
  (accept → gone after reload).
- 2026-09-27 — prompt injection: backend 817 passed / 1 skipped (`tests/test_prompt_injection.py`: 12).
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
  - `models/document.py`: `MarkType.HIDDEN`;
  - `parsers/docx_styles.py`: `TextProps.hidden`;
  - `parsers/docx_inline.py`: `RunFormat.hidden`, the paragraph style's hidden;
  - `parsers/docx.py`: the mark;
  - `fidelity/docx_detect.py`: the default paragraph style; hidden text named as kept hidden;
  - `fidelity/content.py`: `visible_only`, `hidden_words`;
  - `fidelity/exports.py`: `export.pdf.hidden_text`, the PDF check on visible words;
  - `export/docx_export.py`: vanish; `export/pdf_export.py`: hidden runs not printed;
  - `capabilities.py`: docx.hidden_text now supported.
- Frontend:
  - `editor/hiddenText.ts`: the mark, `hiddenWordCount`, `visibleText`;
  - `extensions.ts`, `documentToTiptap.ts`, `tiptapToDocument.ts` (`MARK_ORDER`);
  - `EditorCanvas.tsx` (`show-hidden`), `EditorStatusBar.tsx` (the switch), `DocumentEditorShell.tsx`;
  - `panels/StructurePanel.tsx`, `app/globals.css`.
- Tests:
  - `backend/tests/test_hidden_text.py` (7);
  - `test_golden_documents.py` (02 hidden sentence), `test_docx_detect.py`;
  - `frontend/editor/hiddenText.test.tsx` (6);
  - `frontend/e2e/hidden-text.spec.ts`;
  - E2E helpers now share `API` and `unzipped`.
- Docs: `docs/docx`, `docs/document-model`, `docs/architecture/fidelity.md`, `docs/testing`.

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

- Phase 3, DOCX-013 (P0): character formatting the model doesn't hold yet. Each today becomes plain text, reported
  by the detector.
  - The features: underline styles (double, dotted, wavy...), double strike, caps and small caps, character
    spacing, scale and raised/lowered position, the text's language, right-to-left runs, theme fonts and colours.
  - Plan:
    - extend `Mark`/`textStyle` with validated fields (e.g. `underlineStyle`, `caps`, `smallCaps`, `letterSpacingPt`,
      `lang`);
    - read them in `docx_inline.py` with style resolution, as hidden text is read;
    - carry them through the editor, with Tiptap attributes on textStyle and CSS;
    - write them in the Word export (rPr) and approximate them in PDF (reportlab: caps via text transform,
      spacing), reporting what PDF can't do;
    - move each detector finding to "kept".
  - Tests: import per feature (direct and styled), editor round trip, Word export round trip, PDF note, capability
    rows.

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
