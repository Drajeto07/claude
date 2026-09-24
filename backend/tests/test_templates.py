import pytest

from app.formatting import templates as templates_module
from app.formatting.templates import (
    BUILTIN_TEMPLATES,
    Template,
    UnknownTemplateError,
    create_custom_template,
    get_template,
    list_all_templates,
)
from app.models.document import FormattingProperty, FormattingRule


@pytest.fixture(autouse=True)
def _isolate_custom_templates_dir(tmp_path, monkeypatch):
    """Every test in this file that touches create_custom_template must not
    write into the real backend/data/custom_templates/ -- same isolation
    convention as test_persistence.py's _DATA_DIR redirection."""
    monkeypatch.setattr(templates_module, "_CUSTOM_TEMPLATES_DIR", tmp_path)
    monkeypatch.setattr(templates_module, "_custom_templates", {})

_VALID_CATEGORIES = {"academic", "professional", "official"}


def test_every_builtin_template_has_rules_and_a_valid_category():
    for template_id, template in BUILTIN_TEMPLATES.items():
        assert template.id == template_id
        assert template.rules, f"{template_id} has no rules"
        assert template.category in _VALID_CATEGORIES


def test_get_template_raises_for_unknown_id():
    with pytest.raises(UnknownTemplateError):
        get_template("does-not-exist")


def test_get_template_returns_builtin():
    template = get_template("academic-default")
    assert template.name


def test_custom_template_create_and_list_round_trip():
    rule = FormattingRule(target="Paragraph", property=FormattingProperty.FONT_FAMILY, value="Georgia")

    template = create_custom_template("My Template", "academic", "desc", [rule])

    assert get_template(template.id).name == "My Template"
    assert template.id in {t.id for t in list_all_templates()}
    # Priority/source are engine-controlled, not client-supplied.
    assert template.rules[0].source == "custom_template"
    assert template.rules[0].value == "Georgia"


def test_create_custom_template_writes_a_real_file():
    rule = FormattingRule(target="Paragraph", property=FormattingProperty.FONT_FAMILY, value="Georgia")

    template = create_custom_template("My Template", "academic", "desc", [rule])

    saved_path = templates_module._custom_template_path(template.id)
    assert saved_path.exists()


def test_custom_template_survives_a_fresh_load_from_disk():
    rule = FormattingRule(target="Paragraph", property=FormattingProperty.FONT_FAMILY, value="Georgia")
    template = create_custom_template("My Template", "academic", "desc", [rule])

    # Simulates a server restart: a brand-new read of the directory, not the
    # already-populated in-memory _custom_templates dict.
    reloaded = templates_module._load_custom_templates()

    assert template.id in reloaded
    assert reloaded[template.id].name == "My Template"
    assert reloaded[template.id].rules[0].value == "Georgia"


def test_load_custom_templates_skips_a_corrupt_file_without_raising(tmp_path):
    (tmp_path / "corrupt.json").write_text("{not valid json", encoding="utf-8")

    assert templates_module._load_custom_templates() == {}


def test_save_custom_template_is_atomic_no_tmp_file_left_behind(tmp_path):
    template = Template(id="t1", name="X", category="academic", rules=[])

    templates_module._save_custom_template(template)

    files = list(tmp_path.glob("*"))
    assert len(files) == 1
    assert files[0].suffix == ".json"
