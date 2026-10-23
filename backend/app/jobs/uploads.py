"""A document upload in parts (B-035A): for files the hosting won't take in one request.

On Vercel the API runs as a function whose requests are limited to 4.5 MB (413 before the app sees them), so a
Word or PDF file over about 4 MB can't come in through POST /jobs/import-file. It comes in parts instead, each
well under the limit, and only once every part is there, the whole file checked and found to be the one the
browser hashed, does it become an import job -- through exactly the path a one-request upload takes
(api/jobs.py): the same plan checks, the same content check (security/files.py), the same job.

Where an upload stands is kept in the private store, never in this process: the API may run on many short-lived
instances, so each part may reach another one. Under uploads/{workspace}/{upload}/ there is

    session.json   who started it, the file's name, size, SHA-256 and import options, when, and -- once it
                   became a job -- which job;
    part-00000...  the parts, each written under its own number, so sending one again overwrites it with
                   the same bytes and parts may come in any order.

Nothing here is a document, an asset or a job, and no route serves these keys: an unfinished upload can't be
downloaded or imported. A session is the user's who started it, in their workspace; anyone else is told it
doesn't exist. It lasts SESSION_TTL; the parts go as soon as it became a job, and everything a session left
(abandoned, failed, or finished) is swept once it is older than that -- by the hourly sweep (jobs/files.py) where
jobs run in the background, and, where nothing runs between requests (on Vercel jobs run inside them: no sweep at
all), at every new upload, by anyone, a bounded number at a time. However long nobody uploads, what can be left is
bounded too: a workspace may hold the parts of at most MAX_OPEN_UPLOADS unfinished uploads (each at most the 10 MB
cap), so it never grows beyond that, swept or not.
"""

import hashlib
import json
import logging
import math
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone

from app.storage.base import AssetNotFoundError, StorageProvider

logger = logging.getLogger(__name__)

# 3 MiB a part: a request body of 3,145,728 bytes plus headers, well under the hosting's 4.5 MB.
CHUNK_SIZE = 3 * 1024 * 1024
SESSION_TTL = timedelta(hours=1)
PREFIX = "uploads/"
# Unfinished uploads holding parts a workspace may have at once (the app uploads one file at a time).
MAX_OPEN_UPLOADS = 3
# Uploads one sweep run at an upload's start deletes at most: it stays quick, and the next start goes on.
SWEEP_BATCH = 25
_MANIFEST = "session.json"


class UploadIncomplete(Exception):
    def __init__(self, missing: list[int]) -> None:
        super().__init__(f"{len(missing)} part(s) missing")
        self.missing = missing


class UploadMismatch(Exception):
    """The parts put together aren't the file the upload was started for (size or SHA-256)."""


@dataclass
class UploadSession:
    id: str
    workspace_id: str
    user_id: str
    filename: str
    size: int
    sha256: str
    content_type: str | None
    title: str | None
    autolink: bool
    pdf_mode: str
    chunk_size: int
    chunks: int
    created_at: str
    job_id: str | None = None

    @property
    def prefix(self) -> str:
        return f"{PREFIX}{self.workspace_id}/{self.id}/"

    def part_key(self, index: int) -> str:
        return f"{self.prefix}part-{index:05d}"

    def part_size(self, index: int) -> int:
        """How many bytes part `index` must have: a full part, the last one what is left."""
        return self.chunk_size if index < self.chunks - 1 else self.size - self.chunk_size * (self.chunks - 1)

    def expired(self, now: datetime) -> bool:
        return datetime.fromisoformat(self.created_at) + SESSION_TTL < now


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _manifest_key(workspace_id: str, upload_id: str) -> str:
    return f"{PREFIX}{workspace_id}/{upload_id}/{_MANIFEST}"


async def _save(storage: StorageProvider, session: UploadSession) -> None:
    await storage.put(_manifest_key(session.workspace_id, session.id), json.dumps(asdict(session)).encode(), "application/json")


async def start(
    storage: StorageProvider,
    *,
    workspace_id: str,
    user_id: str,
    filename: str,
    size: int,
    sha256: str,
    content_type: str | None,
    title: str | None,
    autolink: bool,
    pdf_mode: str,
) -> UploadSession:
    session = UploadSession(
        id=str(uuid.uuid4()),
        workspace_id=workspace_id,
        user_id=user_id,
        filename=filename,
        size=size,
        sha256=sha256.lower(),
        content_type=content_type,
        title=title,
        autolink=autolink,
        pdf_mode=pdf_mode,
        chunk_size=CHUNK_SIZE,
        chunks=math.ceil(size / CHUNK_SIZE),
        created_at=_now().isoformat(),
    )
    await _save(storage, session)
    return session


async def find(storage: StorageProvider, *, workspace_id: str, user_id: str, upload_id: str) -> UploadSession | None:
    """The user's upload in their workspace, or None -- for one that doesn't exist, isn't theirs, or whose id isn't
    one this module makes (so nothing a caller sends ever becomes another key)."""
    try:
        if str(uuid.UUID(upload_id)) != upload_id:
            return None
        session = UploadSession(**json.loads(await storage.get(_manifest_key(workspace_id, upload_id))))
    except (ValueError, TypeError, AssetNotFoundError):
        return None
    if session.workspace_id != workspace_id or session.user_id != user_id or session.id != upload_id:
        return None
    return session


async def put_part(storage: StorageProvider, session: UploadSession, index: int, data: bytes) -> None:
    await storage.put(session.part_key(index), data, "application/octet-stream")


async def assemble(storage: StorageProvider, session: UploadSession) -> bytes:
    """The file, its parts in order -- once every part is there (UploadIncomplete otherwise) and the whole is the
    size and SHA-256 the upload was started with (UploadMismatch otherwise)."""
    parts: list[bytes] = []
    missing: list[int] = []
    for index in range(session.chunks):
        try:
            part = await storage.get(session.part_key(index))
        except AssetNotFoundError:
            missing.append(index)
            continue
        if len(part) != session.part_size(index):
            missing.append(index)  # can't happen through the API (it checks each part's size); taken as not there
            continue
        parts.append(part)
    if missing:
        raise UploadIncomplete(missing)
    data = b"".join(parts)
    if len(data) != session.size or hashlib.sha256(data).hexdigest() != session.sha256:
        raise UploadMismatch
    return data


async def finished(storage: StorageProvider, session: UploadSession, job_id: str) -> None:
    """The upload became job `job_id`: recorded (so asking again answers that job), and its parts go."""
    session.job_id = job_id
    await _save(storage, session)
    await discard_parts(storage, session)


async def discard_parts(storage: StorageProvider, session: UploadSession) -> None:
    for index in range(session.chunks):
        try:
            await storage.delete(session.part_key(index))
        except Exception:  # noqa: BLE001 -- left for the sweep, never an error for the person
            logger.warning("Could not delete part %d of upload %s", index, session.id)


async def discard(storage: StorageProvider, session: UploadSession) -> None:
    await discard_parts(storage, session)
    try:
        await storage.delete(_manifest_key(session.workspace_id, session.id))
    except Exception:  # noqa: BLE001
        logger.warning("Could not delete upload %s", session.id)


def _sessions(keys: list[tuple[str, datetime]]) -> dict[str, list[tuple[str, datetime]]]:
    """The listed keys by upload (uploads/{workspace}/{upload})."""
    sessions: dict[str, list[tuple[str, datetime]]] = {}
    for key, written in keys:
        parts = key.split("/")
        if len(parts) >= 4 and key.startswith(PREFIX):
            sessions.setdefault("/".join(parts[:3]), []).append((key, written))
    return sessions


async def sweep(storage: StorageProvider, *, prefix: str = PREFIX, now: datetime | None = None, limit: int | None = None) -> int:
    """Deletes the uploads under `prefix` nothing has been written to for SESSION_TTL -- abandoned, failed or
    finished -- at most `limit` of them. A key that can't be deleted now stays listed, so the next sweep tries it
    again; safe to run any number of times, at once too (deleting what is gone is not an error). Returns how many
    uploads were swept; 0 for a store that can't list."""
    cutoff = (now or _now()) - SESSION_TTL
    try:
        keys = await storage.list(prefix)
    except NotImplementedError:
        return 0
    stale = [found for found in _sessions(keys).values() if max(written for _, written in found) < cutoff]
    swept = failed = 0
    for found in stale[:limit] if limit is not None else stale:
        for key, _ in found:
            try:
                await storage.delete(key)
            except Exception:  # noqa: BLE001 -- still listed: the next sweep tries again
                failed += 1
                logger.warning("Could not delete %s", key)
        swept += 1
    if stale:
        # In the logs, so uploads left behind are seen even where nothing else looks (no scheduled sweep).
        logger.info("Upload sweep: %d old upload(s) found, %d swept, %d key(s) not deleted yet", len(stale), swept, failed)
    return swept


async def open_uploads(storage: StorageProvider, workspace_id: str, *, now: datetime | None = None) -> int:
    """The workspace's unfinished uploads that still hold parts and haven't expired (what MAX_OPEN_UPLOADS bounds)."""
    cutoff = (now or _now()) - SESSION_TTL
    sessions = _sessions(await storage.list(f"{PREFIX}{workspace_id}/"))
    return sum(
        1
        for found in sessions.values()
        if any(key.rsplit("/", 1)[-1].startswith("part-") for key, _ in found) and max(written for _, written in found) >= cutoff
    )
