"""A bounded amount of AI per job and per request (tracker AI-008): a number of
calls and a deadline, after which every call is refused at once and the AI step
takes its fallback -- never hours of retries and timeouts for one document."""

import asyncio

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel, ValidationError

from app.ai import structure_analysis
from app.ai.base import AIProvider
from app.ai.budget import AIBudgetExceededError, BudgetedAIProvider
from app.ai.factory import get_ai_provider
from app.ai.schemas import AIBlock, AIBlockType, AIStructureResponse
from app.ai.structure_analysis import analyze_structure, split_into_chunks
from app.config import Settings, get_settings
from app.main import app
from tests.fakes import FakeAIProvider


def _answer(text: str) -> AIStructureResponse:
    return AIStructureResponse(
        document_type="general",
        document_type_confidence=0.9,
        blocks=[AIBlock(type=AIBlockType.PARAGRAPH, text=text, confidence=0.9)],
    )


def _ask(provider: AIProvider) -> AIStructureResponse:
    return asyncio.run(provider.complete_structured("text", response_model=AIStructureResponse))


def test_calls_beyond_the_allowance_are_refused_at_once():
    inner = FakeAIProvider([_answer("a"), _answer("b"), _answer("c")])
    budget = BudgetedAIProvider(inner, calls=2, seconds=60)

    _ask(budget)
    _ask(budget)
    with pytest.raises(AIBudgetExceededError):
        _ask(budget)
    assert inner.calls == 2 and budget.spent


def test_no_call_starts_after_the_deadline():
    now = [0.0]
    inner = FakeAIProvider([_answer("a")])
    budget = BudgetedAIProvider(inner, calls=10, seconds=30, clock=lambda: now[0])

    now[0] = 31
    with pytest.raises(AIBudgetExceededError):
        _ask(budget)
    assert inner.calls == 0


class _Slow(AIProvider):
    def provider_name(self) -> str:
        return "slow"

    async def complete(self, prompt: str, *, max_tokens: int = 256, system: str | None = None) -> str:
        await asyncio.sleep(5)
        return ""

    async def complete_structured(self, prompt: str, *, response_model: type[BaseModel], max_tokens: int = 8192, system: str | None = None):
        await asyncio.sleep(5)
        raise AssertionError("never answers in time")


def test_a_call_that_runs_past_the_deadline_is_cut_off_and_ends_the_allowance():
    budget = BudgetedAIProvider(_Slow(), calls=10, seconds=0.05)

    with pytest.raises(AIBudgetExceededError):
        _ask(budget)
    assert budget.spent  # nothing more for this job


def test_retries_and_allowances_are_bounded_in_the_settings():
    for bad in ({"ai_structure_max_retries": 10}, {"ai_calls_per_job": 0}, {"ai_seconds_per_job": 7200}):
        with pytest.raises(ValidationError):
            Settings(**bad)


def test_a_document_whose_allowance_runs_out_is_finished_without_the_ai(monkeypatch):
    monkeypatch.setattr(structure_analysis, "CHUNK_CHARS", 30)
    text = "Alpha part one here.\n\nBeta part two here.\n\nGamma part three."
    assert len(split_into_chunks(text)) == 3
    inner = FakeAIProvider([_answer("Alpha part one here.")])

    document = asyncio.run(analyze_structure(BudgetedAIProvider(inner, calls=1, seconds=60), text))

    assert inner.calls == 1  # the refused calls never reached the AI, and weren't retried
    assert [element.confidence for element in document.elements] == [0.9, None, None]
    assert [element.content for element in document.elements] == ["Alpha part one here.", "Beta part two here.", "Gamma part three."]
    assert document.unsupportedFeatures == [structure_analysis._BUDGET_NOTE]


def test_a_request_gets_its_own_allowance(api_db, monkeypatch):
    monkeypatch.setattr(get_settings(), "ai_calls_per_job", 1)
    prose = "this is ordinary prose without any markdown at all so it goes to the ai for its structure"
    fake = FakeAIProvider([_answer(prose.replace("ordinary", "unusual")), _answer(prose)])
    app.dependency_overrides[get_ai_provider] = lambda: fake
    client = TestClient(app, base_url="https://testserver")
    try:
        assert client.post("/api/v1/auth/register", json={"email": "budget@example.com", "password": "long enough password"}).status_code == 201
        created = client.post("/api/v1/documents", json={"text": prose})
    finally:
        app.dependency_overrides.pop(get_ai_provider, None)

    assert created.status_code == 201, created.text
    assert fake.calls == 1  # the first answer changed the text; its retry was over the allowance
    body = created.json()
    assert body["elements"][0]["content"] == prose
    assert structure_analysis._BUDGET_NOTE in [item["reason"] for item in body["importReport"]["items"]]
