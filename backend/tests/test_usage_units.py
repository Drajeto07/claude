"""Usage units and plans as data (tracker PLAN-001, PLAN-002): every unit a plan can
limit is defined once (billing/units.py), GET /usage and GET /billing list each with
the plan's limit, every entitlement the code reads is defined for every plan in
billing/plans.json, and no code compares a plan's name."""

import ast
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from app.billing import units
from app.billing.plans import DEFAULT_PLAN, FREE, PLANS, Entitlements
from app.db.models import Subscription, WorkspaceMember
from app.main import app

client = TestClient(app, base_url="https://testserver")
_APP = Path(__file__).resolve().parent.parent / "app"
_PLANS_JSON = _APP / "billing" / "plans.json"


@pytest.fixture
def signed_in(api_db):
    client.cookies.clear()
    assert client.post("/api/v1/auth/register", json={"email": "units@example.com", "password": "long enough password"}).status_code == 201
    yield api_db
    client.cookies.clear()


def _workspace_id(api_db) -> str:
    with OrmSession(api_db) as session:
        return session.scalars(select(WorkspaceMember.workspace_id)).one()


# -- PLAN-001: the units ---------------------------------------------------------------------


def test_the_units_are_the_ones_the_brief_names_each_once():
    assert [unit.key for unit in units.UNITS] == [
        "documents", "exports", "pdfPages", "ocrPages", "translationCharacters", "batchJobs", "aiOperations", "storageBytes", "templates",
    ]  # fmt: skip
    assert len({unit.metric for unit in units.UNITS if unit.metric}) == len([unit for unit in units.UNITS if unit.metric])
    # Named now, counted once the feature exists: nothing in the app writes their metric yet.
    later = {unit.metric for unit in units.UNITS if not unit.counted}
    assert later == {units.OCR_PAGES}  # translation characters are counted since TRAN-009, batch jobs since FEAT-001
    source = "\n".join(path.read_text(encoding="utf-8") for path in _APP.rglob("*.py") if path.name != "units.py")
    for name in ("OCR_PAGES",):
        assert name not in source


def test_usage_lists_every_unit_with_the_plans_limit(signed_in):
    client.post("/api/v1/documents", json={"text": "# Units\n\nA paragraph."})

    listed = client.get("/api/v1/usage").json()["units"]

    free = PLANS[FREE].entitlements
    assert [unit["key"] for unit in listed] == [unit.key for unit in units.UNITS]
    by_key = {unit["key"]: unit for unit in listed}
    for unit in units.UNITS:
        expected_limit = getattr(free, unit.entitlement)
        assert by_key[unit.key]["limit"] == (None if expected_limit is None else expected_limit * unit.scale), unit.key
        assert by_key[unit.key]["period"] == ("month" if unit.metric else "now")
        assert by_key[unit.key]["available"] is unit.counted
        assert by_key[unit.key]["label"] == unit.label
    assert by_key["documents"]["used"] == 1 and by_key["storageBytes"]["used"] > 0
    assert by_key["storageBytes"]["measure"] == "bytes" and by_key["storageBytes"]["limit"] == free.maxStorageMb * 1024 * 1024
    assert all(by_key[key]["used"] == 0 for key in ("exports", "pdfPages", "ocrPages", "translationCharacters", "batchJobs", "aiOperations"))


def test_the_billing_page_lists_the_same_units_and_follows_the_plan(signed_in):
    with OrmSession(signed_in) as session:
        session.add(Subscription(workspace_id=_workspace_id(signed_in), plan="pro", status="active"))
        session.commit()

    billing = client.get("/api/v1/billing").json()

    assert billing["units"] == client.get("/api/v1/usage").json()["units"]
    pro = PLANS["pro"].entitlements
    assert {unit["key"]: unit["limit"] for unit in billing["units"]}["pdfPages"] == pro.maxPdfPages
    assert {unit["key"]: unit["limit"] for unit in billing["units"]}["aiOperations"] == pro.maxAiOperations


# -- PLAN-002: plans are data --------------------------------------------------------------------


def _raw_plans() -> dict:
    return json.loads(_PLANS_JSON.read_text(encoding="utf-8"))


def _entitlements_the_code_reads() -> set[str]:
    """Entitlements read in app/: attributes of the max*/can* kind and priorityProcessing,
    the entitlement a PlanLimitError names, and each usage unit's."""
    read: set[str] = {unit.entitlement for unit in units.UNITS}
    for path in _APP.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Attribute) and (node.attr == "priorityProcessing" or node.attr[:3] == "max" or node.attr[:3] == "can"):
                if node.attr[3:4].isupper() or node.attr == "priorityProcessing":
                    read.add(node.attr)
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "PlanLimitError" and node.args:
                first = node.args[0]
                for value in (first.body, first.orelse) if isinstance(first, ast.IfExp) else (first,):
                    if isinstance(value, ast.Constant) and isinstance(value.value, str):
                        read.add(value.value)
                    elif not isinstance(value, ast.Attribute):  # unit.entitlement: the units, counted above
                        raise AssertionError(f"{path}: a PlanLimitError whose entitlement can't be read here")
    return read


def test_every_entitlement_the_code_reads_is_defined_for_every_plan():
    read = _entitlements_the_code_reads()
    defined = set(Entitlements.model_fields)

    assert read <= defined, f"read but not an entitlement: {read - defined}"
    assert {"maxAiOperations", "maxExports", "maxPdfPages", "canExportPdf", "priorityProcessing", "maxDocumentSizeMb"} <= read
    for key, plan in _raw_plans()["plans"].items():
        # Written out in plans.json itself, not filled in by a default in the code.
        assert set(plan["entitlements"]) == defined, f"plan {key}: {defined ^ set(plan['entitlements'])}"


def test_the_default_plan_is_plans_json_s_and_every_plan_loads():
    raw = _raw_plans()
    assert DEFAULT_PLAN == FREE == raw["defaultPlan"] and DEFAULT_PLAN in PLANS
    assert set(PLANS) == set(raw["plans"])


def test_an_entitlement_plans_json_doesnt_know_stops_startup():
    entitlements = dict(_raw_plans()["plans"][DEFAULT_PLAN]["entitlements"])
    with pytest.raises(ValidationError):
        Entitlements(**entitlements, maxPdfPagez=10)
    del entitlements["maxExports"]
    with pytest.raises(ValidationError):
        Entitlements(**entitlements)


# Comparisons with a plan's name that can't be avoided, each with its reason: none so far.
_ALLOWED_PLAN_COMPARISONS: dict[str, str] = {}


def _plan_comparisons(source: str, plan_ids: set[str]) -> list[str]:
    """Each comparison in `source` with a plan's id: a string that is one, a collection
    of them, or the name the code has for the default plan."""

    def names_a_plan(node: ast.AST) -> bool:
        if isinstance(node, ast.Constant):
            return isinstance(node.value, str) and node.value.lower() in plan_ids
        if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
            return any(names_a_plan(item) for item in node.elts)
        if isinstance(node, ast.Name):
            return node.id in {"FREE", "DEFAULT_PLAN"}
        if isinstance(node, ast.Attribute):
            return node.attr in {"FREE", "DEFAULT_PLAN"}
        return False

    found = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Compare) and any(names_a_plan(operand) for operand in (node.left, *node.comparators)):
            found.append(ast.unparse(node))
        if isinstance(node, ast.MatchValue) and names_a_plan(node.value):
            found.append(f"case {ast.unparse(node.value)}")
    return found


def test_the_scan_finds_a_comparison_with_a_plans_name():
    ids = set(PLANS)
    assert _plan_comparisons('if plan == "pro":\n    pass', ids) == ["plan == 'pro'"]
    assert _plan_comparisons('ok = subscription.plan in ("business", "Pro")', ids) == ["subscription.plan in ('business', 'Pro')"]
    assert _plan_comparisons("ok = key != FREE", ids) == ["key != FREE"]
    assert _plan_comparisons('match plan:\n    case "free":\n        pass', ids) == ["case 'free'"]
    assert _plan_comparisons('ok = plan in PLANS and status == "active"', ids) == []


def test_no_code_compares_a_plans_name():
    ids = set(PLANS) | {plan.name.lower() for plan in PLANS.values()}
    found = {}
    for path in _APP.rglob("*.py"):
        for comparison in _plan_comparisons(path.read_text(encoding="utf-8"), ids):
            where = f"{path.relative_to(_APP)}: {comparison}"
            if where not in _ALLOWED_PLAN_COMPARISONS:
                found[where] = comparison
    assert not found, "Check an entitlement (billing/plans.json), not a plan's name:\n" + "\n".join(found)
