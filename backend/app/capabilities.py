"""The capability matrix (brief §91): what the platform does with each document
feature -- import, edit in the editor, export, round trip -- and how the
fidelity report classifies it when it meets it. Data, not prose: the API serves
it, the fidelity report's feature keys point into it, and tests check that every
key the code reports is described here and that every "round trip: yes" has a
test behind it.

Support values:
  yes        kept as it was (and editable, for "edit");
  partial    kept with changes, or only some of it;
  preserved  kept out of sight and written back by the Word export;
  no         not kept;
  n/a        doesn't apply.
`policy` is what an import or export report says on meeting the feature;
not_detected means nothing is reported yet -- a known gap, named in `notes`."""

from typing import Literal

from pydantic import Field

from app.fidelity.report import FidelityPolicy
from app.models.base import ApiModel

Support = Literal["yes", "partial", "preserved", "no", "n/a"]
Area = Literal["docx", "pdf", "editor", "text"]


class Capability(ApiModel):
    id: str
    area: Area
    label: str
    importSupport: Support = Field(alias="import")
    edit: Support
    export: Support
    roundTrip: Support
    policy: FidelityPolicy
    # The fidelity report feature keys that describe this feature.
    features: list[str] = Field(default_factory=list)
    # Tests that prove what is claimed: "tests/<file>.py::<test>" or a frontend path.
    tests: list[str] = Field(default_factory=list)
    notes: str = ""

    model_config = {**ApiModel.model_config, "populate_by_name": True}


class CapabilityMatrix(ApiModel):
    capabilities: list[Capability]


_P = FidelityPolicy
_YES, _NOT_EDITABLE, _LOSSY, _UNSUPPORTED, _BLOCKED, _UNSEEN = (
    _P.DETECTED_PRESERVED,
    _P.DETECTED_NOT_EDITABLE,
    _P.LOSSY,
    _P.UNSUPPORTED,
    _P.BLOCKED,
    _P.NOT_DETECTED,
)

# (id, area, label, import, edit, export, round trip, policy, features, tests, notes)
_ROWS: list[tuple] = [
    # -- Word files ---------------------------------------------------------------------
    ("docx.text", "docx", "Paragraphs and headings", "yes", "yes", "yes", "yes", _YES, [],
     ["tests/test_golden_documents.py::test_01_simple", "tests/test_export_round_trip.py::test_structure_survives_a_docx_round_trip",
      "tests/test_fidelity_report.py::test_every_golden_document_imports_with_its_content_verified"],
     "Every word is checked on import (the content check) and on export (the file read back)."),
    ("docx.character_basic", "docx", "Bold, italic, underline, strikethrough, superscript, subscript", "yes", "yes", "yes", "yes", _YES, [],
     ["tests/test_docx_parser.py::test_bold_italic_strike_marks_are_captured", "tests/test_export_round_trip.py::test_character_formatting_survives_a_docx_round_trip"], ""),
    ("docx.character_style", "docx", "Font, size, colour and highlight on text", "yes", "yes", "yes", "yes", _YES, [],
     ["tests/test_docx_fidelity.py::test_character_formatting_that_varies_stays_on_the_text",
      "tests/test_export_round_trip.py::test_character_formatting_survives_a_docx_round_trip"], ""),
    ("docx.underline_variants", "docx", "Underline styles (double, thick, dotted, dashed, wavy); double strikethrough", "yes", "partial", "yes", "partial",
     _LOSSY, ["docx.underline_variant", "export.pdf.underline_style"],
     ["tests/test_docx_detect.py::test_each_unkept_feature_is_named_with_an_example", "tests/test_golden_documents.py::test_02_rich_text",
      "tests/test_character_formatting.py::test_a_word_export_writes_them_back_in_the_schemas_order",
      "frontend/editor/characterFormatting.test.ts"],
     "Kept (DOCX-013): double, thick, dotted, dashed and wavy underlines and a double strikethrough, through the editor (and "
     "Word's paste) and back into Word. Word's other styles show as the closest one (heavy lines at normal weight, dash-dot "
     "as dashed, words-only as a full underline), and that is reported. A PDF draws double and thick lines; dotted, dashed "
     "and wavy ones as plain lines, and says so. They can't be set from the toolbar yet."),
    ("docx.caps", "docx", "All caps and small caps", "yes", "partial", "yes", "yes", _YES, [],
     ["tests/test_golden_documents.py::test_02_rich_text", "tests/test_character_formatting.py::test_run_formatting_is_read_as_word_resolves_it",
      "tests/test_character_formatting.py::test_a_pdf_prints_capitals_and_notes_what_it_cant_draw", "frontend/editor/characterFormatting.test.ts"],
     "Kept (DOCX-013), from the run, its character style or its paragraph's style; the text stays as typed and shows in "
     "capitals. A PDF prints small capitals as smaller capitals. They can't be set from the toolbar yet."),
    ("docx.character_spacing", "docx", "Character spacing; raised and lowered text", "yes", "partial", "yes", "partial", _LOSSY,
     ["export.pdf.character_spacing"],
     ["tests/test_golden_documents.py::test_02_rich_text", "tests/test_character_formatting.py::test_a_word_export_writes_them_back_in_the_schemas_order",
      "tests/test_character_formatting.py::test_a_pdf_prints_capitals_and_notes_what_it_cant_draw", "frontend/editor/characterFormatting.test.ts"],
     "Kept in points (DOCX-013), through the editor and back into Word. A PDF draws raised and lowered text but not the "
     "spacing, and says so. Character scale and kerning aren't kept yet (DOCX-013)."),
    ("docx.hidden_text", "docx", "Hidden text", "yes", "partial", "yes", "yes", _YES, ["docx.hidden_text", "export.pdf.hidden_text"],
     ["tests/test_hidden_text.py::test_hidden_text_is_read_from_the_run_its_style_the_paragraphs_style_as_word_does",
      "tests/test_hidden_text.py::test_a_word_export_hides_it_again", "tests/test_hidden_text.py::test_a_pdf_leaves_it_out_and_says_so",
      "tests/test_golden_documents.py::test_02_rich_text", "frontend/editor/hiddenText.test.tsx", "frontend/e2e/hidden-text.spec.ts"],
     "Kept, and kept hidden (DOCX-025): read as Word resolves it (the run, its character style, its paragraph's style, the "
     "defaults); the editor shows it only on request (Show hidden text); a Word export hides it again; a PDF leaves it out, "
     "as Word's printing does, and says so. Text can't be made hidden in the editor."),
    ("docx.hyperlinks", "docx", "Links to web addresses", "yes", "yes", "yes", "yes", _YES, ["docx.link.unsafe"],
     ["tests/test_docx_fidelity.py::test_links_are_kept_for_safe_addresses_and_plain_addresses_become_links", "tests/test_golden_documents.py::test_05_links",
      "tests/test_docx_detect.py::test_unsafe_links_and_spacing_paragraphs_are_reported"],
     "Only safe addresses (http, https, mailto...) become links; others are kept as plain text and reported."),
    ("docx.empty_paragraphs", "docx", "Empty paragraphs used for spacing", "no", "n/a", "no", "no", _LOSSY, ["docx.empty_paragraph"],
     ["tests/test_docx_detect.py::test_unsafe_links_and_spacing_paragraphs_are_reported"], "Left out and reported; spacing comes from the styles."),
    ("docx.autolinks", "docx", "Web and e-mail addresses written as plain text", "partial", "yes", "yes", "partial", _LOSSY, ["docx.autolink"],
     ["tests/test_docx_fidelity.py::test_links_are_kept_for_safe_addresses_and_plain_addresses_become_links"],
     "Become links on import, and this is reported (DOCX-026)."),
    ("docx.internal_links", "docx", "Links to places inside the document", "preserved", "no", "preserved", "yes", _NOT_EDITABLE, ["docx.link"],
     ["tests/test_docx_preservation.py::test_bookmarks_and_links_to_them_go_back_into_word"], "Plain text in the editor."),
    ("docx.bookmarks", "docx", "Bookmarks", "preserved", "no", "preserved", "yes", _NOT_EDITABLE, ["docx.bookmark"],
     ["tests/test_docx_preservation.py::test_bookmarks_and_links_to_them_go_back_into_word"], ""),
    ("docx.fields", "docx", "Fields (dates, cross-references, page references)", "preserved", "partial", "preserved", "yes", _NOT_EDITABLE,
     ["docx.field", "export.docx.kept_fragment"], ["tests/test_docx_preservation.py::test_a_field_goes_back_with_its_last_result"],
     "Shown as their last result; the Word export puts the field back unless its text was edited."),
    ("docx.toc", "docx", "Table of contents", "partial", "partial", "partial", "partial", _LOSSY, ["docx.toc"], [],
     "Imported as plain text; its page numbers won't update."),
    ("docx.equations", "docx", "Equations", "preserved", "partial", "preserved", "yes", _NOT_EDITABLE, ["docx.equation", "export.docx.kept_fragment"],
     ["tests/test_docx_preservation.py::test_an_equation_goes_back_into_word_as_an_equation", "tests/test_docx_fidelity.py::test_equations_become_linear_text_with_superscripts"],
     "Linear text in the editor; the Word export puts the equation back unless its text was edited."),
    ("docx.comments", "docx", "Comments", "preserved", "no", "preserved", "partial", _NOT_EDITABLE, ["docx.comment"],
     ["tests/test_docx_preservation.py::test_comments_go_back_into_word_with_their_author_and_text"],
     "Not shown in the editor; replies and resolved state aren't kept (DOCX-021)."),
    ("docx.tracked_changes", "docx", "Tracked changes", "partial", "no", "no", "no", _LOSSY, ["docx.tracked_changes"],
     ["tests/test_docx_fidelity.py::test_tracked_changes_come_in_accepted"], "Imported as accepted: insertions kept, deletions removed (DOCX-022)."),
    ("docx.content_controls", "docx", "Content controls (checkboxes, drop-downs, date pickers...)", "partial", "no", "no", "no", _LOSSY, ["docx.content_control"],
     ["tests/test_docx_detect.py::test_each_unkept_feature_is_named_with_an_example"],
     "Unwrapped to their text, and reported; checkbox list items become checklists (DOCX-023)."),
    ("docx.notes", "docx", "Footnotes and endnotes", "partial", "yes", "partial", "partial", _LOSSY, ["docx.notes.moved"],
     ["tests/test_docx_fidelity.py::test_footnotes_are_numbered_in_the_text_and_moved_to_the_end"],
     "Moved to the end of the document as numbered paragraphs (DOCX-024)."),
    ("docx.lists", "docx", "Bulleted and numbered lists with levels", "yes", "yes", "yes", "yes", _YES, [],
     ["tests/test_docx_parser.py::test_nested_list_level_from_ilvl", "tests/test_export_round_trip.py::test_nested_list_levels_survive_a_docx_round_trip"], ""),
    ("docx.list_numbering", "docx", "Numbering formats, start values, continuation and custom labels", "partial", "yes", "partial", "partial", _LOSSY,
     ["docx.list_numbering.format", "docx.list_numbering.label", "docx.list_numbering.multilevel", "docx.list_numbering.empty_item"],
     ["tests/test_docx_numbering.py::test_a_list_keeps_its_format_start_and_continuation_through_a_round_trip",
      "tests/test_nested_blocks_api.py::test_the_word_export_numbers_a_list_from_its_start_in_its_format"],
     "The top level's format (1, a, A, i, I), start and continuation after an interruption are kept; other number styles, labels with their own wording (\"Чл. 1.\", \"(a)\") and 1.1-style numbers are reported (DOCX-016)."),
    ("docx.numbered_headings", "docx", "Headings numbered by Word", "partial", "yes", "partial", "no", _LOSSY, ["docx.numbered_headings"],
     ["tests/test_docx_fidelity.py::test_headings_numbered_by_word_show_their_numbers"],
     "The number becomes part of the heading's text and won't renumber (reported; the content check shows the added words) (DOCX-016)."),
    ("docx.checklists", "docx", "Checklists (checkbox list items)", "yes", "yes", "yes", "yes", _YES, [],
     ["tests/test_docx_fidelity.py::test_checkbox_list_items_become_a_checklist", "tests/test_export_round_trip.py::test_a_checklist_survives_a_docx_round_trip_as_word_checkboxes"], ""),
    ("docx.tables", "docx", "Tables, merged cells, cell shading, column alignment", "yes", "yes", "partial", "partial", _LOSSY, ["export.docx.table_style"],
     ["tests/test_docx_parser.py::test_horizontally_merged_cells_become_one_cell_with_a_colspan",
      "tests/test_export_round_trip.py::test_table_spans_shading_and_alignment_survive_a_docx_round_trip"],
     "Exported with a grid and equal column widths; the original table style isn't kept (DOCX-017)."),
    ("docx.table_geometry", "docx", "Column widths, borders, row heights, table styles", "no", "no", "no", "no", _LOSSY, ["docx.table.geometry"],
     ["tests/test_docx_detect.py::test_each_unkept_feature_is_named_with_an_example"], "Not kept; reported (DOCX-017)."),
    ("docx.table_cell_content", "docx", "Lists, pictures and tables inside table cells", "partial", "yes", "yes", "partial", _UNSUPPORTED,
     ["docx.table.cell_image", "docx.table.nested_table", "docx.table.cell_list"],
     ["tests/test_docx_parser.py::test_picture_in_a_table_cell_is_reported_not_silently_dropped", "tests/test_nested_blocks_api.py::test_the_word_export_keeps_every_nested_block"],
     "Pictures in cells aren't imported yet, nested tables become lines of text and lists in cells lose their bullets (all reported); blocks made in the editor survive (DOCX-027)."),
    ("docx.images", "docx", "Pictures (PNG, JPEG, GIF, BMP)", "yes", "yes", "yes", "yes", _YES, ["docx.image.unreadable", "export.image.missing"],
     ["tests/test_docx_parser.py::test_embedded_picture_becomes_an_image_element_in_document_order", "tests/test_golden_documents.py::test_04_images"], ""),
    ("docx.image_alt_text", "docx", "Pictures' alt text", "yes", "yes", "yes", "yes", _YES, [],
     ["tests/test_docx_parser.py::test_picture_alt_text_is_preserved", "tests/test_nested_blocks_api.py::test_the_word_export_keeps_every_nested_block"], ""),
    ("docx.image_webp", "docx", "WebP pictures", "yes", "yes", "no", "no", _UNSUPPORTED, ["export.docx.image_format"],
     ["tests/test_export_fidelity.py::test_a_webp_picture_word_cannot_hold_is_reported_not_silently_dropped"],
     "A Word export can't hold them yet and reports it (DOCX-018)."),
    ("docx.image_other_formats", "docx", "EMF, WMF, SVG or TIFF pictures", "no", "no", "no", "no", _UNSUPPORTED, ["docx.image.format"],
     ["tests/test_docx_parser.py::test_picture_in_a_non_web_format_is_reported_instead_of_imported"], ""),
    ("docx.image_linked", "docx", "Linked (not embedded) pictures", "no", "no", "no", "no", _UNSUPPORTED, ["docx.image.linked"], [], ""),
    ("docx.image_vml", "docx", "Pictures in the older Word format (VML)", "no", "no", "no", "no", _UNSUPPORTED, ["docx.image.vml"], [], ""),
    ("docx.image_layout", "docx", "Floating pictures, crop and rotation", "partial", "no", "partial", "no", _LOSSY,
     ["docx.image.floating", "docx.image.crop", "docx.image.rotation"], ["tests/test_docx_detect.py::test_each_unkept_feature_is_named_with_an_example"],
     "Floating pictures are placed in line, cropped pictures shown whole and rotated ones upright; all reported (DOCX-018)."),
    ("docx.list_item_images", "docx", "Pictures inside list items", "no", "yes", "yes", "partial", _UNSUPPORTED, ["docx.list_item.image"],
     ["tests/test_docx_parser.py::test_picture_in_a_list_item_is_reported_not_silently_dropped"], "Not imported yet; pictures added in the editor survive (DOCX-027)."),
    ("docx.text_boxes", "docx", "Text boxes", "partial", "yes", "partial", "no", _LOSSY, ["docx.text_box"],
     ["tests/test_docx_fidelity.py::test_text_boxes_are_imported_as_paragraphs"], "Imported as paragraphs after the one they are anchored in."),
    ("docx.objects", "docx", "Charts, SmartArt, shapes and embedded (OLE) objects", "no", "no", "no", "no", _UNSUPPORTED,
     ["docx.embedded_object", "docx.chart", "docx.smartart", "docx.shape"], ["tests/test_docx_detect.py::test_charts_and_shapes_are_named_for_what_they_are"],
     "Left out and reported, each by what it is."),
    ("docx.symbols", "docx", "Symbol-font characters (Wingdings and the like)", "partial", "yes", "partial", "partial", _UNSUPPORTED, ["docx.symbol_characters"], [],
     "Checkbox symbols are kept; others are left out and reported."),
    ("docx.drop_caps", "docx", "Drop caps", "partial", "yes", "partial", "no", _LOSSY, ["docx.drop_cap"], [], "Shown as the normal first letter."),
    ("docx.source_package", "docx", "The original Word file: its styles, headers and footers of every kind, footnotes, properties, theme, settings",
     "yes", "no", "yes", "yes", _NOT_EDITABLE,
     ["export.docx.source_package", "export.docx.source_unreadable", "export.docx.source_missing", "export.pdf.word_only",
      "export.docx.original_blocks", "export.docx.section_lost"],
     ["tests/test_source_package.py::test_a_word_export_keeps_what_the_document_model_doesnt_hold",
      "tests/test_source_package.py::test_a_stored_file_that_isnt_the_one_kept_is_not_used_and_the_export_says_so",
      "tests/test_package_check.py::test_every_export_is_a_sound_package",
      "tests/test_original_blocks.py::test_what_the_model_doesnt_hold_survives_in_unchanged_blocks",
      "tests/test_original_blocks.py::test_a_block_restyled_here_is_written_anew_and_page_breaks_keep_their_sections",
      "tests/test_original_blocks.py::test_where_a_block_came_from_is_the_servers_to_say",
      "frontend/e2e/kept-blocks.spec.ts"],
     "Kept as it was and written back into on a Word export: styles a template or instructions changed and a main header or "
     "footer changed in the app are rewritten (DOCX-010/011); blocks the document didn't change -- in what they hold or how "
     "they look -- are copied as they are, with their fields, content controls, formatting and section breaks, the others "
     "written anew (DOCX-028). A PDF has none of it."),
    ("docx.page_setup", "docx", "Page size, orientation and margins", "yes", "yes", "yes", "yes", _YES, ["docx.page_setup.margins"],
     ["tests/test_docx_fidelity.py::test_page_size_orientation_and_margins_come_from_the_section"], "One page setup for the whole document."),
    ("docx.sections", "docx", "Several sections, columns, section break types, page numbering, page borders, line numbers", "partial", "no", "partial", "no",
     _NOT_EDITABLE,
     ["docx.layout", "docx.sections.page_setup", "docx.sections.break_type", "docx.sections.page_numbering",
      "docx.sections.page_borders", "docx.sections.line_numbers", "docx.sections.vertical_alignment"],
     ["tests/test_docx_fidelity.py::test_a_multi_column_layout_is_reported",
      "tests/test_docx_detect.py::test_a_section_break_breaks_the_page_only_where_word_does",
      "tests/test_docx_detect.py::test_what_sections_change_is_reported",
      "tests/test_source_package.py::test_sections_own_properties_are_kept_and_named",
      "tests/test_original_blocks.py::test_a_page_setup_changed_here_applies_to_every_section",
      "tests/test_original_blocks.py::test_a_section_ending_in_a_changed_paragraph_is_named_as_lost"],
     "One page setup here, for the whole document; section breaks become page breaks where Word starts a new page. A Word export "
     "written into the original file keeps every section's own properties -- the last section's always, an earlier one's while "
     "the paragraph that ends it isn't changed or restyled -- and a page setup changed here applies to all of them (DOCX-028); "
     "a section lost with its paragraph is named in the export report. Sections aren't part of the model yet (DOCX-015)."),
    ("docx.headers_footers", "docx", "Headers and footers", "partial", "yes", "yes", "partial", _NOT_EDITABLE,
     ["docx.header_footer.variants", "docx.header_footer.picture", "docx.header_footer.text"],
     ["tests/test_docx_fidelity.py::test_header_and_footer_keep_their_page_number_fields", "tests/test_fidelity_report.py::test_header_text_that_is_left_out_is_reported",
      "tests/test_source_package.py::test_headers_of_earlier_sections_are_kept_while_their_sections_are",
      "tests/test_original_blocks.py::test_a_header_changed_here_is_the_one_every_linked_section_shows",
      "tests/test_original_blocks.py::test_page_numbers_left_out_are_left_out_of_every_section",
      "tests/test_original_blocks.py::test_page_numbers_asked_for_here_are_on_every_sections_pages"],
     "The main header and footer, with page numbers, are editable; first-page and even-page ones, pictures in them and earlier "
     "sections' ones aren't shown but are kept in the Word export (DOCX-011, DOCX-028: earlier sections' while the paragraph "
     "ending each is unchanged). A main header changed here is rewritten where Word shows it -- the last section's own, or the "
     "one it continues -- and page numbers asked for or left out apply to every section. A PDF has only the main ones."),
    ("docx.watermark", "docx", "Watermarks", "no", "no", "partial", "partial", _NOT_EDITABLE, ["docx.watermark"],
     ["tests/test_source_package.py::test_the_import_report_says_what_the_word_export_keeps"], "Not shown here; kept in the Word export, not in a PDF (DOCX-011)."),
    ("docx.page_breaks", "docx", "Page breaks", "yes", "yes", "yes", "yes", _YES, [],
     ["tests/test_docx_fidelity.py::test_page_breaks_become_page_break_elements", "tests/test_golden_documents.py::test_11_page_breaks"], ""),
    ("docx.styles", "docx", "The document's Word styles", "partial", "yes", "partial", "partial", _LOSSY, ["docx.style.value"],
     ["tests/test_docx_fidelity.py::test_the_documents_word_styles_become_its_own_look"],
     "Read into the app's style system; values outside its range are reported."),
    ("docx.metadata", "docx", "Document properties: title, author, dates, subject, keywords", "yes", "partial", "yes", "yes", _YES, [],
     ["tests/test_docx_detect.py::test_the_files_own_properties_go_back_into_word_not_the_templates"],
     "Only the title can be edited in the app."),
    ("docx.custom_properties", "docx", "Custom document properties and sensitivity labels", "no", "no", "partial", "partial", _NOT_EDITABLE,
     ["docx.metadata.custom_properties", "docx.metadata.sensitivity_label"],
     ["tests/test_docx_detect.py::test_metadata_that_is_not_kept_is_reported_without_its_values",
      "tests/test_source_package.py::test_a_word_export_keeps_what_the_document_model_doesnt_hold"],
     "Reported without their values; not shown here, kept in the Word export written into the original file (DOCX-011), not in a PDF."),
    ("docx.rtl", "docx", "Right-to-left paragraphs", "partial", "partial", "partial", "partial", _LOSSY, ["docx.rtl"],
     ["tests/test_docx_detect.py::test_each_unkept_feature_is_named_with_an_example"], "The text is kept; its direction settings aren't, and this is reported (FONT-004)."),
    ("docx.preserved_inside_blocks", "docx", "Equations, fields, bookmarks or comments inside lists, tables, footnotes or code", "partial", "yes", "partial", "partial",
     _LOSSY, ["docx.preserved.flattened"], ["tests/test_docx_preservation.py::test_what_sits_inside_a_table_is_kept_only_as_text_and_said_so"], "Kept as their text."),
    ("docx.other", "docx", "Other Word features the importer notes", "partial", "n/a", "n/a", "n/a", _LOSSY, ["docx.other"], [], ""),
    # -- PDF ------------------------------------------------------------------------------
    ("pdf.export_text", "pdf", "Text with embedded fonts (Latin, Cyrillic, Greek)", "n/a", "n/a", "yes", "n/a", _YES, [],
     ["tests/test_export_round_trip.py::test_pdf_has_real_cyrillic_text_and_filled_in_page_numbers",
      "tests/test_export_fidelity.py::test_both_exports_of_a_plain_document_are_verified_word_for_word"],
     "Every PDF export is read back and checked word by word."),
    ("pdf.scripts", "pdf", "Arabic, Hebrew, Devanagari, Thai, CJK text and emoji", "n/a", "n/a", "partial", "n/a", _LOSSY, ["export.pdf.script"],
     ["tests/test_export_fidelity.py::test_text_the_pdf_cannot_lay_out_is_reported_and_caught_by_the_check"],
     "Not shaped or laid out correctly yet; reported on every such export (FONT-003)."),
    ("pdf.images", "pdf", "Pictures in PDF exports", "n/a", "n/a", "yes", "n/a", _YES, ["export.image.missing", "export.pdf.image_unreadable"],
     ["tests/test_image_assets_api.py::test_docx_and_pdf_exports_embed_the_stored_picture"], ""),
    ("pdf.alt_text", "pdf", "Alt text and tags for screen readers", "n/a", "n/a", "no", "n/a", _LOSSY, ["export.pdf.alt_text"], [], "Not a tagged PDF yet (FEAT-010)."),
    ("pdf.word_features", "pdf", "Equations, fields, comments and internal links in PDF exports", "n/a", "n/a", "partial", "n/a", _LOSSY,
     ["export.pdf.equation", "export.pdf.field", "export.pdf.link", "export.pdf.comment"], [],
     "Equations as linear text, fields as their last text, no comments, internal links not clickable."),
    ("pdf.tables", "pdf", "Tables in PDF exports", "n/a", "n/a", "partial", "n/a", _LOSSY, ["export.pdf.page_break_in_table"],
     ["tests/test_export_fidelity.py::test_a_page_break_inside_a_table_is_reported_for_the_pdf"], "A grid with equal column widths; page breaks inside a table are dropped and reported."),
    ("pdf.headers_footers", "pdf", "Headers, footers and page numbers in PDF exports", "n/a", "n/a", "partial", "n/a", _LOSSY, [],
     ["tests/test_export_round_trip.py::test_pdf_leaves_out_a_page_number_footer_when_page_numbers_are_off"], "One centred line each."),
    ("pdf.import_text", "pdf", "Text of text-based PDFs", "partial", "yes", "n/a", "n/a", _LOSSY, ["pdf.layout", "pdf.note"],
     ["tests/test_fidelity_report.py::test_a_pdf_upload_says_only_its_text_was_imported"],
     "The extracted text is checked word by word against the document; layout, columns and tables aren't kept (PDF-010, P2E-002)."),
    ("pdf.import_images", "pdf", "Pictures in imported PDFs", "no", "n/a", "n/a", "n/a", _UNSUPPORTED, ["pdf.images"], [], "Reported with their number (P2E-003)."),
    ("pdf.scanned", "pdf", "Scanned PDFs (no text layer)", "no", "n/a", "n/a", "n/a", _BLOCKED, [],
     ["tests/test_pdf_parser.py::test_blank_pdf_raises_pdf_parse_error"], "Refused with a message rather than imported empty: OCR isn't available yet (P2E-006)."),
    # -- the editor -------------------------------------------------------------------------
    ("editor.blocks", "editor", "Paragraphs, headings, lists, checklists, tables, quotes, code, pictures, captions, footnotes, page breaks, rules",
     "n/a", "yes", "n/a", "yes", _YES, [], ["frontend/editor/editorRoundTrip.test.ts", "frontend/editor/nestedBlocks.test.ts"],
     "A test maps every node and mark of the editor's schema."),
    ("editor.nested_blocks", "editor", "Blocks inside table cells, list items and quotes", "n/a", "yes", "n/a", "yes", _YES, [],
     ["frontend/editor/nestedBlocks.test.ts", "frontend/e2e/nested.spec.ts", "tests/test_nested_blocks_api.py::test_nested_blocks_are_stored_as_sent_and_their_picture_as_an_asset"], ""),
    ("editor.list_numbering", "editor", "A list's start number and top-level format", "n/a", "yes", "yes", "yes", _YES, [],
     ["frontend/editor/nestedBlocks.test.ts", "tests/test_nested_blocks_api.py::test_the_word_export_numbers_a_list_from_its_start_in_its_format"], ""),
    ("editor.ai_instructions", "editor", "Formatting instructions: styles, page breaks, and changes to the text", "n/a", "yes", "n/a", "n/a", _YES, [],
     ["tests/test_ai_proposals.py::test_content_changes_wait_for_review_while_formatting_applies",
      "tests/test_ai_proposals.py::test_accepting_applies_the_change_as_one_undoable_step", "frontend/editor/panels/ProposalsList.test.tsx",
      "frontend/e2e/proposals.spec.ts"],
     "Styles and page breaks apply at once; inserting, deleting or moving text becomes a proposal shown with what it would "
     "change, applied only when accepted (AI-005..AI-007)."),
    ("editor.unknown_content", "editor", "Content the document model can't store", "n/a", "no", "n/a", "no", _BLOCKED, [],
     ["frontend/editor/useAutoSave.test.tsx", "frontend/editor/nestedBlocks.test.ts"],
     "The save stops with a message instead of dropping it; the last saved version is kept."),
    ("editor.pasted_alignment", "editor", "Alignment of pasted paragraphs and headings, and alignment set with shortcuts", "n/a", "yes", "n/a", "yes", _YES, [],
     ["frontend/editor/directFormatting.test.ts", "frontend/e2e/direct-formatting.spec.ts",
      "tests/test_editor_direct_styles.py::test_alignment_and_picture_size_become_the_elements_own_style"],
     "Saved as the block's own alignment, as the toolbar sets it, and kept by a block split off it (EDIT-008). Inside lists, "
     "quotes and a cell's other paragraphs it has nowhere to go: the editor names it as not kept."),
    ("editor.picture_size", "editor", "Picture sizes from pasted content", "n/a", "yes", "n/a", "yes", _YES, [],
     ["frontend/editor/directFormatting.test.ts", "frontend/e2e/direct-formatting.spec.ts",
      "tests/test_editor_direct_styles.py::test_alignment_and_picture_size_become_the_elements_own_style"],
     "Saved as the picture's width, a share of the text width; its height follows (EDIT-009). Inside lists, quotes and "
     "cells the editor names it as not kept."),
    ("editor.link_title", "editor", "Links' titles (tooltips)", "yes", "partial", "partial", "yes", _YES, [],
     ["tests/test_link_titles.py::test_word_tooltips_are_imported_and_written_back", "tests/test_link_titles.py::test_markdown_link_titles_are_kept",
      "frontend/editor/directFormatting.test.ts"],
     "Kept from Word (a link's ScreenTip, also a HYPERLINK field's ScreenTip switch) and Markdown, through the editor and back into Word "
     "(EDIT-010); not editable in the app yet; a PDF has no tooltips."),
    ("editor.cell_layout", "editor", "Per-cell alignment and column widths", "n/a", "partial", "n/a", "partial", _LOSSY, [],
     ["frontend/editor/directFormatting.test.ts"],
     "A column keeps one alignment when all its cells agree (a pasted cell's own alignment counts); cells that differ, and "
     "column widths, are named by the editor as not kept (EDIT-011, widths DOCX-017)."),
    ("editor.text_style_values", "editor", "Colours, fonts and sizes the model can't hold", "n/a", "partial", "n/a", "partial", _LOSSY, [],
     ["frontend/editor/directFormatting.test.ts", "frontend/editor/useAutoSave.test.tsx"],
     "Normalised to #rrggbb, basic colour names, one font name and pt sizes; anything else is named by the editor as not "
     "kept (a transparent background is no loss) (EDIT-012)."),
    # -- pasted text and text files ------------------------------------------------------
    ("text.markdown", "text", "Markdown (headings, lists, tables, code, quotes, links, task lists, rules)", "yes", "yes", "n/a", "n/a", _YES, [],
     ["tests/test_fidelity_report.py::test_markdown_syntax_and_link_addresses_are_not_words", "tests/test_markdown_parser.py::test_a_thematic_break_is_a_horizontal_rule"],
     "Every word is checked against the text; raw HTML is kept as the text it is."),
    ("text.markdown_images", "text", "Pictures in Markdown text", "no", "n/a", "n/a", "n/a", _UNSUPPORTED, ["markdown.image"],
     ["tests/test_markdown_parser.py::test_pictures_are_named_as_left_out_not_dropped_silently"],
     "Named as left out, with their description: the app doesn't fetch pictures from web addresses."),
    ("text.prose", "text", "Plain prose (structure found by the AI or by rules)", "partial", "yes", "n/a", "n/a", _LOSSY, ["paste.note", "txt.note"],
     ["tests/test_fidelity_report.py::test_an_ai_answer_that_drops_a_sentence_never_reaches_the_document",
      "tests/test_ai_fidelity.py::test_an_answer_that_alters_the_text_never_reaches_the_document"],
     "An AI answer must hold the text exactly -- every word, number and punctuation mark, in order; one that changes it is "
     "refused and that part is split into paragraphs instead (AI-001..AI-004). Every word is checked again on import."),
]

MATRIX = CapabilityMatrix(
    capabilities=[
        Capability(
            id=row[0], area=row[1], label=row[2], importSupport=row[3], edit=row[4], export=row[5], roundTrip=row[6],
            policy=row[7], features=row[8], tests=row[9], notes=row[10],
        )
        for row in _ROWS
    ]
)
