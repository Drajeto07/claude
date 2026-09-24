from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.formatting.templates import create_custom_template, list_all_templates
from app.models.document import FormattingRule
from app.schemas.formatting import CreateTemplateRequest, TemplateSummary

# Signed-in only. Custom templates are still one global list shared by every
# account until Phase 7 moves them into per-workspace DB storage.
router = APIRouter(dependencies=[Depends(get_current_user)])


@router.get("", response_model=list[TemplateSummary])
def list_templates() -> list[TemplateSummary]:
    return [TemplateSummary.from_template(template) for template in list_all_templates()]


@router.post("", response_model=TemplateSummary, status_code=201)
def create_template(payload: CreateTemplateRequest) -> TemplateSummary:
    rules = [
        FormattingRule(target=rule.target, property=rule.property, value=rule.value, unit=rule.unit)
        for rule in payload.rules
    ]
    template = create_custom_template(payload.name, payload.category, payload.description, rules)
    return TemplateSummary.from_template(template)
