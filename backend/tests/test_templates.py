import json

import pytest
from pydantic import ValidationError

from app.formatting import templates as templates_module
from app.formatting.priorities import Priority
from app.formatting.templates import BUILTIN_TEMPLATES


def test_builtins_load_in_file_order():
    raw = json.loads(templates_module._DATA_FILE.read_text(encoding="utf-8"))
    assert list(BUILTIN_TEMPLATES) == [item["id"] for item in raw]
    assert list(BUILTIN_TEMPLATES)[:3] == ["academic-default", "professional-cv", "official-standard"]


def test_every_builtin_has_a_name_category_and_rules_at_the_builtin_tier():
    for template_id, template in BUILTIN_TEMPLATES.items():
        assert template.id == template_id
        assert template.name.strip() and template.category.strip()
        assert template.rules, f"{template_id} sets nothing"
        assert {(rule.priority, rule.source) for rule in template.rules} == {(Priority.BUILTIN_TEMPLATE, "template")}


def test_a_typo_in_the_builtin_file_stops_the_app_from_loading(tmp_path, monkeypatch):
    broken = tmp_path / "builtin_templates.json"
    broken.write_text(
        json.dumps([{"id": "x", "name": "X", "category": "c", "styleSystem": {"paragraf": {}}}]), encoding="utf-8"
    )
    monkeypatch.setattr(templates_module, "_DATA_FILE", broken)

    with pytest.raises(ValidationError):
        templates_module._load_builtin_templates()


def test_a_repeated_builtin_id_stops_the_app_from_loading(tmp_path, monkeypatch):
    entry = {"id": "same", "name": "X", "category": "c", "styleSystem": {}}
    duplicated = tmp_path / "builtin_templates.json"
    duplicated.write_text(json.dumps([entry, entry]), encoding="utf-8")
    monkeypatch.setattr(templates_module, "_DATA_FILE", duplicated)

    with pytest.raises(ValueError, match="repeats a template id"):
        templates_module._load_builtin_templates()
