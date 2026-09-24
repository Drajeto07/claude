"""Built-in templates: declarative StyleSystem data in builtin_templates.json,
validated when this module loads, so a broken entry stops the app at startup
instead of failing when someone picks it. Workspace/user templates live in the
database (services/template_service.py)."""

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from app.formatting.priorities import Priority
from app.formatting.style_system import StyleSystem, compile_rules
from app.models.document import FormattingRule

_DATA_FILE = Path(__file__).with_name("builtin_templates.json")


class BuiltinTemplate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    name: str
    category: str
    description: str = ""
    styleSystem: StyleSystem

    @property
    def rules(self) -> list[FormattingRule]:
        return compile_rules(self.styleSystem, priority=Priority.BUILTIN_TEMPLATE, source="template")


def _load_builtin_templates() -> dict[str, BuiltinTemplate]:
    templates = [BuiltinTemplate.model_validate(item) for item in json.loads(_DATA_FILE.read_text(encoding="utf-8"))]
    by_id = {template.id: template for template in templates}
    if len(by_id) != len(templates):
        raise ValueError(f"{_DATA_FILE.name} repeats a template id")
    return by_id


# In file order: the order the template gallery shows them in.
BUILTIN_TEMPLATES: dict[str, BuiltinTemplate] = _load_builtin_templates()


class UnknownTemplateError(Exception):
    def __init__(self, template_id: str) -> None:
        super().__init__(f"Unknown template id: {template_id!r}")
