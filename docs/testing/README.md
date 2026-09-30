# Testing

| Layer | Where | Run |
|---|---|---|
| Backend unit + API | `backend/tests/` (pytest; the API tests use a fresh test database, never the real one) | `cd backend && venv/Scripts/python -m pytest -q -p no:cacheprovider` |
| Frontend unit + editor mapping | `frontend/**/*.test.ts(x)` (Vitest, jsdom, the real Tiptap editor) | `cd frontend && npx vitest run` |
| Types + lint | | `cd frontend && npx tsc --noEmit && npx eslint .` |
| End to end | `frontend/e2e/` (Playwright; starts `scripts.e2e_server` on a fresh SQLite at :8100 and `next build && next start` at :3100) | `cd frontend && npx playwright test` |

`next build` type-checks test files too, so run `npx tsc --noEmit` before the end-to-end suite.

## Golden documents

`backend/tests/fixtures/documents/*.docx` are 17 synthetic Word files built by `scripts/make_golden_documents.py`. A
test checks the committed files still match what the builder makes. `13-kept-blocks.docx` holds what only a copy of
the original XML keeps (DOCX-028): a field's code, a content control, a double underline, a bookmark, a landscape
section.

`frontend/tests/fixtures/golden/*.json` is what the importer makes of each one, for the editor's round-trip tests.
A backend test compares each file with a fresh export, byte for byte (ids and times are made stable). Until
2026-09-30 it compared only the text and the page setup, so Phase 3's new fields and the notes' kept fragments went
unexported. Run `python -m scripts.export_golden_json` after changing the importer or the model.

## Word-authored documents

`backend/tests/fixtures/word/*.docx` are 20 synthetic documents written by Microsoft Word itself
(`scripts/make_word_fixtures.py`, TEST-020), so the importer and the exports meet the OOXML a real user's Word writes,
which python-docx doesn't: fields as Word stores them, comments with their extended parts, content controls,
charts, tracked changes, right-to-left text. The folder's README says what each holds and `manifest.json` records it.
They are built only on Windows with Word, and scrubbed of anything that would identify the machine or its user;
`tests/test_word_fixtures.py` checks the committed files for that, and that each imports and exports to a sound Word
file.

## Expected losses

Next to every golden and Word-authored fixture, `<fixture>.expected-loss.json` (TEST-021) holds what the app says it
changes or leaves out of it: its import report and its Word and PDF exports' reports, as an upload and an export
job make them (the file kept, its blocks fingerprinted, the Word export written into it), reduced to each item's
feature, policy, count and whether it changes content, and each content check's status
(`app/fidelity/loss_manifest.py`). `tests/test_expected_losses.py` compares them with what happens now, in CI too,
so a new loss, or one that went away, fails and says which; rewrite the manifests on purpose with
`python -m scripts.export_expected_losses [fixture ...]` and commit them. A PDF's report depends on the fonts the
machine has, so its claims are kept per platform and compared only where they were recorded (so far Windows; the
Linux claims wait for bundled fonts, TEST-021A).

## True fidelity

`tests/test_true_fidelity.py` (TEST-022) takes every fixture through the app's whole path -- imported as an upload
imports it, formatted with the academic template, saved as the editor saves it, exported to Word into the original
-- and compares the Word file that came out with the one that went in on four axes, each on its own
(`app/fidelity/round_trip.py`): content (the words of the body and of the headers and footers), structure (block
kinds, heading levels, list items and levels, table shapes, pictures, and how many charts, SmartArt, embedded
objects, shapes, text boxes, equations and pictures each file holds -- what the model may not -- and its comments:
how many, how many answer another, how many are resolved; DOCX-021; its content controls, DOCX-023 -- 06-lists' checklist becomes two checkbox controls, as the Word export writes
checklists -- and its tracked changes' marks, DOCX-022 --
a07's are accepted after the academic template, which rewrites every block: pinned until DOCX-029), formatting (each
kind's look and the marks on
the text, against what the formatted document had) and metadata (core and custom properties; `modified` is left
out, a file the app wrote was modified then). What each axis differs in today is pinned in
`<fixture>.expected-fidelity.json` (`python -m scripts.export_expected_fidelity`); a new difference, or one that went
away, fails on its axis. It runs through the functions the services call, without a database;
`tests/test_golden_documents.py` takes a document through the API itself. When it was written it found three real
losses, fixed with it: a Word export gave a file without a title the name it was shown under, and replaced a
file's own title with its first heading; and after a template, lists, tables, captions, quotes and headings 4-6
looked one way here and another in Word (the kinds a template didn't set kept their imported look here while Word,
their styles based on Normal, gave them the new body text's). The differences pinned today:
- a07's tracked changes, accepted by the academic template, which rewrites every block (DOCX-029);
- a09's two text boxes' frames (DOCX-019A);
- 06-lists' checklist, which a Word export writes as checkbox controls.

a03's heading numbers were typed into the text until DOCX-016A; they now come back as numbering.

`python -m scripts.export_golden_json` (in `backend/`) writes what the importer makes of each one to
`frontend/tests/fixtures/golden/*.json`. The output is deterministic (stable ids and times), so a regenerated file
only differs where the importer's result did. `test_the_frontend_golden_json_is_current` fails when it's stale.

The frontend loads these into the real editor (`editor/editorRoundTrip.test.ts`) and checks two things:
- each document comes back unchanged;
- opening it produces nothing of its own to save, and nothing it can't keep.

## Fidelity tests

- `tests/test_fidelity_report.py`: the content check, calibrated on the golden documents plus Word-authored audit
  documents (the Word-authored set is now in the repository, TEST-020).
- `tests/test_docx_detect.py`, `test_docx_numbering.py`, `test_link_titles.py`, `test_markdown_parser.py`: each
  detection and each kept feature.
- `tests/test_capabilities.py`: the capability matrix against the code.
- `tests/test_rule_values.py`, `test_editor_direct_styles.py`: rule values and the editor's own formatting.
- `frontend/editor/nestedBlocks.test.ts`, `directFormatting.test.ts`, `useAutoSave.test.tsx`: the editor's side.
- `frontend/e2e/nested.spec.ts`, `direct-formatting.spec.ts`: paste → save → reload in a real browser.
- `tests/test_original_blocks.py`: unchanged blocks copied into the Word export, changed and restyled ones written
  anew, provenance kept by the server, earlier sections' page setup, headers and page numbers.
- `tests/test_character_formatting.py`, `frontend/editor/characterFormatting.test.ts`: underline and strikethrough
  styles, capitals, spacing and raised text through import (style resolution, a run turning its style's bold off),
  Word paste, the editor, a Word export in the schema's order and a PDF (DOCX-013). Golden `02-rich-text.docx` holds
  each.
- `tests/test_sections.py`, `frontend/editor/sectionBreak.test.ts`: section breaks (DOCX-015) through import, the
  editor (settings kept, label, pagination's breaks), a Word export in `sectPr` order, the PDF, validation, and what a
  section written anew loses.
- `tests/test_paragraph_formatting.py`: DOCX-014's paragraph properties, borders and tab stops through import
  (direct and styled), CSS, a Word export in `w:pPr`'s order, the PDF (styles, contextual spacing, box and lines, what
  it names), the detector, and value validation in rules and templates.
- `tests/test_copy_reports.py`: what a Word export keeps of what the app doesn't hold, and says so (FID-007):
  - the language text is in;
  - scale and effects detected;
  - "kept while unchanged" at import;
  - what a rewritten block lost, at export;
  - unsafe links never copied back;
  - the PDF's Word-only note.
- `tests/test_hidden_text.py`, `frontend/editor/hiddenText.test.tsx`, `frontend/e2e/hidden-text.spec.ts`: Word's
  hidden text through import, the editor (hidden until asked for), both exports and the content checks (DOCX-025).
- `frontend/e2e/kept-blocks.spec.ts`: after an edit in the real editor, the export's untouched paragraphs still have
  their content control, double underline and landscape section. This proves the editor gives unchanged blocks back
  exactly as the server fingerprinted them.

## Word files the app writes

`app/export/package_check.py::package_problems` (TEST-023) checks a Word file's package independently of
python-docx. It finds what makes Word refuse a file or open it "with unreadable content". `tests/test_package_check.py`
runs it on every golden document's export, fresh and written into its original (DOCX-011), and shows it catches each
kind of damage. The docx skill's XSD validator needs `defusedxml`, which isn't installed here; this check covers the
package consistency Word itself enforces.

## Malformed files

`tests/malformed_docx.py` breaks a valid Word file in each way a file can be broken: its zip, each XML part cut short,
missing parts and relationships, a DTD, a wrong content type, nesting past the parser's limit, odd numbers, loops.
`tests/test_malformed_files.py` runs the corpus of two fixtures through the parser, the upload route and the jobs
(SEC-010). Each file is either read with every word, or refused with its exact message, and never a 500.

## Checking by hand in a browser

Use the throwaway stack, which has a fresh SQLite database and no real data:
- `tools/dev/throwaway-backend.ps1` (:8100) and `tools/dev/throwaway-frontend.ps1` (:3100);
- or the `backend-throwaway` / `frontend-throwaway` configurations in `.claude/launch.json`.

Never use the `backend` configuration: it uses the real database. Stop the throwaway stack before running the
end-to-end suite, because it uses the same ports.
