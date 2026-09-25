import logging
import time
from typing import Any, TypeVar

import anthropic
from pydantic import BaseModel

from app.ai.base import AIProvider, AIRefusalError, AIStructuredOutputError

T = TypeVar("T", bound=BaseModel)

logger = logging.getLogger(__name__)


class AnthropicProvider(AIProvider):
    """Claude. Every call has a timeout (`timeout_seconds`), and the SDK retries
    a dropped connection, a rate limit or an overloaded server on its own
    (`max_retries`). Each call leaves one "ai.call" log line: the task, how
    long it took, the tokens it used and how it ended -- never the prompt or
    the answer (корекции.docx §20, §51)."""

    def __init__(self, api_key: str, model: str, *, timeout_seconds: float = 180.0, max_retries: int = 2) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=api_key, timeout=timeout_seconds, max_retries=max_retries)
        self._model = model

    def provider_name(self) -> str:
        return "anthropic"

    def _params(self, prompt: str, max_tokens: int, system: str | None) -> dict[str, Any]:
        params: dict[str, Any] = {"model": self._model, "max_tokens": max_tokens, "messages": [{"role": "user", "content": prompt}]}
        if system:
            params["system"] = system
        return params

    def _log(self, task: str, started: float, outcome: str, response: Any = None) -> None:
        usage = getattr(response, "usage", None)
        logger.info(
            "ai.call",
            extra={
                "provider": "anthropic",
                "model": self._model,
                "task": task,
                "outcome": outcome,
                "duration_ms": round((time.perf_counter() - started) * 1000),
                "input_tokens": getattr(usage, "input_tokens", None),
                "output_tokens": getattr(usage, "output_tokens", None),
                "stop_reason": getattr(response, "stop_reason", None),
            },
        )

    async def complete(self, prompt: str, *, max_tokens: int = 256, system: str | None = None) -> str:
        started, response = time.perf_counter(), None
        try:
            response = await self._client.messages.create(**self._params(prompt, max_tokens, system))
        except Exception as exc:
            self._log("text", started, type(exc).__name__)
            raise
        self._log("text", started, "ok", response)
        for block in response.content:
            if block.type == "text":
                return block.text
        return ""

    async def complete_structured(
        self, prompt: str, *, response_model: type[T], max_tokens: int = 8192, system: str | None = None
    ) -> T:
        started, task = time.perf_counter(), response_model.__name__
        try:
            response = await self._client.messages.parse(**self._params(prompt, max_tokens, system), output_format=response_model)
        except Exception as exc:
            self._log(task, started, type(exc).__name__)
            raise
        if response.stop_reason == "refusal":
            self._log(task, started, "refusal", response)
            raise AIRefusalError("Claude declined to produce structured output for this request")
        if response.parsed_output is None:
            self._log(task, started, "no_output", response)
            raise AIStructuredOutputError("Anthropic response had no parsed_output")
        self._log(task, started, "ok", response)
        return response.parsed_output
