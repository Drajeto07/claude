"""D-012: marks a new, empty database and bucket as an isolated preview's own, or checks that they are.

    python -m scripts.preview_identity check
        Read-only. With the preview's settings in the environment (DATABASE_URL, S3_*, SMARTDOC_ENVIRONMENT,
        PRODUCTION_DB_REF, EXPECTED_DB_INSTANCE, EXPECTED_STORAGE_INSTANCE), says whether the database and the
        bucket prove they are this preview's (app/isolation.py), exactly as the deployed app will decide.

    python -m scripts.preview_identity create --this-is-the-new-preview-project
        (with SMARTDOC_ENVIRONMENT=preview-setup: there are no ids to expect yet)
        Writes the two markers, once, and prints the two instance ids to put in the preview's settings (random
        ids, not secrets). It refuses -- before writing anything -- when the settings mention production, when the
        database already holds accounts or documents (a new preview project is empty; production is not), or when
        a marker is already there.

Nothing here prints a URL, a user, a password or a key. Run it only with the owner's approval (D-012).
"""

import argparse
import asyncio
import json
import sys
import uuid

from sqlalchemy import text

from app import isolation
from app.config import get_settings
from app.db.session import get_session_factory
from app.storage.factory import get_storage_provider

# Tables whose rows mean "this database is in use" -- a new preview project has none.
_IN_USE = ("users", "documents")


class Refused(Exception):
    pass


async def _rows(session, table: str) -> int:
    exists = await session.scalar(text("SELECT to_regclass(:name) IS NOT NULL"), {"name": table})
    return int(await session.scalar(text(f'SELECT count(*) FROM "{table}"'))) if exists else 0


async def create(settings, open_session, storage) -> tuple[str, str | None]:
    if not isolation.required(settings):
        raise Refused("SMARTDOC_ENVIRONMENT must name a preview (preview-...)")
    # Settings() already refused to load if DATABASE_URL / S3_* mention PRODUCTION_DB_REF.
    database_id = str(uuid.uuid4())
    async with open_session() as session:
        for table in _IN_USE:
            if await _rows(session, table):
                raise Refused(f"the database already holds {table}: not a new preview project; nothing written")
        if await session.scalar(text("SELECT to_regclass(:name) IS NOT NULL"), {"name": isolation.MARKER_TABLE}):
            raise Refused("the database already has an identity marker; nothing written")
        await session.execute(text(f"CREATE SCHEMA IF NOT EXISTS {isolation.MARKER_SCHEMA}"))
        await session.execute(
            text(
                f"CREATE TABLE {isolation.MARKER_TABLE} (environment text NOT NULL, instance_id text NOT NULL, "
                "created_at timestamptz NOT NULL DEFAULT now())"
            )
        )
        await session.execute(
            text(f"INSERT INTO {isolation.MARKER_TABLE} (environment, instance_id) VALUES (:environment, :instance_id)"),
            {"environment": isolation.expected_environment(settings), "instance_id": database_id},
        )
        # Nobody but the owner's own login reads it through the API: no grants to Supabase's API roles.
        await session.execute(text(f"REVOKE ALL ON SCHEMA {isolation.MARKER_SCHEMA} FROM PUBLIC"))
        await session.commit()

    storage_id = None
    if settings.storage_backend == "s3":
        try:
            await storage.get(isolation.STORAGE_MARKER_KEY)
        except Exception:  # noqa: BLE001 -- absent, as it should be
            pass
        else:
            raise Refused("the bucket already has an identity marker; the database marker was written, the bucket's not")
        storage_id = str(uuid.uuid4())
        marker = {"environment": isolation.expected_environment(settings), "instance_id": storage_id}
        await storage.put(isolation.STORAGE_MARKER_KEY, json.dumps(marker).encode(), "application/json")
    return database_id, storage_id


async def check(settings, open_session, storage) -> str:
    try:
        async with open_session() as session:
            await isolation.verify(settings, session, storage)
    except isolation.IsolationError as exc:
        return f"REFUSED: {exc}"
    return "VERIFIED: the database and the file store are this preview's own"


async def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("action", choices=["check", "create"])
    parser.add_argument("--this-is-the-new-preview-project", action="store_true", dest="confirmed")
    args = parser.parse_args(argv)
    settings = get_settings()
    if args.action == "check":
        verdict = await check(settings, get_session_factory(), get_storage_provider())
        print(verdict)
        return 0 if verdict.startswith("VERIFIED") else 1
    if not args.confirmed:
        print("create writes the markers: add --this-is-the-new-preview-project once you're sure", file=sys.stderr)
        return 2
    try:
        database_id, storage_id = await create(settings, get_session_factory(), get_storage_provider())
    except Refused as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 1
    print(f"EXPECTED_DB_INSTANCE={database_id}")
    if storage_id:
        print(f"EXPECTED_STORAGE_INSTANCE={storage_id}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:])))
