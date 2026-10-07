"""A bounded amount of AI per job and per request (tracker AI-008): at most so
many calls, and all of them within one deadline. Each call's output is capped by
its max_tokens and its input by the size of the piece it's given, so the calls
also bound the tokens a document can use. Once the budget is spent every call
is refused at once -- an AIBudgetExceededError, which every AI step already
treats as a refusal and falls back from -- instead of waiting on retries and
timeouts, which could otherwise add up to hours for one long document."""

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import TypeVar

from pydantic import BaseModel

from app.ai.base import AIProvider, AIRefusalError
from app.observability import AI_CALLS, AI_LATENCY

T = TypeVar("T", bound=BaseModel)
R = TypeVar("R")


class AIBudgetExceededError(AIRefusalError):
    """This job's (or request's) AI calls or time are used up."""


class BudgetedAIProvider(AIProvider):
    def __init__(self, inner: AIProvider, *, calls: int, seconds: float, clock: Callable[[], float] = time.monotonic) -> None:
        self._inner = inner
        self._calls_left = calls
        self._clock = clock
        self._deadline = clock() + seconds

    @property
    def spent(self) -> bool:
        return self._calls_left <= 0 or self._clock() >= self._deadline

    def provider_name(self) -> str:
        return self._inner.provider_name()

    def _admit(self) -> float:
        """One call more, with the time left for it; refused when there's none."""
        remaining = self._deadline - self._clock()
        if self._calls_left <= 0 or remaining <= 0:
            AI_CALLS.inc(outcome="refused")
        if self._calls_left <= 0:
            raise AIBudgetExceededError("The AI calls allowed for this document are used up.")
        if remaining <= 0:
            raise AIBudgetExceededError("The AI time allowed for this document is used up.")
        self._calls_left -= 1
        return remaining

    async def _within(self, call: Callable[[], Awaitable[R]], remaining: float) -> R:
        started = time.perf_counter()
        outcome = "ok"
        try:
            return await asyncio.wait_for(call(), timeout=remaining)
        except TimeoutError as exc:
            outcome = "timeout"
            self._calls_left = 0  # the deadline has passed: nothing more for this job
            raise AIBudgetExceededError("The AI time allowed for this document ran out.") from exc
        except BaseException as exc:
            outcome = type(exc).__name__
            raise
        finally:
            # Every AI call goes through an allowance, so this sees them all (OBS-001).
            AI_CALLS.inc(outcome=outcome)
            AI_LATENCY.observe(time.perf_counter() - started)

    async def complete(self, prompt: str, *, max_tokens: int = 256, system: str | None = None) -> str:
        remaining = self._admit()
        return await self._within(lambda: self._inner.complete(prompt, max_tokens=max_tokens, system=system), remaining)

    async def complete_structured(self, prompt: str, *, response_model: type[T], max_tokens: int = 8192, system: str | None = None) -> T:
        remaining = self._admit()
        return await self._within(
            lambda: self._inner.complete_structured(prompt, response_model=response_model, max_tokens=max_tokens, system=system), remaining
        )
