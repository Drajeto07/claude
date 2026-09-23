import pytest
from anthropic import APITimeoutError

from app.ai.instruction_extraction import _build_prompt, extract_document_edits
from app.ai.schemas import AIDocumentOperation, AIFormattingRule, AIInstructionExtractionResponse
from app.models.document import Document, DocumentMetadata, Element, ElementType
from tests.fakes import FakeAIProvider


def _document() -> Document:
    return Document(
        metadata=DocumentMetadata(title="Test"),
        elements=[
            Element(type=ElementType.HEADING, content="Title", level=1, order=0),
            Element(type=ElementType.PARAGRAPH, content="Body", order=1),
        ],
    )


def _response(target: str = "Heading 1", property_: str = "fontFamily", value: str = "Times New Roman") -> AIInstructionExtractionResponse:
    return AIInstructionExtractionResponse(rules=[AIFormattingRule(target=target, property=property_, value=value)])


@pytest.mark.anyio
async def test_successful_response_produces_rules():
    provider = FakeAIProvider([_response()])

    edits = await extract_document_edits(provider, "Make headings Times New Roman.", _document())

    assert len(edits.rules) == 1
    assert edits.rules[0].target == "Heading 1"
    assert edits.rules[0].value == "Times New Roman"
    assert edits.ai_unavailable is False
    assert provider.calls == 1


@pytest.mark.anyio
async def test_blank_instructions_never_calls_the_provider():
    provider = FakeAIProvider([])

    edits = await extract_document_edits(provider, "   ", _document())

    assert edits.rules == []
    assert edits.operations == []
    assert provider.calls == 0


@pytest.mark.anyio
async def test_retries_once_then_succeeds():
    provider = FakeAIProvider([APITimeoutError(request=None), _response()])

    edits = await extract_document_edits(provider, "Make headings Times New Roman.", _document())

    assert provider.calls == 2
    assert len(edits.rules) == 1


@pytest.mark.anyio
async def test_missing_api_key_type_error_falls_back_and_flags_ai_unavailable():
    # Same regression as test_ai_structure_analysis's -- the real Anthropic
    # client raises a plain TypeError synchronously when no API key is
    # configured, which must degrade gracefully here too.
    auth_error = TypeError("Could not resolve authentication method.")
    provider = FakeAIProvider([auth_error, auth_error])

    edits = await extract_document_edits(provider, "Make headings Times New Roman.", _document())

    assert provider.calls == 2
    assert edits.rules == []
    assert edits.operations == []
    assert edits.ai_unavailable is True


@pytest.mark.anyio
async def test_exhausted_retries_fall_back_and_flag_ai_unavailable():
    provider = FakeAIProvider([APITimeoutError(request=None), APITimeoutError(request=None)])

    edits = await extract_document_edits(provider, "Make headings Times New Roman.", _document())

    assert provider.calls == 2
    assert edits.rules == []
    assert edits.ai_unavailable is True


@pytest.mark.anyio
async def test_unknown_property_is_dropped_not_fatal():
    response = AIInstructionExtractionResponse(
        rules=[
            AIFormattingRule(target="Heading 1", property="fontFamily", value="Georgia"),
            AIFormattingRule(target="Heading 1", property="not-a-real-property", value="whatever"),
        ]
    )
    provider = FakeAIProvider([response])

    edits = await extract_document_edits(provider, "instructions", _document())

    assert len(edits.rules) == 1
    assert edits.rules[0].value == "Georgia"


@pytest.mark.anyio
async def test_unknown_target_is_dropped_not_fatal():
    response = AIInstructionExtractionResponse(
        rules=[AIFormattingRule(target="Not A Real Target", property="fontFamily", value="Georgia")]
    )
    provider = FakeAIProvider([response])

    edits = await extract_document_edits(provider, "instructions", _document())

    assert edits.rules == []


@pytest.mark.anyio
async def test_operation_targeting_a_real_element_id_survives():
    doc = _document()
    heading_id = doc.elements[0].id
    response = AIInstructionExtractionResponse(
        operations=[AIDocumentOperation(op="delete_element", element_id=heading_id)]
    )
    provider = FakeAIProvider([response])

    edits = await extract_document_edits(provider, "Delete the heading.", doc)

    assert len(edits.operations) == 1
    assert edits.operations[0].element_id == heading_id


@pytest.mark.anyio
async def test_operation_with_unknown_op_name_is_dropped_not_fatal():
    response = AIInstructionExtractionResponse(operations=[AIDocumentOperation(op="rewrite_everything")])
    provider = FakeAIProvider([response])

    edits = await extract_document_edits(provider, "instructions", _document())

    assert edits.operations == []


@pytest.mark.anyio
async def test_insert_element_with_invalid_element_type_is_dropped():
    response = AIInstructionExtractionResponse(
        operations=[AIDocumentOperation(op="insert_element", element_type="table", text="x")]
    )
    provider = FakeAIProvider([response])

    edits = await extract_document_edits(provider, "instructions", _document())

    assert edits.operations == []


def test_prompt_includes_real_element_ids_and_content():
    """The prompt must name real element ids and a text preview -- otherwise
    the AI has no way to target a specific element, the whole point of this
    extension over the old type-only targeting."""
    doc = _document()

    prompt = _build_prompt("Delete the heading.", doc)

    assert doc.elements[0].id in prompt
    assert doc.elements[1].id in prompt
    assert "Title" in prompt
    assert "Body" in prompt
