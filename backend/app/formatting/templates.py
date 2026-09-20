from uuid import uuid4

from pydantic import BaseModel, Field

from app.formatting.engine import PRIORITY_BUILTIN_TEMPLATE, PRIORITY_CUSTOM_TEMPLATE
from app.models.document import FormattingProperty, FormattingRule


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


# In-memory only, same MVP no-persistence rule as document_service -- gone on
# server restart, and deliberately not sharing storage with BUILTIN_TEMPLATES
# so a custom id can never silently shadow a built-in one.
_custom_templates: dict[str, Template] = {}


def create_custom_template(name: str, category: str, description: str, rules: list[FormattingRule]) -> Template:
    template = Template(
        id=str(uuid4()),
        name=name,
        category=category,
        description=description,
        rules=[rule.model_copy(update={"priority": PRIORITY_CUSTOM_TEMPLATE, "source": "custom_template"}) for rule in rules],
    )
    _custom_templates[template.id] = template
    return template


def list_all_templates() -> list[Template]:
    return [*BUILTIN_TEMPLATES.values(), *_custom_templates.values()]


def get_template(template_id: str) -> Template:
    template = BUILTIN_TEMPLATES.get(template_id) or _custom_templates.get(template_id)
    if template is None:
        raise UnknownTemplateError(template_id)
    return template
