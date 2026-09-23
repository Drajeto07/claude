import pytest
from anthropic import APITimeoutError

from app.ai.schemas import AIStyleAnalysisResponse, AIStyleFlag
from app.ai.style_analysis import analyze_style
from app.models.document import Document, DocumentMetadata, Element, ElementType
from tests.fakes import FakeAIProvider


def _document(elements: list[Element] | None = None) -> Document:
    return Document(
        metadata=DocumentMetadata(title="Test"),
        elements=elements
        if elements is not None
        else [
            Element(id="h1", type=ElementType.HEADING, content="Title", level=1, order=0),
            Element(id="p1", type=ElementType.PARAGRAPH, content="Formal body paragraph.", order=1),
            Element(id="p2", type=ElementType.PARAGRAPH, content="hey lol this one's super casual", order=2),
        ],
    )


def _response(flagged: list[AIStyleFlag] | None = None) -> AIStyleAnalysisResponse:
    return AIStyleAnalysisResponse(
        consistency_score=0.4,
        tone="Mostly formal with one casual outlier",
        summary="The document is largely formal but one paragraph breaks tone.",
        flagged=flagged if flagged is not None else [AIStyleFlag(element_id="p2", reason="Casual slang breaks the formal tone.")],
    )


@pytest.mark.anyio
async def test_successful_analysis_returns_scored_result():
    provider = FakeAIProvider([_response()])

    result = await analyze_style(provider, _document())

    assert result.status == "ok"
    assert result.consistencyScore == 0.4
    assert result.tone == "Mostly formal with one casual outlier"
    assert len(result.flagged) == 1
    assert result.flagged[0].elementId == "p2"
    assert provider.calls == 1


@pytest.mark.anyio
async def test_empty_document_never_calls_the_provider():
    provider = FakeAIProvider([])

    result = await analyze_style(provider, _document(elements=[]))

    assert result.status == "empty_document"
    assert provider.calls == 0


@pytest.mark.anyio
async def test_document_with_only_blank_elements_is_treated_as_empty():
    provider = FakeAIProvider([])
    blank_doc = _document(elements=[Element(type=ElementType.PARAGRAPH, content="   ", order=0)])

    result = await analyze_style(provider, blank_doc)

    assert result.status == "empty_document"
    assert provider.calls == 0


@pytest.mark.anyio
async def test_flag_referencing_unknown_element_id_is_dropped():
    provider = FakeAIProvider([_response(flagged=[AIStyleFlag(element_id="does-not-exist", reason="hallucinated id")])])

    result = await analyze_style(provider, _document())

    assert result.status == "ok"
    assert result.flagged == []


@pytest.mark.anyio
async def test_retries_once_then_succeeds():
    provider = FakeAIProvider([APITimeoutError(request=None), _response()])

    result = await analyze_style(provider, _document())

    assert provider.calls == 2
    assert result.status == "ok"


@pytest.mark.anyio
async def test_missing_api_key_type_error_falls_back_to_ai_unavailable():
    provider = FakeAIProvider([TypeError("no api key"), TypeError("no api key")])

    result = await analyze_style(provider, _document())

    assert result.status == "ai_unavailable"
    assert result.consistencyScore is None
    assert result.flagged == []
