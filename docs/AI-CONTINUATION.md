# AI continuation — SmartDoc production hardening

Resume with: **"Прочети docs/AI-CONTINUATION.md и продължи от next task."**

Read in this order: this file → `docs/session-state.json` → `python tools/tracker/tracker.py show --open --phase <current>`
→ the brief section for the current phase in `docs/implementation-brief.md` (§104 lists the phases).
Branch: `feature/smartdoc-production-hardening`. The tracker is `SmartDoc_Master_Implementation_Tracker.xlsx`
(repository root); update it with `tools/tracker/tracker.py` after every atomic task (see `tools/tracker/README.md`).

## CURRENT STATE

- Phase 0: DONE (commit `4da4ecb`).
- Phase 1 (editor integrity + content preservation): COMPLETE (every task DONE/VERIFIED; gate run 2026-09-27).
  - `phase-01a-editor-integrity` (`1fe27a9`, DONE): nested blocks in cells/list items/quotes survive the editor, the
    backend and both exports; list start/format; unknown content stops the save visibly.
  - `phase-01b-fidelity-report`: the Document Fidelity Report (`backend/app/fidelity/`): report model (policy class per
    brief §90), the content check (`compare_words`: "No content changes" only when the source's words and the
    document's are identical), an independent DOCX text reader, every import attaches `Document.importReport`, shown in
    the Проверка panel and the status bar.
  - `phase-01c-export-report`: exports report what they approximate or leave out and re-read the file.
  - `phase-01d-capability-matrix`: `backend/app/capabilities.py` (import/edit/export/round-trip per feature, policy,
    report keys, tests), `GET /api/v1/capabilities`, `tests/test_capabilities.py` ties it to the code both ways.
  - `phase-01e-import-detections` (`622d9c1`, FID-002 DONE): the import report names everything the importer changes
    without keeping it. `app/fidelity/docx_detect.py` reads the file itself (styles included) for hidden text, caps,
    underline variants, content controls, custom properties/sensitivity labels (never their values), crop/rotation,
    table geometry, bullets in cells, RTL, autolinks, charts/SmartArt, and per-section differences (page setup, odd/even
    breaks, page numbering, page borders, line numbers, vertical alignment). The importer itself notes empty spacing
    paragraphs, links with unsafe addresses (kept as text), empty numbered items, numbered headings, custom and
    multi-level list labels, shapes. Kept now instead of lost: list number format/start/continuation (Element.numbering,
    back into Word and PDF) and the file's core properties (`DocumentMetadata.sourceProperties`, back into Word instead
    of python-docx's "python-docx"/2013 stamps; author/subject into PDF). Bug fixed: section breaks broke the page by
    the ending section's type; Word uses the next section's (continuous breaks became page breaks). The golden JSON
    export is deterministic now (stable ids and times).
  - `phase-01f-editor-direct-formatting` (`53c84e4`): alignment typed with a shortcut or pasted, and a pasted picture's
    size, are saved as the element's own style (`reconcileWithIds` → `styles`, `PUT /content` `styles`, validated,
    no revision entry); a block split off one keeps its alignment (as Word); pasting into an empty paragraph keeps the
    pasted paragraphs' attributes (editor fix, `pasteIntoEmptyBlock.ts`); after each save the editor shows each block
    the look it was saved with. What the editor holds that the model can't keep (hsl colours, em sizes, nested
    alignment, differing cells, column widths) is named in the status bar and the Проверка panel ("While editing").
    Security (SEC-022, found on the way): rule values reached CSS as raw text — `center;background-image:url(…)` via
    the element-style/page-setting endpoints or an instruction; now `formatting/values.py` checks every value at every
    entry (422 / dropped) and at resolve (stored bad values skipped). FMT-005 done with it.
  - `phase-01g-phase-1-complete` (this commit):
    - link titles (tooltips) are kept from Word (ScreenTips, also the HYPERLINK field's switch) and Markdown, through the
      editor, and back into Word (`Mark.title`, EDIT-010);
    - a run's marks keep one order, MarkType's, on both sides, so opening a document saves nothing (EDIT-007);
    - Markdown pictures are named as left out with their description, and `---` becomes a rule (FID-006, found on the
      way);
    - EDIT-011 is resolved by naming: keeping per-cell alignment and column widths moves to DOCX-017;
    - TEST-010 verified;
    - the documentation tree is started (`docs/document-model`, `docs/architecture/fidelity.md`, `docs/docx`,
      `docs/formatting`, `docs/security`, `docs/testing`).
- Phase 3 (DOCX/OOXML preservation): COMPLETE (gate 2026-09-30: every P0 and P1 task DONE; its P2/P3 follow-ups
  stay open, after the later phases' P0/P1 work).
  - `phase-03a-source-package` (`de23961`), DOCX-010, DOCX-011, DOCX-012 and TEST-023:
    - an uploaded Word file is kept as it was: `Document.sourcePackage` points at a checksummed asset;
    - a Word export of it is written into that file: only the body is regenerated, and styles, headers and footers
      of every kind, the last section's properties, custom properties, the sensitivity label and the theme are the
      original's;
    - styles and the main header or footer are rewritten only where the document changed them;
    - the import report says what the Word export keeps, and a PDF export says what it doesn't;
    - `app/export/package_check.py` independently validates every Word export's package;
    - kept originals count toward plan storage (a decision for Boril whether they should).
  - `phase-03b-original-blocks` (`c8c2d27`), DOCX-028: unchanged blocks keep their original XML in Word exports.
    - The importer records each top-level element's body children (`Element.sourceBlocks`). An upload whose file is
      kept stamps each element's fingerprint (`Element.sourceHash`, `app/export/provenance.py`). The fingerprint
      covers content and look: own, kind's, body's and nested blocks' resolved styles. A page break has none.
    - The copy plan (`docx_export.py::_copy_plan`) groups elements with their children, and uncovered children join
      the group before them. A group is copied when:
      - every element in it is unchanged;
      - it is together and in its original order;
      - its children are contiguous;
      - its XML is self-contained: no tracked changes, no note references, and balanced fields, bookmarks and
        comment ranges.
      Everything else is written anew.
    - Provenance is the server's: `PUT /content` keeps stored values by id (`keep_provenance`).
    - Earlier sections come back with their ending paragraph. Page setup now runs after the body, so:
      - changed sizes and margins reach every section (orientation kept, landscape pages turned);
      - a changed main header is rewritten where Word shows it (link to previous);
      - page numbers left out, or asked for, apply to every section.
    - Reports:
      - the export names a section lost with a changed paragraph (`export.docx.section_lost`, LOSSY);
      - the import report says earlier sections' setup and headers are kept while their ending paragraph is
        unchanged;
      - a PDF export names them as Word-only.
    - Golden set: `13-kept-blocks.docx` (field, content control, double underline, bookmark, landscape section).
      Every golden document stamped and exported into its original is copied, is a sound package and passes the
      content check. `12-complex` rewrites only the footnote paragraph and the note, by design.
    - E2E `e2e/kept-blocks.spec.ts`: after an edit in the real editor, the untouched paragraphs keep their content
      control, double underline and landscape section. So the editor's round trip matches the fingerprints.
  - `phase-03c-hidden-text` (`7d1af86`), DOCX-025: Word's hidden text stays hidden.
    - `MarkType.HIDDEN` (appended, so no existing mark order changes). The importer resolves `w:vanish` as Word does:
      the run, its character style, its paragraph's style (the default one when none), the defaults. `webHidden`
      stays visible.
    - The detector uses the default paragraph style the same way. It names hidden text as kept hidden
      (DETECTED_PRESERVED, not a content change).
    - The editor has a non-inclusive `hidden` mark (`editor/hiddenText.ts`, also parsed from Word's display:none paste).
      CSS hides it unless the page has `show-hidden`, and the status bar's "Show hidden text (N words)" toggles it and
      re-paginates. The Structure panel leaves hidden text out of headings.
    - Word export: `w:vanish`. PDF: hidden runs aren't printed, `export.pdf.hidden_text` says how many words, and
      the PDF content check compares visible words (`document_words(visible_only=True)`).
    - Golden `02-rich-text.docx` gained a hidden sentence (round trip through the editor in Vitest; E2E
      `e2e/hidden-text.spec.ts`).
  - `phase-03d-character-formatting` (`6619159`), DOCX-013 part 1 (the task stays IN_PROGRESS):
    - Model:
      - `Mark.lineStyle`: underline double, thick, dotted, dashed or wavy; strike double;
      - textStyle `caps`, `smallCaps`, `letterSpacingPt`, `baselineShiftPt`, validated (unset and zero are the same).
    - Importer: each is resolved as Word does, like hidden text. Word's other underline styles map to the closest one
      (`LINE_STYLES`), and only those approximations are reported (`docx.underline_variant`). Caps is no longer
      reported.
    - Fix: bold, italic or underline set by a paragraph's style, but turned off by one of its runs, is no longer the
      block's look. The runs that keep it carry it (`_release`/`_carry`).
    - Editor (`editor/characterFormatting.ts`): global attributes on underline, strike and textStyle, with CSS
      rendering; Word's paste CSS (`text-underline`, `position:relative;top`) is read too. Spacing it can't store
      is named (`NOT_KEPT.spacing`).
    - Word export writes each in the schema's `rPr` order (`_put_in_rpr`, `_RPR_ORDER`). Highlight and shading used
      to be appended out of order; they now go in order too.
    - PDF:
      - draws double and thick lines, capitals, small capitals (smaller capitals) and raised or lowered text;
      - notes spacing (`export.pdf.character_spacing`) and dotted, dashed and wavy lines (`export.pdf.underline_style`);
      - its content check counts capitals as printed.
    - Golden `02-rich-text.docx` gained a paragraph with each.
  - `phase-03e-copy-reports` (`d32c6a6`), DOCX-013 part 2 (DOCX-013 done) and FID-007:
    - Language: textStyle `lang` (BCP 47), where it isn't the document's own. It goes through the importer, the editor
      (a real `lang` attribute; TextStyle also parses `span[lang]`) and the Word export. A block written anew keeps
      it, so Word doesn't check Bulgarian as English.
    - Detector: `docx.character_scale` (`w:w`) and `docx.text_effects` (outline, shadow, emboss, imprint, w14
      effects, animation, borders, emphasis marks, fitText, East Asian layout); `effects_of` and `scale_of`.
    - Import report, with the file kept: `KEPT_WHILE_UNCHANGED` features are named as kept in the Word export while
      the paragraph holding them is unchanged. That covers content controls, text boxes, charts/shapes/SmartArt,
      objects, picture crop/rotation/floating, drop caps, empty paragraphs, approximated underlines, scale, effects
      and RTL.
    - Export report: `export.docx.rewritten_blocks` names what rewritten blocks lost (`_lost_in`) and how many.
      `_copy_plan` returns the rewritten groups.
    - Security: `_safe_links` means a group with a link the app doesn't allow (relationship or HYPERLINK field) is
      never copied back.
    - The PDF's Word-only note covers them all. Golden 02 gained a Bulgarian run.
  - `phase-03f-paragraph-formatting` (`eade93e`), DOCX-014 part 1 (the task stays IN_PROGRESS):
    - New FormattingProperty values: INDENT_RIGHT, SHADING, KEEP_WITH_NEXT, KEEP_LINES_TOGETHER, WIDOW_CONTROL,
      CONTEXTUAL_SPACING and DIRECTION. Each is validated (`values.py`), a StyleSystem TextStyle field, and CSS
      (`margin-right`, `background-color`, `break-after`, `break-inside`, `widows`/`orphans`,
      `--contextual-spacing`, `direction`).
    - Importer: `ParaProps` reads `ind/@right`, `shd/@fill`, `keepNext`, `keepLines`, `widowControl`,
      `contextualSpacing` and `bidi`, from the paragraph and its style (`_style_values`, `_element_rules`).
    - Word export: `_apply_paragraph_extras` for both styles and paragraphs, with `_put_in_ppr` in `w:pPr` order.
    - PDF:
      - `rightIndent`, `backColor`, `keepWithNext`, `allowWidows`/`allowOrphans`;
      - RTL paragraphs right-aligned;
      - `KeepTogether`;
      - contextual spacing closes up paragraphs of the same kind (`_close_up`).
    - A paragraph's direction is no longer reported; Word's `w:rtl` on runs still is.
  - `phase-03g-borders-tab-stops` (`c158722`), DOCX-014 part 2 (DOCX-014 done):
    - BORDER_TOP/BOTTOM/LEFT/RIGHT rules ("solid 0.5pt #000000" or "none"; `values.border_value`) and TAB_STOPS
      ("right 16cm dot; left 2cm"; `values.tab_stops_value`), each with a StyleSystem field and the same validation.
    - The importer reads `pBdr` sides and `tabs` (clears skipped) from the paragraph and its style.
    - CSS: `border-*`, which the editor draws, and `--tab-stops`, which the Word export writes back.
    - Word: `_paragraph_borders`, `_tab_stops`, in `w:pPr` order.
    - PDF: a box (all four sides alike) or lines above and below (`_border_lines`). It names borders on the left or
      right alone (`export.pdf.paragraph_borders`) and tab stops (`export.pdf.tab_stops`).
    - Detector: tabs in the text name `docx.tab_stops` (detected_not_editable).
  - `phase-03h-section-breaks` (`047685d`), DOCX-015 part 1a (the task stays IN_PROGRESS):
    - `ElementType.SECTION_BREAK` with `Element.sectionBreak` (`SectionBreak`). It holds how the next section starts,
      plus the ending section's page setup: orientation, size in mm, margins, header and footer distances, columns
      and spacing, page numbering start and format. Only a section break may have it.
    - Importer: each `sectPr` in the body becomes a section break (`section_break_of`), where a derived page break
      used to be.
    - Editor: `editor/sectionBreak.ts` shows the label ("Section break (odd page)") and a summary of the section
      above. Pagination breaks the page except for continuous starts, with even/odd parity (`breakAfter`).
    - Word export:
      - `_add_section_break` writes each break's `sectPr` from the model; `w:type` goes through python-docx's
        `start_type`;
      - the last section's type comes from the last break;
      - with page breaks left out, breaks become continuous;
      - `_lost_sections` counts only deleted breaks;
      - `_lost_in` names what a rewritten section had (its own headers and footers, page borders, line numbering,
        vertical alignment).
    - PDF: a page break unless continuous; `export.pdf.sections` names a page setup it can't use yet.
    - Reports: page setup, break type and page numbering are now detected_not_editable.
  - `phase-03i-pdf-sections` (`35c6771`), DOCX-015 part 1b: the PDF follows each section.
    - `BaseDocTemplate` with a `PageTemplate` per section (`_SectionPage`: size, orientation, margins, column frames),
      and `NextPageTemplate` at each break.
    - `_SectionStart` records each section's first page and numbering. For even/odd starts it ends a blank page when
      the displayed number has the wrong parity.
    - `_Numbering` gives each page its displayed number and format (roman, letters) for the footer and `{PAGE}`.
    - Headers and footers sit in each section's own margins.
    - `_SECTION_AREA` sizes pictures to the section's column and page.
    - `export.pdf.sections` is gone.
  - `phase-03j-section-headers` (`7bbf7f2`), DOCX-015 part 2: headers and footers
    per section (brief §24: the last section's header is no longer every page's).
    - Model: `SectionBreak` is `SectionSettings` now, with the ending section's `header`/`footer`,
      `firstHeader`/`firstFooter`, `evenHeader`/`evenFooter` (None = linked to the previous section, "" = its own,
      empty) and `differentFirstPage`. `Document.lastSection` holds the last section's settings beyond
      `DocumentSettings`; its `header`/`footer` are only ever "" (an own empty one: a rule can't hold ""). Also
      `Document.evenAndOddHeaders`.
    - Importer: `section_texts` reads each sectPr's references by type and `titlePg`; `_last_section()`.
      `part_paragraphs` reads a text box in a header once (it was read two or three times).
    - Editor: `editor/sectionHeaders.ts` (`pageChrome`, mirrors the PDF's `_HeaderTexts`/`_Numbering`) draws each
      page's header, footer and number from its section. `pagination.ts` reports where each section's pages
      begin (`onSectionStarts`): a continuous section's with the page after the one it starts on, the blank page
      before an even/odd start stays the section before's, and even/odd starts go by the displayed number (restarts
      included; the last section's restart comes from the page container's `data-last-section-start`). Page
      elements carry `data-page` and `data-part="header|footer"`.
    - Word export: `_section_headers` writes each section's own parts, `titlePg`, and `pgNumType` (`_page_numbering`,
      the last section's too). Into the original, `_source_headers_and_footers` compares the model's three states
      (text / own empty / linked) with `section_texts`: a text for a linked last section becomes its own (earlier
      sections keep theirs); cleared, it is linked again. Page numbers left out empty the part instead of dropping
      the reference, as the PDF does.
    - PDF: `_HeaderTexts` gives each page its section's texts, first page and even pages; a continuous section's own
      pages start with the next page; the last section's numbering is `lastSection`'s. One `format_number` (Word's
      letters: a..z, aa, bb..) replaces the PDF's shadowed copy.
    - Reports: `docx.header_footer.variants` is gone (kept); page numbering is kept here too; the remaining
      `docx.header_footer.text` says "Some header or footer text isn't shown here"; `export.pdf.word_only` no longer
      lists headers or page setup.
    - Golden `14-section-headers.docx` (front matter i, ii with a cover, a chapter restarting at 1, a linked last
      section) with `e2e/section-headers.spec.ts`.
  - `phase-03k-last-section-layout` (`30a9bb7`), DOCX-015 part 3a: the last section's own
    columns, column spacing and header/footer distances (`Document.lastSection`) in a PDF (`_SectionPage.of`) and a
    fresh Word export (`_section_layout`); PDF headers and footers at each section's distances. The columns note
    says both exports keep them (detected_not_editable); `docx.layout` left `WORD_ONLY`.
  - `phase-03l-section-pages` (`633c1d6`), DOCX-015 part 3b — DOCX-015 DONE:
    - `editor/sectionPages.ts`: a section's page (its size, or the document's turned to its orientation; margins and
      header/footer distances over the document's), as the PDF's `_SectionPage.of`; `columnShift`, `shiftedMargin`.
    - `pagination.ts` lays out page boxes (`Pages`: a page is the section's of the block that needs it; the blank
      page before an even/odd start is the section before's) and reports them (`onPages`: top, section, box). A
      section whose text column isn't the document's gets node decorations `margin-left/right: calc(own + shift)`
      ("auto" kept; a table's wrapper without its own margin). The container carries the document's page as
      `data-page-width/-height`, `data-margin-*`, `data-header-distance`, `data-footer-distance`.
    - `EditorCanvas` draws each page at its box, centred on a desk as wide as the widest page; headers and footers
      at their distances; `usePageSettings` holds the pages and fits the widest.
    - Follow-ups added: DOCX-015A (a last section's custom paper size: A4 is used, reported), DOCX-015B (columns
      shown in the editor), DOCX-015C (edit other sections' headers and footers).
  - `phase-03m-list-levels` (`3bb348a`), DOCX-016 part 1: each level of a list is kept.
    - Model: `ListLevel` (format incl. `decimalZero`, `russianLower/Upper`, `bullet`, `none`; `text` label with `%n`;
      `start`; `indentCm`/`hangingCm`; `legal`; `restartAfter`; `suffix`) in `ListNumbering.levels`;
      `ListNumbering.format` is `ListFormat` (01 and а б в too).
    - `app/formatting/list_numbering.py`: `format_number` (moved from docx_styles, still importable there),
      `level_label`, `Counters` (Word's restart rules, skipped levels show 0), `LEVEL_INDENT_TWIPS`.
    - Importer: `Numbering` holds `LevelDef`s (indent, hanging, isLgl, lvlRestart, suff, font), follows
      `numStyleLink`; `_list_numbering(entries, ...)` takes a level's definition from its first item's numbering and
      shifts `%n` to the list's top; Symbol/Wingdings bullets mapped (`_SYMBOL_BULLETS`, unknown → • and
      `docx.list_numbering.bullet_font`); trailing levels a Word export writes anyway are dropped, all-usual → None
      (`_exported_anyway`, `_usual`). Continuation is counted per definition (`Numbering.counted_with`) and restarts
      where an instance has a startOverride (`_count_key`).
    - Word export: `_list_levels` + `_abstract_numbering` build each list's nine levels element by element (no
      markup from labels), deduplicated by a hash name; `_new_list_numbering` sets every level's startOverride.
    - Editor: `editor/listNumbering.ts` keeps `numbering` (format + levels) on orderedList/bulletList (not rendered);
      `numberingOf` gives it back; formats HTML can't say (01, а) ride on it.
    - Reports: labels, multi-level numbers, own bullets, 01/а б в are detected_not_editable "kept in a Word export;
      the pages here and a PDF show ... for now"; unknown formats (first, one) stay lossy.
    - Golden `15-numbering.docx` (1/2/3/5 levels, own labels, a restart, continuation across a section break); the
      golden signature now includes lists' numbering and section breaks' settings.
  - `phase-03n-pdf-list-labels` (`aa132b4`), DOCX-016 part 2: a PDF numbers each list
    from its levels. `list_numbering.py` now holds `Level`, `list_levels` (moved from the Word export),
    `list_counters`, `item_label` and the defaults (`WORD_LEVELS`, `DEFAULT_FORMATS`, `DEFAULT_BULLETS`), shared by
    both exports and the importer. `_build_list_flowables` hangs each label at its level's indent (ReportLab
    `bulletText`/`bulletIndent`), or leads the text with it for a space/nothing suffix; a bullet is drawn in a font
    that has it (`fonts.font_for`: the text's, else Segoe UI Symbol, DejaVu Sans...). The import notes say a PDF
    shows labels, multi-level numbers, own bullets and 01/а б в.
  - `phase-03o-list-labels` (`bcdc9af`), DOCX-016 part 3 — DOCX-016 DONE: the editor
    shows each item's label. `editor/listLabels.ts` mirrors `list_numbering.py` (`formatListNumber`, `levelLabel`,
    `Counters`, `listLevels`, `itemLabel`); the `ListLabels` plugin decorates each list item with `data-label` (a
    sub-list nesting as a level counts on; one of its own counts from the item's level + 1) and a list with its own
    levels with their indents (`padding-left`); globals.css draws `li[data-label]::before` in place of the marker and
    closes up nested lists. `sectionHeaders.formatPageNumber` is `formatListNumber`. Only number styles the app
    doesn't have stay reported. Visual baseline updated (nested lists without a gap). Follow-ups DOCX-016A (numbered
    headings as live numbering), DOCX-016B (more number styles).
  - `phase-03p-table-geometry` (`49c5a78`), DOCX-017 part 1a: a table's geometry and look.
    - Model: `TableContent.columnWidthsCm/widthCm/widthPercent/align/indentCm/borders (TableBorders)/cellMargins/
      style/look (TableLook)/headerBold`; `TableRow.heightCm/heightRule/repeatHeader`; `TableCell.verticalAlign/align/
      borders (CellBorders)/margins`. Border values validated by `formatting/values.border_value`.
    - Importer: `parsers/docx_tables.py` (`TableStyles` resolves a table style through basedOn: borders, margins,
      alignment, indent, first row; `table_properties`, `row_properties`, `cell_properties`). Header rows only from
      tblHeader or a style's first row the table shows (its fill and bold applied); no more forced first-row header.
      A cell unlike its column keeps its own alignment. `docx.table.style_look` names by-position style colours.
      `docx.table.geometry` (docx_detect) is gone.
    - Word export `_add_table`: the style where the file has it, else resolved borders; Table Grid + centred + bold
      header only for a table made here; tblW/jc/tblInd/tblBorders/tblCellMar/tblLook, gridCol widths, tcW, trHeight,
      tblHeader, tcBorders/shd/tcMar/vAlign, per-cell alignment -- in schema order (`_put_in`).
    - PDF `_build_table`: grid widths scaled to fit (`_column_widths`), every cell edge resolved (`_border_commands`),
      padding from margins, VALIGN, exact and least row heights (`_row_heights`), repeated header rows, hAlign.
    - Editor: `editor/tableLook.ts` (attributes on table/row/cell carry the model; a plugin draws resolved borders,
      padding, v-align, row heights, the wrapper's alignment/indent; colwidth for widths); tiptapToDocument keeps
      per-cell alignment and widths (the "not kept" notes for them are gone). Visual baseline updated.
  - `phase-03q-table-cells` (`62e7957`), DOCX-017 part 1b — DOCX-017 DONE: a Word
    cell's contents as blocks (`_CellPart`, `_cell_parts`, `_cell_body`, `_cell_list`; `_table` →
    `_table_content(lift=...)`), pictures in cells kept (their size reported, `docx.table.cell_image_size`), lists in
    cells numbered, nested tables read recursively; the Word export no longer piles empty paragraphs after a table
    in a cell. Floating tables (`TableContent.floating`, `TableFloat` from tblpPr; `docx.table.floating`) and
    `TableRow.cantSplit` kept and written back. `docx.table.cell_image`, `nested_table`, `cell_list` reports are gone.
    Golden `16-table-engine.docx` (+ `e2e/tables.spec.ts`); the golden signature compares tables' geometry. Follow-ups
    DOCX-017A (draw a style's banded rows and first/last columns here and in a PDF), DOCX-017B (float tables here and
    in a PDF).
  - `phase-03r-pictures` (`17dfd4d`), DOCX-018 — DOCX-018 DONE: a picture keeps its type and name, alt text and title, the
    size Word draws it at, its crop, turn and flips, and where a floating one sits (`ImageContent` mime/name/widthCm/
    heightCm/crop (`ImageCrop`)/rotation/flipHorizontal/flipVertical/placement (`ImagePlacement`); read by
    `parsers/docx_pictures.py::picture_properties`). Word export writes them back (`a:srcRect`, `a:xfrm`, a
    rebuilt `wp:anchor` via `_float`, `wp:effectExtent` for a turned picture's room via `_turn_room`), WebP as PNG
    (`_word_picture`). PDF crops/flips/turns with PIL (`_shaped_picture`) and sizes a turned picture by its turned
    outline (`export/images.py::turned_box`); an unchanged picture keeps its exact width
    (`picture_width_cm`: the importer's width rule is rounded to 0.1%). Editor: `editor/pictureLook.ts` (a crop =
    the whole picture clipped, edges pulled in by margins; a turned one gets its turned room). Floating pictures are
    shown in line here and in a PDF (reported, DETECTED_NOT_EDITABLE). Reports `docx.image.crop`/`rotation` and
    `docx.table.cell_image_size` are gone. Found and fixed on the way:
    - fingerprints (`export/provenance.py`) counted default values, so every field added to the model since DOCX-028
      (DOCX-017's row/table fields, the picture flips) made blocks stored before it look changed -- the Word export
      then rewrote them instead of copying their XML. Fingerprints now leave defaults out; hashes stamped earlier
      are checked as the model stood then (`_STAMPED_BEFORE`), pinned by
      `test_a_block_stored_before_the_model_grew_is_still_unchanged`;
    - in a PDF, blocks nested in a table cell, a list item or a quote had no style at all (Helvetica, leading =
      font size: text by a picture in a cell was covered); they now take the look of what holds them (`_inside`).
    Golden `17-pictures.docx` (+ `e2e/pictures.spec.ts`); the golden signature compares pictures' properties.
    Follow-ups DOCX-018A (float pictures and wrap text around them here and in a PDF), DOCX-018B (crop and turn in
    the editor).
  - `phase-03s-list-item-pictures` (`a6c0b98`), DOCX-027 — DOCX-027 DONE (its cell half came with DOCX-017): a numbered
    paragraph's pictures are what its item holds after its text (`ListItem.blocks` image blocks, `_picture_blocks`,
    `_pictures`), top-level and in table cells (a cell's list is no longer split by an item's picture); a numbered
    paragraph holding only a picture is an item (it used to be left out as an empty item). The Word export writes an
    item's leading pictures back into its own paragraph (`_add_image(..., into=paragraph)`), so a round trip is
    stable; the editor and a PDF draw them under the item's text. `docx.list_item.image` is gone. Golden
    17-pictures.docx has the list; the golden signature compares what list items hold (`_held`). Follow-up
    DOCX-027A: an item that is only a picture shows its number on a line of its own here and in a PDF (Word: beside
    the picture).
  - `phase-03t-source-styles` (`54a36e4`), FMT-004 — FMT-004 DONE (audit AUD-03): a Word file's own formatting is complete.
    What its styles and document defaults leave unset is what Word draws there -- no bold or italics, no spacing,
    single lines, left aligned, no indent, 10 pt Times New Roman (`docx_styles.py::as_word_draws`, the last level of
    every style the importer takes, and of each paragraph compared with its kind in `_element_rules`; a table's
    or a note's look is only what its text shares, so those fall back on their kind). Word tables leave no gap
    after them (the Table kind's spacing after is 0, and the PDF no longer adds 6 pt anyway). So the render
    spec's defaults (a bold heading, 18/6 pt around it, 8 pt after paragraphs and tables, a 1 cm quote indent,
    small italic captions) no longer stand in for the file's; they still shape documents made here, and a
    template still restyles an import (templates sit above the source). Documents imported earlier keep the
    rules they were imported with. Visual baseline updated (12-complex + Академичен: its quote isn't indented,
    its captions aren't italic, no gap after its table -- as in Word).
  - `phase-03u-no-silent-autolink` (`914476f`), DOCX-026 — DOCX-026 DONE (audit AUD-03/AUD-13): web and e-mail addresses a
    Word file has as plain text stay text, as its author left them (Word links them only while one types). An upload
    can ask for links: `autolink` on `POST /jobs/import-file` and `POST /documents/upload` (the job payload carries
    it), the wizard's checkbox for a .docx (`importFile(..., { autolink })`); the importer reads it from a context
    variable (`parsers/docx.py::_AUTOLINK`, set by `import_docx` for one import), and only then does the import
    report say "became links" (`detect_docx_features(..., autolink=)`). Unsafe addresses (javascript:, file:, UNC)
    were already kept as text and reported (`docx.link.unsafe`). Golden 05-links.docx says its plain address stays
    text; `e2e/links.spec.ts` uploads it both ways.
  - `phase-03v-word-fixtures` (`505d97f`), TEST-020 — TEST-020 DONE (audit AUD-20): 20 synthetic documents written by
    Microsoft Word itself in `backend/tests/fixtures/word/` (the audit's a01-a12 and r01-r05, plus a13-pictures,
    a14-modified-styles, a15-links), built by `scripts/make_word_fixtures.py` (Word COM; Windows + Word only; refuses
    while Word is open; kills nothing), each feature recorded in `manifest.json`, the folder's README saying what
    each holds. Every file is scrubbed (`scrub`): the Word user's name and initials, Office's sensitivity labels
    (MSIP_Label_*, the organisation's tenant), comment authors' sign-in identities (w15:presenceInfo -- the audit's
    a07 carried the Word account's e-mail there), any company, manager or author Office filled in; the fixtures'
    own made-up values stay. `tests/test_word_fixtures.py` checks the committed files for all of that, that the
    manifest lists every file with nothing refused, and that each imports and exports to a sound Word file.
  - `phase-03w-expected-losses` (`05c6c69`), TEST-021 — TEST-021 DONE (audit AUD-20): next to each of the 37 fixtures (17
    golden, 20 Word-authored), `<fixture>.expected-loss.json` holds what the app says it changes or leaves out:
    the import report and the Word and PDF exports' reports, as an upload and an export job make them (the file
    kept, `with_source_kept`, fingerprints stamped, the Word export written into the original), reduced to each
    item's feature, policy, count and contentChanged plus each content check's status
    (`app/fidelity/loss_manifest.py`). `tests/test_expected_losses.py` compares them with what happens now (CI too)
    and says which item is new, gone or changed; `python -m scripts.export_expected_losses [fixture ...]` rewrites
    them on purpose. PDF claims depend on the machine's fonts, so they are kept per platform (win32 so far) and
    compared only there: TEST-021A records the Linux ones once fonts are bundled (Phase 11). What they record today
    includes the known gaps: a03's numbered headings typed into the text (DOCX-016A), a07's tracked changes
    accepted (DOCX-022), a09's charts/SmartArt/objects left out (DOCX-019), a11's scripts missing from the PDF.
  - `phase-03x-true-fidelity` (`6869d5c`), TEST-022 — TEST-022 DONE (audit AUD-20): every fixture through the app's whole path
    (imported as an upload imports it, the academic template, the editor's save, a Word export into the original)
    and the file that came out against the one that went in, on four axes each on its own
    (`app/fidelity/round_trip.py`, `tests/test_true_fidelity.py`, pinned per fixture in
    `<fixture>.expected-fidelity.json`, `scripts/export_expected_fidelity.py`): content (body and header words),
    structure (kinds, heading levels, list levels, table shapes, pictures), formatting (each kind's look and the
    marks, against the formatted document), metadata (core and custom properties, not `modified`). It found three
    real losses, fixed with it:
    - a Word export gave a file without a title the name it was shown under, and replaced a file's own title with
      its first heading: `SourceProperties.title` ("" for none) and `importedTitle` keep them apart, the export
      writes the file's own while the document keeps its import title;
    - after a template, the kinds it didn't set looked one way here and another in Word -- their Word styles, based
      on Normal, took the new body text's look while here they kept their imported one. The import now leaves out
      of each kind what it only inherits from Normal (`docx_styles.py::inherit_from_normal`, what
      `render_spec.FROM_BODY` says each takes), so here too they follow the body text; and a Word export into the
      original writes every kind's style once Normal changed (`_define_styles`), so Word shows each as it looks here.
    Today only a03's heading numbers typed into the text differ (DOCX-016A).
  - `phase-03y-drawings-kept` (`9b2249d`), DOCX-019 — DOCX-019 DONE (text boxes as boxes: DOCX-019A): a Word export of the
    kept file puts charts, SmartArt, shapes, embedded objects and VML drawings back even into a paragraph written
    anew -- from the original paragraph an element came from (`sourceBlocks`, the server's own copy, nothing the
    browser sent), where they were in its text (`_put_back_drawings`, `_insert_at` splits the run), and a paragraph
    of nothing but drawings after its group (`_copy_plan`'s third answer). Their parts and relationships stay; the
    SmartArt's drawing part, referenced only from its data part (`dsp:dataModelExt relId`), was being dropped even
    for copied blocks -- fixed. Drawing ids are made unique (`_unique_drawing_ids`); the package check names an id
    used twice and no longer counts Word's own empty `r:blip=""` as a missing relationship. Import report with the
    file kept: charts, SmartArt, shapes, embedded objects are "not shown here or in a PDF; a Word export keeps them"
    (`KEPT_DRAWINGS`, not content changed). The export report no longer claims crop/rotation/floating are lost in a
    rewritten block (DOCX-018 writes them), and names a shape with text as a text box. The true fidelity test now
    counts each file's charts, SmartArt, objects, shapes, text boxes, equations and pictures: before this change a09
    lost its chart, SmartArt and embedded sheet after a template; now only its two text boxes' frames (DOCX-019A;
    their text stays the document's paragraphs). Word opens the rewritten a09 export (hidden Word, read-only): same
    inline chart and OLE sheet, equations, SmartArt.
  - `phase-03z-fields` (`2d8ad45`), DOCX-020 — DOCX-020 DONE (header fields beyond page numbers in a header edited here:
    DOCX-020A): measured in Word first (hidden, read-only, fields updated): dates, author, title, file name, REF,
    PAGEREF, SEQ, links, CITATION (its sources part kept: no "Invalid source specified") and a header's STYLEREF
    already survived; a table of contents (both exports) and a bibliography (written anew) didn't -- fields running
    across paragraphs. Now the import keeps where such a field starts (`field_open`, its code, on the block it
    begins in) and ends (`field_close`, on the block it ends in; Word ends one in a paragraph of its own, which the
    import leaves out -- the end goes on the block before, `paragraph: true`, `_close_fields_in`), the two named by
    one region; a table of contents is kept too (`docx.toc` now DETECTED_NOT_EDITABLE). A Word export writes them
    back around their entries (only regions whose start comes before their end, each once: `_balanced_regions`,
    else written as text and `export.docx.field_region`), and into the original groups a region's blocks so an
    unchanged table of contents is copied whole. Word then shows a06's TOC and bibliography and r01's TOC and
    updates them. Found on the way (by the true fidelity test): the fragment writer wrote a run of text only where
    one started at a fragment's edge, so text in other formatting between two edges was left out of a paragraph
    written anew (a06's italic book title) -- it now writes every piece.
  - `phase-03aa-comment-threads` (`5c4bf69`), DOCX-021 — DOCX-021 DONE. Measured in Word first (hidden, read-only,
    `scratchpad/word_comments.py`): a07's author, text and range survived both exports, but its reply came back as
    a comment of its own and its resolved comment as open -- the export dropped commentsExtended (which names each
    comment by its last paragraph's paraId) since comments written anew get new ids. Now the import keeps each
    comment's id, the one it answers and whether it is resolved (`commentId`/`replyTo`/`done`,
    `parsers/docx_comments.py`), and a Word export writes commentsExtended again for the comments the file has
    (`_thread_comments`: copied ones from the original's, written ones from the import's, parents by the ids they
    have now; paraIds given to comments written anew). Found on the way, in Word: python-docx puts a later
    comment's end and reference on the same run before an earlier one's, and Word takes a reply whose reference
    comes first for a comment of its own -- they now go in the comments' order (`_after_earlier_ends`). The true
    fidelity test's structure axis counts comments, replies and resolved ones (catches the loss: mutation-checked);
    the package check names thread entries that name no comment. Word shows a07's copied, rewritten and new-file
    exports' threads as in the source. Ranges: a comment over several paragraphs was ended where its first
    paragraph does by every export (measured); it is now kept like a field across paragraphs (the comment with a
    region on its first block, `comment_close` on its last; one ending in an empty paragraph ends where the block
    before does), its end and reference moved there on export (`_OPEN_COMMENTS`), its blocks one group into the
    original; one running into a list/table/code, or whose last paragraph is deleted, covers its first paragraph
    and the report says so (`docx.comment_range`, `export.docx.comment_range`). Word shows it over all three
    paragraphs, rewritten and in a new file.
  - Found on the way (P0, pre-existing since DOCX-028, not fixed in that commit): a block deleted in the editor
    came back in a Word export into the original. Tracked as DOCX-028B.
  - `phase-03ab-deleted-blocks` (`0485210`), DOCX-028B (P0) — DOCX-028B DONE. Reproduced: three paragraphs, the second deleted
    -> all three in the export; a paragraph's picture deleted -> back with its unchanged paragraph. The copy plan
    took an original child no element holds for one the import left out (a spacing paragraph) and copied it with
    the block before. Now stamping as imported records how many elements each body child was read into
    (`Document.sourceBlockUse`, `provenance.block_use`; server-side, saves only replace elements); a child fewer
    elements hold now had one deleted: never copied nor taken for one left out, and a group still holding it is
    written anew (`_copy_plan`, `use`); children the import left out still go with the block before. A document
    stamped before this has its file read again as its import read it (`_block_use`). Also fixed by it: a section
    break deleted here whose paragraph was unchanged came back the same way. Proven through the API and through the
    editor (e2e: a paragraph deleted in the editor is gone from the export, the untouched blocks still copied).
  - `phase-03ac-tracked-changes` (`122d2a2`), DOCX-022 — DOCX-022 DONE (rejecting all, and paragraph-mark deletions joining
    paragraphs as Word does on accepting: DOCX-022A). Measured in Word first: every export accepted a07's 7
    revisions (0 after). Now the import still reads them as accepted (a row deleted while tracking is gone -- it came
    in as an empty row) and marks the document `trackedChanges` "kept": a Word export into the original copies
    every unchanged block with its tracked changes (`_self_contained(revisions=)`; a moved text's range balanced
    within the group like a bookmark); a block changed or restyled here has its own accepted and the export report
    names "tracked changes"; the import report says they're kept for export (`TRACKED_KEPT`). Accepting them all
    is the person's choice, on the review after the upload and in the Проверка panel (`TrackedChangesChoice`,
    `PUT /documents/{id}/tracked-changes`); the content stays as it is (read as accepted either way); accepted, no
    export has them and none says they're lost (`TRACKED_ACCEPTED`, lossy as chosen). Word: a07's unchanged export
    has its 7 revisions and gives exactly the file's text on accepting all and on rejecting all; with its table
    edited, accepting gives the app's view and rejecting puts the moved paragraph back while the table stays as
    edited. The true fidelity axis counts tracked-change marks (a07: 19 -> 0 after the academic template, which
    rewrites every block: pinned until DOCX-029).
  - `phase-03ad-content-controls` (`256e7f6`), DOCX-023 — DOCX-023 DONE (controls inside tables, lists and text boxes, still
    kept only while unchanged: DOCX-023A). Measured in Word first: a08 written anew had none of its 8 controls and
    Word couldn't read its 2 legacy form fields as form fields. Now every kind (plain/rich text, checkbox,
    drop-down, combo box, date, picture, repeating section) goes back with its properties: one in a paragraph as a
    `control` fragment with its sdtPr/sdtEndPr and the text just before and after it (so a control whose text was
    changed -- filled in, chosen again -- goes between those; a checkbox's state follows its symbol); one around
    blocks as open/close markers on its first and last block (`preservedAttributes["controls"]`, `_Controls` puts
    it back around the blocks written, inner first; one that lost its first or last block: written without it and
    `export.docx.control_region`); a picture control with its picture (`preservedAttributes["control"]`). A legacy
    form field keeps its ffData. Ids made unique (`_unique_control_ids`). What comes back from the browser is
    checked (one sdtPr/sdtEndPr, no relationships). The import report: `docx.content_control` kept for export;
    `docx.content_control.nested` (tables, lists, text boxes) lossy / kept while unchanged. The internal-link and
    control containers nest (a stack). The true fidelity axis counts content controls (06-lists' checklist: 0 -> 2
    checkbox controls, as the export writes checklists -- pinned). Word: a08 written anew and edited has all 8
    controls with their types, titles, entries and date format, the checkbox unchecked once its symbol is, and
    both form fields working.
  - `phase-03ae-notes` (`4cd515b`), DOCX-024 — DOCX-024 DONE. Measured in Word first: a10's 3 footnotes and 2 endnotes came
    back as 0 and 0 in every export, paragraphs at the end. Now the editor still shows them at the end, each
    reference as its label, but the import keeps each reference as a `note` fragment around its label and each note
    block as the note it is (`preservedAttributes["note"]`: "footnote:1" + label); a Word export writes real
    references where the labels are and the notes into their parts again (`_write_notes`, `_Notes`: with their ids,
    so a block nobody changed is copied with its reference -- `_NOT_COPIED` no longer refuses note references, only
    ones to a note deleted here; without the label, split into paragraphs; in Word's own "footnote text"/"footnote
    reference" styles; a part made with its two separators when the file has none). A note deleted here leaves its
    label as text; one referred to from a list or table, or whose reference was deleted, is written at the end
    (`export.docx.notes_at_end`); a PDF prints them at the end (`export.pdf.notes`). Found on the way: the export
    asked for "Footnote Text", found none of that exact name beside Word's "footnote text", and added a second
    FootnoteText style -- styles are now found in any case (`_named_style`); the package check names a style id
    defined twice and a note reference to a note that isn't there. Word: a10 into the original and in a new file has
    all 5 notes, each after its sentence; edited (one deleted, one revised) as edited; r01's footnote too.
  - `phase-03af-heading-numbering` (`ab029ad`), DOCX-016A — DOCX-016A DONE. Measured in Word first: a03 written anew had its
    headings' numbers typed into their text, and a heading edited here showed two ("2.1 2.1 Scope and aims": its
    style's and the typed one). Now when one list numbers the headings, each at its own level, the import keeps the
    headings' own text and the numbering (`Document.headingNumbering`: a ListLevel per heading level + the
    original's `sourceNumId`); a heading Word doesn't number (a Title) is `Element.numbered: false`. The editor
    (`editor/headingNumbers.ts`: decorations, `data-number` drawn by globals.css; the numbering set from the
    document into the extension's storage), the PDF and a Word export count them in order
    (`list_numbering.heading_labels`), so they follow when headings move. Into the original a heading written anew
    is numbered with the original's numbering (counts on with the copied ones); a new file gets a numbering made
    from the levels, and its Heading styles number with it. Headings numbered by more than one list, or not each at
    its own level, keep their typed numbers as before -- and written anew into the original, `numId 0`, never a
    second number. Word: a03 into the original, in a new file, and each with a heading edited: 1, 2, 2.1, 3 as
    numbering, the edited one "2.1 Scope and aims". a03's true fidelity content axis is verified now (the typed
    numbers were 5 added words).
  - `phase-03-complete` — the Phase 3 gate. Every Word fixture exported two ways (through the app with the
    academic template into the original, every block written anew; and as a new file) and opened in Word (hidden,
    read-only): it found a real regression -- a06's exports wouldn't open ("The file appears to be corrupted"):
    its citation content control holds its CITATION field, both over the same text, and since DOCX-023 the fragment
    writer opened and closed the two in the same order, so the field began outside the control and ended in it.
    Now over the same text a control or link is outermost and what opened last closes first; the package check
    names a field that starts outside a control or link and ends inside it (it had passed that file). After the fix
    all 60 files open in Word; the only differences Word counts are a09's known ones (its text boxes' frames,
    DOCX-019A; a new file has no original to take its charts and objects from -- an upload's Word export is always
    into its original). a07's threads, a08's 8 controls and 2 form fields, a10's 5 notes, a03's heading numbers all
    as in the file after the template's rewrite and in a new file (a07's revisions accepted by the rewrite, pinned
    for DOCX-029).
- Phase 4 (security + resource limits): COMPLETE (gate 2026-10-01: every P0 and P1 task DONE; SEC-020, a P2,
  stays open, and SEC-021 needs Boril).
  - `phase-04a-malformed-docx` — SEC-010: a Word file that can't be read is a 400 `invalid_file` with a message
    for people, from the upload route, the import and reference jobs and the template extract route: never a 500,
    nothing stored. The parser checks every XML part first (`_check_parts`, streamed, no tree): well-formed, no
    DTD (OPC forbids them). A probe found two silent gaps that closes: a DTD's entities made python-docx read an
    empty document, and parts nothing reads (theme, font table, customXml, app.xml) went in broken -- a Word export
    into the original would have carried them back out. After that, a failure (no body, a root that isn't
    WordprocessingML) says "couldn't be read"; the log names the exception type and the innermost frames, never its
    message. `tests/malformed_docx.py` breaks two fixtures 34 and 40 ways; `tests/test_malformed_files.py` pins which
    are read (every word, or the loss reported) and which are refused with which exact message, through the parser,
    the upload route (no row, no asset left) and the jobs; an external entity is never read; the log leaks nothing.
    Mutation-checked: each of the 10 guards, removed, fails a test.
  - Test fix found on the way: the frontend golden JSON had not been regenerated since Phase 3 added
    `numbered`, `trackedChanges`, `sourceBlockUse`, `headingNumbering` and kept note fragments. Its freshness
    test compared only the text and the page setup. It now compares every file byte for byte with a fresh export.
    Vitest passes on the regenerated set.
  - `phase-04b-malformed-pdf` — SEC-011 and SEC-023:
    - SEC-011: a PDF that can't be read is a 400 `invalid_file` with its message (not valid, password, too much
      data, no text, damaged), from the upload, the import job and an instructions file (one app-level handler,
      as for Word). Whatever pypdf throws is a refusal, logged by type and frames.
    - The probe found a silent loss: pypdf mends a stream that doesn't decode, or an object that isn't there,
      and loses that text with only a warning (page 1's words gone). `read_pdf` collects pypdf's warnings per read
      (a ContextVar) and tells repairs that lose nothing from ones that lose text: the import then reports
      `pdf.damaged` as a content change; an instructions file is refused; a damaged file with no text left says
      so, not "scanned". pypdf's warnings never reach the log (they can quote the file) -- the log gets counts.
      Pictures that can't be counted are said to be possibly left out, never counted as none.
    - SEC-023, found by the same corpus: text XML can't hold (a PDF's backspace, pasted control codes) was stored
      and then made every Word export of that document fail. Every text field is an `XmlText` now: those codes are
      dropped whoever sends them (importers, the editor, the AI), word separators become spaces; the text
      importers clean before the content check and report `text.control_characters`.
    - `build_document_from_pdf` was dead code duplicating the upload's PDF branch (that duplicate is how the
      upload path was first missed here): removed.
    - `tests/malformed_pdf.py` (19 variants from reportlab PDFs written the same every time) and
      `tests/test_malformed_pdfs.py` (45) pin each through the reader, the upload route, the import job and the
      instructions route. Mutation-checked: 17/17 killed.
  - `phase-04c-picture-limits` — SEC-012:
    - Limits in `security/files.py`: a picture 20 MB, 50 megapixels, 20,000 px on a side; a document 1000 pictures
      and 200 MB of them (an export holds a document's pictures in memory at once -- `export_assets`).
    - `picture_problem` judges a picture by its header before anything decodes it; only PNG/JPEG/GIF/WebP/BMP are
      ever opened (`formats=` on every `Image.open`: Pillow would otherwise try 43 formats, EPS among them, which
      runs Ghostscript), and a picture must be the type it claims. Pillow's own backstop for any other decode
      (reportlab's): `MAX_IMAGE_PIXELS` = half the limit, so Pillow itself refuses past it. (A warnings filter set
      at import doesn't survive an import inside `catch_warnings()` -- pytest's collection is one -- so nothing
      rests on one.)
    - Word import: past the limits, left out and said to be (`docx.image.too_large` / `too_many`). The editor's
      save: such a picture removed and named; a save past the document's number or bytes refused with 413
      `too_large` before anything is stored -- and the editor says why and stops retrying. Export: one stored
      before the limits left out (`export.image.too_large`).
    - Found on the way (frontend): a failing save was sent again every 1.2 s instead of backing off -- each try
      gave an unsaved block a new id, whose sync was an editor update that scheduled the next save. The
      autosave's own writes (ids, looks saved) schedule nothing now; a test pins the 0/5/20 s backoff.
    - `tests/malformed_pictures.py` (18 pictures) and `tests/test_picture_limits.py` (25); 16/16 backend
      mutations killed, the frontend loop fix checked the same way. The migration test's "PNG" (a signature and
      junk) is removed now like any picture that can't be decoded: it uses a real one.
  - `phase-04d-link-policy` — SEC-014: one policy for link addresses (`security/links.py::safe_href`): an
    absolute address of a kind that opens a page, a mail, a call or a chat (http, https, ftp, ftps, mailto, tel,
    callto, sms, xmpp -- the editor's Tiptap list but cid:); bare www. gets https://; never javascript:, data:,
    vbscript:, file:, UNC, relative, #anchor, or past 2048 characters; control codes dropped and tabs/newlines
    inside removed before the scheme is read (as browsers do). The model keeps no other address (`Mark.href`):
    such a link keeps its text. Word import reports it (docx.link.unsafe, now the shared rule), Markdown reports
    relative/other-scheme links (markdown.link.unsafe), neither export writes one as a live link whatever it is
    handed, the health check never calls one usable. The editor uses the same rule (`editor/linkPolicy.ts` as
    Tiptap's `isAllowedUri`, and the reconcile names a link it can't keep). `frontend/tests/fixtures/
    link-policy.json` (34 cases) is read by the backend and the frontend tests, so the two can't drift.
    14/14 mutations killed (11 backend, 3 frontend).
  - `phase-04e-field-policy` — SEC-015: only fields that show what the document holds or works out stay fields
    (`security/fields.py::ALLOWED_FIELDS`, HYPERLINK only to a SEC-014 address or a bookmark); DDE, DDEAUTO,
    INCLUDETEXT, INCLUDEPICTURE, INCLUDE, IMPORT, LINK, RD, DATABASE, MACROBUTTON, PRINT and anything unlisted keep
    their last result as text:
    - an upload is cleaned before it is read or kept (`clean_package` / `neutralize_fields`: body, headers,
      footers, notes, comments, building blocks; nested fields and ones deleted with tracked changes too), so no
      export into the kept original carries one out, and copied unchanged blocks are clean; reported as
      `docx.field.unsafe`;
    - the importer keeps no such field whoever calls it; the export writes a field fragment only when its field
      may be one, and a region field whose start is refused loses its end (no end without a start);
    - found while scoping: a save took `preservedAttributes` from the browser as sent -- a crafted save could put
      a DDE field into the next Word export. Now `provenance.py::keep_preserved` keeps the server's for every block
      at any depth, as `keep_provenance` does; a new block has none. Also a `HYPERLINK "javascript:"` field used to
      be kept as a field fragment (`_keeps_field` kept everything) -- no longer.
    - `tests/test_field_policy.py` (32); 11/11 mutations killed (two survivors first showed missing cases: a
      refused field whose instruction holds an allowed one, and an allowed field deleted with tracked changes).
      Word opened the cleaned file and its export (hidden, read-only): no repair, fields DATE and PAGE only.
  - `phase-04f-security-suite` — TEST-030: the security regression suite is one pytest marker (`-m security`,
    registered in pytest.ini) over the SEC-010..015 corpora, prompt injection, upload checks, document authorization
    and the new `tests/test_security_suite.py`, which reads the API's OpenAPI schema so no route goes unchecked:
    all 33 routes that take an id answer another workspace exactly as a missing id (404, the same body -- which
    also catches an ownership check done after a sub-resource lookup), need sign-in, and leave the owner's
    document, picture, job and template as they were (a route without a request in its table fails the suite);
    all 37 writes refuse another site's Origin. CI runs the suite as its own step, then `-m "not security"`: each
    test once. Mutation-checked: removing the document, asset, job or template ownership check, or the
    cross-site check, fails it (5/5).
  - Phase 4's P0 tasks are all DONE.
  - `phase-04g-external-targets` — SEC-016: the Word file kept as the original keeps no external target but links a
    link may have (`security/package.py::clean_package`, which now also holds SEC-015's field cleaning): a remote
    template (attachedTemplate), a linked picture's link (the embedded picture stays), a sub-document, a linked
    object, a mail merge (its data source, connection string and query) go at upload, with what referred to them;
    a link to a refused address keeps its text. Reported as `docx.link.unsafe` (the importer's own words, one
    constant) and `docx.external.unsafe`. Found: python-docx keeps orphan relationships on save, so an unsafe
    link's relationship (a06's `file:///C:/secret/local.txt`) used to travel out in every Word export even though
    the text was plain. `tests/test_external_targets.py`; 8/8 mutations killed; Word opens the cleaned file and its
    export without repair.
  - `phase-04h-svg` — SEC-017: SVG verified refused everywhere, no app change needed (the protections held):
    pasted (an SVG data URI, or SVG bytes claiming PNG) removed and nothing stored; a Word SVG picture read as its
    PNG fallback (svgBlip), an SVG-only one reported as an unsupported format; Markdown never parses a data:image/svg
    address as a picture; `picture_problem` refuses it; an export handed one leaves it out and says so; a stored
    asset is served with its type, nosniff and a sandbox CSP -- by the route and by the API-wide headers (two
    layers: removing one changes nothing a browser sees, removing both fails `tests/test_svg.py`).
  - `phase-04i-error-envelope` — SEC-019: every error is {code, message, details, request_id} with a message for
    people; `tests/test_error_envelope.py` sweeps every OpenAPI operation (signed in and not, junk ids and body)
    plus an unknown path, a wrong method, an invalid body (no value echoed -- a password stays out), a body too
    large and a forced crash (a plain 500, nothing of the crash in it). Found: a format request's invalid conflict
    resolutions answered with pydantic's own report, values included -- now a RequestValidationError like any
    other. 3/3 mutations killed.
  - `phase-04j-limits` — SEC-013: every resource limit reviewed and written into one table
    (docs/security/README.md "Limits", also PERF-007's record of user-facing maximums). Measured: a Word file
    reads in about a third of a millisecond a paragraph, and a PDF page's text takes longer than in step with what
    is drawn on it (13 s for 2 MB of content, minutes beyond). Closed: a Word file may have 50,000 paragraphs and
    50,000 table cells (counted in the streaming part check, so for free); a PDF page 2 MB of content, and a PDF
    60 s of reading in all, checked between pages. Markdown needs no new limit within the 2,000,000 characters of
    pasted text. `tests/test_limits.py` tests each on an ordinary file with the limit lowered; 4/4 mutations
    killed. Job timeouts are JOB-001's (the cloud session).
  - `phase-04-complete` — the Phase 4 gate. Every P0 and P1 task of Phase 4 is DONE (SEC-010..019, SEC-022,
    SEC-023, TEST-030); SEC-020 (P2, a nonce-based CSP for the Next.js app) stays open and SEC-021 needs Boril.
    Every Word fixture as an upload now keeps it -- cleaned of refused fields and external targets -- was exported
    two ways (through the app with the academic template into that cleaned original, and as a new file; scratchpad
    `phase4_gate_exports.py`); the package check finds nothing in any of the 60 files. Word (hidden, read-only)
    opens all 60 without repair and counts in each the pictures, shapes, equations, tables, comments, content
    controls, form fields, notes, sections, links and fields by type: the exports hold what the cleaned original
    holds but where already known -- a09's text boxes' frames written anew (DOCX-019A), as at the Phase 3 gate;
    and in a new file, which an upload never gets (its Word export is always into its original; the export job
    says so when that is missing), a09's chart and embedded object (no original to take them from) and a06's
    STYLEREF field in a header (a new file's headers are their text and page numbers). What cleaning changed in
    the fixtures: a05's GLOSSARY field in a footer (a template's building block, from outside the document:
    refused, its last result stays) and a06's link to a local file (its text stays); the field test now pins
    AUTOTEXT, AUTOTEXTLIST and GLOSSARY as refused. Found, not a regression: a04's SVG picture is shown as the PNG
    copy Word keeps with it; copied unchanged into the original it stays SVG, written anew (a template, an edit)
    it is the PNG, and no report says so -- DOCX-018C (P2).
- Phase 5 (performance + autosave + history): in progress.
  - Delegated to a cloud session (2026-10-01): Phase 5's PERF-001 (linear table export), JOB-001 (job safety),
    PERF-004 (bounded, compressed version history), PERF-002 + PERF-006 (benchmarks, UTF-8 JSON), each on its own
    `cloud/...` branch from the commit after this one, with a report in `docs/cloud-reports/<ID>.md`. Not
    delegated: PERF-003 (delta autosave changes the save protocol SEC-015's server-side guarantees rest on) and
    PERF-007 (overlaps SEC-013). When the branches arrive: fetch, review each diff against the rules in the cloud
    prompt, run the full suites here (Word checks for PERF-001's exports), apply any migration to Supabase only
    after review, then merge one by one into feature/smartdoc-production-hardening and update the tracker.
  - `phase-05a-delta-autosave` — PERF-003: a save sends what changed, not the document. `PATCH /content` names
    its revision in If-Match (428 without it) and carries the top-level elements changed (whole), added (each with
    the id of the one before it) and removed, and the direct styles. The server builds the whole list from its own
    copy (`services/content_patch.py::patched_elements`) and saves it through the function `PUT /content` uses
    (`DocumentService._take_elements`: provenance and preserved fragments stay the server's, pictures become
    assets, consecutive saves are one undo step), so a patch can do nothing a whole save can't; one that doesn't
    fit is a 409 `patch_mismatch`, and nothing is written. The answer (`ContentSaved`, `content_delta`) is how the
    stored document differs from that revision -- the elements changed or added as stored, their order only when
    it isn't the patch's, every other changed part whole -- and the editor applies it to its copy
    (`editor/contentPatch.ts::applyContentSaved`). Threshold: a moved block, more than half the blocks (and 20)
    changed, or no known revision -> the whole document by PUT, as before; so does a refused patch (409, 412,
    422, 428), and a 412 is announced only if the whole save gets one too. Measured (BENCH-010/011): a
    one-paragraph save of a 300-page document (1,651 elements) is 1.4 KB each way instead of 2.2 and 2.1 MB; at
    12,201 elements (a 1M-character paste), under 1 KB instead of 9.3 and 8.7 MB. Found: the server still reads,
    validates and writes the stored document whole on every save -- 0.37 s and 2 s there (four whole dumps, one
    validation, the JSON in and out), with the event loop blocked meanwhile: PERF-008 (P2), after the cloud's
    PERF-004 is merged. Tests: `tests/test_content_patch.py` (20; 40 random edits saved as a patch to one document
    and whole to its twin store the same, and each answer applied to the version before is exactly the stored
    document), `editor/contentPatch.test.ts`, `useAutoSave.test.tsx`, `services/api/documents.test.ts`; the E2E
    typing test checks the browser sends that paragraph alone. 16/16 mutations killed. Browser check (throwaway
    stack): typing in paragraph 301 of a 601-block document sent one PATCH, whose answer held that paragraph and
    the metadata; the text was there after a reload.
- Phase 6 (accounts + billing + entitlements): in progress, started while the cloud's Phase 5 branches are pending.
  - `phase-06a-atomic-plan-limits` — PLAN-003, first part: a limit holds when requests race. Each check that counts
    (documents, templates, storage) used to count and then let the use happen, so two requests at once could both
    pass a limit with room for one. Now the check right before the use holds the workspace until the transaction
    that makes it ends (`entitlements_service.py::hold_workspace`, `hold=True`): a no-op UPDATE of the workspace's
    row, the same statement on both databases -- PostgreSQL takes the row's lock, SQLite its write lock -- so a
    second request waits and then counts the first one's. Held: `DocumentService.create` (every new document,
    however it is made), `TemplateService.create`, and a save with a pasted picture (an ordinary save holds
    nothing); the earlier checks that refuse before a file is read hold nothing. `tests/test_plan_limits_atomic.py`
    runs the race on two real connections to one SQLite file (the second check still waiting half a second later,
    refused once the first commits; all three fail without the hold) and checks which paths hold; 6/6 mutations
    killed. Not yet: AI operations (two AI jobs at once can each use what is left of the month) -- a reservation
    per call, released when it fails, which has to agree with JOB-001's retries and timeouts, so after the cloud's
    JOB-001 is merged. Not run against PostgreSQL here (none on this machine; CI's PostgreSQL job runs only the
    migrations, and CI runs only for pull requests and main): TEST-031.
  - `phase-06b-email-sender` — ACCT-001: how the app sends e-mail (`app/mail/sender.py`), chosen by EMAIL_BACKEND:
    "outbox" (the default) writes each message as an `.eml` file into `backend/data/outbox` (gitignored) and sends
    nothing; "smtp" sends through SMTP_HOST with STARTTLS or TLS -- an unencrypted connection is refused at startup
    unless the server is on this machine, and SMTP needs a host and an EMAIL_FROM address. Messages will carry
    reset and verification tokens, so no log line holds a body or an address: `mail.sent` has the kind and the
    address's hash, a failure the error's type alone, and the raised `EmailDeliveryError` carries nothing of the
    server's answer (`from None`). Sending runs in a thread with a timeout. A dependency (`get_email_sender`), so
    every test gets an in-memory sender (`tests/conftest.py::sent_mail`, autouse): no test can send or write into
    the real outbox. `tests/test_email.py` (6, in the security suite); 7/7 mutations killed. The provider and its
    credentials are Boril's; `.env.example` and the README list the settings.
  - `phase-06c-password-reset` — ACCT-002: "Forgot your password?" on sign-in. `POST /auth/password-reset` answers the
    same 202, as quickly, for any address: the account is looked up and the e-mail sent after the answer
    (`services/password_reset.py`, a background task on its own session). The link,
    `FRONTEND_URL/reset-password#token=...`, keeps the token in the fragment (no request carries it; the page sends
    no referrer and drops the token from the address bar once used). Tokens: `account_tokens` (migration
    `1da599e1913f`, RLS on), only the SHA-256 kept, an hour, single use by one `UPDATE ... RETURNING`, void once a
    newer link is asked for or the account's address changes, and for their purpose only (the table serves
    ACCT-003 too). `POST /auth/password-reset/confirm`: a new password, every session ended, a "password changed"
    e-mail; every token that doesn't work is the same 400 `invalid_token`. Limits: 10/h per address, 3/h per e-mail
    address, 20/h confirmations per address. Frontend: `/forgot-password`, `/reset-password`
    (`components/PasswordResetForms.tsx`). Tests: `tests/test_password_reset.py` (9, security suite),
    `PasswordResetForms.test.tsx` (5), and the E2E flow (`e2e/auth.spec.ts`, the link read from the E2E backend's
    outbox, `E2E_OUTBOX_DIR`); 13/13 mutations killed. The outbox now writes 8-bit text, so a link reads unbroken.
    Migration applied to Supabase (head `1da599e1913f`; advisors INFO only).
  - `phase-06d-email-verification` — ACCT-003: signing up sends a link to confirm the address
    (`FRONTEND_URL/verify-email#token=...`, two days, once, `account_tokens` purpose `email_verification`); the
    dashboard says so while it isn't confirmed (`components/VerifyEmail.tsx::VerifyEmailBanner`) and sends another
    link on request (`POST /auth/verify-email`, signed in, 5/h per user, nothing when confirmed already, a newer link
    voiding the older); the link's page confirms with one click (`POST /auth/verify-email/confirm`, signed in or
    not), so a mail scanner opening links confirms nothing, and only the address the link was sent to, if the
    account still has it. `users.email_verified_at` (migration `0417f0f393fc`); `UserResponse.emailVerified`.
    Nothing is refused to an unconfirmed account yet -- what to require it for is Boril's call. The two confirmation
    routes share one limit, renamed `RATE_LIMIT_ACCOUNT_LINK` (20/h per address); `services/password_reset.py` is now
    `services/account_mail.py` (both kinds of mail). Tests: `tests/test_email_verification.py` (5, security
    suite), `VerifyEmail.test.tsx` (4), the E2E flow; 8/8 mutations killed. Migration applied to Supabase (head
    `0417f0f393fc`).
  - `phase-06e-password-change` — ACCT-004: "Your account" (`/settings/account`, `components/AccountSettings.tsx`, a
    person icon in the header) changes the password: `PUT /auth/password` {currentPassword, newPassword}, signed in;
    the current one checked first (`AuthService.change_password`), tries counted with sign-ins (the per-account
    login limit); every other session ended and this one kept (`revoke_sessions(keep_token=)`); a "password
    changed" e-mail that says the other browsers were signed out. A wrong current password is a 400
    `wrong_password`, nothing changed. Tests: `tests/test_password_change.py` (3, security suite),
    `AccountSettings.test.tsx` (3), the E2E change and sign-in with the new password; 7/7 mutations killed.
  - ACCT-005 (account deletion) begun, not wired in: branch `wip/acct-005-account-deletion` (`472c352`, on `d44cb7e`)
    holds the policy and service (`services/account_deletion.py`), `AuthService.password_is`, `DeleteAccountRequest`,
    the goodbye message and SQLite engines enforcing foreign keys. Handed to the second cloud batch (W1).
- Hand-off, 2026-10-01: Boril's weekly limit ran out until 2026-10-06. He merged PR #7 (this branch into `main`,
  `9fdcf7a`); the first cloud batch's four PRs (#3-#6) are NOT merged anywhere -- still on `370ed49`. The second
  cloud batch (`docs/cloud-prompts/batch-2.md`, about $71 of credit) starts with W0: merge #4, #5, #6, #3 into this
  branch with one Alembic head (c3a91f7d2b64 on 0417f0f393fc, b8534d3c4256 on c3a91f7d2b64), CI fixed (next typegen
  before tsc, an audit step, `pytest -m postgres` on CI's PostgreSQL = TEST-031), PERF-007's jobs row, and W0 alone
  may merge once CI is green. Then W1 accounts (ACCT-005..007), W2 metering (PLAN-003 AI operations, PLAN-001, 002,
  005), W3 PDF foundation (PDF-010..012 + P2E-008 fixtures), W4 Stripe flows (PLAN-004), W5 save cost (PERF-008 +
  the export's style lookups), W6 CSP + storage retention (SEC-020, STOR-001), W7 E2E workflows (TEST-040): draft
  PRs for review here. The Word-check scripts used by the gates are now in `tools/word/`.
- The second cloud batch, merged 2026-10-06 (reports in `docs/cloud-reports/`):
  - W0 (by the cloud, PR #8): the first batch's PERF-001 (500x8 Word export 0.7 s), PERF-002 (scripts/benchmark.py),
    PERF-004 (zlib version history, 50 steps / 10 MB a document), PERF-006 (UTF-8 JSON storage), JOB-001 (job safety)
    integrated; one Alembic head; CI: next typegen, a dependency audit job, `pytest -m postgres` on CI's PostgreSQL
    (TEST-031, INFRA-011); next 16.3.8 (critical advisory); PERF-007's jobs row.
  - Merged here: W2 metering (PLAN-001..005: units in billing/units.py, plans as data, AI operations reserved
    atomically, storage in bytes), W3 PDF foundation (PDF-010..012: pdfminer.six geometry layer, page classifier,
    `pdfInspection`; fixtures for P2E-008), W6 SEC-020 (nonce CSP in frontend/proxy.ts) and STOR-001 (storage
    retention), W1 accounts (ACCT-005 deletion, ACCT-006 sessions, ACCT-007 sign-in delay and new-browser e-mail;
    migration b4b303454a89), W4 PLAN-004 (Stripe flows; d41f7a60c9e2 re-parented onto b4b303454a89).
  - Fixes found merging on Windows (`7ba8c0c`): `%-d` in the new-browser e-mail (glibc-only); account deletion
    compared a plan's name (now: a Stripe subscription still renewing); `.gitattributes` marks binaries (autocrlf had
    rewritten the fixture PDFs); the fixture test checks for DejaVu Sans first; a locale-proof billing test.
  - Supabase migrated to `d41f7a60c9e2` (c3a91f7d2b64, b8534d3c4256, b4b303454a89, d41f7a60c9e2); advisors INFO only.
  - Word gate after PERF-001: the 60 files open, every count identical to the Phase 4 gate.
  - W5 and W7 stopped at the cloud's weekly limit with nothing pushed; done here:
    - `phase-05b-save-and-export-cost` (`a1cb8f8`) -- PERF-008: a patch save's row, undo step and answer share one dump,
      and validation, dumps, the delta and the undo step's compression run on a worker thread: at 12,201 elements a
      save 1.47 -> 1.32 s and the event loop's longest stall 586 -> 214-239 ms (1,651: 73 -> 25-37 ms). The Word
      export works out style ids and numIds once an export: 6,801 blocks 15.3 -> 5.1 s, all 74 fixture exports byte
      for byte the same but core.xml's time. `tests/test_save_and_export_costs.py`, 4/4 mutations.
    - `test-040-e2e-workflows` (`a00632e`) -- TEST-040: the brief's 24 workflows mapped in docs/testing/README.md;
      `e2e/workflows.spec.ts` adds manual edit (toolbar bold), a typed link, a table from the menu, PDF import.
  - Gates (2026-10-06): Phase 5 COMPLETE (PERF-005, a P2, open), Phase 6 COMPLETE, Phase 7 COMPLETE: backend 2139
    passed / 11 skipped, Vitest 253, Playwright 42, Word gate 60/60 identical to Phase 4's.
- Phase 8 (PDF -> editable), 2026-10-06:
  - `phase-08a-pdf-structure` (`4d67979`) -- P2E-001 `Element.layout` (ElementLayout: page, box, rotation, lastPage,
    column, lines, source; server-owned like sourceBlocks). P2E-002 `parsers/pdf_structure.py`: deterministic
    reconstruction from the geometry read (XY cut with columns, paragraphs, headings by size/bold, lists with checked
    numbering, captions, running header/footer/page numbers -> settings, links/colours/bold/italic, turned text).
    Ingestion uses it when every page was read and >=95% of the text read's words are found, else the text path with
    `pdf.structure_not_rebuilt`. P2E-008 `structure.pdf` fixture; `tests/test_pdf_structure.py` 29, 10/10 mutations.
  - `phase-08b-pdf-conversion-report` (`33c0e4b`) -- P2E-005 `Document.pdfConversion` (fidelity/pdf_conversion.py):
    confidence per aspect and in all (<=0.6 while tables/pictures aren't rebuilt); report items pdf.annotations,
    pdf.form_fields, pdf.outline, pdf.links. `tests/test_pdf_conversion.py` 8, 6/6 mutations. Backend 2176/11,
    Vitest 253, Playwright 42.
  - `phase-08c-pdf-pictures` (`e4d00f9`) -- P2E-003: pictures paired by XObject name (geometry PdfImage.name), decoded
    by `parsers/pdf_pictures.py` within caps, placed in reading order as IMAGE elements (assets at create), no wider
    than the text; logos/scan backgrounds/rules/limits reported. 7 tests, 9/9 mutations.
  - `phase-08d-pdf-tables` (`b26e13c`) -- P2E-004: `parsers/pdf_tables.py` ruled grids -> TABLE elements, merged cells,
    shading, header by shade/bold; space-only columns stay rows-as-paragraphs (`pdf.unruled_tables`). 7 tests, 10/10.
  - `phase-08e-ocr-interface` (`c18d162`) -- P2E-006: `app/ocr` (OcrProvider, NoOcr default, results made safe);
    scanned pages read through a configured engine; OCR_PROVIDER=none until Boril picks an engine. 8 tests, 7/7.
  - `phase-08f-pdf-import-ux` (`b113092`) -- P2E-007: wizard choice Editable / Layout-focused (`pdf_mode`), layout mode
    keeps pages (page breaks) and fonts/sizes; Fidelity panel "Imported from PDF" + conversion confidence per aspect.
    4 backend tests, Vitest 256, Playwright 43, 7/7.
  - Phase 8 gate (2026-10-06): COMPLETE -- P2E-001..008 all done; backend 2201 passed / 11 skipped, Vitest 256,
    Playwright 43. GATE-009 (PDF conversion has confidence/reporting) PASS.
- Phase 10 (Translation MVP), 2026-10-06 -- docs/translation/README.md:
  - `phase-10a-translation-core` (`a5a341c`) -- TRAN-001 segments + tag protocol (<mN>, <xN/>, <br/>), TRAN-002
    providers (AITranslator batched + untrusted wrapper; PseudoTranslator), TRAN-003 cross-language validation (tags,
    digit groups, %, units by measure, identifiers, locked glossary, length). 20 tests, 11/11 mutations.
  - `phase-10b-translation` (`23b6c56`) -- TRAN-004 Document.glossary; TRAN-005 POST /documents/{id}/translate ->
    replace_content proposals (accept checks the block is unchanged, keeps id/style/provenance); TRAN-006 POST
    /jobs/translate-document -> new linked document (translatedFrom, copied pictures, translation report); TRAN-007
    language detection + GET/PUT language; TRAN-008 Превод panel; TRAN-009 translation characters counted + reserved;
    TRAN-010 tests (API 9, extra 3, Vitest +11, e2e 2), 9/9 mutations.
  - Phase 10 gate: COMPLETE; backend 2250 passed / 11 skipped, Vitest 267, Playwright 45. GATE-010 and GATE-011 PASS.
  - TRANSLATION_PROVIDER: "ai" by default (needs the Anthropic key, like every AI feature); the E2E server uses "pseudo".
- Phase 11 (FontResolver + multilingual rendering), 2026-10-07 -- docs/fonts/README.md:
  - `phase-11-fonts` (`ad6887f`) -- FONT-001 fontTools catalogue (coverage by script, metrics, fsType); FONT-002
    deterministic FontResolver; FONT-003 HarfBuzz shaping (uharfbuzz), own UAX#9 bidi (`app/bidi.py`, registered as
    reportlab's `rlbidi` in `app/__init__.py`), `export/rtl.py` RtlParagraph (reportlab 5.0.1 leaves bidi off for shaped
    or mixed-font paragraphs), notes export.pdf.script (undrawable characters) and export.pdf.text_layer (Devanagari/Thai);
    read-back via pdfminer for right-to-left documents; FONT-004 Word per-script rFonts/lang/rtl/bidi; FONT-006
    tests/test_multilingual.py 29, 11/11 mutations. New deps uharfbuzz 0.56.3, fonttools 4.66.1 (locks regenerated).
    Backend 2279/11, Vitest 267, Playwright 45.
  - TRACKER NOT YET UPDATED for Phase 11: the workbook was open in Excel (~$ lock). Run
    `bash tools/tracker/queued_phase11.sh` once it's closed, then excel_recalc.py, commit, push, and delete the script.
  - CI watch: the expected-loss manifests' linux PDF claims for a08/a09/a11 were recorded before Phase 11; CI may need
    `python -m scripts.export_expected_losses` run on Linux (it keeps other platforms' claims).
- Phase 12 (Format by Example hardening), 2026-10-07 -- docs/formatting/README.md "Format by Example":
  - `phase-12-format-by-example` (`fb0e4de`) -- FMT-001 `StyleSystem.structure` (table border/header shading/bold that
    most tables share, list levels most items use, heading numbering), set by `formatting/structure.py` when a
    template is applied; FMT-002 the AI's heading levels used only when they fit the headings' sizes
    (`semantic_labeling._sizes_agree`); FMT-003 `POST /documents/{id}/style-preview` (`formatting/style_preview.py`,
    engine on a copy, nothing saved) and the Templates panel's Now / With this look. tests/test_format_by_example.py 6,
    TemplatesPanel.test.tsx 2, 9/9 mutations. Backend 2289/11, Vitest 269, Playwright 45.
  - TRACKER NOT YET UPDATED for Phase 12 either: run `bash tools/tracker/queued_phase12.sh` after queued_phase11.sh.
- Phase 13 (Document Health 2.0), 2026-10-07 -- README "Document Health 2.0":
  - `phase-13-document-health` (`d673602`) -- HLTH-001 nine more checks in `formatting/health.py` (alt_text, hidden_text,
    language, unsupported, sections, lists, empty_paragraphs -- moved out of spacing --, layout, duplicated_formatting);
    HLTH-002 `formatting/health_fixes.py`: `POST /documents/{id}/health/fixes` adds ProposedChange source="health"
    (elementHash = block fingerprint, checkId); `proposals.accept` applies it only to the unchanged block (delete or
    replacement), one undo step; `prune_stale` drops health fixes for changed blocks on save. HealthCheck.fixes counts
    them. Frontend: Health panel propose per check / all, ProposalsList health rendering, status bar "N fixes to review"
    apart from AI changes. tests/test_health_2.py 15, HealthPanel.test.tsx 2, e2e/health.spec.ts; 12/12 mutations.
    Backend 2308/11, Vitest 272, Playwright 46. HLTH-003 (AI explanations, P2) open.
  - TRACKER NOT YET UPDATED: run `bash tools/tracker/queued_phase13.sh` after the Phase 11 and 12 scripts.
- Phase 14 (Review Changes), 2026-10-07 -- README "Review Changes":
  - `phase-14-review-changes` (`ed68af3`) -- REV-002 `editor/panels/ReviewPanel.tsx` (rail tab Преглед): all waiting
    proposals grouped by category, filter chips, source tags, Accept all per category except content; ProposalsList
    now exports ProposalCard + useProposalActions. REV-003: `engine.apply_operations(..., accepted=False)` refuses
    insert/delete/move (UnacceptedContentChangeError); only `proposals.accept` passes accepted=True;
    `proposals.accept_category` + `POST /documents/{id}/proposals/accept` (one undo step, 422 content_needs_review,
    `changes_text` keeps word-changing proposals of other categories waiting; translations excepted).
    tests/test_review_changes.py 6, ReviewPanel.test.tsx 4, e2e/review.spec.ts; 8/8 mutations. Backend 2317/11,
    Vitest 276, Playwright 47. AUD-05 note queued. REV-004/005 (P2) open.
  - TRACKER NOT YET UPDATED: run `bash tools/tracker/queued_phase14.sh` after the Phase 11-13 scripts.
- Phase 16a (accessibility), 2026-10-07 -- README "Accessibility":
  - `phase-16a-accessibility` (`21611e8`) -- FEAT-010 `formatting/accessibility.py` (7 checks, ids a11y_*,
    reuses health detectors; WCAG contrast), `GET /documents/{id}/accessibility`, Health panel Accessibility section
    (HealthPanel's CheckList is shared). FEAT-011 `e2e/accessibility.spec.ts` (axe-core 4.13.0 pinned; serious/critical
    = failure) with the fixes it needed. tests/test_accessibility.py 11; 11/11 mutations. Backend 2331/11, Vitest 277,
    Playwright 49.
  - TRACKER NOT YET UPDATED: run `bash tools/tracker/queued_phase16a.sh` after the Phase 11-14 scripts.
- Phase 16b (observability), 2026-10-07 -- docs/operations/README.md:
  - `phase-16b-observability` (`59cea2a`) -- OBS-002 `app/observability.py` ContextFilter (operation_id, job_id on
    every record), operation = the request id, carried into jobs as payload.operationId; OBS-001 metrics registry
    (Counter/Histogram, Prometheus text) at `GET /api/metrics` for the `METRICS_TOKEN` bearer; route labels rebuilt
    from path params (`route_template`: FastAPI 0.141's included routers don't expose the full template).
    tests/test_metrics.py 5; 11/11 mutations. Backend 2336/11; Playwright 48 + 1 flaky.
  - Flaky: e2e kept-blocks "a paragraph deleted in the editor stays deleted" once left "Underlined twi" (Shift+Home
    didn't select before the Backspaces); 6/6 on rerun. Harden it if it recurs (wait for the caret / select by drag).
  - TRACKER NOT YET UPDATED: run `bash tools/tracker/queued_phase16b.sh` after the earlier queued scripts.
- Phase 17a/18a, 2026-10-07:
  - `phase-17a-performance-gates` (`570a2da`) -- TEST-041 `scripts/perf_gate.py` + `docs/performance/gates.json` + CI job
    "Performance gate" (base and head on one runner). First run (23b6c56 vs branch) caught PDF export 500 blocks +66%
    (FontResolver's per-character script lookup); fixed (lru_cache on `language._script`, one-run fast path in
    `font_resolver.resolve`), rerun passed 0.377 vs 0.385 s (`docs/performance/gate-2026-10-07.md`).
  - `docs-011` (`88f66f3`) -- docs/pdf, docs/deployment, docs/README.md index (DOCS-011 complete).
  - `docs-010` (`95873d8`) -- `docs/final-production-readiness.md`, the 16-section final report.
  - INFRA-010 BLOCKED: no Docker on this machine (virtualization off in BIOS), no hosting target.
  - TRACKER NOT YET UPDATED: run `queued_phase17a.sh` and `queued_phase18a.sh` after the earlier queued scripts.
- Phase 18b (release audit), 2026-10-07:
  - Word gate rerun (tools/word, Word not running): 60/60 open without repair, every count identical to 2026-10-06's
    (results in the scratchpad: release_word.txt, release_counts.json; package check none). GATE-006 evidence.
  - Dependency audit as CI runs it: werkzeug 3.1.8 CVE-2026-102598 (dev lock, via moto), sharp <0.35.5 and
    source-map-js 1.2.1 (npm high, production) -> fixed in `f185825` (uv --upgrade-package werkzeug; npm audit fix,
    patch bumps); both audits clean; moto tests 16, Vitest 277, Playwright 49.
  - Gates queued (`tools/tracker/queued_phase18b.sh`): PASS 001-003, 005-007, 012, 014, 015 (008-011 earlier);
    004 and 013 NOT_EVALUATED pending CI's PostgreSQL job. docs/final-production-readiness.md sections 13-15 updated.
- P2 work (every P0/P1 done but INFRA-010), 2026-10-07:
  - `docx-015a` (`4a3c2ca`) -- a last section on an unlisted paper size keeps it: Document.lastSection width/height
    (parser), editor basePage, PDF, Word export (`_section_layout`); report `docx.page_setup.size` (preserved);
    `engine._drop_custom_page_size` in recompute_styles clears it once a PAGE_SIZE/ORIENTATION rule above the source
    tier exists. tests/test_sections.py +2, sectionPages.test.ts +1; 4/4 mutations. Backend 2346/11, Vitest 278,
    Playwright 49. Tracker: `tools/tracker/queued_docx015a.sh`.
  - DOCX-015B DEFERRED (reason in `tools/tracker/queued_docx015bc.sh`: columns need editor/pagination.ts itself to lay
    blocks into columns and pages together; the technique -- flex column, margins add up, decorations move/pull blocks --
    is proven by DOCX-018A's editor/floatWrap.ts. The first reason given, margin collapsing, was wrong: corrected).
  - `docx-015c` (`6282fd3`) -- PUT /documents/{id}/section-text (section break kinds; last section's first/even kinds,
    recorded in Document.lastSectionEdited for exports into the original); editor overlay: double-click a page's
    header/footer, "Same as previous"; `sectionHeaders.chromeTarget`. Golden JSON regenerated (new field). Backend
    2352/11, Vitest 280, Playwright 50; 4/4 mutations. Tracker: `queued_docx015bc.sh`.
  - `docx-017a` (`b7573d6`) -- table styles' conditional formats (bands with their sizes, first/last row and column,
    corners) resolved per cell in Word's order from tblLook (`docx_tables.position_look`), under own shading/run
    formatting; only borders by position reported. Golden 16-table-engine regenerated (white header text). Backend
    2355/11, Vitest 280, Playwright 50; 6/6 mutations. Tracker: `queued_docx017a.sh`.
  - `docx-018a` (`eb9009b`) -- floating pictures text wraps around: side at import (`docx_pictures.float_side`,
    ImagePlacement.side); PDF wraps line by line (ImageAndFlowables); the editor (flex column: no CSS floats) wraps block
    by block (`editor/floatWrap.ts`). Manifests a04/a13/17 + golden 17 re-recorded. Backend 2370/11, Vitest 281,
    Playwright 51; 5/5 mutations.
  - TRACKER UP TO DATE (2026-10-07): Excel closed the workbook; every queued script applied in order (DOCX-018A's
    went in first, out of order -- harmless: run numbers only), excel_recalc 3787 formulas, 0 errors; queue scripts
    deleted. Tracker: 159/187 done; P0 open 0; P1 open 1 (INFRA-010, blocked).
  - `docx-018c` (`5c026b5`) -- an SVG picture's PNG copy named: import note `docx.image.svg` (lossy), and the export's
    rewritten-blocks report names "SVG pictures (written as their PNG copy)" (`_lost_in`, SVG_BLIP in docx_pictures.py).
    a04 manifest re-recorded. Backend 2371/11; 2/2 mutations. Tracker updated directly.
  - `docx-019a` (`d0e90fe`) -- text boxes as boxes: ElementType.TEXT_BOX + TextBoxContent; importer `_text_box` (blocks
    as a cell's), editor `editor/textBox.ts` (floatWrap handles floating boxes), PDF `_build_text_box`, Word export
    `_add_text_box` (scratch cell -> txbxContent, `_float`). Word gate 60/60 (a09 keeps its boxes). a09 fidelity manifest
    + golden JSON re-recorded. Backend 2377/11, Vitest 284, Playwright 52; 5/5 mutations.
  - `docx-020a` (`147bece`) -- header fields beyond page numbers: a header/footer field the policy allows is read as
    `{FIELD instr|result}` (`formatting/header_fields.py`; `_as_field` in docx_styles); pages, preview and PDF show the
    result (`fillPageFields` in `editor/headerFields.ts`, pdf `_fill`); a Word export writes the field with its result
    (`_write_page_text`/`_append_field`). Refused, `|{}`-holding and past-500-character ones become their result.
    Backend 2383/11, Vitest 286, Word gate 60/60 unchanged; 2/2 mutations; Word sees STYLEREF/DATE/PAGE/DOCPROPERTY.
  - `docx-022a` (`1e15388`) -- tracked changes rejected + deleted paragraph marks: `parsers/docx_revisions.py`
    (`reject_all` -- matches Word's Reject All, measured on a synthetic file and a07; `join_deleted_marks` -- the accepted
    reading joins a paragraph whose mark was deleted into the next, as Accept All does). Choice "rejected": the service
    re-reads the kept file with them rejected and keeps that file (undoable; 409 `edits_would_be_lost` until
    `discardEdits`, the UI asks). docx_source skips deleted rows. Backend 2389/11, Vitest 290, Playwright 53, Word gate
    60/60; 8/8 mutations. Also `dc5a515`: the float-wrap e2e test polls (it flaked 1 in 3).
  - `docx-023a` (`081c993`) -- nested content controls: inline ones in cell paragraphs, list items and text-box
    paragraphs as `control` fragments (`_Importer._controls`; `preservedAttributes["ooxml"]` on TableCell/ListItem/
    paragraph blocks); ones around cells/rows as `preservedAttributes["controls"]` (outermost first, with a group) on
    TableCell/TableRow, wrapped back by `_wrap_in_controls`; `keep_preserved` walks items/rows/cells. Rows inside a
    table-level control are now read (they were dropped). `docx_inline.control_written_back` = the one rule. Word: all
    controls back, opens clean; a08 8/8. Backend 2395/11, Vitest 290, Playwright 53, gate 60/60; 11/11 mutations.
  - `test-021a` (`9760557`) -- BLOCKED: CI's backend job now records the Linux PDF claims after its tests and uploads
    them (artifact `expected-loss-linux`); `scripts/merge_expected_losses.py DIR` takes only those claims. Left: download
    one run's artifact, merge, commit (needs GitHub; no Linux here).
  - `docx-029` (`0b01b81`) -- restyled blocks copied where nothing conflicts: stamp keeps `Document.sourceStyles`;
    `provenance.look_changes` (look-only change, changed properties); `docx_export._RestyleCopy` (own look apart from
    kind as imported, Word style = kind's written style, own pPr/rPr sets none of the changes). a07 fidelity manifest
    19->7 tracked marks. Backend 2404/11, Vitest 290, Playwright 53, gate 60/60; 7/7 mutations.
  - `perf-005` (`4981bdb`) -- typing in long documents: `e2e/perf-typing.spec.ts` (PERF_TYPING=1; _PROFILE, _TRACE) measures
    keydown->next frame in a production build. Fixes: `editor/blockDom.ts` (one walk instead of quadratic nodeDOM in
    pagination/floatWrap), `editor/textEdit.ts` (decorations mapped on text-only edits; layout waits 300 ms while
    typing). 5k p50 145->47 ms; 12k ~185->130 ms; the rest (PM per-update walk + Chrome relayout of 12k children) is
    PERF-005A (P3). Vitest 296, Playwright 53.
  - `pdf-020` (`bd1a3bf`) -- PDF page operations service: `app/services/pdf_pages.py` + `app/api/pdf.py`
    (POST /api/v1/pdf/info|pages|split|merge; no catalogue copied, unsafe actions dropped; 422 `pdf_pages`). No UI yet.
    test_pdf_pages.py 13, 12/12 mutations. Backend 2424/11.
  - `p2e-020` (`8602607`) -- frames hook: `app/formatting/frames.py` (`frame_of`: Word anchors, layout-focused PDF boxes;
    derived, nothing stored) + `docs/architecture/layout-preserving.md`. Follow-up P2E-021 (P3). test_frames.py 5, 5/5.
  - `font-005` (`c304ee5`) -- editor font stacks = the PDF export's fallbacks: `fonts.METRIC_COMPATIBLE`/`fallback_stack`
    (resolver tries Carlito/Caladea/Liberation/Arimo/Tinos/Cousine first), `frontend/editor/fontFallbacks.json` written
    by `scripts/export_font_fallbacks.py` (currency test). Backend 2434/11, Vitest 299, Playwright 53.
  - `hlth-003` (`ae65d6d`) -- AI explains Health findings, never scores: `app/ai/health_explanation.py`, POST
    `.../health/explain` (no score sent; rating answers dropped; unknown check voids answer; metered), Health panel
    "Explain". 8/8 mutations; security suite lists the route. Backend 2442/11, Vitest 301.
  - `rev-004` (`a1c91e8`) -- Repair document: `formatting/repair.py` (GET .../repair: Health findings by the brief's
    six kinds + malformed input), new `broken_tables` check/fix (`formatting/table_repair.py`), Преглед panel
    `RepairSection` (propose -> proposals -> accept). 11/11 mutations; e2e repair. Also `858c8ec`: deflaked the
    account-deletion rate-limit test (minute window race). Backend 2453/11, Vitest 303, Playwright 54.
  - `rev-005` (`842999c`) -- clean copy: `formatting/clean_copy.py`, POST .../clean-copy, Проверка panel
    `CleanCopySection` (5 explicit actions, none preselected; new document, own pictures, no source file; 422
    tracked_changes / nothing_chosen). 11/11 mutations. Backend 2460/11, Vitest 305, Playwright 55.
  - `feat-001` (`fe4a89d`) -- batch formatting: POST /jobs/batch-format + GET /jobs/batches/{id} (format job per document,
    batchId in payload; template only; maxBatchJobs, batch_jobs counted), documents list checkbox column + `BatchBar`.
    e2e server's free plan gets 20 batches. 9/9 mutations. Backend 2472/11, Vitest 307, Playwright 56.
- Phase 2 (AI fidelity + destructive-operation review): COMPLETE (gate 2026-09-27; CORE-005 deferred with reason).
  - `phase-02a-ai-fidelity-check` (`78f5c8f`), AI-001..AI-004:
    - `app/fidelity/text_check.py::check_text` compares an AI answer with its source token by token, in order.
      Tokens are words, numbers with their sign, decimals, separators and percent sign, and every punctuation mark.
      Typographic variants and line-start list/heading marks don't count.
    - Differences are classified: number, unit, negation, sentence, duplicate, reordered, punctuation, words.
      Numbers and units are protected facts. `changed_numbers` covers text whose words may rightly change.
    - Structure analysis refuses any answer that alters its piece. It retries once, then splits that piece alone
      into paragraphs, and logs what changed without the text.
    - This replaces the 20%-unknown-words check (AUD-02).
  - `phase-02b-ai-proposals` (`5f67f5a`), AI-005..AI-007 and REV-001:
    - instruction operations are sorted by what they touch;
    - styles and page breaks apply at once (after the formatting pass, which used to drop a style set on one
      element);
    - inserting, deleting or moving text becomes a `ProposedChange` on `Document.proposals`, with what it would
      change;
    - the user accepts it (validated against the current document, one undoable step, 409 when it no longer fits)
      or rejects it;
    - the Instructions panel lists the proposals, and the status bar counts them;
    - the E2E server has a scripted AI (`backend/scripts/e2e_ai.py`) for two fixed instructions.
  - `phase-02c-ai-budget` (`03f6a44`), AI-008:
    - every job and every request that calls the AI gets an allowance: `AI_CALLS_PER_JOB` calls and
      `AI_SECONDS_PER_JOB` seconds (`ai/budget.py`);
    - past it, calls are refused at once, and a running call is cancelled at the deadline;
    - structure analysis then splits the rest into paragraphs, with a note in the import report;
    - retries are capped at 0–3.
  - `phase-02d-prompt-injection` (`8253a6a`), AI-009 and SEC-018:
    - every AI task fences the document in a per-call tag, marked as data;
    - every AI answer field that reaches a document is bounded (`ai/schemas.py`) — before, a structure answer could
      store any document type, a heading level 99 or a code language with quotes;
    - `tests/test_prompt_injection.py` covers hostile documents.
  - Phase 2 gate (`76c50ee`, docs only):
    - suites: backend 817 / 1 skipped, Vitest 117, Playwright 20;
    - browser check in the throwaway stack:
      - "make the title red and delete “This draft paragraph”" made the title red at once;
      - the paragraph was kept and listed under Changes to review, with the notice and the status-bar count;
      - Accept removed it, and a reload kept it removed with nothing pending;
    - CORE-005 (the general command model) is DEFERRED: proposals implement validate, preview, apply and undo;
      the shared abstraction waits for a second kind (translation, repair, batch).
  - Tracker: up to date (the Phase 2 and 3a updates queued while the workbook was open in Excel were applied).

## LAST VERIFIED

- 2026-10-01 — password change (ACCT-004): backend 1795 passed / 1 skipped; Vitest 240 passed; Playwright 34 passed; tsc and eslint clean;
  7/7 mutations killed. ACCT-004 VERIFIED.
- 2026-10-01 — e-mail verification (ACCT-003): backend 1790 passed / 1 skipped; Vitest 237 passed; Playwright 33 passed; tsc and eslint
  clean; 8/8 mutations killed. ACCT-003 VERIFIED.
- 2026-10-01 — password reset (ACCT-002): backend 1781 passed / 1 skipped; Vitest 233 passed; Playwright 32 passed; tsc and eslint clean;
  13/13 mutations killed. ACCT-002 VERIFIED.
- 2026-10-01 — e-mail sender (ACCT-001): backend 1768 passed / 1 skipped; 7/7 mutations killed. ACCT-001 VERIFIED.
- 2026-10-01 — atomic plan limits (PLAN-003, documents, templates, storage): backend 1762 passed / 1 skipped; the race tests fail without the
  hold; 6/6 mutations killed. PLAN-003 stays IN_PROGRESS (AI operations after JOB-001).
- 2026-10-01 — delta autosave (PERF-003): backend 1758 passed / 1 skipped; Vitest 228 passed; Playwright 31 passed; tsc and eslint clean;
  16/16 mutations killed; browser check in the throwaway stack. PERF-003 VERIFIED.
- 2026-10-01 — Phase 4 gate: backend 1734 passed / 1 skipped; Vitest 217 passed; Playwright 31 passed; tsc and eslint clean; every
  Word fixture as an upload keeps it, exported two ways, opens in Word (60 files) with what it holds but the known
  new-file differences; package check clean. Phase 4 COMPLETE.
- 2026-10-01 — limits (SEC-013): backend 1730 passed / 1 skipped; 4/4 mutations killed. SEC-013 VERIFIED.
- 2026-10-01 — error envelope (SEC-019): backend 1725 passed / 1 skipped; the envelope sweep 61 tests; 3/3 mutations killed.
  SEC-019 VERIFIED.
- 2026-09-30 — SVG (SEC-017): `pytest -m security` 441 passed; the two header layers each redundant, both needed
  together (mutation). SEC-017 VERIFIED.
- 2026-09-30 — external targets (SEC-016): backend 1658 passed / 1 skipped; Playwright 31 passed; 8/8 mutations killed; fixture outputs
  unchanged; Word opens the cleaned file and its export. SEC-016 VERIFIED.
- 2026-09-30 — security regression suite (TEST-030): `pytest -m security` 433 passed; `-m "not security"` 1223 passed / 1 skipped;
  5/5 mutations killed. TEST-030 VERIFIED; Phase 4 P0s all DONE.
- 2026-09-30 — field policy (SEC-015): backend 1550 passed / 1 skipped; Playwright 31 passed; 11/11 mutations killed; fixture outputs
  unchanged; Word opens the cleaned file and its export with DATE and PAGE only. SEC-015 VERIFIED.
- 2026-09-30 — link policy (SEC-014): backend 1518 passed / 1 skipped; Vitest 217 passed; Playwright 31 passed; tsc and eslint clean;
  14/14 mutations killed. SEC-014 VERIFIED.
- 2026-09-30 — picture limits (SEC-012): backend 1480 passed / 1 skipped; Vitest 179 passed; Playwright 31 passed; tsc and eslint
  clean; 16/16 mutations killed (+ the autosave loop fix). SEC-012 VERIFIED.
- 2026-09-30 — malformed PDFs + text XML can't hold (SEC-011, SEC-023): backend 1455 passed / 1 skipped; the PDF corpus 45 tests;
  mutation check 17/17 killed; OpenAPI unchanged. SEC-011 and SEC-023 VERIFIED.
- 2026-09-30 — malformed Word files (SEC-010): backend 1410 passed / 1 skipped; the new corpus 110 tests; mutation check 10/10
  killed. SEC-010 VERIFIED.
- 2026-09-30 — Phase 3 gate: backend 1300 passed / 1 skipped; Vitest 177 passed; Playwright 31 passed; tsc and eslint clean; every Word
  fixture exported two ways opens in Word (60 files), comment threads, content controls, notes and heading numbers
  as in the file; the a06 regression the gate found is fixed and covered. Phase 3 COMPLETE.
- 2026-09-30 — numbered headings stay numbering (DOCX-016A): backend 1298 passed / 1 skipped; Vitest 177 passed; Playwright 31 passed;
  tsc and eslint clean; Word: a03's headings 1, 2, 2.1, 3 as numbering in all four exports, the edited one with one
  number. DOCX-016A VERIFIED.
- 2026-09-30 — footnotes and endnotes stay notes (DOCX-024): backend 1290 passed / 1 skipped; Vitest 172 passed; Playwright 30 passed;
  tsc and eslint clean; Word: a10's 3 footnotes and 2 endnotes back after their sentences, into the original and in
  a new file, edited ones as edited; r01's footnote. DOCX-024 VERIFIED.
- 2026-09-30 — content controls of every kind back with their properties (DOCX-023): backend 1280 passed / 1 skipped; Vitest
  172 passed; Playwright 30 passed; tsc and eslint clean; Word: a08's 8 controls and 2 form fields as in the file, edited
  ones as edited. DOCX-023 VERIFIED.
- 2026-09-30 — tracked changes kept for Word or accepted as chosen (DOCX-022): backend 1270 passed / 1 skipped; Vitest 172 passed;
  Playwright 30 passed; tsc and eslint clean; Word: a07's revisions, accept-all and reject-all as in the file.
  DOCX-022 VERIFIED.
- 2026-09-30 — deleted blocks stay deleted (DOCX-028B): backend 1261 passed / 1 skipped; Vitest 166 passed; Playwright 29 passed; tsc and
  eslint clean; OpenAPI and frontend types regenerated. DOCX-028B VERIFIED.
- 2026-09-30 — comment threads (DOCX-021): backend 1252 passed / 1 skipped; Vitest 166 passed; Playwright 28 passed; tsc and eslint
  clean; Word showed a07's copied, rewritten and new-file exports' reply under its comment and the resolved one
  resolved, and a comment over three paragraphs over all three. DOCX-021 VERIFIED.
- 2026-09-30 — fields running across paragraphs (DOCX-020): backend 1233 passed / 1 skipped; Vitest 166 passed; Playwright 28 passed; tsc
  and eslint clean; Word updated the rewritten a06/r01 exports' TOC, bibliography and citation with no errors.
  DOCX-020 VERIFIED.
- 2026-09-30 — drawings kept in rewritten blocks (DOCX-019): backend 1227 passed / 1 skipped; Vitest 166 passed; Playwright 28 passed; tsc
  and eslint clean; Word opened the rewritten a09 export. DOCX-019 VERIFIED.
- 2026-09-30 — the true fidelity test (TEST-022) and its three fixes: backend 1224 passed / 1 skipped; Vitest 166 passed; Playwright
  28 passed; tsc and eslint clean. TEST-022 VERIFIED.
- 2026-09-30 — expected-loss manifests (TEST-021): backend 1075 passed / 1 skipped. TEST-021 VERIFIED.
- 2026-09-30 — Word-authored fixtures (TEST-020): backend 1037 passed / 1 skipped; secret scan clean (498 files). TEST-020 VERIFIED.
- 2026-09-30 — no silent autolink (DOCX-026): backend 996 passed / 1 skipped; Vitest 166 passed; Playwright 28 passed; tsc and eslint
  clean. DOCX-026 VERIFIED.
- 2026-09-29 — source styles over defaults (FMT-004): backend 993 passed / 1 skipped; Vitest 164 passed; Playwright 27 passed; tsc and
  eslint clean. FMT-004 VERIFIED.
- 2026-09-29 — pictures in list items (DOCX-027): backend 990 passed / 1 skipped; Vitest 164 passed; Playwright 27 passed; tsc and eslint
  clean. DOCX-027 VERIFIED. Seen in the browser and in the rendered PDF (golden 17's list).
- 2026-09-29 — pictures (DOCX-018): backend 987 passed / 1 skipped; Vitest 164 passed; Playwright 27 passed; tsc and eslint clean. DOCX-018
  VERIFIED. Seen in the browser (the golden page: crop, flip-then-turn, turned room) and in the PDF (rendered).
- 2026-09-29 — table cells' contents, floating tables (DOCX-017 part 1b): backend 968 passed / 1 skipped; Vitest 158;
  Playwright 26; tsc and eslint clean. DOCX-017 VERIFIED.
- 2026-09-29 — table geometry (DOCX-017 part 1a): backend 959 passed / 1 skipped; Vitest 155; Playwright 25; tsc and
  eslint clean.
- 2026-09-29 — list labels in the editor (DOCX-016 part 3): backend 953 passed / 1 skipped; Vitest 152; Playwright 25;
  tsc and eslint clean. DOCX-016 VERIFIED.
- 2026-09-29 — PDF list labels (DOCX-016 part 2): backend 953 passed / 1 skipped; Vitest 148; Playwright 24.
- 2026-09-29 — list levels (DOCX-016 part 1): backend 951 passed / 1 skipped; Vitest 148; Playwright 24; tsc and
  eslint clean.
- 2026-09-29 — pages per section in the editor (DOCX-015 part 3b): backend 937 passed / 1 skipped; Vitest 144;
  Playwright 24; tsc and eslint clean. DOCX-015 VERIFIED.
- 2026-09-29 — the last section's layout (DOCX-015 part 3a): backend 937 passed / 1 skipped; Vitest 140;
  Playwright 23; tsc and eslint clean.
- 2026-09-29 — headers and footers per section (DOCX-015 part 2): backend 936 passed / 1 skipped; Vitest 140;
  Playwright 23; tsc and eslint clean.
- 2026-09-27 — PDF sections (DOCX-015 part 1b): backend 920 passed / 1 skipped; Vitest 132; Playwright 22; tsc and eslint
  clean.
- 2026-09-27 — section breaks (DOCX-015 part 1a): backend 919 passed / 1 skipped; Vitest 132; Playwright 22; tsc and
  eslint clean.
- 2026-09-27 — borders and tab stops (DOCX-014 part 2): backend 913 passed / 1 skipped; Vitest 129; Playwright 22;
  tsc and eslint clean.
- 2026-09-27 — paragraph formatting (DOCX-014 part 1): backend 903 passed / 1 skipped; Vitest 129; Playwright 22;
  tsc and eslint clean.
- 2026-09-27 — copy reports + language (DOCX-013 part 2, FID-007): backend 894 passed / 1 skipped; Vitest 129;
  Playwright 22; tsc and eslint clean.
- 2026-09-27 — character formatting (DOCX-013 part 1): backend 888 passed / 1 skipped; Vitest 128; Playwright 22; tsc and
  eslint clean.
- 2026-09-27 — hidden text (DOCX-025): backend 876 passed, 1 skipped; Vitest 125; Playwright 22 (new
  `e2e/hidden-text.spec.ts`); tsc and eslint clean.
- 2026-09-27 — original blocks (DOCX-028): backend 869 passed, 1 skipped; Vitest 119; Playwright 21 (new
  `e2e/kept-blocks.spec.ts`); tsc and eslint clean; all 13 golden documents copied into sound packages.
- 2026-09-27 — source package + patch writer: backend 838+ / 1 skipped; Vitest 117; Playwright 20; every golden
  export (fresh and into its original) passes the package check.
- 2026-09-27 — Phase 2 gate: backend 817 / 1 skipped, Vitest 117, Playwright 20; browser check of Changes to review
  (accept → gone after reload).
- 2026-09-27 — prompt injection: backend 817 passed / 1 skipped (`tests/test_prompt_injection.py`: 12).
- 2026-09-27 — AI budget: backend 805 passed / 1 skipped (`tests/test_ai_budget.py`: 6).
- 2026-09-27 — AI proposals: backend 799 passed / 1 skipped; Vitest 117; Playwright 20 (new
  `e2e/proposals.spec.ts`: instruct → the deletion waits → accept → reload → reject → reload); tsc and eslint
  clean.
- 2026-09-27 — AI fidelity check: backend 789 passed / 1 skipped (`tests/test_ai_fidelity.py`: 36).

- 2026-09-27 — Phase 1 gate:
  - backend 754 passed / 1 skipped; Vitest 113; Playwright 19; tsc and eslint clean.
  - browser check in the throwaway stack:
    - a Markdown picture was named on import;
    - a pasted centred line, a 160 px picture and a titled link survived a reload (centred; width 24.9%; title
      kept);
    - an hsl colour was named "not kept" while editing and was gone after the reload.

- 2026-09-27 — editor direct formatting + rule values: backend 749 passed / 1 skipped; Vitest 109; Playwright 19
  (new `e2e/direct-formatting.spec.ts`: paste → reload keeps centred line and 50% picture; hsl colour named); tsc,
  eslint clean.
- 2026-09-27 — import detections: backend 713 passed / 1 skipped; Vitest 84; tsc and eslint clean. Probe confirmed the
  section-break bug before the fix (continuous → page break) and the new test pins Word's behaviour.
- 2026-09-27 — export report: backend 694 passed / 1 skipped; Vitest 84; Playwright 18; tsc and eslint clean.

## WHAT WAS CHANGED

- Backend: `services/auth_service.py` (`change_password`); `api/auth.py` (`PUT /password`); `schemas/auth.py`
  (`ChangePasswordRequest`); `mail/messages.py` and `services/account_mail.py` (`kept_one`).
- Frontend: `components/AccountSettings.tsx`, `app/settings/account`, `components/AccountMenu.tsx` (the link),
  `services/api/auth.ts` (`changePassword`); generated types.
- Tests: `backend/tests/test_password_change.py`; `frontend/components/AccountSettings.test.tsx`;
  `e2e/auth.spec.ts`.
- Docs: `README.md`, `docs/security/README.md`, `docs/testing/README.md`, `docs/architecture/final-audit.md`.

## WHAT PASSED

- Backend 1795 passed / 1 skipped; Vitest 240; Playwright 34; tsc and eslint clean; mutations 7/7.

## WHAT FAILED

- Nothing open.

## WHAT REMAINS

- Phase 4: SEC-020 (P2, a nonce-based CSP for the Next.js app); SEC-021 needs Boril.
- Phase 5: PERF-001, JOB-001, PERF-004, PERF-002 and PERF-006 with the cloud session (review and merge when Boril
  reports its result); PERF-007's job timeouts with JOB-001; PERF-005 and PERF-008 (P2).
- Phase 6: PLAN-003's AI operations (after JOB-001); ACCT-005..007, PLAN-001, PLAN-002, PLAN-004, PLAN-005,
  STOR-001; TEST-031 (the concurrency tests on PostgreSQL in CI).
- Phase 3's P2/P3 follow-ups: DOCX-015A..C, DOCX-016B, DOCX-017A..B, DOCX-018A..C, DOCX-019A, DOCX-020A,
  DOCX-022A, DOCX-023A, DOCX-027A, DOCX-029, TEST-021A.
- Phases 7–18 as listed in the tracker.
- Needs Boril (never guess): Stripe account and prices, e-mail provider credentials, Anthropic API key for real-model
  checks, hosting/deployment target, SEC-021 (sensitivity-label metadata in `корекции.docx` in public history),
  how long kept originals stay in storage.

## NEXT ACTION

- The tracker is current (no queued scripts). Every P0/P1 task is DONE except INFRA-010 (BLOCKED: no Docker on this
  machine; a deployment needs Boril's hosting target). GATE-004 and GATE-013 wait for CI's PostgreSQL job result.
- Continue with the P2 tasks in the tracker's order (`tracker.py show --open --priority P2`): next FEAT-002 (batch
  export: many documents to a zip; reuse the list selection and BatchBar); TEST-021A BLOCKED (CI artifact to merge),
  FEAT-001/002, OBS-003, TEST-043; DOCX-015B deferred (reason in
  the tracker). P3 after.
- Owner decisions waiting (final report, section 15): hosting target, Stripe account and prices, SMTP provider, a
  real Anthropic key and a real-document round, the OCR engine, fonts in the production image, retention periods and
  the sign-in delay, `style-src-attr 'unsafe-inline'`, PDF classifier thresholds, METRICS_TOKEN and who scrapes it.

## IMPORTANT WARNINGS

- Never mark a task VERIFIED/DONE without evidence and tests (the tool refuses anyway). DONE also needs the commit.
- The repository is PUBLIC (github.com/Drajeto07/claude). Run the secret scan before every push (it also flags MSIP
  sensitivity labels now; `корекции.docx` is the known hit, SEC-021). Never commit `backend/.env`, the user's
  stress-test DOCX, Office lock files, or any password the user pasted in chat.
- Excel/Word on this machine stamp `MSIP_Label_*` (organisation tenant ID) into Office files on save: the tracker
  tools strip them; scrub any Word fixture before committing.
- Tests must never touch the real Supabase database (`backend/.env` points at it); the test suite enforces this.
- `next build` (and so the E2E web server) type-checks test files too: run `npx tsc --noEmit` before E2E.
- The FastAPI dev server's auto-reload silently does nothing: restart it after backend edits.
- Browser checks: use the throwaway stack (preview configs `smartdoc-backend-throwaway` / `smartdoc-frontend-throwaway`,
  or `tools/dev/throwaway-*.ps1`) — never the `backend` config, which uses the real database. Stop them before E2E
  (same ports 8100/3100). The browser pane may be hidden: `find`/`form_input`/`get_page_text` work, clicks may not.
- Close the tracker in Excel before running `tracker.py` (it refuses to write while `~$` lock files exist).
  `excel_recalc.py` needs a Python with pywin32 (the `%TEMP%\sda` venv broke when Windows cleaned %TEMP% --
  make a venv with `pip install pywin32 openpyxl` wherever is handy).
- After changing the importer, regenerate `python -m scripts.export_golden_json` (backend) — the output is stable, so
  the diff shows only real changes.
- The resume reminder is a session-only cron job (hourly at :23, expires after 7 days); it only fires while this session is
  open and idle. Delete it (CronList + CronDelete) when the brief is finished or only Boril-input items remain.
