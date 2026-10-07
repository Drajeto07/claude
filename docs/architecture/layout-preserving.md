# Layout-preserving documents (P2E-020)

How blocks that sit at a place on the page -- rather than in the flow of the text -- are modelled
now, the hook every renderer can ask about them, and how the editor and the exports are to draw
them. Brief §42: add layout primitives only where an import needs them; the semantic document
stays the model.

## What the model holds today

| Source | Field | What it says |
|---|---|---|
| Word, a floating picture | `ImageContent.placement` (`ImagePlacement`, DOCX-018) | Word's anchor: measured from (page, margin, column, character / page, margin, paragraph, line...), the offset (cm) or a named place, the wrap, the distances; `side` -- the side the editor and a PDF float it to |
| Word, a text box | `TextBoxContent.placement` (DOCX-019A) | the same anchor |
| PDF, any block | `Element.layout` (`ElementLayout`, P2E-001) | where the block was on its page: page, box (points, from the top left), rotation, column, lines -- provenance, kept by the server through every save |
| PDF, the pages | `Document.pdfInspection` (PDF-012) | each page's size, boxes and rotation |
| PDF, the choice | `PdfConversion.mode` (P2E-007) | "editable" (the text flows) or "layout" (each PDF page a page, the text in its own fonts and sizes) |

What is drawn today: a Word export writes the anchors back as they were (`wp:anchor`). The editor and
a PDF float a picture or text box to its side with the text beside it (`editor/floatWrap.ts`,
`pdf_export._wrapped`), or draw it in line. A layout-focused PDF import keeps its pages (a page break
where each began) and the look of its text, but its blocks flow down each page in reading order.

## The hook: frames (`app/formatting/frames.py`)

`frame_of(document, element)` answers, for any block, where it is meant to sit when it isn't in the
flow, from what the model already holds. Nothing new is stored:

- a floating picture or text box from Word: its anchor, as a `Frame` of source `docx-anchor`. It has
  a horizontal and a vertical `FramePosition` (what it is measured from, the offset in points or the
  named place), its size, rotation, wrap, and distances in points;
- a block of a PDF imported layout-focused: its box on its page, as a `Frame` of source `pdf-layout`,
  on that page and measured from its top left corner, with no wrap;
- anything else is `None`. That covers a block in the flow and a PDF imported as an editable
  document, whose boxes say only where the text came from.

`frames(document)` gives every top-level block's frame by id. Units are points throughout, as a PDF's
are; Word's centimetres are converted at the edge. A renderer that honours frames asks this instead
of reading each source's fields, so a new source (OCR boxes, a shape) adds a branch here, not a case
in every renderer.

## Target: drawing frames

1. **PDF export** (first: the most exact and the easiest to check). After the flow is laid out
   (reportlab platypus), each framed block is drawn on its page:
   - `pdf-layout` frames on the page they name, at their box;
   - `docx-anchor` frames on the page their anchor paragraph lands on, measured from that page, its
     margins or the column, or from the paragraph as their positions say.
   Text that wraps (square, tight, through) is laid out around the frame's box: a platypus frame
   split around it, as `_wrapped` does today for side floats. topAndBottom keeps the band clear;
   behind and inFront are drawn on the canvas under or over the text.
2. **The editor's pages.** A positioned layer per page, absolute within the page's overlay. The
   paginator (`editor/pagination.ts`) treats a wrapping frame as a band the flow avoids, as
   `floatWrap.ts` now does for side floats; a `pdf-layout` page draws its blocks at their boxes. A
   layout-focused document is then a set of pages of positioned blocks, editable in place.
3. **Moving a frame** edits its source:
   - for a Word anchor, the placement's offsets (cm), so a Word export writes the new position;
   - for a PDF block, a stored position of its own. `ElementLayout` stays provenance (where it came
     from); the position it is drawn at would be a new field, kept by the server as the other
     layout data is, and set only by an explicit move.
   Until then frames stay derived, and no client can set one.
4. **Anchoring rules** (Word's, which a PDF's page frames fit):
   - a frame anchored to a paragraph or line moves with it and goes onto the page it reflows onto;
   - one anchored to a page or its margins stays on that page number;
   - a `pdf-layout` frame stays on its page.
   Deleting the anchor paragraph deletes its frames, as Word does.
5. **Tests.**
   - The Word gate already opens every export: a frame written back is checked in Word (shape counts,
     positions read through the object model).
   - PDF frames: render the export's pages to images and compare each framed block's box with its
     frame (pdfplumber boxes of the drawn text), within a point.
   - The editor: e2e boxes of positioned blocks against their frames.

## Not now

- Shapes, SmartArt, charts and WordArt: the model has none (kept only in Word exports).
- Text running from one text box into another (linked text boxes).
- Frames in headers and footers.
- Rotated text other than 90/180/270 for PDF blocks.

The tracker follows the drawing work as P2E-021 (PDF export honours frames), then the editor and
moving frames.
