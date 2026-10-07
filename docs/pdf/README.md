# PDF

PDF in (an imported PDF made an editable document) and PDF out (the export). The details of the import live in
[`docs/architecture/fidelity.md`](../architecture/fidelity.md); this page is the map.

## PDF in

1. **The text read** (`parsers/pdf.py`, pypdf): what text the file has, page by page, within the limits
   (`MAX_PDF_PAGES`, 1,000 pages, and the upload limits in `security/files.py`). A PDF with no text at all and no OCR engine is refused, said so.
2. **The inspection** (PDF-010..012): every character with its font, size, colour, box and render mode, the
   drawings, pictures, links, form fields, outline and metadata (`parsers/pdf_geometry.py`); each page called
   `text`, `scanned`, `hybrid` or `empty` (`parsers/pdf_classify.py`); the result kept as `Document.pdfInspection`.
   It never refuses an import: what it can't read is marked incomplete.
   [fidelity.md, "The PDF inspection"](../architecture/fidelity.md#the-pdf-inspection)
3. **The reconstruction** (P2E-002..004, deterministic, no AI, `parsers/pdf_structure.py`): reading order by an XY
   cut (columns), running headers, footers and page numbers moved to the document's, paragraphs, headings by size,
   lists by markers that count on, captions, tables from ruling lines (merged cells, shading, header rows), pictures
   in place. Used only when the layout read had every page and at least 95% of the text read's words; otherwise
   the text read's document, with `pdf.structure_not_rebuilt` saying why.
   [fidelity.md, "The PDF -> editable reconstruction"](../architecture/fidelity.md#the-pdf---editable-reconstruction)
4. **Editable or layout-focused** (P2E-007, `pdf_mode`): `editable` (the default) is the reconstruction; `layout`
   keeps a page break per PDF page and every run's font and size. Nothing is placed at its exact position: frames
   and anchors are the layout-preserving architecture's (P2E-020, not built).
5. **Confidence and the report** (P2E-005): `Document.pdfConversion` -- how sure the conversion is in all and per
   aspect (text, paragraphs, headings, lists, captions, tables, pictures, reading order), and which blocks are guesses. The Проверка panel shows
   "Imported from PDF", the mode and the confidence; the Structure panel marks the guesses. Every word is checked
   against the text read (`Document.importReport`).
6. **OCR** (P2E-006): `app/ocr` is the interface an engine sits behind; only `OCR_PROVIDER=none` exists -- which
   engine to run is the owner's decision. Scanned pages come in as their pictures meanwhile.

## PDF out

- **One render specification** (`formatting/render_spec.py`) for the editor, the Word export and the PDF: page sizes,
  margins and the resolved styles mean the same in all three.
- **The writer** (`export/pdf_export.py`, reportlab): a style per block from its resolved CSS, runs as markup (fonts,
  sizes, colours, highlights, raised and lowered text, links), lists, checkboxes, tables with merged cells and
  shading, pictures from asset storage (only the user's), headers and footers with page numbers.
- **Fonts and scripts** (FONT-001..004, [`docs/fonts/README.md`](../fonts/README.md)): TrueType fonts installed on the
  server are embedded (the document's own, else one of the same kind). The deterministic FontResolver splits text
  into runs by script and gives each a font that draws it (fallback chains per script, a symbol font for symbols);
  Arabic, Hebrew, Devanagari and Thai are shaped (HarfBuzz) and right-to-left text is laid out by the Unicode bidi
  algorithm (`app/bidi.py`, `export/rtl.py`). A character no installed font draws is named in the export's report
  (`export.pdf.script`). Production images need the Noto fonts for the scripts they must draw.
- **Checked after writing** (`fidelity/exports.py`): the PDF's text is read back and compared with the document's
  words; what the export approximates or leaves out is in its report. Devanagari and Thai text can't be compared
  that way (the read-back can't order shaped clusters): said so (`export.pdf.text_layer`).
- **Speed**: exports are background jobs (`POST /api/v1/jobs/export`); the performance gate (TEST-041,
  [`docs/performance/README.md`](../performance/README.md)) holds the PDF export to the base branch's time.

## Tests

`tests/test_pdf_parser.py`, `test_pdf_geometry.py`, `test_pdf_inspection.py`, `test_pdf_structure.py`,
`test_pdf_tables.py`, `test_pdf_pictures.py`, `test_pdf_conversion.py`, `test_pdf_import_modes.py`,
`test_malformed_pdfs.py`, `test_pdf_fixtures.py` (the import); `test_pdf_export.py`, `test_export_fidelity.py`, `test_multilingual.py` (the
export); e2e `workflows.spec.ts` (PDF import, editable and layout-focused). See [`docs/testing`](../testing/README.md).

## Not supported (yet)

Exact positioning (frames, text boxes at their place), OCR without an engine configured, PDF forms as editable
fields, and writing a tagged (accessible) PDF.
