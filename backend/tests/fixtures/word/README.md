# Word-authored fixtures

Twenty synthetic documents written by Microsoft Word itself (tracker TEST-020, audit AUD-20), so the importer and
the exports meet the OOXML a real user's Word writes: revision ids, theme fonts, compatibility settings, fields as
Word stores them, comments with their extended parts. The golden documents in `../documents/` are made with
python-docx and don't have any of that.

| File | What it holds |
| --- | --- |
| a01-formatting | Fonts and sizes; bold, italic, underline (double, wavy, dotted, thick), strikethrough, small and all caps, super- and subscript, hidden text; RGB and theme colours, highlight, shading; spacing, scale, position, kerning; German and Bulgarian language tags; alignment, indents, spacing, line spacing (multiple, exact, at least); keep with next, keep lines together, widow control off, page break before, outline level; tab stops with a leader; a bordered, shaded paragraph; empty spacing paragraphs; plain-text addresses |
| a02-tables | Explicit widths, an exact row height, a repeated header row, custom borders and shading, cell alignment and margins, merged cells; a borderless layout table; a nested table, bullets and a picture in a cell; a table style with its caption; a 45-row table; vertical text |
| a03-lists | A custom bullet; roman and letter numbering; legal multilevel 1 / 1.1 / 1.1.1; five levels; continuing across a paragraph, restarting, starting at 5; mixed numbered and bulleted levels; numbered headings; an empty item |
| a04-images | PNG with alt text and a caption; a cropped JPEG; GIF, BMP, SVG and WebP; floating pictures wrapped every way, one rotated; a 4000 × 3000 JPEG; a picture in the header |
| a05-sections | A different first page; a landscape section with its own margins and header; two columns; an odd-page break with roman numbering; odd and even headers; page borders, line numbers, a background colour; a DRAFT watermark; PAGE, NUMPAGES and SECTIONPAGES |
| a06-fields | A table of contents; DATE, TIME, AUTHOR, TITLE, FILENAME; a bookmark with REF and PAGEREF; SEQ captions; STYLEREF in the header; links, one to a local file; a citation and a bibliography |
| a07-review | Comments with ranges, a reply and a resolved one; tracked insertions, deletions, a formatting change, a move, table rows inserted and deleted |
| a08-content-controls | Plain and rich text, checkbox, drop-down, combo box, date and picture controls; a repeating section; legacy form fields |
| a09-objects | A text box, a shape with text, SmartArt, a chart, an embedded Excel sheet, equations, Wingdings symbols, a drop cap |
| a10-notes | Footnotes (with bold text) and endnotes |
| a11-multilingual | English, Bulgarian, German, Greek, Arabic and Hebrew (right to left), Chinese, Hindi and emoji with their language tags; a right-to-left table |
| a12-properties | Core, extended and custom properties; a custom XML part; a theme; custom paragraph and character styles; compatibility settings |
| a13-pictures | A picture cropped, one turned a quarter and flipped, one floating 2 cm from the margin; pictures in numbered list items, one item only its picture; a picture in a table cell |
| a14-modified-styles | Word's styles changed: a Heading 1 that isn't bold and has no spacing, Normal with none, a quote without an indent, a caption that isn't italic; a table with text right after it |
| a15-links | A web link with a ScreenTip, a mail link, plain-text addresses, a bookmark with a link to it and a PAGEREF |
| r01-university-paper | A title, a table of contents, an abstract, numbered headings typed as text, a footnote, a numbered list, a figure with its caption, a styled table, references, page numbers |
| r02-cv | A borderless layout table with a photo, bullets, a skills grid |
| r03-contract | "Чл. 1." multilevel numbering (1.1, (а), (i)), a bold defined term, a signature table, "Стр. X от Y" |
| r04-medical-synthetic | Bold labels and a lab table with a value marked red (every name and number made up) |
| r05-invoice | A logo in the header, right-aligned amounts, a merged total row, a table style |

`manifest.json` records, per file, each feature Word put in and any it refused.

## Making them

`python -m scripts.make_word_fixtures [builder ...]` on Windows with Microsoft Word (it refuses while Word is open).
Word writes different bytes every time, so rebuild only on purpose and commit the result.

Each file is then scrubbed of what would identify the machine or its user (`scrub` in the script): the Word user's
name and initials, the sensitivity labels Office stamps with the organisation's tenant, comment authors' sign-in
identities, and any company, manager or author Office filled in. The made-up values the fixtures set themselves
stay. `tests/test_word_fixtures.py` checks the committed files for all of it, and the pre-push secret scan looks for
sensitivity labels too.
