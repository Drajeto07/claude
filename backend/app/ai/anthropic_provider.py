from typing import TypeVar

import anthropic
from pydantic import BaseModel

from app.ai.base import AIProvider, AIRefusalError, AIStructuredOutputError

T = TypeVar("T", bound=BaseModel)


class AnthropicProvider(AIProvider):
    def __init__(self, api_key: str, model: str) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._model = model

    def provider_name(self) -> str:
        return "anthropic"

    async def complete(self, prompt: str, *, max_tokens: int = 256) -> str:
        response = await self._client.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        for block in response.content:
            if block.type == "text":
                return block.text
        return ""

    async def complete_structured(self, prompt: str, *, response_model: type[T], max_tokens: int = 8192) -> T:
        response = await self._client.messages.parse(
            model=self._model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
            output_format=response_model,
        )
        if response.stop_reason == "refusal":
            raise AIRefusalError("Claude declined to produce structured output for this request")
        if response.parsed_output is None:
            raise AIStructuredOutputError("Anthropic response had no parsed_output")
        return response.parsed_output
