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

## The original file (DOCX-010/011)

An uploaded Word file is kept as it was: an asset of its workspace, referenced by `Document.sourcePackage` (asset id,
SHA-256, size). It counts toward the plan's storage, and the unused-asset sweep removes it a day after the document
is deleted.

**Writing the export into it.** A Word export of an imported document is written into that file
(`export/docx_export.py::_emptied`):
- its body is replaced by the document's content;
- everything else is the original file's: styles, numbering definitions, the last section's properties (page
  setup, columns, page numbering, borders), headers and footers of every kind with their pictures, fields and
  watermarks, footnotes, custom properties and sensitivity labels, theme, settings, fonts, custom XML.

**Rewritten only where the document changed them:**
- Word styles are rewritten only for the kinds of block whose look a template, an instruction or a person set.
- The main header or footer is rewritten only when its text in the app differs from the file's.
- Page lengths within 0.02 cm of the file's own are left as they are.

**Housekeeping on write:**
- The old body's pictures, links, objects and charts are left out (`_drop_unused_relationships`).
- Comments are cleared and the kept ones written again, so there are no duplicates or orphaned replies.
- A built-in style the file lacks is copied from python-docx's template, without references the file can't
  resolve.

**When the original can't be used.** The checksum is checked first. A file that is missing, altered or unreadable
isn't used; the export is built fresh and the export report says why (`export.docx.source_missing`,
`export.docx.source_unreadable`).

**What the import report says.** Once the original is stored, the report reflects what the Word export keeps. The
last section's first-page and even-page headers and footers, watermark, header pictures, custom properties,
sensitivity label, columns and own section properties become "kept for export". Headers and footers, and
properties, of earlier sections are still named as left out. A PDF export says those parts are in a Word export
only (`export.pdf.word_only`).

**Still regenerated.** Paragraph-level formatting outside the model, content controls, fields other than the kept
ones, and section breaks inside the body are regenerated from the document. Keeping unchanged blocks' original XML
is the next step (DOCX-028).

**Checking the result.** Every Word export can be checked by `export/package_check.py` (TEST-023). It reads the zip
on its own: well-formed parts, content types, relationships that resolve, and defined styles, lists and comments.
The golden documents' exports, fresh and written into their originals, all pass.

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
