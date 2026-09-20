import pytest
from anthropic import APITimeoutError

from app.ai.instruction_extraction import extract_formatting_rules
from app.ai.schemas import AIFormattingRule, AIInstructionExtractionResponse
from tests.fakes import FakeAIProvider


def _response(target: str = "Heading 1", property_: str = "fontFamily", value: str = "Times New Roman") -> AIInstructionExtractionResponse:
    return AIInstructionExtractionResponse(rules=[AIFormattingRule(target=target, property=property_, value=value)])


@pytest.mark.anyio
async def test_successful_response_produces_rules():
    provider = FakeAIProvider([_response()])

    rules = await extract_formatting_rules(provider, "Make headings Times New Roman.")

    assert len(rules) == 1
    assert rules[0].target == "Heading 1"
    assert rules[0].value == "Times New Roman"
    assert provider.calls == 1


@pytest.mark.anyio
async def test_blank_instructions_never_calls_the_provider():
    provider = FakeAIProvider([])

    rules = await extract_formatting_rules(provider, "   ")

    assert rules == []
    assert provider.calls == 0


@pytest.mark.anyio
async def test_retries_once_then_succeeds():
    provider = FakeAIProvider([APITimeoutError(request=None), _response()])

    rules = await extract_formatting_rules(provider, "Make headings Times New Roman.")

    assert provider.calls == 2
    assert len(rules) == 1


@pytest.mark.anyio
async def test_missing_api_key_type_error_falls_back_to_empty_list():
    # Same regression as test_ai_structure_analysis's -- the real Anthropic
    # client raises a plain TypeError synchronously when no API key is
    # configured, which must degrade gracefully here too.
    auth_error = TypeError("Could not resolve authentication method.")
    provider = FakeAIProvider([auth_error, auth_error])

    rules = await extract_formatting_rules(provider, "Make headings Times New Roman.")

    assert provider.calls == 2
    assert rules == []


@pytest.mark.anyio
async def test_exhausted_retries_fall_back_to_empty_list():
    provider = FakeAIProvider([APITimeoutError(request=None), APITimeoutError(request=None)])

    rules = await extract_formatting_rules(provider, "Make headings Times New Roman.")

    assert provider.calls == 2
    assert rules == []


@pytest.mark.anyio
async def test_unknown_property_is_dropped_not_fatal():
    response = AIInstructionExtractionResponse(
        rules=[
            AIFormattingRule(target="Heading 1", property="fontFamily", value="Georgia"),
            AIFormattingRule(target="Heading 1", property="not-a-real-property", value="whatever"),
        ]
    )
    provider = FakeAIProvider([response])

    rules = await extract_formatting_rules(provider, "instructions")

    assert len(rules) == 1
    assert rules[0].value == "Georgia"


@pytest.mark.anyio
async def test_unknown_target_is_dropped_not_fatal():
    response = AIInstructionExtractionResponse(
        rules=[AIFormattingRule(target="Not A Real Target", property="fontFamily", value="Georgia")]
    )
    provider = FakeAIProvider([response])

    rules = await extract_formatting_rules(provider, "instructions")

    assert rules == []
