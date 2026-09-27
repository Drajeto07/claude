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
sensitivity label, columns and own section properties become "kept for export". Earlier sections' own page setup,
properties, headers and footers are "kept for export while the paragraph that ends each section isn't changed or
restyled here" (see below). A PDF export says those parts are in a Word export only (`export.pdf.word_only`).

## Unchanged blocks keep their original XML (DOCX-028)

A block nobody changed is written into the Word export as it is in the original file, with what the model doesn't
hold: a field's code, a content control, a double underline, hidden text, a bookmark, a section break. A changed
block is written anew from the document.

**Provenance.**
- The importer records the body children each top-level element came from (`Element.sourceBlocks`):
  - a list takes its items' paragraphs;
  - a paragraph takes a drop cap merged into it;
  - a page break a section break or `pageBreakBefore` made takes that paragraph.
- When the file is kept, `DocumentService.create` stamps each element's fingerprint as imported
  (`Element.sourceHash`, `app/export/provenance.py`).
- The fingerprint covers what the element holds and how it looks:
  - its resolved style, its kind's and the body's, and those of the blocks nested in it (a template or an
    instruction that restyles paragraphs restyles each one);
  - not how the editor spells it: ids, order, empty values and run boundaries are left out.
- A page break has no look, so restyling leaves it and the section break it may carry as they were.
- Provenance is the server's. `PUT /content` keeps what the server has for each element id, whatever the client
  sends (`keep_provenance`). A new block, or a second one claiming the same id, has none, so no block can claim
  another's original XML.

**The copy plan** (`export/docx_export.py::_copy_plan`).
- Elements and the body children they came from form groups: a list and its items, a paragraph and its text boxes,
  a paragraph and the page break its section break made.
- Children no element came from (empty paragraphs the import dropped, a chart it left out) join the group before
  them.
- A group is copied, its children once, when all of these hold:
  - every element in it is unchanged;
  - its elements are together and in their original order (a moved group is copied where the document now has it);
  - its children are contiguous;
  - page breaks are included in the export, if it holds one;
  - its XML is self-contained: no tracked changes, no note references (the import moved the notes' text), no
    altChunk or sub-document, and every field, bookmark and comment range that starts in it ends in it.
- Everything else is written anew, as before.
- Written anew, a block's section break is lost. Its section's pages then follow the section after it, and the
  export report names it (`export.docx.section_lost`).
- Regenerated bookmarks avoid the ids the copied blocks use, and comments no copied or written block refers to
  are dropped.

**Earlier sections.** A section break lives in the paragraph that ends its section, so a copied paragraph brings
its section back. The app has one page setup and one main header and footer (the last section's). What is changed
here applies across sections, as the app shows it:
- A page size or margin changed in the app is written into every kept section. Each keeps its orientation unless
  that is what changed; a landscape section's page stays turned.
- A main header or footer changed in the app is rewritten where Word shows it for the last section. That is its
  own, or the earlier one it continues (Word's link to the previous section), so every section showing it shows the
  new text. A section with a header of its own (a cover page, a different chapter heading) keeps it.
- Page numbers:
  - left out of the export: every section's headers and footers that show them are left out, first-page and
    even-page ones included;
  - asked for here (`showPageNumbers`): they go into every section's main footer that lacks them.

Sections themselves aren't part of the document model yet (DOCX-015). Until then, a section survives only while
its ending paragraph does.

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
- `test_golden_documents.py`: the 13 synthetic golden files, upload → edit → format → export → re-import
  (`13-kept-blocks.docx`: a field, a content control, a double underline, a bookmark, a landscape section)
- `test_original_blocks.py`: the copy plan, provenance, and earlier sections' page setup, headers and page numbers
- `test_source_package.py`, `test_package_check.py`: the original file and every export's package
- `frontend/e2e/kept-blocks.spec.ts`: a Word file edited in the real editor still has its content control, double
  underline and landscape section in the untouched paragraphs of its export
- `test_link_titles.py`
- `test_fidelity_report.py`

Word-authored fixtures (the audit set) stay outside the repository until they are scrubbed and committed (TEST-020).
