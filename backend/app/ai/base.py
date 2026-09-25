from abc import ABC, abstractmethod
from typing import TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class AIRefusalError(Exception):
    """Raised when the model declines to produce structured output at all."""


class AIStructuredOutputError(Exception):
    """Raised when the provider returns no usable parsed output."""


class AIProvider(ABC):
    """Provider-agnostic interface (NFR-006: AI provider must be replaceable
    without changing the editor core). `system` holds a task's rules, kept
    apart from the message, which carries the user's request and document
    (ai/prompting.py, корекции.docx §22)."""

    @abstractmethod
    def provider_name(self) -> str: ...

    @abstractmethod
    async def complete(self, prompt: str, *, max_tokens: int = 256, system: str | None = None) -> str: ...

    @abstractmethod
    async def complete_structured(
        self, prompt: str, *, response_model: type[T], max_tokens: int = 8192, system: str | None = None
    ) -> T: ...
