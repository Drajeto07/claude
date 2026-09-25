"""How often a client may call what (корекции.docx §33, §76). Signing in,
registering, AI work, uploads and exports each have an allowance, and every
client has a generous overall one against floods. A refusal is 429
"rate_limited" with Retry-After; nothing of the refused request is done.

Counters are fixed windows, kept in this process's memory by default. With
RATE_LIMIT_BACKEND=redis they live in Redis (REDIS_URL), so several API
processes share them. If Redis can't be reached, requests are let through
(and the failure logged): losing the limits for a while beats losing the API."""

import hashlib
import logging
import math
import time
from dataclasses import dataclass
from typing import Protocol

from app.config import get_settings

logger = logging.getLogger(__name__)

_UNITS = {"second": 1, "minute": 60, "hour": 3600, "day": 86400}


@dataclass(frozen=True)
class Rate:
    limit: int
    seconds: int

    @classmethod
    def parse(cls, text: str) -> "Rate | None":
        """"20/minute" -> 20 per 60 s; "" or "0/…" -> no limit."""
        if not text.strip():
            return None
        count, _, unit = text.strip().partition("/")
        if unit.strip().rstrip("s") not in _UNITS or not count.strip().isdigit():
            raise ValueError(f"A rate limit looks like '20/minute', not {text!r}")
        rate = cls(int(count), _UNITS[unit.strip().rstrip("s")])
        return rate if rate.limit > 0 else None


class RateLimitedError(Exception):
    def __init__(self, scope: str, retry_after: int) -> None:
        super().__init__(f"Too many requests. Please wait {retry_after} second{'' if retry_after == 1 else 's'} and try again.")
        self.scope = scope
        self.retry_after = retry_after


class Counter(Protocol):
    async def hit(self, key: str, rate: Rate) -> int | None:
        """Counts one request; None while within the rate, otherwise the seconds
        until its window ends."""
        ...


def _window(rate: Rate, now: float) -> tuple[int, int]:
    """The window `now` falls in, and the seconds left in it (at least 1)."""
    index = int(now // rate.seconds)
    return index, max(1, math.ceil((index + 1) * rate.seconds - now))


class MemoryCounter:
    _PRUNE_AT = 50_000

    def __init__(self) -> None:
        self._counts: dict[str, tuple[float, int]] = {}  # key -> (its window's end, count)

    async def hit(self, key: str, rate: Rate) -> int | None:
        now = time.time()
        index, left = _window(rate, now)
        window_key = f"{key}:{rate.seconds}:{index}"
        _, count = self._counts.get(window_key, (0.0, 0))
        self._counts[window_key] = (now + left, count + 1)
        if len(self._counts) > self._PRUNE_AT:
            self._counts = {k: v for k, v in self._counts.items() if v[0] > now}
        return left if count + 1 > rate.limit else None

    def reset(self) -> None:
        self._counts.clear()


class RedisCounter:
    def __init__(self, url: str) -> None:
        from redis.asyncio import from_url  # only this backend needs it

        self._redis = from_url(url)

    async def hit(self, key: str, rate: Rate) -> int | None:
        index, left = _window(rate, time.time())
        window_key = f"ratelimit:{key}:{rate.seconds}:{index}"
        try:
            async with self._redis.pipeline(transaction=True) as pipe:
                pipe.incr(window_key)
                pipe.expire(window_key, left + 1)
                count, _ = await pipe.execute()
        except Exception:  # noqa: BLE001 -- fail open, see the module docstring
            logger.warning("Rate limiting skipped: Redis unreachable", exc_info=True)
            return None
        return left if int(count) > rate.limit else None


_counter: Counter | None = None


def counter() -> Counter:
    global _counter
    if _counter is None:
        settings = get_settings()
        _counter = RedisCounter(settings.redis_url) if settings.rate_limit_backend == "redis" else MemoryCounter()
    return _counter


def reset() -> None:
    """Forgets every count (tests start each from zero)."""
    if isinstance(_counter, MemoryCounter):
        _counter.reset()


def rate_for(scope: str) -> Rate | None:
    return Rate.parse(getattr(get_settings(), f"rate_limit_{scope}"))


async def enforce(scope: str, key: str) -> None:
    """Counts a request of `scope` for `key` (a user, an address, a session);
    RateLimitedError once the scope's allowance for the window is used up."""
    rate = rate_for(scope)
    if rate is None:
        return
    retry_after = await counter().hit(f"{scope}:{key}", rate)
    if retry_after is not None:
        raise RateLimitedError(scope, retry_after)


def hashed(value: str) -> str:
    """A key that doesn't keep what it identifies (an email address, a session token)."""
    return hashlib.sha256(value.strip().lower().encode()).hexdigest()[:32]
