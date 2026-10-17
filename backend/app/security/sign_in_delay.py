"""A growing wait after wrong passwords for one account (ACCT-007).

No lockout: one that an attacker could trigger by failing on purpose would lock the
owner out too. Instead, after SIGN_IN_FREE_FAILURES wrong passwords for an account
within SIGN_IN_FAILURE_WINDOW_MINUTES, each next try for it waits 1 s, 2 s, 4 s ... at
most SIGN_IN_MAX_DELAY_SECONDS before its password is checked. The wait comes before
the check, whether the password turns out right or not, so a guesser who gives up on
slow answers learns nothing from a fast one. The right password still gets in, and
clears the count. The per-account rate limit (rate_limit_login_account) stays.

Keyed by a hash of the address, the same whether or not it has an account. Counted
in this process by default, or in Redis with RATE_LIMIT_BACKEND=redis, like the rate
limits; if Redis can't be reached, nobody waits (the failure logged)."""

import asyncio
import logging
import time
from typing import Protocol

from app.config import get_settings
from app.security.rate_limit import hashed

logger = logging.getLogger(__name__)

# Swapped by the tests, which never really wait.
sleep = asyncio.sleep
clock = time.time


class FailureStore(Protocol):
    async def failed(self, key: str, window: int) -> None:
        """Counts a failure; the count is forgotten `window` seconds after the last one."""
        ...

    async def failures(self, key: str) -> int: ...

    async def clear(self, key: str) -> None: ...


class MemoryFailures:
    _PRUNE_AT = 50_000

    def __init__(self) -> None:
        self._counts: dict[str, tuple[int, float]] = {}  # key -> (failures, when they are forgotten)

    async def failed(self, key: str, window: int) -> None:
        now = clock()
        count = await self.failures(key)
        self._counts[key] = (count + 1, now + window)
        if len(self._counts) > self._PRUNE_AT:
            self._counts = {k: v for k, v in self._counts.items() if v[1] > now}

    async def failures(self, key: str) -> int:
        count, until = self._counts.get(key, (0, 0.0))
        return count if until > clock() else 0

    async def clear(self, key: str) -> None:
        self._counts.pop(key, None)

    def reset(self) -> None:
        self._counts.clear()


class RedisFailures:
    def __init__(self, url: str) -> None:
        from redis.asyncio import from_url  # only this backend needs it

        self._redis = from_url(url)

    async def failed(self, key: str, window: int) -> None:
        try:
            async with self._redis.pipeline(transaction=True) as pipe:
                pipe.incr(f"signin:{key}")
                pipe.expire(f"signin:{key}", window)
                await pipe.execute()
        except Exception:  # noqa: BLE001 -- fail open, see the module docstring
            logger.warning("Sign-in failure not counted: Redis unreachable", exc_info=True)

    async def failures(self, key: str) -> int:
        try:
            return int(await self._redis.get(f"signin:{key}") or 0)
        except Exception:  # noqa: BLE001
            logger.warning("Sign-in failures not read: Redis unreachable", exc_info=True)
            return 0

    async def clear(self, key: str) -> None:
        try:
            await self._redis.delete(f"signin:{key}")
        except Exception:  # noqa: BLE001
            logger.warning("Sign-in failures not cleared: Redis unreachable", exc_info=True)


_store: FailureStore | None = None


def store() -> FailureStore:
    global _store
    if _store is None:
        settings = get_settings()
        _store = RedisFailures(settings.redis_url) if settings.rate_limit_backend == "redis" else MemoryFailures()
    return _store


def reset() -> None:
    """Forgets every count (tests start each from zero)."""
    if isinstance(_store, MemoryFailures):
        _store.reset()


def delay_for(failures: int) -> float:
    """The wait before a try, after `failures` recent wrong passwords."""
    settings = get_settings()
    over = failures - settings.sign_in_free_failures
    if over < 0:
        return 0.0
    return min(2.0 ** min(over, 30), settings.sign_in_max_delay_seconds)


async def wait_before_check(email: str) -> float:
    """Waits as long as the account's recent failures call for; returns the seconds waited."""
    seconds = delay_for(await store().failures(hashed(email)))
    if seconds > 0:
        await sleep(seconds)
    return seconds


async def password_failed(email: str) -> None:
    await store().failed(hashed(email), get_settings().sign_in_failure_window_minutes * 60)


async def password_succeeded(email: str) -> None:
    await store().clear(hashed(email))
