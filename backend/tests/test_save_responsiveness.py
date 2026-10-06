"""A save of a big document doesn't hold the event loop (PERF-008): the work on the
document itself -- reading it into the model, dumping it, working out the answer,
compressing the undo step -- runs in threads, in pieces small enough that the loop, which
needs the interpreter's lock as well, gets its turn between them. So the other requests
this process serves are not held up for the length of the save.

Measured with a ticker task in the same loop: the longest wait between two of its ticks,
against how long the save took. Both come from the same run, so a slow or busy machine
slows both; only the ratio is asserted, and the best of several saves, so a moment when
the machine itself stalled doesn't decide it."""

import asyncio
import gc
import json
import threading
import time

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.base import AIStructuredOutputError
from app.ai.factory import get_ai_provider
from app.db.base import Base
from app.main import app
from app.services import document_service, version_history
from scripts.benchmark import blocks_document
from tests.fakes import FakeAIProvider

_BLOCKS = 10000


@pytest.fixture
def no_ai():
    app.dependency_overrides[get_ai_provider] = lambda: FakeAIProvider([AIStructuredOutputError("no AI in tests")] * 3)
    yield
    app.dependency_overrides.pop(get_ai_provider, None)


@pytest.fixture
def no_collections():
    # A full garbage collection is a pause of the interpreter's own, the same before and
    # after any change to how a save is made (GC_GEN0_THRESHOLD is about it); it is left
    # out so the number says what the save's own work does to the loop.
    gc.collect()
    gc.disable()
    yield
    gc.enable()


async def _ticking(call):
    """(the call's result, how long it took, the longest wait between two ticks of a
    task that asks to run every 2 ms)."""
    stop = asyncio.Event()
    gaps: list[float] = []

    async def tick():
        last = time.perf_counter()
        while not stop.is_set():
            await asyncio.sleep(0.002)
            now = time.perf_counter()
            gaps.append(now - last)
            last = now

    ticker = asyncio.create_task(tick())
    await asyncio.sleep(0.05)  # the ticker is running
    started = time.perf_counter()
    result = await call()
    took = time.perf_counter() - started
    stop.set()
    await ticker
    return result, took, max(gaps)


async def _big_document(client) -> tuple[str, dict]:
    registered = await client.post("/api/v1/auth/register", json={"email": "loop@example.com", "password": "long enough password"})
    assert registered.status_code == 201
    document_id = (await client.post("/api/v1/documents", json={"text": "# Big\n\nFirst."})).json()["id"]
    body = json.dumps({"elements": blocks_document(_BLOCKS)}, ensure_ascii=False).encode()
    saved = await client.put(f"/api/v1/documents/{document_id}/content", content=body, headers={"Content-Type": "application/json"})
    assert saved.status_code == 200
    return document_id, saved.json()


async def test_the_loop_keeps_running_while_a_big_document_is_saved(api_db, no_ai, no_collections):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://testserver") as client:
        document_id, saved = await _big_document(client)
        path = f"/api/v1/documents/{document_id}/content"
        paragraph = next(element for element in saved["elements"] if element["type"] == "paragraph")
        revision = saved["revision"]
        rounds = []

        for step in range(5):
            text = f"{paragraph['content']} {step}"
            changed = {**paragraph, "content": text, "inline": [{"text": text, "marks": []}]}

            async def patch():
                return await client.patch(path, json={"changed": [changed]}, headers={"If-Match": str(revision)})

            answer, took, longest = await _ticking(patch)
            assert answer.status_code == 200
            revision = answer.json()["revision"]
            rounds.append((took, longest))

    ratios = [longest / took for took, longest in rounds]
    # Before this change the loop was held for a quarter to a half of a save of this size; now the
    # longest piece is a few hundredths of it.
    assert min(ratios) < 0.12, [(round(took, 3), round(longest, 3)) for took, longest in rounds]


async def test_the_work_on_the_document_runs_in_threads_on_plain_data(api_db, no_ai, monkeypatch):
    """The same thing said without a clock: what a save hands to asyncio.to_thread, and
    in which thread it runs. Nothing that belongs to the session (the session, a row, a
    version) is ever given to a thread."""
    calls: list[tuple[str, bool]] = []
    real = asyncio.to_thread

    async def recording(function, *args, **kwargs):
        for value in (*args, *kwargs.values()):
            assert not isinstance(value, (AsyncSession, Base)), (function.__name__, type(value))

        def run():
            calls.append((function.__name__, threading.current_thread() is not threading.main_thread()))
            return function(*args, **kwargs)

        return await real(run)

    monkeypatch.setattr(document_service.asyncio, "to_thread", recording)
    monkeypatch.setattr(version_history.asyncio, "to_thread", recording)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://testserver") as client:
        assert (await client.post("/api/v1/auth/register", json={"email": "threads@example.com", "password": "long enough password"})).status_code == 201
        created = (await client.post("/api/v1/documents", json={"text": "# T\n\nOne.\n\nTwo."})).json()
        path = f"/api/v1/documents/{created['id']}/content"
        changed = {**created["elements"][1], "content": "One!", "inline": [{"text": "One!", "marks": []}]}
        calls.clear()
        assert (await client.patch(path, json={"changed": [changed]}, headers={"If-Match": str(created["revision"])})).status_code == 200

    ran = {name for name, _ in calls}
    assert {"document_from_json", "dump_document", "patched_elements", "_adopt", "_settle", "stored_form", "pack_snapshot", "content_delta"} <= ran, ran
    assert all(in_thread for _, in_thread in calls), calls
