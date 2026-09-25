from typing import TypeVar

from pydantic import BaseModel

from app.ai.base import AIProvider

T = TypeVar("T", bound=BaseModel)


class FakeAIProvider(AIProvider):
    """Hand-written test double against our own stable AIProvider interface --
    deliberately not patching the anthropic SDK's internals, which would be
    brittle against the next SDK version bump.

    `responses` is consumed one-per-call to `complete_structured`; an entry
    that's an Exception instance is raised instead of returned, so tests can
    script "fail N times then succeed."
    """

    def __init__(self, responses: list[BaseModel | Exception]) -> None:
        self._responses = list(responses)
        self.calls = 0
        # What each call was sent: its message and its system prompt.
        self.prompts: list[str] = []
        self.systems: list[str | None] = []

    def provider_name(self) -> str:
        return "fake"

    async def complete(self, prompt: str, *, max_tokens: int = 256, system: str | None = None) -> str:
        return ""

    async def complete_structured(
        self, prompt: str, *, response_model: type[T], max_tokens: int = 8192, system: str | None = None
    ) -> T:
        self.calls += 1
        self.prompts.append(prompt)
        self.systems.append(system)
        if not self._responses:
            raise AssertionError("FakeAIProvider ran out of scripted responses")
        result = self._responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result
