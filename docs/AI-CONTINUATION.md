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
  - Delegated to a cloud session (2026-10-01): Phase 5's PERF-001 (linear table export), JOB-001 (job safety),
    PERF-004 (bounded, compressed version history), PERF-002 + PERF-006 (benchmarks, UTF-8 JSON), each on its own
    `cloud/...` branch from the commit after this one, with a report in `docs/cloud-reports/<ID>.md`. Not
    delegated: PERF-003 (delta autosave changes the save protocol SEC-015's server-side guarantees rest on) and
    PERF-007 (overlaps SEC-013). When the branches arrive: fetch, review each diff against the rules in the cloud
    prompt, run the full suites here (Word checks for PERF-001's exports), apply any migration to Supabase only
    after review, then merge one by one into feature/smartdoc-production-hardening and update the tracker.
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

- The Phase 4 gate (`phase-04-complete`): `backend/tests/test_field_policy.py` pins AUTOTEXT, AUTOTEXTLIST and
  GLOSSARY as refused and STYLEREF as kept; `docs/security/README.md` names the building-block fields.
- Tracker: DOCX-018C added (the gate's finding).

## WHAT PASSED

- Backend 1734 passed / 1 skipped; Vitest 217; Playwright 31; tsc and eslint clean.
- Word: the 60 gate files open without repair, with what the cleaned original holds but the known new-file
  differences (CURRENT STATE, `phase-04-complete`).

## WHAT FAILED

- Nothing open. Found by the gate, not a regression: DOCX-018C (a Word SVG picture written anew becomes its PNG copy
  without a report).

## WHAT REMAINS

- Phase 4: SEC-020 (P2, a nonce-based CSP for the Next.js app); SEC-021 needs Boril.
- Phase 5 (performance + autosave + history): PERF-001, JOB-001, PERF-004, PERF-002 and PERF-006 with the cloud
  session (review and merge when Boril reports its result); PERF-003 here; PERF-007's job timeouts with JOB-001;
  PERF-005 (P2).
- Phase 3's P2/P3 follow-ups: DOCX-015A..C, DOCX-016B, DOCX-017A..B, DOCX-018A..C, DOCX-019A, DOCX-020A,
  DOCX-022A, DOCX-023A, DOCX-027A, DOCX-029, TEST-021A.
- Phases 6–18 as listed in the tracker.
- Needs Boril (never guess): Stripe account and prices, e-mail provider credentials, Anthropic API key for real-model
  checks, hosting/deployment target, SEC-021 (sensitivity-label metadata in `корекции.docx` in public history),
  how long kept originals stay in storage.

## NEXT ACTION

- Phase 5, PERF-003 (P1): delta autosave. Every save now sends the whole document (`PUT /content`: every element
  and the direct styles), so a save costs in step with the document's length. Plan: the editor sends what changed
  since the save the server last acknowledged -- elements added, changed (whole) and removed by id, and the order
  -- with the revision it is based on; the server applies that to its copy under every check a full save has
  (`keep_provenance`, `keep_preserved`, the model's validation, picture limits) and answers with the new revision.
  Past a threshold (most of the document changed, or a change a patch can't say), or on a revision conflict, the
  editor sends the whole document as now. Tests: a patch and a full save store the same document (over random
  edits); a patch can do nothing a full save can't (crafted fragments, an unknown id, a block moved under another
  parent); the conflict path; the size of a one-paragraph save in a long document. Keep clear of the cloud's files
  (`jobs/`, `services/version_history.py`, the table writer) so its branches merge cleanly.
- When Boril reports the cloud session's result: fetch the `cloud/*` branches; review each diff against the rules in
  the cloud prompt (scratchpad `cloud_prompt_phase5.md`); run the full suites here (Word checks for PERF-001's
  exports); apply JOB-001's and PERF-004's migrations to Supabase (with RLS) only after review; merge one by one
  into feature/smartdoc-production-hardening; update the tracker.

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
  `excel_recalc.py` needs a Python with pywin32 (e.g. `%TEMP%\sda\Scripts\python.exe`, the audit venv).
- After changing the importer, regenerate `python -m scripts.export_golden_json` (backend) — the output is stable, so
  the diff shows only real changes.
- The resume reminder is a session-only cron job (hourly at :23, expires after 7 days); it only fires while this session is
  open and idle. Delete it (CronList + CronDelete) when the brief is finished or only Boril-input items remain.
