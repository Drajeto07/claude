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
  empty numbered item still takes its number. Every instance (`w:num`) of one definition (`w:abstractNum`) numbers on
  where the last left off unless it restarts the level (`startOverride`), as in Word. An item's pictures (DOCX-027)
  are what it holds after its text (`ListItem.blocks`, image blocks with their properties), in a table cell too, and
  a numbered paragraph holding only a picture is an item. They are drawn under the item's text here and in a PDF; a
  Word export writes an item's leading pictures back into its own paragraph, where Word keeps them.
- **List levels (DOCX-016):** each level of a list, from its top one (`ListNumbering.levels`): format (1, 01, a, A,
  i, I, а, А, bullet, none), label (`lvlText`, its `%n` counted from the list's top), start, indent and hanging,
  legal numbering (`isLgl`), restart (`lvlRestart`) and suffix. A level items are at is defined by its first item's
  numbering ("List Bullet 2" has its own); a list using a numbering style's levels (`numStyleLink` → `styleLink`)
  gets them. Bullets drawn from Symbol or Wingdings become the characters they show. Levels a Word export writes
  anyway (1., a., i. or •, ◦, ▪ at 0.63 cm a level) aren't kept, so a round trip is stable.
  `app/formatting/list_numbering.py` counts as Word does (`format_number`, `level_label`, `Counters`,
  `list_levels`, `item_label`); both exports number lists with it, and the editor with its mirror
  (`editor/listLabels.ts`: each item's `data-label`, drawn in place of the browser's marker, and a list's own
  indents). A PDF hangs each label at its level's indent; a bullet is drawn in a font that has it
  (`fonts.font_for`). Only number styles the app doesn't have (first, one, 一 二) are reported.
- **Tables (DOCX-017):** `parsers/docx_tables.py` reads a table's grid widths, width, alignment and indent, borders
  and cell margins -- its style's (`TableStyles`, through basedOn) under its own -- each row's height and tblHeader,
  each cell's vertical alignment, borders and margins, and the style's name and tblLook. A style's first row, when
  the table shows it, makes that row a header; nothing else makes a header. What a style colours, bolds or italicises
  by position -- banded rows and columns in bands of its size, the first and last row and column, the corner cells --
  becomes the cells' own look as Word draws it (DOCX-017A, `docx_tables.position_look`): its conditional formats in
  Word's order (whole table, bands, first and last column, first and last row, corners), only the parts the table's
  tblLook shows, banded rows leaving out a first and last row it shows; a cell's own shading and a run's own bold,
  italic or colour win. Borders by position aren't resolved and are reported (`docx.table.style_look`). A Word export
  writes it all back (`_add_table`, children in the schema's order) and references the style where the file has it;
  a table made here still gets Table Grid, centred, with a bold header. A PDF draws the grid's widths, every cell
  edge as Word resolves it (own, neighbour's, table's), margins, vertical alignment, exact and least row heights and
  repeated header rows; the editor draws the same (`editor/tableLook.ts`). A cell holding more than one plain
  paragraph keeps what it holds as its blocks (`_cell_parts`, `_cell_body`): paragraphs, lists numbered as Word
  numbers them, pictures (at their size from Word, as wide as the cell at most), and tables inside it, read the
  same way (`_table_content(..., lift=False)`: their text keeps its font, size and colour on its runs). A floating
  table (`tblpPr`) keeps where it floats for a Word export and is shown in line here and in a PDF (reported); a row
  kept whole (`cantSplit`) stays so.
- **Pictures (DOCX-018):** `parsers/docx_pictures.py` (`picture_properties`) reads a picture's type and name, alt
  text (`descr`) and title apart, the size Word draws it at (`wp:extent`), what is cropped away (`a:srcRect`, as
  fractions), how it is turned and flipped (`a:xfrm`), and where a floating one sits (`wp:anchor`: how text wraps
  around it, its position from what, its distance from the text; `ImagePlacement`). A Word export writes them all
  back: WebP goes in as PNG, since Word can't hold it; an SVG picture is read as the PNG copy Word keeps with it, said
  so on import (`docx.image.svg`) and, when its paragraph is written anew without the SVG, in the export's
  rewritten-blocks report (DOCX-018C); a floating one gets its `wp:anchor` again (`_float`). A width
  rule sets the width, the height following the picture's own proportions; while the rule is still the share of
  the text width the importer made of the picture's own width, that width is written exactly
  (`export/images.py::picture_width_cm`). A turned picture takes the room of its turned outline, as Word lays it
  out (`turned_box`): its size stays the picture's, and `wp:effectExtent` adds to or takes from each side. A PDF
  crops, flips and turns it as Word shows it (`_shaped_picture`), at its size; the editor draws it so too
  (`editor/pictureLook.ts`: a crop is the whole picture clipped to the part kept, its edges pulled in; margins give
  a turned one its turned room). A floating picture text wraps around (square, tight, through) floats to its side
  here and in a PDF (DOCX-018A): the side is worked out at import (`docx_pictures.float_side`: its alignment, else the
  half of the text column its middle is in) and kept as `ImagePlacement.side`. A PDF wraps the text blocks after it
  around it line by line (reportlab's `ImageAndFlowables`, up to 12 blocks, until a table, picture or break); the
  editor -- a flex column, where CSS floats don't apply -- moves those blocks over by its width and Word's distance
  and pulls the first up beside it (`editor/floatWrap.ts`), so they wrap block by block. Behind or in front of the
  text, top-and-bottom and centred ones are shown in line (reported, `docx.image.floating`); a wrapped one is reported
  as `docx.image.floating_wrapped`.
- **Text boxes (DOCX-019A):** a Word text box (`wps:txbx`, or an older VML `v:textbox`) is a `text_box` element after
  the paragraph it is anchored in, holding its paragraphs, lists, pictures and tables as a table cell does (their runs
  keep their own look), with `TextBoxContent`: size, outline (`a:ln`, or none), fill (`a:solidFill`), insets
  (`bodyPr`), name and, floating, its placement and side (`docx_pictures.text_box_properties`). The editor shows it as a
  box (`editor/textBox.ts`) whose text is edited in place; a PDF draws it as a box (`_build_text_box`); one text wraps
  around floats at its side with the text beside it (floatWrap.ts / ImageAndFlowables). A Word export copies it while
  its paragraph is unchanged, and otherwise writes a Word text box anew (`_add_text_box`: its blocks written as a
  cell's, moved into `w:txbxContent`, floated by `_float`). Not read: theme colours a shape takes from its style.
- **Blocks nested in a PDF:** a block in a table cell, a list item or a quote has no style of its own (only
  top-level elements do); a PDF draws its text in the look of what holds it -- font, size, line height, colour,
  alignment -- as the editor does by CSS inheritance (`pdf_export.py::_inside`).
- **Links:** addresses and ScreenTips (`Mark.title`, from `w:hyperlink/@w:tooltip` or a HYPERLINK field's `\o`).
  Only safe addresses become links; the others are reported. Web and e-mail addresses written as plain text stay
  text, as the file has them (DOCX-026): Word links them only while one types. An upload can ask for them to become
  links (`autolink`, the wizard's checkbox for a Word file; `parsers/docx.py::_AUTOLINK`), and the import report then
  says so (`docx.autolink`).
- **Document properties:** the file's core properties (`DocumentMetadata.sourceProperties`). Its own title is kept
  apart (`title`, "" when it has none) from the one the document is shown under (the file's, else its first
  heading's or its name, `importedTitle`): while the document keeps that one, a Word export writes the file's own
  title back -- none is made up for a file without one -- and once renamed, the new name (TEST-022).
- **Section breaks (DOCX-015):** each section's end is a section break element. It records how the next section
  starts (a section's `w:type` says how that section starts, ECMA-376 §17.6.22, so it's the next section's), and the
  page setup of the section it ends. The editor shows it with that setup, and its pages break where Word's do: not
  after a continuous break, and on an even or odd page where it says so -- by the number that page shows, as
  Word does. Each section's pages there have its size, orientation, margins and header and footer distances
  (`editor/sectionPages.ts`, the PDF's rules); its blocks are moved to its page's text column by margin decorations
  over their own margins. Its columns aren't shown. A Word export writes each back as its `sectPr`, in the schema's
  order, with the last section's `w:type` from the last break.
- **Headers and footers by section (DOCX-015):** each section's own main, first-page and even-page headers and
  footers (`section_texts`: its `headerReference`/`footerReference` by type, and `titlePg`), with text boxes read
  once (`part_paragraphs`). One it has no reference for is linked to the previous section's. The last section's are
  `DocumentSettings` and `Document.lastSection`; `w:evenAndOddHeaders` is `Document.evenAndOddHeaders`. Each page in
  the editor, a PDF (`_HeaderTexts`) and Word shows its own section's. A Word export writes them per section: a
  reference and part for each it has, none for a linked one; `titlePg`; and its numbering (`pgNumType`), the last
  section's too.
- **Sections in a PDF (DOCX-015):**
  - Each section gets its own page template: size, orientation, margins, and columns as frames side by side. Its
    pictures are sized to its column and page.
  - A section to an even or odd page starts on one, with a blank page before it when needed, as in Word.
  - Its pages are numbered its way: a restart, roman numerals, letters as Word counts them (a..z, aa, bb..;
    `format_number`), the last section's too (`_Numbering`, `_SectionStart`).
  - A continuous break to a different page setup takes effect on the next page. So do its header, footer and
    numbering: the page it starts on stays the section before's, as in Word.
- **Structure-level preservation:** equations, fields, bookmarks and comments (`preservedAttributes`), kept for export.
  A field running across paragraphs -- a table of contents, a bibliography (DOCX-020) -- is kept as where it starts
  on the block it begins in (`field_open`, with its code) and where it ends on the block it ends in (`field_close`),
  the two named by one region. Word ends one in a paragraph of its own, which the import leaves out: the end goes on
  the block before, marked to be written in a paragraph of its own again. A Word export writes the field back around
  its entries -- only a region whose start comes before its end, each once (`_balanced_regions`; else it is written
  as its text and the export says so, `export.docx.field_region`) -- and into the original it keeps the region's
  blocks one group, so an unchanged table of contents is copied whole. Word updates it as its own.
  Only fields that show what the document holds or works out are fields at all (SEC-015,
  `docs/security/README.md`). DDE, INCLUDETEXT, INCLUDEPICTURE and the like keep their last result as text in the
  document, in the kept original and in every export. The browser can't add a fragment: a save keeps the server's.
- **Numbered headings (DOCX-016A).** Word's numbers for headings stay numbering.
  - When one list numbers the headings, each at its own level (Heading 2 at the second), the import keeps the
    headings' own text and the numbering (`Document.headingNumbering`, with the original's `sourceNumId`).
  - A heading Word doesn't number, such as a Title, is `numbered: false`.
  - The editor (`editor/headingNumbers.ts`), the PDF and a Word export count the headings in order
    (`list_numbering.heading_labels`), so the numbers follow when headings move.
  - Into the original, a heading written anew is numbered with the original's numbering, so it counts on with the
    copied ones. In a new file the numbering is made from the document's levels, and the Heading styles number
    with it.
  - Headings numbered by more than one list, or not each at its own level, keep their numbers typed into their text,
    as before. Written anew into the original, such a heading is never numbered a second time by its style
    (`numId 0`).
  - Measured in Word on a03. Before: a new file had the numbers typed into the text, and a heading edited here showed
    "2.1 2.1 Scope and aims". Now: 1, 2, 2.1, 3 as numbering in all four exports, the edited one "2.1 Scope and aims".
- **Footnotes and endnotes (DOCX-024).** Notes stay notes.
  - The editor shows them at the end of the document, each reference as its label (1, 2, 3; i, ii).
  - The import keeps each reference as a `note` fragment around its label, and each note block as the note it is
    (`preservedAttributes["note"]`: `footnote:1` and its label).
  - A Word export writes real references where the labels are, and writes the notes into their parts again:
    - with their ids, so a block nobody changed is copied with its reference;
    - without the label the import put before them, and split into paragraphs where the import joined them;
    - in Word's own note styles ("footnote text", "footnote reference"), the file's or made as Word makes them;
    - into a notes part made with its two separators, for a file that has none.
  - A note changed here is written as it is now.
  - A note deleted here leaves its reference's label as text. A block that referred to it is written anew, never
    copied with a reference to nothing.
  - A note referred to from a list or a table (kept there only as its label), and a note whose reference was
    deleted, are written at the end of the document, and the export says so (`export.docx.notes_at_end`). A PDF
    prints them at the end, and says so (`export.pdf.notes`).
  - Measured in Word on a10. Before: its 3 footnotes and 2 endnotes came back as 0 and 0, as paragraphs at the
    end. Now: all of them, each after its sentence, into the original and in a new file; r01's footnote too.
  - Found on the way: a Word export asked for the style "Footnote Text", found none of that name beside Word's own
    "footnote text", and added a second FootnoteText. Styles are now found in any case (`_named_style`), and the
    package check names a style id defined twice, and a note reference to a note that isn't there.
- **Content controls (DOCX-023, brief §31).** Every kind goes back into Word with its properties (title, tag, list
  entries, date format, lock, placeholder), also where the text around or in it was changed here:
  - Kinds: plain and rich text, checkbox, drop-down, combo box, date, picture, repeating section.
  - In a paragraph, a control is kept around its text: a fragment of kind `control` with its `sdtPr` (and `sdtEndPr`),
    and the text just before and after it. Once its text is changed (filled in, chosen again), it goes between
    those.
  - A checkbox's state follows the symbol it shows.
  - One around blocks (a repeating section and its item, a rich text control around paragraphs) is kept as where it
    starts and ends: `preservedAttributes["controls"]` on its first and last block. A Word export puts it back
    around the blocks written for them (`_Controls`), one inside another first. One that lost its first or last
    block here is written without it, and the export says so (`export.docx.control_region`).
  - A picture control goes with its picture (`preservedAttributes["control"]`).
  - A legacy form field (a text field, a checkbox) keeps its settings (`ffData`) with its code.
  - Each control's id stays its own (`_unique_control_ids`), such as for a paragraph pasted twice.
  - Over the same text a control or a link holds what else is kept there, and what opened last closes first. A
    citation control around its field holds all of it. The Phase 3 gate found a06's field crossing its control,
    a file Word calls corrupted. The package check now names a field that starts outside a control or link and
    ends inside it.
  - What comes back from the browser is checked before it is written: one `sdtPr` or `sdtEndPr`, no relationships.
  - In a table, a list or a text box they're kept only as their text, and copied while unchanged
    (`docx.content_control.nested`). The export reports them lost from such a block written anew.
  - Measured in Word on a08 written anew. Before: none of its 8 controls, and its 2 form fields unreadable as form
    fields. Now: all of them as in the file, and changed ones as changed here.
- **Tracked changes (DOCX-022).** The import reads them as accepted: insertions kept, deletions removed, a row
  deleted while tracking gone (it used to come in as an empty row). The file then has `Document.trackedChanges`
  "kept":
  - The editor shows the document as it would be once they are accepted.
  - A Word export into the original copies every unchanged block with its tracked changes: insertions, deletions,
    formatting changes, moves (the moved text's range balanced within the group, like a bookmark), and table and
    section changes. Word shows them again (a07: 7 revisions, as in the file; 0 before).
  - A block changed or restyled here is written anew with its own accepted, and the export report names
    "tracked changes" among what it lost. Rejecting them all in Word leaves that block as it is here.
  - A move whose two ends are in different blocks keeps the end in a block not changed here. Rejecting it in
    Word puts the moved text back there, while the changed block keeps what it has.
  - Measured in Word on a07, accepting all and rejecting all:
    - unchanged export: gives exactly what the file itself gives;
    - its table (the move's other end) edited: accepting all gives what the app shows; rejecting all puts the
      moved paragraph back, and the table stays as edited here.
- Accepting them all is the person's choice. It is offered on the review after the upload and in the Проверка
  panel, and made with `PUT /documents/{id}/tracked-changes` ("kept" or "accepted"; "rejected" below).
  - The content stays as it is either way, since the import read it as accepted.
  - The import report says which choice holds (`TRACKED_KEPT`: kept for export; `TRACKED_ACCEPTED`: lossy, as
    chosen).
  - Accepted, no export has them, and the export report doesn't count them as lost.
- A document whose file isn't kept has its tracked changes as accepted. There is no choice to make for it (409).
- A paragraph whose mark was deleted while tracking runs into the next one, as Word does on accepting (DOCX-022A,
  measured in Word): the next one keeps its own style and alignment; one whose text was deleted too is gone.
  `parsers/docx_revisions.join_deleted_marks` does it in the tree the importer reads; a top-level one stays there,
  empty, so the joined block's `sourceBlocks` name both paragraphs and an unchanged one is copied with both, its
  deleted mark included. The word check's own reading skips a row deleted while tracking, as the import does.
- Rejecting them all (DOCX-022A) is a third choice, "rejected": the document is read again from the kept file with
  every change rejected (`parsers/docx_revisions.reject_all`) -- deletions and moves from back, insertions and
  moves to out, formatting, paragraph, section, table, row and cell property changes back to what they were, an
  inserted row or cell out and a deleted one kept, a paragraph whose mark was inserted run into the next one --
  and that file is kept instead (the earlier one stays stored, so Undo brings the document and its file back).
  - Measured in Word: the result is what Word's Reject All gives, paragraph by paragraph (the synthetic file in
    `tests/test_tracked_changes_reject.py`, and a07, which then opens with 0 revisions).
  - The document's id, title, history and glossary stay; everything read from the file is the new reading's, and
    the notes on what was made safe in the file (SEC-015/016) are kept. The report says `TRACKED_REJECTED` (lossy,
    as chosen); no export has them.
  - Changes made here since the upload (blocks, words, a template, a rule set here) would go: the route answers
    409 `edits_would_be_lost` until the caller sends `discardEdits` -- the app asks the person first.
  - Once rejected there is nothing left to keep or accept (409); Undo is the way back.
- **Comment threads (DOCX-021):** each kept comment carries its id in the file (`commentId`), the comment it
  answers (`replyTo`) and whether it is resolved (`done`). The import reads these from commentsExtended, which
  names each comment by its last paragraph's paraId (`parsers/docx_comments.py`).
  - A Word export writes commentsExtended again for the comments the file now has (`_thread_comments`):
    - a comment copied from the original gets what the original says of it;
    - a comment written anew gets what the import kept, and a paraId of its own;
    - each names the comment it answers by the id that one has now.
  - A thread's comments are written together, the first before its replies. Their end marks and references go
    in that order too (`_after_earlier_ends`). Measured in Word: a reply whose reference comes before its
    comment's is taken for a comment of its own.
  - Nothing is written when no comment answers another or is resolved.
  - commentsIds and commentsExtensible (durable ids, UTC dates) are left out, and Word makes them again. The
    original's people part stays.
  - Word checked, hidden and read-only: a07's exports, copied, rewritten and in a new file, show the reply
    under its comment and the resolved comment resolved.
  - A comment over more than one paragraph keeps its range. It is kept like a field running across paragraphs:
    - the comment, with a region, goes on the block it begins in; `comment_close` goes on the block it ends in;
    - one ending in an empty paragraph (left out) ends where the block before does;
    - a Word export moves the comment's end and reference there (`_OPEN_COMMENTS`), and into the original it keeps
      the region's blocks one group.
    - Before this, every export ended it where its first paragraph does.
    - One running on into a list, a table or code ends where its first paragraph does, and the import report says
      so (`docx.comment_range`).
    - One whose last paragraph is deleted here covers the paragraph it begins in, and the export says so
      (`export.docx.comment_range`).
- **Paragraph formatting (DOCX-014):**
  - Kept as formatting rules, from the paragraph and from its style: the right indent, shading, keep with next, keep
    lines together, widow control, contextual spacing, the paragraph's direction, borders on each side and tab
    stops.
  - Word's other border styles become solid. A border between paragraphs (`w:between`) and bar borders aren't kept.
  - Tab stops aren't shown in the editor (a tab is a gap of fixed width) or in a PDF (four spaces), and the reports
    say so. The Word export writes them back.
  - A Word export writes them back, in `w:pPr`'s schema order (`_put_in_ppr`, `_apply_paragraph_extras`).
  - A PDF follows them: `rightIndent`, `backColor`, `keepWithNext`, `allowWidows`/`allowOrphans`, `KeepTogether`,
    and no space between paragraphs of the same kind. A right-to-left paragraph is right-aligned. Borders become a
    box (all four sides alike) or lines above and below; a border on the left or right alone is named.
  - Word's right-to-left marking on runs (`w:rtl`) is still named (`docx.rtl`); the paragraph's direction isn't.
- **Character formatting (DOCX-013):**
  - These are resolved the way hidden text is (below) and carried on runs:
    - underline styles (double, thick, dotted, dashed, wavy);
    - a double strikethrough;
    - all caps and small caps (all caps wins when both are set, as in Word);
    - character spacing;
    - raised or lowered text;
    - the language text is in (`w:lang`), where it isn't the document's own. A block written anew keeps it, so Word
      doesn't check Bulgarian text as English.
  - Word's other underline styles become the closest one and are reported: heavy lines at normal weight, dash-dot as
    dashed, words-only as a full underline.
  - Bold, italic or underline that a paragraph's style sets but a run turns off is no longer the block's look. The
    runs that keep it carry it instead, so the one that turned it off doesn't show it (`_release`).
- **Hidden text (DOCX-025):** `w:vanish`, resolved as Word does, becomes the `hidden` mark. The sources, in order: the
  run, its character style, its paragraph's style (the default paragraph style when it has none), the document's
  defaults. `webHidden`, which only hides text in Word's web view, is shown. The editor shows hidden text only on request
  (the status bar's "Show hidden text", with Word's dotted line), a Word export writes it hidden again, and a PDF
  leaves it out.

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
- Comments are cleared and the kept ones written again, so there are no duplicates. Their threads are written
  again for them (commentsExtended, DOCX-021), so no reply points at a comment that isn't there.
- A built-in style the file lacks is copied from python-docx's template, without references the file can't
  resolve.

**When the original can't be used.** The checksum is checked first. A file that is missing, altered or unreadable
isn't used; the export is built fresh and the export report says why (`export.docx.source_missing`,
`export.docx.source_unreadable`).

**What the import report says.** Once the original is stored, the report reflects what the Word export keeps. The
watermark, header pictures, custom properties, sensitivity label, the last section's columns and its own section
properties (page borders, line numbering, vertical alignment) become "kept for export". Earlier sections' own
properties are "kept for export while the paragraph that ends each section isn't changed or restyled here" (see
below). Every section's headers and footers are shown and kept (DOCX-015). A PDF export says what is in a Word
export only (`export.pdf.word_only`).

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
  - not how the editor spells it: ids, order, empty values, values a field has by default and run boundaries are
    left out. Defaults count for nothing so that a field the model gains later (with its default) leaves stored
    fingerprints as they were; one stamped before that (to DOCX-018, when defaults counted) is checked as the model
    stood when it was stamped (`_STAMPED_BEFORE`).
- A page break has no look, so restyling leaves it and the section break it may carry as they were.
- Provenance is the server's. `PUT /content` (and `PATCH /content`, which saves what changed the same way) keeps
  what the server has for each element id, whatever the client sends (`keep_provenance`). A new block, or a second one claiming the same id, has none, so no block can claim
  another's original XML.

**The copy plan** (`export/docx_export.py::_copy_plan`).
- Elements and the body children they came from form groups: a list and its items, a paragraph and its text boxes,
  a paragraph and the page break its section break made.
- Children no element came from (empty paragraphs the import dropped, a chart it left out) join the group before
  them.
- A block deleted here stays deleted (DOCX-028B). When the document is stamped as imported, it records how many
  elements each child was read into (`Document.sourceBlockUse`; server-side, since saves only replace elements).
  - A child fewer elements hold now had one deleted. If no element holds it, it is never copied, and never taken
    for one the import left out. If some still do (a paragraph whose picture was deleted), their group is written
    anew.
  - A document stamped before this was kept has its file read again, as its import read it (`_block_use`).
  - Before this, a deleted paragraph came back in a Word export into the original: it was copied with the
    block before it. So did a deleted picture, with its unchanged paragraph.
- A group is copied, its children once, when all of these hold:
  - every element in it is unchanged, and no element that came from its children was deleted;
  - its elements are together and in their original order (a moved group is copied where the document now has it);
  - its children are contiguous, apart from those of blocks deleted here;
  - page breaks are included in the export, if it holds one;
  - its XML is self-contained: no reference to a footnote or endnote deleted here (DOCX-024), no altChunk or
    sub-document, no tracked changes unless the document keeps them (DOCX-022), and every field, bookmark,
    comment range and moved text's range that starts in it ends in it.
- Everything else is written anew, as before.
- Written anew, a block's section break is lost. Its section's pages then follow the section after it, and the
  export report names it (`export.docx.section_lost`).
- Regenerated bookmarks avoid the ids the copied blocks use, and comments no copied or written block refers to
  are dropped.
- A group with a link the app doesn't allow (`safe_href`: web, mail, phone and ftp only) is written anew, so the
  link stays the plain text the importer made it.
- Written anew, a group keeps its drawings (DOCX-019): the charts, SmartArt, shapes, embedded objects and VML
  drawings of an element's original paragraph go back into the paragraph written for it, where they were in its
  text (`_put_back_drawings`, splitting the run they fall in), and a paragraph of nothing but drawings goes back
  after the group (`_copy_plan`'s third answer). They come from the kept original file -- the server's own copy,
  nothing the browser sent -- with their parts: every relationship they name is kept, the one a SmartArt's data
  part names for its drawing too. A text box isn't put back: it is an element of its own (DOCX-019A). Drawings copied or put back keep their ids unless one is taken
  (`_unique_drawing_ids`; the package check names an id used twice).

**What the reports say (FID-007).**
- **Import report.** With the file kept, charts, SmartArt, shapes and embedded objects are named as not shown here
  or in a PDF but kept by a Word export (`KEPT_DRAWINGS`, DOCX-019). What else lives inside blocks is named as kept
  in the Word export while the paragraph that holds it isn't changed or restyled (`KEPT_WHILE_UNCHANGED` in
  `fidelity/imports.py`). That covers:
  - content controls and text boxes;
  - drop caps and empty spacing paragraphs;
  - approximated underline styles, character scale, text effects, right-to-left text.
- **Export report.** An export that writes such a block anew names what it lost (`export.docx.rewritten_blocks`,
  `_lost_in`), with how many blocks. Proofing exclusions (`w:noProof`) are named there too.
- A PDF names them all as kept in a Word export only.

**Earlier sections.** A section break lives in the paragraph that ends its section, so a copied paragraph brings
its section back; one written anew is written from the model's section break, headers and footers included
(DOCX-015), and names what it lost (pictures in its headers, page borders, line numbering, vertical alignment). The
app edits one page setup, the last section's main header and footer in Page settings, and every page's header and
footer on the page itself:
- A page size or margin changed in the app is written into every kept section. Each keeps its orientation unless
  that is what changed; a landscape section's page stays turned.
- A page's header or footer, double-clicked on the page, is edited as its own section's (DOCX-015C,
  `PUT /documents/{id}/section-text`): of the kind that page shows (a section's first page shows its first-page
  one when it has a different first page; even pages their even-page one with different odd and even pages).
  "Same as previous" makes it none of its own again, so the previous section's shows (Word's link to previous).
  A changed section break is written anew in a Word export, headers included; the last section's first-page and
  even-page ones edited here are written into the original's last section (`Document.lastSectionEdited`), the rest
  of it stays the original's.
- A last section on a paper size the app doesn't list (A4, Letter, Legal) keeps it (DOCX-015A): `Document.lastSection`
  holds its width and height, the editor's pages, the PDF and a Word export use them, and the import report says it
  was kept (`docx.page_setup.size`). A page size or orientation chosen here -- in Page settings, by an instruction or a
  template, anything above the source document's own rules -- replaces it (`engine._drop_custom_page_size`).
- The last section's main header or footer, changed in the app, becomes its own: a section that showed the
  previous one's (Word's link to the previous section) gets a part of its own, so the earlier sections keep theirs,
  as the pages here and a PDF show them. Cleared, it is linked to the previous section's again; one of its own left
  empty (`Document.lastSection`) stays its own.
- Fields in a header or footer (DOCX-020A, `formatting/header_fields.py`): `{PAGE}` and `{NUMPAGES}` are the page
  number and count; any other field the field policy allows (STYLEREF, DATE, DOCPROPERTY...) is read as
  `{FIELD <instruction>|<last result>}`. The pages here and a PDF show its result; the header editor shows the
  placeholder, so a header edited here keeps the field while the placeholder stays; a Word export writes it as the
  field with that result (Word updates it). A field whose instruction or result holds `|`, `{` or `}`, one the policy
  refuses (also when typed by hand), and every field in a header longer than the model's 500 characters, is its result
  as text.
- Page numbers:
  - left out of the export: every section's headers and footers that show them are left out whole, first-page and
    even-page ones included. Each stays its section's own, empty, as in a PDF: removing it would show the previous
    section's;
  - asked for here (`showPageNumbers`): they go into every section's main footer that lacks them.

**Checking the result.** Every Word export can be checked by `export/package_check.py` (TEST-023). It reads the zip
on its own. It checks:
- well-formed parts, content types, and relationships that resolve;
- defined styles, lists and comments;
- comment-thread entries that name comments the file has.
The golden documents' exports, fresh and written into their originals, all pass.

## Export

`backend/app/export/docx_export.py` (`build_docx`) writes:
- styles from `resolvedStyles`;
- nested blocks;
- list numbering: each list's own levels (format, label, start, indent, legal numbering, restart, suffix,
  bullet) or the usual ones, built element by element, and a start override;
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
