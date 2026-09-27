# Word (DOCX) import and export

The capability matrix (`backend/app/capabilities.py`, `GET /api/v1/capabilities`) is the feature-by-feature record of
what is supported, kept, reported or left out, with the tests behind each claim. This page covers how the pieces fit.

## Import

`backend/app/parsers/docx.py` (`import_docx`) works with three helpers:
- `docx_inline.py`: runs, links, fields, notes, text boxes and the importer's `Notes`;
- `docx_styles.py`: the style resolver, numbering and page setup;
- `app/fidelity/docx_detect.py`: detections for the import report.

What the importer keeps, as of Phase 1:
- **Lists:** number format, start value and continuation across interrupting paragraphs (`Element.numbering`). An
  empty numbered item still takes its number.
- **Links:** addresses and ScreenTips (`Mark.title`, from `w:hyperlink/@w:tooltip` or a HYPERLINK field's `\o`).
  Only safe addresses become links; the others are reported.
- **Document properties:** the file's core properties (`DocumentMetadata.sourceProperties`).
- **Section breaks:** they break the page where Word does. A section's `w:type` says how that section starts
  (ECMA-376 §17.6.22), so the break after a section ending takes its type from the next section.
- **Structure-level preservation:** equations, fields, bookmarks and comments (`preservedAttributes`), kept for export.

What it reports instead of keeping is in `docs/architecture/fidelity.md`. The report names each item with an
example: hidden text, caps, underline variants, content controls, per-section page setup, and so on.

## Export

`backend/app/export/docx_export.py` (`build_docx`) writes:
- styles from `resolvedStyles`;
- nested blocks;
- list numbering, with a format per level and a start override;
- links with their tooltips;
- the kept fragments;
- the document's own core properties.

What it approximates is reported (`export.docx.*`), and the written file is read back for the content check.

## Tests

- `backend/tests/test_docx_*.py`
- `test_golden_documents.py`: the 12 synthetic golden files, upload → edit → format → export → re-import
- `test_link_titles.py`
- `test_fidelity_report.py`

Word-authored fixtures (the audit set) stay outside the repository until they are scrubbed and committed (TEST-020).
