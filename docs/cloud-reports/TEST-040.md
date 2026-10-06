# TEST-040 Playwright workflows from the brief

Branch `cloud/test-040-e2e-workflows`, base `8966ec7`. Brief section 79 lists 24 browser workflows.

## Summary

Each workflow is mapped to the specs that walk it (a table in `docs/testing/README.md`, section "Browser workflows").
Of the 24: three are "not built yet" (19 translation selection, 20 whole-document translation, 22 Review Changes);
two are new (4 structure review, with the outline; 18 PDF import); the other 19 had a spec already, and for nine of them
(3 paste, 6 manual edit, 9 undo, 10 redo, 13 hyperlink, 14 image, 15 tables, 16 lists, 17 caption) a test was added
for the part the old specs did not walk. Row 11 (export DOCX) also gained content checks of the downloaded file.

Nine new tests in `frontend/e2e/workflows.spec.ts`, each with its own user and documents:

1. structure review: the outline shows the headings found, nested, and folds
2. paste: Markdown text becomes lists, a table and a link, which stay after a reload and reach the Word file
3. manual edit: bold, a bullet list and a table added by hand are saved and exported
4. undo and redo of typing: the toolbar buttons and the keys, and the server holds what is left
5. hyperlink: an address typed in the text becomes a link, kept after a reload; an unsafe one stays text
6. image: a pasted picture is stored with the document, still there after a reload, and in the Word file
7. caption: a Word file's caption is edited in the browser and is still a caption in the Word file
8. PDF import: a PDF's text becomes a document that can be edited and exported
9. delete: a deleted document is gone for good, its address no longer opens

## Steps the app does not offer (said in the table, not faked)

- **Hyperlink**: no link dialog or toolbar button. A link comes from typing/pasting an address, Markdown or a Word file; that is what is tested.
- **Image**: no insert-picture step (the "Add element" menu lists Image greyed out, "coming in a future update"). Pictures come from a Word file or a paste; the paste is tested.
- **Caption**: no way to make or insert a caption in the editor; captions come from a Word file. The test edits one and checks the export keeps the Caption style.
- **Translation selection, whole-document translation**: no route or screen (only an enum value in the document model). No test.
- **Review Changes**: the shared layer of brief sections 58/89 does not exist. Only the AI-deletion list ("Changes to review") exists and is covered by `proposals.spec.ts`. The compare page has no browser test (not part of the 24).
- **PDF import**: the E2E AI is a stub, so a PDF goes through the naive segmenter; headings are not asserted. Scanned PDFs (OCR) are not built.
- **.txt upload**: no browser test of its own (the text source is covered by paste).

## Files changed

- `frontend/e2e/workflows.spec.ts` (new).
- `frontend/e2e/helpers.ts`: added `pasteHtml`, `PNG_DATA_URL` (both moved out of `nested.spec.ts`), `downloadExport` (UI download of DOCX/PDF, returns name and bytes, asserts the export's read-back check), `zipNames`, `makePdf` (a one-page text PDF built in memory, no binary committed), `caretAtEndOf`, `toolbarButton`, `toggleToolbar`; `createDocument` now also takes an in-memory file (`{ name, mimeType, buffer }`).
- `frontend/e2e/nested.spec.ts` and `frontend/e2e/documents.spec.ts`: use the shared helpers instead of private copies. Assertions unchanged (the export test still checks name, signature and the read-back status).
- `frontend/e2e/templates.spec.ts`: one wait added to an existing test (see Flakiness).
- `docs/testing/README.md`: the workflow table (row 24 now lists the account sessions list and account deletion that came with ACCT-005..007).
- No app code, no backend code, no `data-testid` or accessible name added. No dependency added.

## Design decisions

- **Synthetic documents only**: Markdown/HTML text, the committed golden Word files the other specs already use (`08-caption.docx`), and a PDF written by `makePdf` in TypeScript, so CI needs no Python step and no binary fixture.
- **No fixed sleeps.** Waits are on interface states ("Saved", aria-pressed, focus, downloads) or `expect.poll` on the server's stored document. The undo/redo test polls `GET /documents/{id}` because the editor also saves on blur: clicking a toolbar button saves at once, so "wait for the next save request" is racy.
- **No Windows assumptions**: no paths with separators typed by hand, no font checks.
- A toolbar button exists twice on the page (the toolbar and the Properties side panel), hence `toolbarButton` takes the first one (the toolbar's, first in the DOM).

## Flakiness found and fixed in the new tests

- Selecting text with Home/Shift+End and pressing End right after the click lost the text once in three runs (the Enter replaced the selection). The test now types a bold line instead of selecting one, and every test places the caret through `caretAtEndOf` (click, editor focused, End).
- Characters typed immediately after a toolbar click ("mi" of "milk" lost once in three runs): the toolbar hands the focus back a moment after the click. `toggleToolbar` waits for the pressed state and for the focus. A person cannot type within that frame, so I did not treat it as an app bug, but it is worth knowing: any future spec that types straight after a toolbar click needs the same wait.

## Results

- Each new test run 3 times (`--repeat-each 3` over the file): after the merge, 27 of 27 passed; `manual edit` (the flaky one before its fix) 6/6 on top.
- Merged with the integration branch (`7ba8c0c`, ACCT-005..007, SEC-020 CSP spec, PLAN-001, PDF-012) with a merge commit and no conflicts; nothing the base added made a workflow row redundant except row 24.
- `npm run lint`: 0 errors (one warning for the untracked, git-excluded `playwright.local.config.ts`). `npx next typegen` + `npx tsc --noEmit`: clean.
- Backend suite: not run (backend untouched). Vitest: not run (no unit-tested code touched).

- Existing test `templates.spec.ts` "create a template of your own": failed 2 of 5 full runs (strict-mode violation: the editor's heading and the library both showed the name before the navigation finished). Fixed by waiting for the `/templates` URL; 6/6 afterwards. Not a weakening.
- Existing test `auth.spec.ts` "a forgotten password": failed in 2 full runs under heavy machine load (other workers), never alone: the e-mail was filled before the page hydrated, so the field was empty on submit. Not changed; follow-up: wait for hydration (e.g. re-fill until the value holds) there.

## Mutation check

These are tests of existing behaviour, not a new guard, so the check is that each test can fail:

- The undo/redo test would pass trivially on its first poll (the Redo click's blur-save already stored "First line."), so that poll was removed; the remaining poll needs a real save of the redone text.
- The hyperlink test asserts that `javascript:alert(1)` stays text (SEC-014) and the image test asserts the pasted picture's src moved to `/api/v1/assets/`: both would fail if the link policy or the picture storage stopped working (they assert states that only exist because of them). I did not break the app to confirm this (no app change is allowed in this task); the first failures of `manual edit` and `undo` during development show the assertions do detect lost text.

## Risks and open questions

- Tests use the real Chromium in CI, here an older one from `/opt/pw-browsers`. CI's e2e job is the final check.
- The suite is now about 36 tests and runs one worker at a time; the new spec adds roughly 1.5 minutes.
- `workflows.spec.ts` "PDF import" depends on the naive segmenter producing paragraphs from the PDF's lines; if structure analysis in E2E ever gets an AI stub, the test still holds (it asserts text only).

## Decisions for the owner

- Whether translation and the Review Changes layer get a Playwright spec when they are built (rows 19, 20, 22 stay "not built yet").
- Whether an insert-link button, an insert-picture step and a "turn into caption" command are wanted: they are workflows 13, 14, 17 of the brief, tested today only through the paths that exist.

## Not done

- Workflows 19, 20 and 22 (nothing to test).
- A browser test for scanned-PDF import (OCR not built) and for the compare page.

## Full suite

Whole suite through the lock, after the merge: **46 passed, 1 skipped** (visual.spec, Windows only), 0 failed (47 tests: the base's 38 plus 9 new). Before the templates fix one earlier post-merge run was 45 passed, 1 failed (that test), 1 skipped.
