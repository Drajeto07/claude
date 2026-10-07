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
Area = Literal["docx", "pdf", "editor", "text", "translation"]


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
    ("docx.character_scale", "docx", "Character scale (stretched or squeezed text)", "partial", "no", "partial", "no", _LOSSY,
     ["docx.character_scale"],
     ["tests/test_copy_reports.py::test_stretched_text_and_text_effects_are_named",
      "tests/test_copy_reports.py::test_a_block_written_anew_names_what_it_lost"],
     "Shown at normal width and reported; a Word export written into the original keeps it while the paragraph is "
     "unchanged, and names it when the paragraph was written anew (DOCX-013, FID-007)."),
    ("docx.text_effects", "docx", "Text effects: outline, shadow, emboss, glow, emphasis marks, borders around text", "partial", "no",
     "partial", "no", _LOSSY, ["docx.text_effects"],
     ["tests/test_copy_reports.py::test_stretched_text_and_text_effects_are_named",
      "tests/test_copy_reports.py::test_with_the_file_kept_they_are_kept_while_unchanged"],
     "Not shown, and reported; kept in a Word export written into the original while the paragraph is unchanged, and named "
     "when it was written anew (DOCX-013, FID-007)."),
    ("docx.language", "docx", "The language text is in (spelling and grammar)", "yes", "partial", "yes", "no", _YES, [],
     ["tests/test_copy_reports.py::test_the_language_text_is_in_is_kept_where_it_isnt_the_documents_own",
      "frontend/editor/characterFormatting.test.ts"],
     "Kept where it isn't the document's own (DOCX-013): the editor marks it (the browser checks spelling in it) and a Word "
     "export writes it back. A PDF has no language per run."),
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
     ["tests/test_docx_fidelity.py::test_links_are_kept_for_safe_addresses_and_plain_addresses_stay_text", "tests/test_golden_documents.py::test_05_links",
      "tests/test_docx_detect.py::test_unsafe_links_and_spacing_paragraphs_are_reported"],
     "Only safe addresses (http, https, mailto...) become links; others are kept as plain text and reported."),
    ("docx.empty_paragraphs", "docx", "Empty paragraphs used for spacing", "no", "n/a", "no", "no", _LOSSY, ["docx.empty_paragraph"],
     ["tests/test_docx_detect.py::test_unsafe_links_and_spacing_paragraphs_are_reported"], "Left out and reported; spacing comes from the styles."),
    ("docx.autolinks", "docx", "Web and e-mail addresses written as plain text", "yes", "yes", "yes", "yes", _YES, ["docx.autolink"],
     ["tests/test_docx_fidelity.py::test_links_are_kept_for_safe_addresses_and_plain_addresses_stay_text",
      "tests/test_autolink.py::test_plain_text_addresses_stay_text_by_default",
      "tests/test_autolink.py::test_asked_for_they_become_links_and_the_report_says_so",
      "tests/test_autolink.py::test_the_upload_takes_the_option"],
     "Stay text, as the file has them (DOCX-026). An upload can ask for them to become links (autolink); the import "
     "report then says so."),
    ("docx.internal_links", "docx", "Links to places inside the document", "preserved", "no", "preserved", "yes", _NOT_EDITABLE, ["docx.link"],
     ["tests/test_docx_preservation.py::test_bookmarks_and_links_to_them_go_back_into_word"], "Plain text in the editor."),
    ("docx.bookmarks", "docx", "Bookmarks", "preserved", "no", "preserved", "yes", _NOT_EDITABLE, ["docx.bookmark"],
     ["tests/test_docx_preservation.py::test_bookmarks_and_links_to_them_go_back_into_word"], ""),
    ("docx.fields", "docx", "Fields (dates, cross-references, page references)", "preserved", "partial", "preserved", "yes", _NOT_EDITABLE,
     ["docx.field", "export.docx.kept_fragment", "export.docx.field_region"],
     ["tests/test_docx_preservation.py::test_a_field_goes_back_with_its_last_result",
      "tests/test_docx_preservation.py::test_text_between_kept_fragments_in_other_formatting_is_written_too",
      "tests/test_docx_fields.py::test_word_s_own_table_of_contents_and_bibliography_survive_a_template"],
     "Shown as their last result; the Word export puts the field back unless its text was edited -- one running "
     "across paragraphs (a bibliography) too, around them (DOCX-020). In a header or footer edited here only page "
     "numbers stay fields (DOCX-020A)."),
    ("docx.external_targets", "docx", "What a Word file fetches from outside itself (a remote template, linked pictures, sub-documents, mail-merge data)",
     "no", "no", "no", "n/a", _LOSSY, ["docx.external.unsafe"],
     ["tests/test_external_targets.py::test_a_word_file_keeps_no_external_target_but_safe_links",
      "tests/test_external_targets.py::test_an_upload_says_so_and_no_word_export_points_outside_it"],
     "Taken out of the Word file kept as the original, with what referred to it (SEC-016): no export fetches anything "
     "when opened. Links keep their text when their address isn't one a link may have (docx.link.unsafe)."),
    ("docx.fields_unsafe", "docx", "Fields that run a program or pull in outside content (DDE, INCLUDETEXT, INCLUDEPICTURE...)",
     "no", "no", "no", "n/a", _LOSSY, ["docx.field.unsafe"],
     ["tests/test_field_policy.py::test_a_word_file_s_unsafe_fields_are_kept_as_their_result_everywhere",
      "tests/test_field_policy.py::test_a_save_can_t_add_a_field_to_the_next_word_export"],
     "Kept as their last result (SEC-015): in the document, in the Word file kept as its original (so no export "
     "carries one out -- nor from a header, a note or a comment), and in what an export writes back. Only fields that "
     "show what the document holds or works out stay fields (security/fields.py), and a save can't add any."),
    ("docx.toc", "docx", "Table of contents", "yes", "partial", "preserved", "yes", _NOT_EDITABLE, ["docx.toc", "export.docx.field_region"],
     ["tests/test_docx_fields.py::test_a_table_of_contents_is_kept_where_it_starts_and_ends",
      "tests/test_docx_fields.py::test_written_anew_a_table_of_contents_goes_back_around_its_entries",
      "tests/test_docx_fields.py::test_into_the_original_an_unchanged_table_of_contents_is_copied_whole",
      "tests/test_docx_fields.py::test_a_table_of_contents_missing_its_last_paragraph_is_written_as_its_text"],
     "Shown as its entries (their page numbers as they were); a Word export keeps it a table of contents, for Word "
     "to update (DOCX-020). One whose first or last paragraph is deleted here is written as its text, and said so."),
    ("docx.equations", "docx", "Equations", "preserved", "partial", "preserved", "yes", _NOT_EDITABLE, ["docx.equation", "export.docx.kept_fragment"],
     ["tests/test_docx_preservation.py::test_an_equation_goes_back_into_word_as_an_equation", "tests/test_docx_fidelity.py::test_equations_become_linear_text_with_superscripts"],
     "Linear text in the editor; the Word export puts the equation back unless its text was edited."),
    ("docx.comments", "docx", "Comments", "preserved", "no", "preserved", "yes", _NOT_EDITABLE,
     ["docx.comment", "docx.comment_range", "export.docx.comment_range"],
     ["tests/test_docx_preservation.py::test_comments_go_back_into_word_with_their_author_and_text",
      "tests/test_docx_comments.py::test_a_thread_copied_into_the_original_is_as_it_was",
      "tests/test_docx_comments.py::test_a_thread_written_anew_into_the_original_keeps_its_replies_and_resolved_state",
      "tests/test_docx_comments.py::test_a_thread_goes_into_a_new_word_file_together",
      "tests/test_docx_comments.py::test_a_comment_over_several_paragraphs_keeps_its_range"],
     "Not shown in the editor; a Word export puts them back with their replies, which are resolved, and their ranges, "
     "over several paragraphs too (DOCX-021). One running on into a list or table ends before it, and is said so."),
    ("docx.tracked_changes", "docx", "Tracked changes", "partial", "no", "preserved", "partial", _NOT_EDITABLE, ["docx.tracked_changes"],
     ["tests/test_docx_fidelity.py::test_tracked_changes_come_in_accepted",
      "tests/test_docx_tracked_changes.py::test_an_unchanged_document_keeps_its_tracked_changes_in_a_word_export",
      "tests/test_docx_tracked_changes.py::test_a_block_changed_here_has_its_changes_accepted_and_the_export_says_so",
      "tests/test_docx_tracked_changes.py::test_the_choice_is_the_users_and_the_report_says_which",
      "tests/test_tracked_changes_reject.py::test_rejecting_gives_what_word_gives_on_reject_all",
      "tests/test_tracked_changes_reject.py::test_the_accepted_reading_joins_a_paragraph_whose_mark_was_deleted_to_the_next",
      "tests/test_tracked_changes_reject.py::test_rejecting_all_reads_the_document_again_and_undo_brings_the_changes_back",
      "frontend/e2e/tracked-changes.spec.ts"],
     "Shown as if accepted (a paragraph whose mark was deleted joined to the next, as in Word); a Word export into the "
     "original keeps them in every block not changed or restyled here (one changed has its own accepted, and the export "
     "says so), unless the person accepts them all (DOCX-022) or rejects them all, which reads the document again from "
     "the file without them (DOCX-022A)."),
    ("docx.content_controls", "docx", "Content controls (checkboxes, drop-downs, date pickers...)", "preserved", "no", "preserved", "partial", _NOT_EDITABLE,
     ["docx.content_control", "docx.content_control.nested", "export.docx.control_region"],
     ["tests/test_docx_detect.py::test_each_unkept_feature_is_named_with_an_example",
      "tests/test_docx_content_controls.py::test_a_file_written_anew_has_every_control_back_with_its_properties",
      "tests/test_docx_content_controls.py::test_controls_in_blocks_changed_here_go_back_too",
      "tests/test_docx_content_controls.py::test_a_checkbox_follows_the_symbol_it_shows",
      "tests/test_docx_content_controls.py::test_legacy_form_fields_keep_their_settings",
      "tests/test_nested_content_controls.py::test_a_file_written_anew_has_every_control_back_around_its_text_cell_and_rows",
      "tests/test_nested_content_controls.py::test_a_save_from_the_editor_keeps_them_and_can_t_add_one"],
     "Shown as their text; a Word export puts every kind back with its properties -- text, drop-downs, dates, checkboxes, "
     "pictures, repeating sections -- also around text changed here (DOCX-023), in table cells, list items and text boxes "
     "too, and around cells and rows (DOCX-023A). One around paragraphs inside a cell or a text box only while unchanged; "
     "checkbox list items become checklists."),
    ("docx.notes", "docx", "Footnotes and endnotes", "partial", "yes", "yes", "partial", _YES,
     ["docx.notes.moved", "export.docx.notes_at_end", "export.pdf.notes"],
     ["tests/test_docx_fidelity.py::test_footnotes_are_numbered_in_the_text_and_moved_to_the_end",
      "tests/test_docx_notes.py::test_notes_go_back_into_word_as_notes",
      "tests/test_docx_notes.py::test_an_unchanged_block_is_copied_with_its_reference",
      "tests/test_docx_notes.py::test_a_note_deleted_here_leaves_its_label_as_text"],
     "Shown at the end of the document, each reference as its label; a Word export writes them back as real notes "
     "(DOCX-024). One referred to from a list or a table, and a PDF's, at the end of the document."),
    ("docx.lists", "docx", "Bulleted and numbered lists with levels", "yes", "yes", "yes", "yes", _YES, [],
     ["tests/test_docx_parser.py::test_nested_list_level_from_ilvl", "tests/test_export_round_trip.py::test_nested_list_levels_survive_a_docx_round_trip"], ""),
    ("docx.list_numbering", "docx", "Numbering formats, start values, continuation and custom labels", "partial", "yes", "partial", "partial", _LOSSY,
     ["docx.list_numbering.format", "docx.list_numbering.bullet_font", "docx.list_numbering.empty_item"],
     ["tests/test_docx_numbering.py::test_a_list_keeps_its_format_start_and_continuation_through_a_round_trip",
      "tests/test_docx_numbering.py::test_each_level_keeps_its_format_label_start_and_indent",
      "tests/test_docx_numbering.py::test_a_lists_own_levels_come_back_from_a_word_export",
      "tests/test_docx_numbering.py::test_a_list_taking_its_levels_from_a_numbering_style_has_them",
      "tests/test_docx_numbering.py::test_bullets_drawn_from_symbol_fonts_are_the_characters_they_show",
      "tests/test_docx_numbering.py::test_a_label_is_written_as_text_never_as_markup",
      "tests/test_docx_numbering.py::test_numbers_count_and_restart_as_word_counts_them",
      "tests/test_docx_numbering.py::test_a_pdf_numbers_each_level_with_its_own_label",
      "tests/test_docx_numbering.py::test_a_pdf_draws_a_lists_own_bullets",
      "frontend/editor/listLabels.test.ts",
      "frontend/editor/listNumbering.test.ts",
      "tests/test_number_formats.py::test_every_style_here_was_checked_against_word",
      "tests/test_number_formats.py::test_a_style_is_kept_through_an_import_and_a_word_export_without_a_word_about_it",
      "tests/test_number_formats.py::test_a_pdf_draws_the_labels_in_their_style",
      "frontend/editor/numberFormats.test.ts",
      "frontend/e2e/list-labels.spec.ts",
      "tests/test_nested_blocks_api.py::test_the_word_export_numbers_a_list_from_its_start_in_its_format"],
     "Each level of a list is kept (DOCX-016): its format (1, 01, a, A, i, I, а, А, bullets), its label (\"Чл. %1.\", "
     "\"(%2)\", \"%1.%2.\"), start, indent and hanging, legal numbering, when it restarts and what follows the label; "
     "a bullet from a symbol font as the character it shows. The pages here and a PDF number each item with them, as "
     "Word does (the pages here at the levels' indents), and a Word export writes them back. Word's other number "
     "styles -- 1st, ①, 一, 十一, א, أ, ก ... -- too, each label as Word shows it (DOCX-016B); only numbers spelled in "
     "words (One, First) are numbered 1, 2, 3 and reported."),
    ("docx.numbered_headings", "docx", "Headings numbered by Word", "yes", "yes", "yes", "yes", _YES, ["docx.numbered_headings"],
     ["tests/test_docx_fidelity.py::test_headings_numbered_by_word_keep_their_numbers_as_numbering",
      "tests/test_heading_numbering.py::test_the_numbers_follow_when_headings_move",
      "tests/test_heading_numbering.py::test_a_new_word_file_numbers_the_headings_again",
      "tests/test_heading_numbering.py::test_a_heading_edited_here_gets_one_number_into_the_original",
      "tests/test_heading_numbering.py::test_a_pdf_prints_the_numbers",
      "frontend/editor/headingNumbers.test.ts"],
     "Kept as numbering: shown before each heading here and in a PDF, counted over the headings in order so it "
     "follows when they move, and written back to Word as the heading styles' numbering (DOCX-016A). Headings "
     "numbered by more than one list, or not each at its own level, keep their numbers in their text, as before."),
    ("docx.checklists", "docx", "Checklists (checkbox list items)", "yes", "yes", "yes", "yes", _YES, [],
     ["tests/test_docx_fidelity.py::test_checkbox_list_items_become_a_checklist", "tests/test_export_round_trip.py::test_a_checklist_survives_a_docx_round_trip_as_word_checkboxes"], ""),
    ("docx.tables", "docx", "Tables, merged cells, cell shading, column and cell alignment", "yes", "yes", "yes", "yes", _YES, [],
     ["tests/test_docx_parser.py::test_horizontally_merged_cells_become_one_cell_with_a_colspan",
      "tests/test_export_round_trip.py::test_table_spans_shading_and_alignment_survive_a_docx_round_trip",
      "tests/test_docx_tables.py::test_a_cell_aligned_unlike_its_column_keeps_its_own_alignment"],
     "Header rows come only from the file (a row Word repeats, or a style's first row the table shows), never "
     "made up (DOCX-017)."),
    ("docx.table_geometry", "docx", "Column widths, table width, alignment and indent, row heights, borders, cell margins, vertical alignment, table styles",
     "yes", "no", "yes", "yes", _NOT_EDITABLE, ["docx.table.style_look", "docx.table.floating", "export.docx.table_style"],
     ["tests/test_docx_tables.py::test_a_tables_grid_borders_margins_and_style_are_kept",
      "tests/test_docx_tables.py::test_a_header_row_needs_evidence",
      "tests/test_docx_tables.py::test_a_word_export_writes_the_tables_geometry_back",
      "tests/test_docx_tables.py::test_a_pdf_draws_the_tables_widths_and_borders",
      "tests/test_docx_tables.py::test_a_table_made_here_keeps_its_grid_and_bold_header",
      "tests/test_docx_tables.py::test_a_floating_table_and_a_row_kept_whole_come_back_from_a_word_export",
      "tests/test_floating_tables.py::test_a_floating_table_gets_its_side_at_import_and_keeps_where_it_floats_in_word",
      "tests/test_floating_tables.py::test_a_pdf_wraps_the_text_around_a_floating_table_at_its_side",
      "tests/test_golden_documents.py::test_16_table_engine",
      "tests/test_docx_tables.py::test_a_table_styles_banded_rows_columns_and_corners_are_drawn_as_word_draws_them",
      "tests/test_docx_tables.py::test_only_the_parts_a_table_shows_are_drawn",
      "tests/test_docx_tables.py::test_the_drawn_look_reaches_a_pdf_and_a_new_word_file",
      "frontend/e2e/tables.spec.ts",
      "frontend/editor/tableLook.test.ts"],
     "Kept (DOCX-017): each grid column's width, the table's width, alignment and indent, row heights (least or exact), "
     "borders -- the table's sides and inside lines, and each cell's own -- and cell margins, with a Word table style's "
     "resolved where the table has none of its own, cells' vertical alignment, and the style's name and look. The pages "
     "here and a PDF draw them (each cell edge as Word resolves it); a Word export writes them back, and the style too "
     "where the file has it. What a style colours, bolds or italicises by position -- banded rows and columns (in bands of "
     "its size), the first and last row and column, the corner cells -- is resolved into the cells as Word draws it, in "
     "Word's order and from the parts the table shows (DOCX-017A); a cell's own shading and a run's own formatting win. "
     "Borders by position are shown only by Word, from the original, and reported. A table text flows around keeps exactly where it floats for a Word export, and "
     "floats to its side here and in a PDF with the text beside it (DOCX-017B); centred or as wide as the text, in line "
     "(reported). A row kept whole on one page stays so. Not editable "
     "here yet."),
    ("docx.table_cell_content", "docx", "Paragraphs, lists, pictures and tables inside table cells", "yes", "yes", "yes", "yes", _YES,
     [],
     ["tests/test_docx_parser.py::test_a_picture_in_a_table_cell_is_kept_as_the_cells_block",
      "tests/test_docx_tables.py::test_a_cells_paragraphs_lists_and_tables_are_its_blocks",
      "tests/test_docx_tables.py::test_a_cells_blocks_come_back_from_a_word_export",
      "tests/test_docx_pictures.py::test_in_a_pdf_the_text_by_a_picture_in_a_cell_keeps_the_tables_look",
      "tests/test_nested_blocks_api.py::test_the_word_export_keeps_every_nested_block"],
     "A cell holding more than one plain paragraph keeps what it holds, in order, as its blocks (DOCX-017): its "
     "paragraphs, its lists numbered as Word numbers them, its pictures and the tables inside it, read the same way. A "
     "picture in a cell keeps its size from Word, as wide as the cell at most (DOCX-018). Blocks made in the editor "
     "survive too (DOCX-027)."),
    ("docx.images", "docx", "Pictures (PNG, JPEG, GIF, BMP)", "yes", "yes", "yes", "yes", _YES, ["docx.image.unreadable", "export.image.missing"],
     ["tests/test_docx_parser.py::test_embedded_picture_becomes_an_image_element_in_document_order", "tests/test_golden_documents.py::test_04_images"], ""),
    ("docx.image_properties", "docx", "Pictures' size, name, crop, rotation and flips", "yes", "yes", "yes", "yes", _YES, [],
     ["tests/test_docx_pictures.py::test_a_pictures_size_crop_turn_and_name_are_kept",
      "tests/test_docx_pictures.py::test_a_word_export_writes_crop_turn_and_flips_back",
      "tests/test_docx_pictures.py::test_an_unchanged_picture_keeps_its_exact_size_and_a_new_width_rule_still_wins",
      "tests/test_docx_pictures.py::test_a_turned_picture_takes_the_room_of_its_turned_outline",
      "tests/test_docx_pictures.py::test_a_pdf_draws_the_picture_cropped_and_turned",
      "tests/test_docx_pictures.py::test_a_picture_cropped_and_turned_in_the_editor_is_so_in_word_written_into_the_original",
      "tests/test_golden_documents.py::test_17_pictures",
      "frontend/editor/pictureLook.test.ts",
      "frontend/editor/pictureEdit.test.ts",
      "frontend/e2e/pictures.spec.ts"],
     "A picture keeps its type and name, the size Word draws it at, what is cropped away and how it is turned and "
     "flipped (DOCX-018): shown so here and in a PDF, written back into a Word export. Turned, it takes the room of "
     "its turned outline, as in Word. A width rule sets the width -- one the document hasn't changed keeps the "
     "picture's own exactly -- the height following its proportions. Its crop, turn and flips are changed in the "
     "Properties panel (DOCX-018B), and both exports follow."),
    ("docx.image_alt_text", "docx", "Pictures' alt text", "yes", "yes", "yes", "yes", _YES, [],
     ["tests/test_docx_parser.py::test_picture_alt_text_is_preserved", "tests/test_nested_blocks_api.py::test_the_word_export_keeps_every_nested_block"], ""),
    ("docx.image_webp", "docx", "WebP pictures", "yes", "yes", "yes", "yes", _YES, ["export.docx.image_format"],
     ["tests/test_export_fidelity.py::test_a_webp_picture_goes_into_word_as_png"],
     "Word can't hold WebP, so a Word export puts the picture in as PNG (DOCX-018); one no program can read is "
     "reported as left out."),
    ("docx.image_other_formats", "docx", "EMF, WMF, SVG or TIFF pictures", "no", "no", "no", "no", _UNSUPPORTED, ["docx.image.format", "docx.image.svg"],
     ["tests/test_docx_parser.py::test_picture_in_a_non_web_format_is_reported_instead_of_imported",
      "tests/test_svg.py::test_a_word_svg_picture_is_read_as_its_png_fallback_or_not_at_all",
      "tests/test_docx_pictures.py::test_an_svg_picture_is_named_where_its_png_copy_stands_in_for_it"],
     "An SVG picture with Word's own PNG fallback is read as the PNG (SEC-017), and the import report says so "
     "(docx.image.svg, DOCX-018C). A Word export written into the original keeps the SVG while its paragraph is "
     "unchanged; one written anew gets the PNG, named in the export's rewritten-blocks report."),
    ("docx.image_limits", "docx", "Pictures past the limits (20 MB, 50 megapixels; 1000 or 200 MB in a document)", "no", "no", "no", "n/a", _UNSUPPORTED,
     ["docx.image.too_large", "docx.image.too_many", "export.image.too_large"],
     ["tests/test_picture_limits.py::test_a_word_file_s_pictures_past_the_limits_are_left_out_and_said_to_be",
      "tests/test_picture_limits.py::test_an_export_leaves_out_a_picture_from_before_the_limits"],
     "Judged by the picture's header before anything decodes it (SEC-012): left out and said to be on import, an editor "
     "save past them is refused, and an export leaves out one stored before the limits."),
    ("docx.image_linked", "docx", "Linked (not embedded) pictures", "no", "no", "no", "no", _UNSUPPORTED, ["docx.image.linked"], [], ""),
    ("docx.image_vml", "docx", "Pictures in the older Word format (VML)", "no", "no", "no", "no", _UNSUPPORTED, ["docx.image.vml"], [], ""),
    ("docx.image_layout", "docx", "Floating pictures", "preserved", "no", "preserved", "yes", _NOT_EDITABLE,
     ["docx.image.floating", "docx.image.floating_wrapped"],
     ["tests/test_docx_pictures.py::test_a_floating_picture_keeps_where_it_floats_in_a_word_export",
      "tests/test_docx_pictures.py::test_the_side_a_floating_picture_floats_to",
      "tests/test_docx_pictures.py::test_a_pdf_wraps_the_text_around_a_floating_picture_at_its_side",
      "frontend/editor/pictureLook.test.ts",
      "frontend/e2e/pictures.spec.ts"],
     "A floating picture keeps where it floats and how text wraps around it for a Word export (DOCX-018). One text wraps "
     "around (square, tight, through) floats to its side here and in a PDF, the side worked out at import from its "
     "alignment or position (ImagePlacement.side, DOCX-018A), with the text blocks after it beside it -- line by line in "
     "a PDF, block by block on the pages here (editor/floatWrap.ts) -- up to a table, a picture or a break. Behind or in "
     "front of the text, top-and-bottom and centred ones are shown in line (reported). Where it floats isn't editable here yet."),
    ("docx.list_item_images", "docx", "Pictures inside list items", "yes", "yes", "yes", "yes", _YES, [],
     ["tests/test_docx_parser.py::test_a_picture_in_a_list_item_is_the_items_block",
      "tests/test_docx_pictures.py::test_a_list_items_pictures_are_what_it_holds_and_come_back_in_its_paragraph",
      "tests/test_docx_pictures.py::test_a_list_items_picture_in_a_table_cell_is_what_the_item_holds",
      "tests/test_docx_pictures.py::test_a_pdf_draws_a_list_items_pictures_under_its_text",
      "tests/test_docx_pictures.py::test_a_pdf_draws_the_number_of_an_item_that_is_only_a_picture_beside_it",
      "tests/test_golden_documents.py::test_17_pictures",
      "frontend/e2e/pictures.spec.ts"],
     "An item's pictures are what it holds after its text (DOCX-027), in a table cell too: shown under its text here "
     "and in a PDF, and back in its own paragraph in a Word export, where Word keeps them. A numbered paragraph "
     "holding only a picture is an item too, its number beside the picture as in Word (DOCX-027A)."),
    ("docx.text_boxes", "docx", "Text boxes", "yes", "yes", "yes", "yes", _NOT_EDITABLE, ["docx.text_box"],
     ["tests/test_docx_fidelity.py::test_an_older_vml_text_box_is_a_box_too",
      "tests/test_text_boxes.py::test_a_word_text_box_is_a_box_holding_its_own_paragraphs",
      "tests/test_text_boxes.py::test_a_text_box_written_anew_is_a_word_text_box_again",
      "tests/test_text_boxes.py::test_a_pdf_draws_the_box_with_its_text",
      "frontend/editor/textBox.test.ts",
      "frontend/e2e/text-boxes.spec.ts"],
     "A text box is a block of its own after the paragraph it is anchored in (ElementType.TEXT_BOX, DOCX-019A), holding "
     "its paragraphs, lists, pictures and tables as a table cell does, with its size, outline, fill, insets, name and "
     "placement (TextBoxContent). It is a box here (its text edited in place) and in a PDF; one text wraps around floats "
     "at its side with the text beside it, as a floating picture does; others are shown after their paragraph. A Word "
     "export copies it while its paragraph is unchanged and writes a Word text box (wps) anew otherwise, floating as it "
     "did. Its exact position isn't editable here; Word's theme colours on a shape aren't read; translation skips it "
     "(said, as for any block holding blocks)."),
    ("docx.objects", "docx", "Charts, SmartArt, shapes and embedded (OLE) objects", "preserved", "no", "preserved", "yes", _NOT_EDITABLE,
     ["docx.embedded_object", "docx.chart", "docx.smartart", "docx.shape"],
     ["tests/test_docx_detect.py::test_charts_and_shapes_are_named_for_what_they_are",
      "tests/test_docx_drawings.py::test_charts_smartart_and_objects_come_back_into_a_file_written_anew",
      "tests/test_docx_drawings.py::test_a_shape_goes_back_where_it_was_in_its_text_and_on_its_own"],
     "Not shown here or in a PDF (reported, each by what it is); a Word export of the kept file puts them back from "
     "the original, where they were, even into a paragraph written anew (DOCX-019). A shape with text is a text box."),
    ("docx.symbols", "docx", "Symbol-font characters (Wingdings and the like)", "partial", "yes", "partial", "partial", _UNSUPPORTED, ["docx.symbol_characters"], [],
     "Checkbox symbols are kept; others are left out and reported."),
    ("docx.drop_caps", "docx", "Drop caps", "partial", "yes", "partial", "no", _LOSSY, ["docx.drop_cap"], [], "Shown as the normal first letter."),
    ("docx.source_package", "docx", "The original Word file: its styles, headers and footers of every kind, footnotes, properties, theme, settings",
     "yes", "no", "yes", "yes", _NOT_EDITABLE,
     ["export.docx.source_package", "export.docx.source_unreadable", "export.docx.source_missing", "export.pdf.word_only",
      "export.docx.original_blocks", "export.docx.section_lost", "export.docx.rewritten_blocks"],
     ["tests/test_source_package.py::test_a_word_export_keeps_what_the_document_model_doesnt_hold",
      "tests/test_source_package.py::test_a_stored_file_that_isnt_the_one_kept_is_not_used_and_the_export_says_so",
      "tests/test_package_check.py::test_every_export_is_a_sound_package",
      "tests/test_original_blocks.py::test_what_the_model_doesnt_hold_survives_in_unchanged_blocks",
      "tests/test_original_blocks.py::test_a_block_restyled_here_is_written_anew_and_page_breaks_keep_their_sections",
      "tests/test_original_blocks.py::test_where_a_block_came_from_is_the_servers_to_say",
      "tests/test_original_blocks.py::test_a_block_stored_before_the_model_grew_is_still_unchanged",
      "tests/test_copy_reports.py::test_a_block_written_anew_names_what_it_lost",
      "tests/test_copy_reports.py::test_a_link_the_app_doesnt_allow_is_never_copied_back",
      "frontend/e2e/kept-blocks.spec.ts"],
     "Kept as it was and written back into on a Word export: styles a template or instructions changed and a main header or "
     "footer changed in the app are rewritten (DOCX-010/011); blocks the document didn't change -- in what they hold or how "
     "they look -- are copied as they are, with their fields, content controls, formatting and section breaks, the others "
     "written anew (DOCX-028) -- and the export names what they lost, while the import report says what lives in "
     "blocks as kept while unchanged (FID-007). A block with a link the app doesn't allow is always written anew. A PDF "
     "has none of it."),
    ("docx.page_setup", "docx", "Page size, orientation and margins", "yes", "yes", "yes", "yes", _YES, ["docx.page_setup.margins", "docx.page_setup.size"],
     ["tests/test_docx_fidelity.py::test_page_size_orientation_and_margins_come_from_the_section",
      "tests/test_sections.py::test_a_last_section_on_an_unlisted_paper_size_keeps_it_in_both_exports",
      "tests/test_sections.py::test_a_page_size_chosen_here_replaces_the_unlisted_one"],
     "The document's page setup is its last section's; the other sections keep their own (docx.sections). A paper size "
     "the app doesn't list is kept as the last section's own (Document.lastSection, DOCX-015A) -- on the pages here and in "
     "both exports -- until a page size or orientation is chosen here."),
    ("docx.sections", "docx", "Several sections, columns, section break types, page numbering, page borders, line numbers", "partial", "no", "partial", "no",
     _NOT_EDITABLE,
     ["docx.layout", "docx.sections.page_setup", "docx.sections.break_type", "docx.sections.page_numbering",
      "docx.sections.page_borders", "docx.sections.line_numbers", "docx.sections.vertical_alignment"],
     ["tests/test_docx_fidelity.py::test_a_multi_column_layout_is_reported",
      "tests/test_docx_detect.py::test_a_section_break_says_how_the_next_section_starts_as_word_does",
      "tests/test_docx_detect.py::test_what_sections_change_is_reported",
      "tests/test_source_package.py::test_sections_own_properties_are_kept_and_named",
      "tests/test_original_blocks.py::test_a_page_setup_changed_here_applies_to_every_section",
      "tests/test_original_blocks.py::test_a_section_ending_in_a_changed_paragraph_is_written_from_its_section_break",
      "tests/test_sections.py::test_a_section_break_holds_how_the_next_section_starts_and_the_setup_of_the_one_it_ends",
      "tests/test_sections.py::test_a_word_export_writes_each_section_back_in_the_schemas_order",
      "tests/test_sections.py::test_a_section_written_anew_keeps_its_own_headers",
      "tests/test_sections.py::test_a_pdf_gives_each_section_its_own_pages_and_numbers",
      "tests/test_sections.py::test_the_last_sections_own_page_numbering_is_kept_in_both_exports",
      "tests/test_sections.py::test_numbers_are_counted_as_word_counts_them",
      "frontend/editor/sectionBreak.test.ts",
      "frontend/editor/sectionHeaders.test.ts",
      "frontend/editor/sectionPages.test.ts",
      "frontend/e2e/section-headers.spec.ts"],
     "Section breaks are elements of their own (DOCX-015): how the next section starts (next page, continuous, even or "
     "odd page) and the page setup of the section they end -- size, orientation, margins, header and footer distances, "
     "columns, page numbering's start and style; Document.lastSection holds the last section's. A Word export writes each "
     "back; one written into the original copies a section's other properties (page borders, line numbering, vertical "
     "alignment, pictures in its headers and footers) while its paragraph is unchanged (DOCX-028) and names them when not. "
     "A PDF follows each section's page size, orientation, margins, columns and header and footer distances, its even "
     "or odd start and its page numbering. The pages here give each section its own size, orientation, margins and "
     "header and footer distances -- its text as wide as its page's -- number it and start its even or odd pages as Word "
     "does; its columns aren't shown (one column). A deleted section break is named."),
    ("docx.headers_footers", "docx", "Headers and footers", "partial", "partial", "yes", "partial", _NOT_EDITABLE,
     ["docx.header_footer.picture", "docx.header_footer.text"],
     ["tests/test_docx_fidelity.py::test_header_and_footer_keep_their_page_number_fields",
      "tests/test_fidelity_report.py::test_every_header_a_section_shows_is_kept_and_none_is_named_as_left_out",
      "tests/test_sections.py::test_each_section_has_its_own_headers_and_footers_or_the_previous_ones",
      "tests/test_sections.py::test_a_word_export_writes_each_sections_headers_and_links_the_rest",
      "tests/test_sections.py::test_a_pdf_shows_each_page_its_sections_headers",
      "tests/test_sections.py::test_a_continuous_section_shows_its_own_header_from_the_next_page",
      "tests/test_sections.py::test_a_last_section_with_its_own_empty_header_shows_none",
      "tests/test_sections.py::test_a_text_box_in_a_header_is_read_once",
      "tests/test_golden_documents.py::test_14_section_headers",
      "tests/test_source_package.py::test_headers_of_earlier_sections_are_their_sections_own",
      "tests/test_original_blocks.py::test_a_header_changed_here_is_the_last_sections_own",
      "tests/test_original_blocks.py::test_a_header_cleared_here_shows_the_previous_sections_again",
      "tests/test_original_blocks.py::test_page_numbers_left_out_are_left_out_of_every_section",
      "tests/test_original_blocks.py::test_page_numbers_asked_for_here_are_on_every_sections_pages",
      "tests/test_sections.py::test_an_earlier_sections_header_is_edited_as_its_own_and_both_exports_follow",
      "tests/test_sections.py::test_the_last_sections_first_page_header_is_edited_into_the_original",
      "frontend/editor/sectionHeaders.test.ts",
      "frontend/e2e/section-headers.spec.ts"],
     "Every section's headers and footers -- the main ones, its first page's (with a different first page) and even pages' "
     "(with different odd and even pages) -- are kept as text with their page-number fields; one a section has none of is "
     "the previous section's, as Word's link to previous (DOCX-015). Each page here shows its own section's, numbered as "
     "its section says; a Word export writes them per section and a PDF shows them per page. The last section's main "
     "header and footer are edited in Page settings -- a text becomes its own; cleared, it shows the previous section's. "
     "Every page's header and footer is edited on the page (double-click) as its section's own, of the kind the page "
     "shows (first-page, even-page or main); \"Same as previous\" links it to the previous section's again (DOCX-015C, "
     "PUT .../section-text). Pictures in them aren't shown and are kept in the Word export only (DOCX-011, "
     "DOCX-028: earlier sections' while the paragraph ending each is unchanged). Page numbers asked for or left out apply "
     "to every section; one left out takes its header or footer with it, as in a PDF."),
    ("docx.watermark", "docx", "Watermarks", "no", "no", "partial", "partial", _NOT_EDITABLE, ["docx.watermark"],
     ["tests/test_source_package.py::test_the_import_report_says_what_the_word_export_keeps"], "Not shown here; kept in the Word export, not in a PDF (DOCX-011)."),
    ("docx.page_breaks", "docx", "Page breaks", "yes", "yes", "yes", "yes", _YES, [],
     ["tests/test_docx_fidelity.py::test_page_breaks_become_page_break_elements", "tests/test_golden_documents.py::test_11_page_breaks"], ""),
    ("docx.styles", "docx", "The document's Word styles", "partial", "yes", "partial", "partial", _LOSSY, ["docx.style.value"],
     ["tests/test_docx_fidelity.py::test_the_documents_word_styles_become_its_own_look",
      "tests/test_source_styles.py::test_a_heading_style_that_isnt_bold_stays_regular_and_unspaced",
      "tests/test_source_styles.py::test_what_the_file_leaves_unset_is_what_word_draws",
      "tests/test_source_styles.py::test_a_template_still_restyles_an_imported_document"],
     "Read into the app's style system; values outside its range are reported. What the styles leave unset is what "
     "Word draws there, never the app's defaults (FMT-004): a heading style that isn't bold stays regular."),
    ("docx.metadata", "docx", "Document properties: title, author, dates, subject, keywords", "yes", "partial", "yes", "yes", _YES, [],
     ["tests/test_docx_detect.py::test_the_files_own_properties_go_back_into_word_not_the_templates",
      "tests/test_true_fidelity.py::test_what_comes_out_is_what_went_in"],
     "Only the title can be edited in the app. A file without a title gets none made up for it by a Word export, "
     "and a file's own title isn't replaced by the name it is shown under, until the document is renamed (TEST-022)."),
    ("docx.custom_properties", "docx", "Custom document properties and sensitivity labels", "no", "no", "partial", "partial", _NOT_EDITABLE,
     ["docx.metadata.custom_properties", "docx.metadata.sensitivity_label"],
     ["tests/test_docx_detect.py::test_metadata_that_is_not_kept_is_reported_without_its_values",
      "tests/test_source_package.py::test_a_word_export_keeps_what_the_document_model_doesnt_hold"],
     "Reported without their values; not shown here, kept in the Word export written into the original file (DOCX-011), not in a PDF."),
    ("docx.rtl", "docx", "Right-to-left paragraphs", "yes", "partial", "yes", "partial", _LOSSY, ["docx.rtl"],
     ["tests/test_docx_detect.py::test_each_unkept_feature_is_named_with_an_example",
      "tests/test_paragraph_formatting.py::test_paragraph_formatting_is_read_from_the_paragraph_and_its_style"],
     "A paragraph's direction is kept (DOCX-014): drawn right to left in the editor, written back into Word, right-aligned "
     "in a PDF, which can't lay out Arabic or Hebrew yet (FONT-004). Word's right-to-left marking on runs isn't, and is "
     "reported."),
    ("docx.paragraph_borders", "docx", "Paragraph borders (a box, lines above, below or beside)", "yes", "partial", "yes", "partial", _LOSSY,
     ["export.pdf.paragraph_borders"],
     ["tests/test_paragraph_formatting.py::test_borders_and_tab_stops_are_read_from_the_paragraph_and_its_style",
      "tests/test_paragraph_formatting.py::test_a_word_export_writes_borders_and_tab_stops_back",
      "tests/test_paragraph_formatting.py::test_a_pdf_draws_a_box_or_a_line_and_names_the_rest"],
     "Kept as a border rule per side (solid, double, dotted or dashed; its width and colour), from the paragraph and its "
     "style, drawn in the editor and written back into Word (DOCX-014). Word's other border styles become solid; a "
     "border between paragraphs isn't kept. A PDF draws a box or lines above and below, and names a border on the left "
     "or right alone. They can't be set from the toolbar yet."),
    ("docx.tab_stops", "docx", "Tab stops (positions, alignment, dot leaders)", "yes", "no", "yes", "partial", _NOT_EDITABLE,
     ["docx.tab_stops", "export.pdf.tab_stops"],
     ["tests/test_paragraph_formatting.py::test_borders_and_tab_stops_are_read_from_the_paragraph_and_its_style",
      "tests/test_paragraph_formatting.py::test_a_word_export_writes_borders_and_tab_stops_back",
      "tests/test_paragraph_formatting.py::test_tabs_in_the_text_are_named_as_not_shown"],
     "Kept as a rule for the Word export (DOCX-014); the editor shows each tab as a gap of fixed width and a PDF as four "
     "spaces, and both say so."),
    ("docx.paragraph_formatting", "docx",
     "Right indent, shading, keep with next, keep lines together, widow control, contextual spacing", "yes", "partial", "yes", "yes", _YES, [],
     ["tests/test_paragraph_formatting.py::test_paragraph_formatting_is_read_from_the_paragraph_and_its_style",
      "tests/test_paragraph_formatting.py::test_a_word_export_writes_them_back_in_the_schemas_order",
      "tests/test_paragraph_formatting.py::test_a_pdf_follows_them",
      "tests/test_paragraph_formatting.py::test_contextual_spacing_closes_up_paragraphs_of_the_same_kind_in_a_pdf"],
     "Kept as formatting rules from the paragraph and its style (DOCX-014), drawn with CSS's own properties (break-after, "
     "break-inside, widows), written back into Word and followed by the PDF. The editor draws shading and indents; its "
     "pages don't follow the pagination controls yet. They can't be set from the toolbar yet."),
    ("docx.preserved_inside_blocks", "docx", "Equations, fields, bookmarks or comments inside lists, tables, footnotes or code", "partial", "yes", "partial", "partial",
     _LOSSY, ["docx.preserved.flattened"], ["tests/test_docx_preservation.py::test_what_sits_inside_a_table_is_kept_only_as_text_and_said_so"], "Kept as their text."),
    ("docx.other", "docx", "Other Word features the importer notes", "partial", "n/a", "n/a", "n/a", _LOSSY, ["docx.other"], [], ""),
    # -- PDF ------------------------------------------------------------------------------
    ("pdf.export_text", "pdf", "Text with embedded fonts (Latin, Cyrillic, Greek)", "n/a", "n/a", "yes", "n/a", _YES, [],
     ["tests/test_export_round_trip.py::test_pdf_has_real_cyrillic_text_and_filled_in_page_numbers",
      "tests/test_export_fidelity.py::test_both_exports_of_a_plain_document_are_verified_word_for_word"],
     "Every PDF export is read back and checked word by word."),
    ("pdf.scripts", "pdf", "Arabic, Hebrew, Devanagari, Thai, CJK text and emoji", "n/a", "n/a", "yes", "n/a", _LOSSY,
     ["export.pdf.script", "export.pdf.text_layer"],
     ["tests/test_multilingual.py::test_each_script_is_drawn_in_a_font_that_has_it_or_said_not_to_be",
      "tests/test_multilingual.py::test_arabic_is_shaped_and_right_to_left_text_is_laid_out_and_aligned_right_to_left",
      "tests/test_multilingual.py::test_each_script_run_gets_a_font_that_draws_it",
      "tests/test_export_fidelity.py::test_text_no_installed_font_draws_is_reported_and_caught_by_the_check"],
     "Each script run in an installed, embeddable font that has it (FontResolver, FONT-001/002); Arabic, Hebrew, Devanagari "
     "and Thai shaped (HarfBuzz); right-to-left paragraphs laid out and aligned right to left (FONT-003). What no installed "
     "font draws is named; Devanagari and Thai look right but can't be copied out as text, and that is said. Colour emoji "
     "are drawn in a monochrome symbol font where one has them."),
    ("docx.script_fonts", "docx", "Per-script fonts, languages and direction in Word exports", "n/a", "n/a", "yes", "n/a", _YES, [],
     ["tests/test_multilingual.py::test_word_runs_carry_their_scripts_fonts_languages_and_direction"],
     "w:rFonts eastAsia and cs, w:lang eastAsia and bidi, w:rtl, w:bCs/w:iCs on runs; w:bidi on a paragraph led by "
     "right-to-left text (FONT-004)."),
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
    ("pdf.import_text", "pdf", "Text of text-based PDFs", "yes", "yes", "n/a", "n/a", _LOSSY,
     ["pdf.layout", "pdf.note", "pdf.damaged", "pdf.text_reads_differ", "pdf.unreadable_characters"],
     ["tests/test_fidelity_report.py::test_a_pdf_upload_says_its_structure_was_rebuilt_from_its_layout",
      "tests/test_pdf_structure.py::test_every_word_is_kept_and_checked",
      "tests/test_pdf_inspection.py::test_the_editable_import_keeps_every_word_the_text_read_finds",
      "tests/test_malformed_pdfs.py::test_a_malformed_pdf_is_read_whole_read_with_its_loss_said_or_refused"],
     "Read twice: the text read (pypdf) and the layout read (pdfminer). The rebuilt document is checked word by word "
     "against the layout's lines, and those against the text read's words: any the layout read missed are named. A damaged "
     "PDF's readable text is imported, and the damage said to have cost text (SEC-011)."),
    ("pdf.import_structure", "pdf", "Headings, paragraphs, lists, captions, columns, running headers and page numbers of "
     "text-based PDFs, rebuilt from where the text sits", "partial", "yes", "n/a", "n/a", _LOSSY,
     ["pdf.running_header", "pdf.running_footer", "pdf.page_numbers", "pdf.list_markers", "pdf.structure_not_rebuilt", "pdf.unruled_tables"],
     ["tests/test_pdf_structure.py::test_the_structure_fixture", "tests/test_pdf_structure.py::test_two_columns_are_read_one_after_the_other",
      "tests/test_pdf_structure.py::test_text_pdf_headings_paragraphs_links_and_colours",
      "tests/test_pdf_structure.py::test_turned_pages_are_read_in_their_text_s_direction",
      "tests/test_pdf_structure.py::test_when_the_layout_read_finds_less_text_than_the_text_read_the_text_is_used",
      "tests/test_pdf_structure.py::test_the_layout_is_kept_through_saves_and_never_taken_from_the_editor",
      "tests/test_pdf_tables.py::test_a_ruled_table_cell_by_cell", "tests/test_pdf_tables.py::test_merged_cells",
      "tests/test_pdf_tables.py::test_columns_of_space_alone_stay_text_and_are_said_to"],
     "Deterministic, no AI (P2E-002): reading order by an XY cut with columns; headings by size and weight; lists by "
     "bullets, numbers and indents (numbers that don't count on stay text); captions; bold, italic, colours and web links; "
     "a paragraph running on to the next column or page. Each block keeps its page, box, rotation and column (ElementLayout, "
     "P2E-001) and a confidence. Tables drawn with lines are rebuilt cell by cell, merged cells and header rows included "
     "(P2E-004); columns set by space alone stay a paragraph a row, reported. A file the layout read can't fully stand "
     "behind is imported as its text, and the report says why."),
    ("pdf.conversion_confidence", "pdf", "How sure a PDF conversion is: each block, each aspect (text, paragraphs, headings, lists, "
     "captions, tables, columns, pictures, reading order) and in all", "yes", "n/a", "n/a", "n/a", _NOT_EDITABLE, [],
     ["tests/test_pdf_conversion.py::test_the_structure_fixture_s_conversion",
      "tests/test_pdf_conversion.py::test_what_isn_t_rebuilt_yet_holds_the_confidence_down"],
     "Document.pdfConversion, kept as imported (P2E-005); a block's own is Element.confidence. Under 0.6 is marked for a look."),
    ("pdf.import_layout", "pdf", "A PDF imported layout-focused: each page a page, the text in its own fonts and sizes", "partial", "yes", "n/a",
     "n/a", _LOSSY, [],
     ["tests/test_pdf_import_modes.py::test_layout_focused_keeps_the_pages_and_the_look",
      "tests/test_pdf_import_modes.py::test_the_choice_travels_through_the_upload_and_the_import_job",
      "frontend/editor/panels/FidelityPanel.test.tsx", "frontend/e2e/workflows.spec.ts"],
     "Chosen at upload (brief §93, P2E-007): a page break where each PDF page began, no paragraph run on across one, fonts "
     "and sizes as text style. Nothing sits at its exact place on the page (frames are P2E-020). The Fidelity panel shows "
     "\"Imported from PDF\", the mode and the conversion's confidence aspect by aspect."),
    ("pdf.import_extras", "pdf", "Notes, highlights, form fields, the outline and links to places in imported PDFs", "no", "n/a", "n/a", "n/a",
     _UNSUPPORTED, ["pdf.annotations", "pdf.form_fields", "pdf.outline", "pdf.links"],
     ["tests/test_pdf_conversion.py::test_what_the_pdf_holds_that_the_document_doesn_t_is_said"],
     "Reported, with how many, never dropped silently (P2E-005): a form's labels come in as text, its fields and their "
     "values don't; web links are kept, links into the file and unsafe ones come in as their text."),
    ("pdf.import_images", "pdf", "Pictures in imported PDFs", "yes", "yes", "n/a", "n/a", _LOSSY,
     ["pdf.images", "pdf.picture_position", "pdf.running_pictures", "pdf.scan_backgrounds"],
     ["tests/test_pdf_pictures.py::test_pictures_go_in_where_they_stood", "tests/test_pdf_pictures.py::test_a_picture_past_the_limits_is_reported_not_decoded",
      "tests/test_pdf_structure.py::test_a_text_layer_over_a_scan_says_so"],
     "Placed in the text where they stood, at their size (no wider than the text), stored as assets (P2E-003); a scanned "
     "page with no text comes in as its picture. A logo repeated in the header or footer, the scan under a text layer, a "
     "rule or a dot, and any picture past the decoding limits or unreadable are reported, never dropped silently."),
    ("pdf.scanned", "pdf", "Scanned PDFs (no text layer)", "no", "n/a", "n/a", "n/a", _BLOCKED, [],
     ["tests/test_pdf_parser.py::test_blank_pdf_raises_pdf_parse_error", "tests/test_pdf_inspection.py::test_a_scanned_pdf_is_still_refused"],
     "Refused with a message rather than imported empty while no OCR provider is configured (the default); with one, read "
     "by it (pdf.ocr)."),
    ("pdf.ocr", "pdf", "Scanned pages read by OCR", "partial", "yes", "n/a", "n/a", _LOSSY, ["pdf.ocr", "pdf.ocr_failed"],
     ["tests/test_ocr.py::test_a_scan_is_read_by_ocr_into_paragraphs", "tests/test_ocr.py::test_what_an_engine_gives_back_is_made_safe",
      "tests/test_ocr.py::test_an_engine_that_fails_costs_that_page_and_says_so"],
     "Behind a provider interface (app/ocr, P2E-006): words with confidence, box, page, language/script; untrusted, made "
     "safe; blocks no surer than the engine. No engine is configured by default: which one (local Tesseract, a cloud "
     "service) is the owner's choice."),
    ("pdf.scanned_pages", "pdf", "Scanned pages in a PDF that has text elsewhere", "no", "n/a", "n/a", "n/a", _UNSUPPORTED, ["pdf.scanned_pages"],
     ["tests/test_pdf_inspection.py::test_a_pdf_upload_carries_its_inspection_and_says_what_its_pages_are"],
     "Found by the page classifier (PDF-011) and reported with their numbers; the page comes in as its picture (P2E-003), "
     "its words as text only when an OCR provider is configured (P2E-006)."),
    ("pdf.hybrid_pages", "pdf", "Scanned pages under a text layer (PDFs run through OCR)", "partial", "yes", "n/a", "n/a", _LOSSY,
     ["pdf.hybrid_pages"],
     ["tests/test_pdf_inspection.py::test_a_pdf_upload_carries_its_inspection_and_says_what_its_pages_are",
      "tests/test_pdf_geometry.py::test_scanned_and_hybrid_pages_with_their_evidence"],
     "The text layer's words are imported as they are, and the page reported: they may hold the mistakes of whatever read "
     "the scan (PDF-011)."),
    ("pdf.inspection", "pdf", "What is on each page: its kind, fonts, colours, lines, pictures, links, annotations, boxes and "
     "rotation; the outline, form fields and metadata", "yes", "n/a", "n/a", "n/a", _NOT_EDITABLE, [],
     ["tests/test_pdf_inspection.py::test_each_fixture_is_inspected_page_by_page",
      "tests/test_pdf_geometry.py::test_each_fixture_page_by_page", "tests/test_pdf_geometry.py::test_links_annotations_outline_and_metadata"],
     "Kept with the imported document as its PDF inspection (PDF-010..012); the same read gives the structure "
     "reconstruction its lines (P2E-002). Metadata by name only, form fields without values, links counted."),
    # -- translation ----------------------------------------------------------------------
    ("translation.blocks", "translation", "Blocks, list items, table cells or part of a block's text translated as proposals", "n/a", "yes",
     "n/a", "n/a", _LOSSY, [],
     ["tests/test_translation_api.py::test_blocks_are_proposed_with_their_formatting_and_accepted_one_by_one",
      "tests/test_translation_api.py::test_items_cells_and_part_of_a_block_and_what_isnt_translated",
      "tests/test_translation_api.py::test_a_translation_that_changes_a_fact_is_never_proposed",
      "tests/test_translation_core.py::test_formatting_travels_as_tags_and_comes_back_exactly", "frontend/e2e/translation.spec.ts"],
     "Segments keep their formatting as tags (TRAN-001); every answer is checked for tags, numbers, percentages, units, "
     "identifiers and locked glossary terms (TRAN-003); what passes is a proposal, original against translation, applied "
     "only when accepted and undoable (TRAN-005). Code, nested blocks and Word fields placed by the text aren't "
     "translated, and are named. \"AI-assisted translation -- review required\", never certified."),
    ("translation.document", "translation", "A whole document translated as a new version linked to the original", "n/a", "yes", "n/a", "n/a",
     _LOSSY, ["translation.ai_assisted", "translation.kept_original", "translation.not_translated"],
     ["tests/test_translation_api.py::test_a_whole_document_becomes_a_translated_version_and_the_original_stays",
      "frontend/e2e/translation.spec.ts"],
     "TRAN-006: the original is never changed; the version (metadata.translatedFrom) has its own copies of the pictures "
     "and a report of what kept its original text and why. Translation characters are a plan unit (TRAN-009)."),
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
    ("text.unsafe_links", "text", "Links to addresses a document can't open (relative ones, javascript:, file:...)", "no", "no", "no", "n/a", _LOSSY,
     ["markdown.link.unsafe"],
     ["tests/test_link_policy.py::test_a_link_keeps_only_an_address_a_document_can_open",
      "tests/test_link_policy.py::test_markdown_links_to_other_addresses_keep_their_text_and_are_said_to"],
     "Kept as plain text. One policy for every link (SEC-014): the model keeps no other address, whoever sends it, and "
     "neither export writes one as a live link."),
    ("text.markdown_images", "text", "Pictures in Markdown text", "no", "n/a", "n/a", "n/a", _UNSUPPORTED, ["markdown.image"],
     ["tests/test_markdown_parser.py::test_pictures_are_named_as_left_out_not_dropped_silently"],
     "Named as left out, with their description: the app doesn't fetch pictures from web addresses."),
    ("text.control_characters", "text", "Control codes in text (a PDF's broken font, pasted text)", "no", "no", "n/a", "n/a", _UNSUPPORTED,
     ["text.control_characters"],
     ["tests/test_malformed_pdfs.py::test_control_codes_never_reach_a_document_and_are_said_to_be_left_out"],
     "No document can hold them (XML can't): left out on import and said to be, and never kept from the editor or the AI "
     "(SEC-023) -- they made a Word export fail."),
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
