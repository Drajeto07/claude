# The document model

One JSON document per SmartDoc document: `backend/app/models/document.py`. The frontend gets its types from the backend's
OpenAPI schema (`python -m scripts.export_openapi` in `backend/`, then `npm run generate-types` in `frontend/`; a
contract test fails when the committed schema is stale). `schemaVersion` is 1.

## Elements

`Document.elements` is a flat, ordered list of top-level blocks (`Element`). `type` is one of heading, paragraph, list,
table, image, quote, caption, footnote, code_block, page_break, section_break, horizontal_rule, other.

A **section break** (DOCX-015) ends a Word section. Its `sectionBreak` (`SectionSettings`) holds:
- `start`: how the next section starts (nextPage, continuous, evenPage, oddPage);
- the page setup of the pages above it, each value optional over the document's own: orientation, page width and
  height in mm, margins and header/footer distances in cm, columns and their spacing, and the page numbering's
  start and format;
- that section's own headers and footers: `header`/`footer`, `firstHeader`/`firstFooter` (shown on its first page
  when `differentFirstPage`), `evenHeader`/`evenFooter` (on even-numbered pages when the document has
  `evenAndOddHeaders`). Each is text with `{PAGE}`/`{NUMPAGES}` fields; `""` is one of its own left empty, and
  None is the previous section's (Word's "link to previous"; in the first section, none).

The last section's page setup and main header and footer are `DocumentSettings`; `Document.lastSection` holds the
rest of its settings (first-page and even-page texts, numbering, columns). Its `header`/`footer` there are only ever
`""`: a main one of its own left empty, which a formatting rule can't hold. Only a section break may have
`sectionBreak`.

Each page shows its own section's header, footer and number, and has its section's size, orientation and margins,
in the editor (`editor/sectionHeaders.ts`, `editor/sectionPages.ts`), a PDF and Word alike. A page is in the section it
begins in: a continuous section's own pages start with the page after the one it starts on, and the blank page before
an even or odd start is the section before's.

- `content` is the block's plain text; `inline` its formatted text (runs, below). An element's look is not stored on it:
  `styleRef` names its entry in `resolvedStyles`, computed by the formatting engine from `formattingRules`
  (`docs/formatting/`).
- **Nested blocks** (tracker CORE-001): a table cell's `blocks`, a list item's `blocks` and a quote's `children` hold
  whole elements when the container holds more than one paragraph. When set they are the content, and the
  container's `inline` is only its plain text. Depth is capped at `MAX_BLOCK_DEPTH` = 8 (422 beyond). Read nested
  content only through `walk_elements`, `child_blocks` and `inline_runs`.
- **Lists**: `listItems` hold one entry per item, with `level` for depth, `checked` for checklists and `blocks` for
  whatever else the item holds. `ordered` marks a numbered list, and `numbering` (`ListNumbering`: `start` 0..999999,
  the top level's `format`, and `levels`) is set only when the list doesn't count 1, 2, 3 (or go •, ◦, ▪). `levels`
  (DOCX-016) holds a Word list's own levels from its top one (`ListLevel`: `format`, `text` -- the label, `%n` for
  level n's number, a bullet's character -- `start`, `indentCm`, `hangingCm`, `legal`, `restartAfter`, `suffix`).
  The editor keeps it on the list node (`editor/listNumbering.ts`), gives it back on save, and shows each item's
  label from it (`editor/listLabels.ts`), as Word and both exports number it.
- **Tables**: `rows` → `cells` with `colspan`, `rowspan`, `header`, `background`. `alignments` holds one alignment per
  grid column, kept when every cell starting in that column agrees; where they differ, each cell keeps its own
  (`align`). Geometry and look (DOCX-017): `columnWidthsCm` (the grid), `widthCm`/`widthPercent`, `align`, `indentCm`,
  `borders` (`TableBorders`: top, bottom, left, right, insideH, insideV, each a border value as paragraph borders
  write them, or "none"), `cellMargins`, the Word `style` name and its `look` (`TableLook`); per row `heightCm` with
  `heightRule` (atLeast/exact) and `repeatHeader` (Word's tblHeader); per cell `verticalAlign`, `borders`
  (`CellBorders`) and `margins`. `headerBold` is true for a table made here (its header cells drawn bold) and false
  for one from Word (drawn as its text and style say). A header cell is one the file says is: a row Word repeats,
  or a style's first row the table shows -- never just the first row. `floating` (`TableFloat`) is where a table
  text flows around sits (Word's tblpPr: anchors, position, distance from the text); a row's `cantSplit` keeps it
  whole on one page.
- **Images**: `assetId` for a stored picture (asset storage), else `src`. `alt` and `title` are kept too, and from
  Word (DOCX-018) its `mime` and `name`, `widthCm`/`heightCm` (the size Word draws it at), `crop` (`ImageCrop`: the
  share cut off each side), `rotation` (degrees, clockwise), `flipHorizontal`/`flipVertical`, and for a floating
  one `placement` (`ImagePlacement`: `wrap`, the horizontal and vertical position -- from what, aligned or at a
  distance -- its distance from the text, `allowOverlap`, `layoutInCell`). A width rule (`imageWidth`, a share of
  the text width) still sets a picture's width; its height follows its own proportions.
- `preservedAttributes` is the preservation layer: Word content the editor can't show. It is kept through every save
  and written back by the Word export. It travels through the browser, so the exporter trusts none of it
  (`_valid_fragment`). It holds:
  - `ooxml`: fragments in a block's text, such as equations, fields, bookmarks, comments, content controls and
    note references;
  - `controls`: where a content control around blocks starts and ends (DOCX-023);
  - `control`: the picture content control an image is in;
  - `note`: the footnote or endnote a note block is, such as `footnote:1` with its label (DOCX-024).
- `sourceBlocks` and `sourceHash` are a top-level element's provenance in its Word file: the indices of the body
  children it was read from, and its fingerprint as imported (only when the file is kept). While the fingerprint
  still matches, a Word export copies those children as they are (DOCX-028, `docs/docx/README.md`). The server
  owns both: a save keeps its own values for each element id.
- `Document.sourceBlockUse` records, for each body child of that file, how many elements it was read into at
  import (0 for one the import left out). A child fewer elements hold now had one deleted here, and a Word export
  never copies it back (DOCX-028B). It is set when the document is stamped as imported. Saves never touch it:
  they replace elements only.

## Inline runs and marks

`InlineRun` = `text` + `marks`. A `Mark` has a `type` (bold, italic, underline, strike, code, link, superscript,
subscript, textStyle, hidden) and the fields its type uses:

- `link`: `href`, plus `title`, the tooltip (Word's ScreenTip, at most 500 characters).
- `underline`: `lineStyle` (double, thick, dotted, dashed, wavy; none means a plain line). `strike`: `lineStyle`
  "double" or none (DOCX-013).
- `textStyle`: `fontFamily` (one safe font name), `fontSizePt` (0–400), `color` and `backgroundColor` (#rgb, #rrggbb or
  a basic colour name). Also `caps` and `smallCaps` (true or unset), `letterSpacingPt` and `baselineShiftPt` (points,
  ±100; negative condenses or lowers; zero is unset), and `lang`, the language the text is in (a BCP 47 tag, only
  where it isn't the document's own, DOCX-013). These values end up in style attributes and exported files, so the
  model validates them.
- `hidden` (no fields): Word's hidden text (DOCX-025). The text stays in `content` and in the content checks, but not
  on a page: the editor shows it only on request, a Word export hides it again, and a PDF leaves it out.

A run's marks are always kept in `MarkType` order (`InlineRun._canonical_order`). The editor sorts what it reads the
same way (`MARK_ORDER` in `frontend/editor/tiptapToDocument.ts`, pinned to the OpenAPI enum by a test), so opening
a document never looks like a change (EDIT-007).

## Metadata and reports

- `metadata.sourceProperties`: a Word file's own core properties (author, last modified by, created, modified, subject,
  keywords, description, category). A Word export writes them back instead of python-docx's template values
  (DOCX-012).
- `importReport`: the Document Fidelity Report of the import (`docs/architecture/fidelity.md`).

## Where the editor maps it

- `frontend/editor/documentToTiptap.ts`: Document → editor.
- `frontend/editor/tiptapToDocument.ts`: editor → elements, reconciled by id.

Anything in the editor that the mapping doesn't know stops the save with a message, and the last saved version stays
(EDIT-005). Formatting the editor holds on a top-level block itself is saved as that element's own style: alignment
typed with a shortcut or pasted, and a picture's width (EDIT-008/009). Formatting the model can't hold is named as not
kept (EDIT-012).
