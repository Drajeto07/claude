"""Font fallbacks (tracker FONT-005): what stands in for a font that isn't installed -- the fonts
made with its widths first (Carlito for Calibri, Liberation Sans for Arial...), then the best of
its kind -- one list for the PDF export and the editor's CSS stacks (frontend/editor/fontFallbacks.json,
written from app/export/fonts.py)."""

from unittest import mock

from app.export import fonts
from app.export.fonts import fallback_stack, font_kind


def test_a_fonts_stand_ins_are_the_ones_made_with_its_widths_then_its_kind():
    assert fallback_stack("Calibri")[:3] == ["Calibri", "Carlito", "Arial"]
    assert fallback_stack("cambria")[:3] == ["cambria", "Caladea", "Times New Roman"]  # matched in any case
    assert fallback_stack("Courier New")[:3] == ["Courier New", "Liberation Mono", "Cousine"]
    assert fallback_stack("Aptos")[:2] == ["Aptos", "Arial"]  # no font of its widths: its kind's
    assert fallback_stack(None)[0] == "Arial"
    stack = fallback_stack("Arial")
    assert len(stack) == len({name.lower() for name in stack})  # each once


def test_constantia_is_a_serif_as_the_editor_always_said():
    assert font_kind("Constantia") == "serif" and font_kind("Segoe UI") == "sans" and font_kind("Consolas") == "mono"


def test_the_pdf_export_draws_a_metric_compatible_font_before_its_kind():
    fonts.resolved_family.cache_clear()
    installed = {"Carlito", "Arial"}
    try:
        with mock.patch.object(fonts, "_register", side_effect=lambda family: object() if family in installed else None):
            assert fonts.resolved_family("Calibri") == "Carlito"  # not Arial: Carlito breaks lines as Calibri does
            assert fonts.resolved_family("Aptos") == "Arial"
    finally:
        fonts.resolved_family.cache_clear()


def test_the_editors_copy_is_current():
    from scripts.export_font_fallbacks import TARGET, font_fallbacks_json

    assert TARGET.read_text(encoding="utf-8") == font_fallbacks_json(), "python -m scripts.export_font_fallbacks"
