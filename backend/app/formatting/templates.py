import logging
import os
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, Field

from app.formatting.engine import PRIORITY_BUILTIN_TEMPLATE, PRIORITY_CUSTOM_TEMPLATE
from app.models.document import FormattingProperty, FormattingRule

logger = logging.getLogger(__name__)


class Template(BaseModel):
    id: str
    name: str
    category: str
    description: str = ""
    rules: list[FormattingRule] = Field(default_factory=list)


def _rule(target: str, property: FormattingProperty, value: str, unit: str | None = None) -> FormattingRule:
    return FormattingRule(
        target=target, property=property, value=value, unit=unit, priority=PRIORITY_BUILTIN_TEMPLATE, source="template"
    )


BUILTIN_TEMPLATES: dict[str, Template] = {
    "academic-default": Template(
        id="academic-default",
        name="Академичен (по подразбиране)",
        category="academic",
        description="Курсова работа / реферат / дипломна работа -- Times New Roman, 1.5 междуредие, обосновани абзаци.",
        rules=[
            _rule("Paragraph", FormattingProperty.FONT_FAMILY, "Times New Roman"),
            _rule("Paragraph", FormattingProperty.FONT_SIZE, "12", "pt"),
            _rule("Paragraph", FormattingProperty.ALIGNMENT, "justify"),
            _rule("Paragraph", FormattingProperty.LINE_SPACING, "1.5"),
            _rule("Paragraph", FormattingProperty.FIRST_LINE_INDENT, "1.25", "cm"),
            _rule("Heading 1", FormattingProperty.FONT_FAMILY, "Times New Roman"),
            _rule("Heading 1", FormattingProperty.FONT_SIZE, "14", "pt"),
            _rule("Heading 1", FormattingProperty.BOLD, "true"),
            _rule("Heading 2", FormattingProperty.FONT_FAMILY, "Times New Roman"),
            _rule("Heading 2", FormattingProperty.FONT_SIZE, "13", "pt"),
            _rule("Heading 2", FormattingProperty.BOLD, "true"),
            _rule("Heading 3", FormattingProperty.FONT_FAMILY, "Times New Roman"),
            _rule("Heading 3", FormattingProperty.FONT_SIZE, "12", "pt"),
            _rule("Heading 3", FormattingProperty.BOLD, "true"),
            _rule("Heading 3", FormattingProperty.ITALIC, "true"),
            _rule("Document", FormattingProperty.PAGE_SIZE, "A4"),
            _rule("Document", FormattingProperty.ORIENTATION, "portrait"),
            _rule("Document", FormattingProperty.MARGIN_TOP, "2", "cm"),
            _rule("Document", FormattingProperty.MARGIN_BOTTOM, "2", "cm"),
            _rule("Document", FormattingProperty.MARGIN_LEFT, "3", "cm"),
            _rule("Document", FormattingProperty.MARGIN_RIGHT, "2", "cm"),
        ],
    ),
    "professional-cv": Template(
        id="professional-cv",
        name="Професионален (CV)",
        category="professional",
        description="CV / мотивационно писмо / доклад -- Calibri, компактно междуредие, ляво подравняване.",
        rules=[
            _rule("Paragraph", FormattingProperty.FONT_FAMILY, "Calibri"),
            _rule("Paragraph", FormattingProperty.FONT_SIZE, "11", "pt"),
            _rule("Paragraph", FormattingProperty.ALIGNMENT, "left"),
            _rule("Paragraph", FormattingProperty.LINE_SPACING, "1.15"),
            _rule("Heading 1", FormattingProperty.FONT_FAMILY, "Calibri"),
            _rule("Heading 1", FormattingProperty.FONT_SIZE, "16", "pt"),
            _rule("Heading 1", FormattingProperty.BOLD, "true"),
            _rule("Heading 2", FormattingProperty.FONT_FAMILY, "Calibri"),
            _rule("Heading 2", FormattingProperty.FONT_SIZE, "12", "pt"),
            _rule("Heading 2", FormattingProperty.BOLD, "true"),
            _rule("Document", FormattingProperty.PAGE_SIZE, "A4"),
            _rule("Document", FormattingProperty.ORIENTATION, "portrait"),
            _rule("Document", FormattingProperty.MARGIN_TOP, "2", "cm"),
            _rule("Document", FormattingProperty.MARGIN_BOTTOM, "2", "cm"),
            _rule("Document", FormattingProperty.MARGIN_LEFT, "2", "cm"),
            _rule("Document", FormattingProperty.MARGIN_RIGHT, "2", "cm"),
        ],
    ),
    "official-standard": Template(
        id="official-standard",
        name="Официален документ",
        category="official",
        description="Молба / заявление / жалба -- Times New Roman, единично междуредие, без отстъп на нов абзац.",
        rules=[
            _rule("Paragraph", FormattingProperty.FONT_FAMILY, "Times New Roman"),
            _rule("Paragraph", FormattingProperty.FONT_SIZE, "12", "pt"),
            _rule("Paragraph", FormattingProperty.ALIGNMENT, "justify"),
            _rule("Paragraph", FormattingProperty.LINE_SPACING, "1"),
            _rule("Heading 1", FormattingProperty.FONT_FAMILY, "Times New Roman"),
            _rule("Heading 1", FormattingProperty.FONT_SIZE, "13", "pt"),
            _rule("Heading 1", FormattingProperty.BOLD, "true"),
            _rule("Document", FormattingProperty.PAGE_SIZE, "A4"),
            _rule("Document", FormattingProperty.ORIENTATION, "portrait"),
            _rule("Document", FormattingProperty.MARGIN_TOP, "2.5", "cm"),
            _rule("Document", FormattingProperty.MARGIN_BOTTOM, "2.5", "cm"),
            _rule("Document", FormattingProperty.MARGIN_LEFT, "2.5", "cm"),
            _rule("Document", FormattingProperty.MARGIN_RIGHT, "2.5", "cm"),
        ],
    ),
}


class UnknownTemplateError(Exception):
    def __init__(self, template_id: str) -> None:
        super().__init__(f"Unknown template id: {template_id!r}")


# File-based, same lightweight pattern as services/persistence.py (one JSON
# file per template, atomic temp+replace write, best-effort load skipping a
# corrupt file) -- kept self-contained here rather than sharing that other
# module's functions, to avoid a persistence.py <-> templates.py import
# cycle for what Phase 3/7 will replace with real DB-backed persistence
# anyway. Deliberately not sharing storage with BUILTIN_TEMPLATES so a
# custom id can never silently shadow a built-in one.
_CUSTOM_TEMPLATES_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "custom_templates"


def _custom_template_path(template_id: str) -> Path:
    return _CUSTOM_TEMPLATES_DIR / f"{template_id}.json"


def _save_custom_template(template: Template) -> None:
    _CUSTOM_TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    target = _custom_template_path(template.id)
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(template.model_dump_json(), encoding="utf-8")
    os.replace(tmp, target)


def _load_custom_templates() -> dict[str, Template]:
    templates: dict[str, Template] = {}
    if not _CUSTOM_TEMPLATES_DIR.exists():
        return templates
    for path in _CUSTOM_TEMPLATES_DIR.glob("*.json"):
        try:
            template = Template.model_validate_json(path.read_text(encoding="utf-8"))
        except Exception:
            logger.exception("Failed to load persisted custom template from %s -- skipping", path)
            continue
        templates[template.id] = template
    return templates


_custom_templates: dict[str, Template] = _load_custom_templates()


def create_custom_template(name: str, category: str, description: str, rules: list[FormattingRule]) -> Template:
    template = Template(
        id=str(uuid4()),
        name=name,
        category=category,
        description=description,
        rules=[rule.model_copy(update={"priority": PRIORITY_CUSTOM_TEMPLATE, "source": "custom_template"}) for rule in rules],
    )
    _custom_templates[template.id] = template
    _save_custom_template(template)
    return template


def list_all_templates() -> list[Template]:
    return [*BUILTIN_TEMPLATES.values(), *_custom_templates.values()]


def get_template(template_id: str) -> Template:
    template = BUILTIN_TEMPLATES.get(template_id) or _custom_templates.get(template_id)
    if template is None:
        raise UnknownTemplateError(template_id)
    return template
