"""Repair document (tracker REV-004, brief §60): what is broken in a document, by kind --
numbering, inconsistent styles, tables, links, structures the app doesn't hold, malformed input
-- each with its proposed fix where one can be worked out. Detected issue, proposed fix, preview,
apply: the findings are Document Health's deterministic checks (health.py), the fixes its
proposals (health_fixes.py) -- each shown with the block as it would be, applied only when
accepted, to the block as it was checked (the Review panel, REV-002). Nothing here changes the
document; no AI is involved."""

from typing import Literal

from app.formatting.health import HealthCheck, check_health
from app.models.base import ApiModel
from app.models.document import Document

RepairKind = Literal["numbering", "styles", "tables", "links", "structures", "input"]

# Each Health check by the kind of repair it is, in the brief's order.
_KINDS: dict[str, RepairKind] = {
    "numbering": "numbering",
    "lists": "numbering",
    "hierarchy": "numbering",
    "fonts": "styles",
    "heading_sizes": "styles",
    "spacing": "styles",
    "direct_formatting": "styles",
    "duplicated_formatting": "styles",
    "alignment": "styles",
    "layout": "styles",
    "tables": "tables",
    "broken_tables": "tables",
    "links": "links",
    "unsupported": "structures",
    "sections": "structures",
    "page_breaks": "structures",
    "empty_paragraphs": "structures",
}
TITLES: dict[RepairKind, str] = {
    "numbering": "Numbering and headings",
    "styles": "Inconsistent styles",
    "tables": "Tables",
    "links": "Links",
    "structures": "What the app doesn't hold",
    "input": "Malformed input",
}


class RepairIssue(ApiModel):
    kind: RepairKind
    checkId: str
    title: str
    status: Literal["warn", "fail"]
    summary: str
    elementIds: list[str]
    # How many fixes can be proposed for it now (0: none can be worked out -- see the summary).
    fixes: int


class RepairReport(ApiModel):
    issues: list[RepairIssue]
    fixes: int


def _input_issue(document: Document) -> RepairIssue | None:
    """The import's own check of the words found them changed: the file was damaged or read wrong."""
    report = document.importReport
    if report is None or report.content is None or report.content.verified:
        return None
    content = report.content
    summary = f"The import's text differs from the file's: {content.missing} words missing, {content.added} added, {content.moved} moved. Compare it with the original (Проверка)."
    return RepairIssue(kind="input", checkId="import_content", title="The file's text", status="fail", summary=summary, elementIds=[], fixes=0)


def _issue(check: HealthCheck) -> RepairIssue:
    ids = list(dict.fromkeys(element_id for issue in check.issues for element_id in issue.elementIds))[:100]
    return RepairIssue(kind=_KINDS[check.id], checkId=check.id, title=check.title, status=check.status, summary=check.summary, elementIds=ids, fixes=check.fixes)


def repair_report(document: Document) -> RepairReport:
    """Every problem a repair is for, in the brief's order of kinds, with how many fixes it has."""
    found = [_issue(check) for check in check_health(document).checks if check.id in _KINDS and check.status in ("warn", "fail")]
    if (problem := _input_issue(document)) is not None:
        found.append(problem)
    order = list(TITLES)
    found.sort(key=lambda issue: (order.index(issue.kind), issue.status != "fail"))
    return RepairReport(issues=found, fixes=sum(issue.fixes for issue in found))


def repair_check_ids(report: RepairReport) -> list[str]:
    """The checks whose fixes a "repair everything" proposes."""
    return [issue.checkId for issue in report.issues if issue.fixes]
