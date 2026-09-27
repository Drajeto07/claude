# The document model

One JSON document per SmartDoc document: `backend/app/models/document.py`. The frontend gets its types from the backend's
OpenAPI schema (`python -m scripts.export_openapi` in `backend/`, then `npm run generate-types` in `frontend/`; a
contract test fails when the committed schema is stale). `schemaVersion` is 1.

## Elements

`Document.elements` is a flat, ordered list of top-level blocks (`Element`). `type` is one of heading, paragraph, list,
table, image, quote, caption, footnote, code_block, page_break, horizontal_rule, other.

- `content` is the block's plain text; `inline` its formatted text (runs, below). An element's look is not stored on it:
  `styleRef` names its entry in `resolvedStyles`, computed by the formatting engine from `formattingRules`
  (`docs/formatting/`).
- **Nested blocks** (tracker CORE-001): a table cell's `blocks`, a list item's `blocks` and a quote's `children` hold
  whole elements when the container holds more than one paragraph. When set they are the content, and the
  container's `inline` is only its plain text. Depth is capped at `MAX_BLOCK_DEPTH` = 8 (422 beyond). Read nested
  content only through `walk_elements`, `child_blocks` and `inline_runs`.
- **Lists**: `listItems` hold one entry per item, with `level` for depth, `checked` for checklists and `blocks` for
  whatever else the item holds. `ordered` marks a numbered list, and `numbering` (`ListNumbering`: `start` 0..999999
  and `format`) is set only when the list doesn't count 1, 2, 3.
- **Tables**: `rows` → `cells` with `colspan`, `rowspan`, `header`, `background`. `alignments` holds one alignment per
  grid column, kept when every cell starting in that column agrees. Per-cell alignment and column widths aren't in
  the model yet (DOCX-017); the editor names them as not kept.
- **Images**: `assetId` for a stored picture (asset storage), else `src`. `alt` and `title` are kept too. A
  picture's size is a formatting rule (`imageWidth`, a share of the text width).
- `preservedAttributes` is the preservation layer: Word content the editor can't show (equations, fields, bookmarks,
  comments). It is kept through every save and written back by the Word export. It travels through the browser, so
  the exporter trusts none of it (`_valid_fragment`).
- `sourceBlocks` and `sourceHash` are a top-level element's provenance in its Word file: the indices of the body
  children it was read from, and its fingerprint as imported (only when the file is kept). While the fingerprint
  still matches, a Word export copies those children as they are (DOCX-028, `docs/docx/README.md`). The server
  owns both: a save keeps its own values for each element id.

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
