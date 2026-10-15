"""D-012: an isolated preview proves, before it serves anyone, that the database and the file
store it is connected to are its own -- by what they say about themselves, not by what their
URLs look like.

Each isolated resource carries an identity marker that only its setup writes:

- the database: one row in ``smartdoc_identity.deployment`` (its own schema, outside the app's
  tables and the migrations), holding the environment and a random instance id;
- the file store: the object ``_smartdoc/identity.json`` in the bucket, with the same two fields.

A preview (SMARTDOC_ENVIRONMENT=preview...) expects both instance ids (EXPECTED_DB_INSTANCE,
EXPECTED_STORAGE_INSTANCE -- random ids, not secrets). Production has no marker that says
"preview", let alone with the expected id, so a preview that was pointed at it -- by a pasted URL,
a pooler address, a rollback or a typo -- finds no match and refuses every request (503) except the
health probe, which says why. Fail-closed: no marker, a second row, another environment, another
id, a database or store that doesn't answer -- all mean "not proven", never "probably fine".

Nothing here writes anything; the markers are made once, by scripts/preview_identity.py.
"""

import json
import logging
import time
from dataclasses import dataclass

from sqlalchemy import text

from app.config import Settings

logger = logging.getLogger(__name__)

MARKER_SCHEMA = "smartdoc_identity"
MARKER_TABLE = f"{MARKER_SCHEMA}.deployment"
STORAGE_MARKER_KEY = "_smartdoc/identity.json"

# A failed proof is tried again after this long (a database that was briefly away); a proof that
# passed holds for the life of the process -- its settings can't change under it.
RETRY_AFTER_SECONDS = 30


class IsolationError(Exception):
    """Why a preview isn't proven to be on its own resources. The message names no host, user or key."""


@dataclass(frozen=True)
class Identity:
    environment: str
    instance_id: str


def required(settings: Settings) -> bool:
    """Whether this deployment must prove its isolation (Settings.isolation_required): a preview by its name, by
    Vercel's own variables for a pinned branch, or by any guard setting it carries."""
    return settings.isolation_required


def expected_environment(settings: Settings) -> str:
    """The environment a preview's markers must name: "preview" for any preview-* deployment."""
    return "preview"


def check_identity(found: list[Identity], expected_instance: str, settings: Settings, what: str) -> None:
    """Exactly one marker, naming a preview and the instance this deployment expects."""
    if not expected_instance:
        raise IsolationError(f"{what}: no expected instance id is set for this preview")
    if not found:
        raise IsolationError(f"{what}: no identity marker (not an isolated preview resource)")
    if len(found) > 1:
        raise IsolationError(f"{what}: more than one identity marker")
    identity = found[0]
    if identity.environment != expected_environment(settings):
        raise IsolationError(f"{what}: the marker names another environment ({identity.environment!r})")
    if identity.instance_id != expected_instance:
        raise IsolationError(f"{what}: the marker names another instance")


async def database_identity(session) -> list[Identity]:
    """The database's markers, as the connected database itself reports them. A database without the
    marker schema (production, a fresh one) raises; the caller treats any failure as not proven."""
    rows = await session.execute(text(f"SELECT environment, instance_id FROM {MARKER_TABLE}"))
    return [Identity(str(environment), str(instance_id)) for environment, instance_id in rows]


def parse_storage_marker(raw: bytes) -> list[Identity]:
    try:
        data = json.loads(raw)
        return [Identity(str(data["environment"]), str(data["instance_id"]))]
    except (ValueError, KeyError, TypeError) as exc:
        raise IsolationError("file store: the identity marker can't be read") from exc


async def verify(settings: Settings, session, storage) -> None:
    """Both proofs, or IsolationError. Storage is checked only when the deployment keeps files in a
    bucket (STORAGE_BACKEND=s3); a preview on a local disk has no shared store to reach."""
    try:
        found = await database_identity(session)
    except IsolationError:
        raise
    except Exception as exc:  # noqa: BLE001 -- any failure to read the marker is "not proven"
        raise IsolationError("database: the identity marker can't be read") from exc
    check_identity(found, settings.expected_db_instance, settings, "database")

    if settings.storage_backend != "s3":
        return
    try:
        raw = await storage.get(STORAGE_MARKER_KEY)
    except Exception as exc:  # noqa: BLE001 -- missing object, refused key, store away: all "not proven"
        raise IsolationError("file store: no identity marker (not an isolated preview bucket)") from exc
    check_identity(parse_storage_marker(raw), settings.expected_storage_instance, settings, "file store")


class IsolationGate:
    """Holds the outcome for the process: proven once, it stays proven; refused, it is tried again
    after RETRY_AFTER_SECONDS, and until then every request is refused with the same reason."""

    def __init__(self) -> None:
        self.proven = False
        self.reason: str | None = None
        self._checked_at = 0.0

    def reset(self) -> None:
        self.__init__()

    async def ensure(self, settings: Settings, open_session, storage_provider) -> bool:
        if self.proven or not required(settings):
            return True
        if self.reason is not None and time.monotonic() - self._checked_at < RETRY_AFTER_SECONDS:
            return False
        self._checked_at = time.monotonic()
        try:
            async with open_session() as session:
                await verify(settings, session, storage_provider())
        except IsolationError as exc:
            self.reason = str(exc)
            logger.error("Preview isolation not proven: %s; refusing requests", self.reason)
            return False
        except Exception:  # noqa: BLE001 -- e.g. the store's settings are incomplete: not proven
            self.reason = "the isolation check could not run"
            logger.exception("Preview isolation check failed to run; refusing requests")
            return False
        self.proven, self.reason = True, None
        logger.info("Preview isolation proven: database and file store carry this preview's identity")
        return True

    def state(self, settings: Settings) -> str:
        """For /api/health: "not-required", "verified", "pending" or "refused: <reason>"."""
        if not required(settings):
            return "not-required"
        if self.proven:
            return "verified"
        return f"refused: {self.reason}" if self.reason else "pending"


gate = IsolationGate()
