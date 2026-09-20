import pytest

from app.formatting.templates import (
    BUILTIN_TEMPLATES,
    UnknownTemplateError,
    create_custom_template,
    get_template,
    list_all_templates,
)
from app.models.document import FormattingProperty, FormattingRule

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
