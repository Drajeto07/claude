import pytest
from anthropic import APITimeoutError

from app.ai.base import AIRefusalError
from app.ai.schemas import AIBlock, AIBlockType, AIStructureResponse
from app.ai.structure_analysis import analyze_structure
from app.models.document import ElementType
from tests.fakes import FakeAIProvider

SAMPLE_TEXT = "This is an ordinary paragraph of plain, unstructured prose text used for testing."


def _valid_response(text: str = SAMPLE_TEXT) -> AIStructureResponse:
    return AIStructureResponse(
        document_type="general",
        document_type_confidence=0.8,
        blocks=[AIBlock(type=AIBlockType.PARAGRAPH, text=text, confidence=0.9)],
    )


@pytest.mark.anyio
async def test_successful_response_produces_document():
    provider = FakeAIProvider([_valid_response()])

    document = await analyze_structure(provider, SAMPLE_TEXT)

    assert document.documentType == "general"
    assert len(document.elements) == 1
    assert document.elements[0].type == ElementType.PARAGRAPH
    assert document.elements[0].content == SAMPLE_TEXT
    assert document.elements[0].confidence == 0.9
    assert provider.calls == 1


@pytest.mark.anyio
async def test_retries_once_then_succeeds():
    provider = FakeAIProvider([APITimeoutError(request=None), _valid_response()])

    document = await analyze_structure(provider, SAMPLE_TEXT)

    assert provider.calls == 2
    assert document.elements[0].content == SAMPLE_TEXT


@pytest.mark.anyio
async def test_missing_api_key_type_error_falls_back_gracefully():
    # Regression test: found live when uploading a file with no
    # ANTHROPIC_API_KEY configured -- the real Anthropic client raises a
    # plain TypeError synchronously (before any network call) when it can't
    # resolve authentication, which must degrade to the naive segmenter
    # fallback like any other AI failure, not surface as an unhandled 500.
    auth_error = TypeError(
        "Could not resolve authentication method. Expected one of api_key, auth_token, or credentials to be set."
    )
    provider = FakeAIProvider([auth_error, auth_error])

    document = await analyze_structure(provider, "Short Title\n\nA longer paragraph follows here.")

    assert provider.calls == 2
    assert document.elements[0].confidence is None


@pytest.mark.anyio
async def test_exhausted_retries_fall_back_to_naive_segmenter():
    provider = FakeAIProvider([AIRefusalError("declined"), AIRefusalError("declined again")])

    document = await analyze_structure(provider, "Short Title\n\nA longer paragraph follows here.")

    assert provider.calls == 2
    # The naive segmenter (not the AI path) produced this -- its signature is
    # confidence=None, unlike the AI path which always sets a real number.
    assert document.elements[0].confidence is None


@pytest.mark.anyio
async def test_fidelity_check_rejects_fabricated_text_and_falls_back():
    fabricated = AIStructureResponse(
        document_type="general",
        document_type_confidence=0.9,
        blocks=[AIBlock(type=AIBlockType.PARAGRAPH, text="Completely unrelated invented sentence.", confidence=0.9)],
    )
    provider = FakeAIProvider([fabricated, fabricated])

    document = await analyze_structure(provider, SAMPLE_TEXT)

    # Both attempts fabricated text and got rejected by the fidelity check,
    # so this must have fallen back to the naive segmenter.
    assert provider.calls == 2
    assert document.elements[0].confidence is None


@pytest.mark.anyio
async def test_list_block_produces_list_element_with_items():
    response = AIStructureResponse(
        document_type="general",
        document_type_confidence=0.7,
        blocks=[
            AIBlock(
                type=AIBlockType.LIST,
                text="",
                ordered=False,
                items=[{"text": "first item", "level": 0}, {"text": "second item", "level": 0}],
                confidence=0.85,
            )
        ],
    )
    provider = FakeAIProvider([response])

    document = await analyze_structure(provider, "first item second item")

    element = document.elements[0]
    assert element.type == ElementType.LIST
    assert element.ordered is False
    assert [item.inline[0].text for item in element.listItems] == ["first item", "second item"]
