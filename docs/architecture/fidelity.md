# Fidelity: what an import, an edit or an export changed

Brief §17 and §90. The platform never says "No content changes" unless it proved it, and it names everything it
changed, approximated or left out.

## The Document Fidelity Report

The report model lives in `backend/app/fidelity/report.py`. Each `FidelityItem` has:
- a stable feature key (`docx.hidden_text`, `export.pdf.script`...);
- a **policy class**: `detected_preserved`, `detected_not_editable` (kept for export only), `lossy`, `unsupported`,
  `blocked` or `not_detected`;
- a reason for people;
- a count;
- an example of the text it concerns (`sourceState`);
- `contentChanged` when words, pictures or other content were lost, not only their look.

The report's content fields are:
- `reviewCount`: items a person should look at, i.e. lossy, unsupported or blocked ones;
- `contentLossCount`;
- `contentStatus`: `verified`, `changed` or `unverified`.

## The content check

`compare_words` (`fidelity/content.py`) compares the source's words with the result's, in order. It reports
`verified` only when the two are identical. An export to PDF may add words (page numbers, headers), so it passes
when the source's words appear in order.

The source is read independently of the importer:
- **Word files:** `fidelity/docx_source.py` mirrors only the importer's deliberate choices: accepted revisions, field
  results, linear math, drop caps, text boxes after their paragraph, note labels.
- **Pasted or Markdown text:** `fidelity/text_sources.py` counts the words a reader sees. Syntax, link addresses and
  a picture's description are not counted.
- **PDFs:** a document rebuilt from the layout (below) is checked against the words of the lines the layout read
  found, with only the list markers made into list numbering and the running headers and footers moved into the
  document's taken out; those lines' words are checked in turn against the text read's (pypdf), and any word only the
  text read found is named (`pdf.text_reads_differ`). A document made from the text alone is checked against it.

Header and footer words are checked as a multiset. Each import path attaches its report as `Document.importReport`.

## The PDF inspection

A PDF import also reads where everything is on the pages (PDF-010..012), once the text read has accepted the file:
- `parsers/pdf_geometry.py` reads each character with its font, size, colour, box and render mode; the lines,
  rectangles, curves and pictures (with their boxes and pixel sizes); links and annotations; page boxes and rotation;
  the outline, form fields and metadata. pdfminer.six reads what is drawn, pypdf the file's structure. Boxes are in
  points on the page as shown, from its top left.
- `parsers/pdf_classify.py` calls each page `text`, `scanned` (pictures and no text), `hybrid` (text over a picture
  covering at least half the page: a scan under OCR's invisible text layer, confidence 0.95; visible text over such
  a picture, 0.6) or `empty`, with its evidence: text and picture coverage, visible and invisible characters (render
  mode 3 or 7), fonts.
- `fidelity/pdf_inspection.py` sums each page up as it is read and keeps the result as `Document.pdfInspection`
  (`models/pdf_inspection.py`), sent with the document. Metadata is kept by name only, form fields without values,
  links counted by kind. Scanned pages in a PDF that has text elsewhere are reported as `pdf.scanned_pages` (their
  words weren't imported, a content change); hybrid pages as `pdf.hybrid_pages`.

The inspection never refuses an import: a file the geometry read refuses, a limit it meets or a failure is an
inspection marked incomplete (`complete`, `stopped`, `notRead`).

## The PDF -> editable reconstruction

The same read of the pages gives `parsers/pdf_structure.py` its lines (P2E-002, deterministic, no AI):
- `page_lines`, page by page as the read hands it over: characters on one baseline make a row, split into pieces at
  gaps wider than words leave; text not upright is read in its own direction (90: down the page, 270: up it). The
  pieces go into reading order by an XY cut: down a gutter when the text on both sides is column-like (side by side,
  each side wider than 12% of the page -- so a ruled table's cells aren't columns), else across at the widest gap; the
  parts left uncut are lines again, with runs (bold and italic from the font's name, colour, the web link a run is
  under).
- `build_pdf_document`: lines repeated in the top or bottom 12% of at least half the pages (two at least) are running
  headers and footers (the document's `header`/`footer`) or page numbers (`showPageNumbers`), reported as
  `pdf.running_header`, `pdf.running_footer`, `pdf.page_numbers`; a running line that changes from page to page stays
  in the text. Lines make paragraphs, broken at a gap wider than the paragraph's own line gaps, a first-line indent, a
  short line ending a sentence, or a change of size or weight; a paragraph runs on into the next column or page when
  its last line doesn't end a sentence and the next starts in lower case. A short block set 15% larger than the body
  text is a heading, levelled by size (a bold line at body size is the level below, at confidence 0.55). A line
  starting with a bullet or a number is a list item, levelled by its indent (`pdf.list_markers`): numbers must count on
  at each level, or the markers stay as text; a lone letter ("A. Smith") is no list. "Figure 1", "Table 2"... or a short
  line under a picture is a caption. A row split by wide gaps (a table's) stays a paragraph of its own until tables
  are rebuilt (P2E-004). A glyph the file gives no text for is shown as U+FFFD (`pdf.unreadable_characters`), except
  one starting a line, taken for a symbol font's bullet; a control code is left out (`text.control_characters`).
- Each block gets its `layout` (`docs/document-model/README.md`) and a `confidence`: 0.9 when read plainly, 0.75 for
  a smaller heading, a caption named so, a paragraph run on across a page, 0.55 for a guess. The page size (A4,
  Letter, Legal and orientation) and the margins come from the pages.
- `ingestion_service._rebuilt` uses the rebuilt document only when the layout read had every page and found at least
  95% of the text read's words (a few words more are named, never dropped silently); otherwise the document is the
  text read's, as before the reconstruction, with `pdf.structure_not_rebuilt` saying why. The document is
  `uploaded_pdf`, and its first version is "Imported from PDF file ...".

## The PDF conversion's confidence and report

`fidelity/pdf_conversion.py` (P2E-005) keeps how sure a PDF conversion is as `Document.pdfConversion`, as imported:
- `aspects`, each with a confidence, a count and a note: `text` (0.95 read from drawn text and checked; 0.75 when a
  few words were found by one read only; 0.6 for a text layer over a scan or glyphs without text; 0.5 with scanned
  pages or words that don't match), `paragraphs`, `headings`, `lists`, `captions` (their blocks' mean, with how many
  are guesses), `tables` (0.3 while rows come in a paragraph each, P2E-004), `columns` (0.75), `pictures` (0 until
  P2E-003), `readingOrder` (0.9; 0.75 with columns or paragraphs run on across a column or page; 0.55 with turned
  text; 0.5 for the text alone).
- `confidence` in all: the blocks' confidence weighted by their text, no higher than the text's or the reading
  order's, and no higher than 0.6 while the file holds tables or pictures that aren't rebuilt. The import report's
  `pdf.layout` item carries it. `lowConfidenceBlocks` counts the blocks under 0.6, which the Structure panel marks.

What the PDF holds that the document doesn't keep is reported, never dropped silently: notes, highlights and other
marks (`pdf.annotations`, named in words), a form's fields and their values (`pdf.form_fields`; the labels come in
as text), the outline (`pdf.outline`; the headings make the document's), and links into the file or to addresses a
document may not open (`pdf.links`; the text alone keeps no link at all, and says so).

## What the importer changes

Two sources name what the Word importer changes without keeping it (FID-002):
- `fidelity/docx_detect.py` reads the file itself, styles included. It finds hidden text (named as kept hidden since
  DOCX-025, with the same style resolution as the importer), caps, underline variants,
  content controls, custom properties and sensitivity labels (never their values), crop and rotation, table
  geometry, bullets in cells, right-to-left text, autolinks, charts and SmartArt, and what sections change.
- The importer's own `Notes` (`parsers/docx_inline.py`) record what it meets while reading: empty spacing paragraphs,
  links with unsafe addresses, list labels it can't express, shapes, embedded objects, and more.

The Markdown importer reports pictures it doesn't fetch (FID-006).

## Exports

`fidelity/exports.py` collects what an export approximates or leaves out (a `collecting` context around
`build_docx` / `build_pdf`). It then re-reads the written file:
- a Word export must hold exactly the document's words, hidden text included;
- a PDF must hold every word a page shows, in order. Hidden text isn't printed, as in Word, and the report says how many
  words that is (`export.pdf.hidden_text`). Text set in capitals is compared in capitals.

With the original Word file kept, a Word export copies the blocks nobody changed (DOCX-028). The import report then
names what lives in blocks as kept while its paragraph is unchanged. An export that writes such a block anew names
what that block lost (`export.docx.rewritten_blocks`, FID-007). Together they never promise what the export didn't do.

A PDF draws double and thick lines, capitals, small capitals (smaller capitals) and raised or lowered text. It can't
draw character spacing (`export.pdf.character_spacing`), or dotted, dashed and wavy underlines, which are drawn as plain
lines (`export.pdf.underline_style`).

The export job returns this report and the UI shows it under Download.

## The capability matrix

`backend/app/capabilities.py`, served at `GET /api/v1/capabilities`, lists every feature with:
- its import, edit, export and round-trip support;
- the policy class;
- the report keys that name it;
- the tests behind each claim.

`tests/test_capabilities.py` ties it to the code both ways:
- every key the code reports is described;
- every described key is reported somewhere;
- every cited test exists;
- nothing claims a clean round trip without a test.

## In the editor

- **The Проверка panel** (`frontend/editor/panels/FidelityPanel.tsx`) shows the verdict, where the words differ, and
  every item. It also has a **While editing** section: formatting the editor holds that the document can't keep,
  which `reconcileWithIds` names as `notes` on every save.
- **The status bar** shows the import verdict ("No content changes" only when proven and nothing else was lost),
  the review count, and "N formatting changes not kept".
