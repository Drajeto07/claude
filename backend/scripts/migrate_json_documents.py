"""One-shot migration: backend/data/documents/*.json (the pre-database JSON-file
store, see app/services/persistence.py) -> the `documents` table.

Every migrated document is attached to one existing account's personal
workspace, so it shows up for that user after sign-in -- register in the app
first. Never touches the source JSON files (doc §70); re-running is always safe,
since a document id already present in the database is skipped, never
overwritten. Nothing imports or calls this automatically.

Run from backend/, with DATABASE_URL already reachable:

    .\\venv\\Scripts\\python.exe -m scripts.migrate_json_documents --owner-email you@example.com [--dry-run] [--only ID ...]
"""

import argparse
import asyncio

from sqlalchemy import select

from app.db.models import User
from app.db.session import get_session_factory
from app.repositories.document_repository import DocumentRepository
from app.services import persistence
from app.services.auth_service import normalize_email
from app.services.document_service import DocumentService
from app.storage.factory import get_storage_provider


async def migrate(
    owner_email: str, dry_run: bool, session_factory=None, storage=None, only: list[str] | None = None
) -> None:
    """`session_factory` and `storage` are injectable so tests can use a
    throwaway SQLite engine and asset directory instead of the real ones.
    Each document goes through DocumentService.create -- the same path as a
    fresh upload (inline images become assets, version history starts) -- and
    is committed on its own, so one bad file can't undo the others."""
    session_factory = session_factory or get_session_factory()
    storage = storage or get_storage_provider()
    documents = persistence.load_all_documents()
    print(f"Found {len(documents)} document(s) in the JSON store at {persistence._DATA_DIR}.")
    if only:
        documents = {doc_id: doc for doc_id, doc in documents.items() if doc_id.startswith(tuple(only))}
        print(f"--only selects {len(documents)} of them.")

    migrated: list[str] = []
    skipped: list[str] = []
    failed: list[tuple[str, str]] = []

    async with session_factory() as session:
        owner = (
            await session.execute(select(User).where(User.email == normalize_email(owner_email)))
        ).scalar_one_or_none()
        if owner is None:
            raise SystemExit(f"No account for {owner_email!r} -- register in the app first, then re-run.")
        repo = DocumentRepository(session)
        service = DocumentService(session, user_id=owner.id, storage=storage)

        for document_id, document in documents.items():
            try:
                if await repo.get(document_id) is not None:
                    skipped.append(document_id)
                    continue
                if not dry_run:
                    await service.create(document)
                migrated.append(document_id)
            except Exception as exc:  # noqa: BLE001 -- one bad document must not abort the whole batch
                await session.rollback()
                failed.append((document_id, str(exc)))

    verb = "Would migrate" if dry_run else "Migrated"
    print(f"\n{verb}: {len(migrated)} (into {owner_email}'s personal workspace)")
    print(f"Already present in DB (skipped): {len(skipped)}")
    print(f"Failed: {len(failed)}")
    for document_id, reason in failed:
        print(f"  - {document_id}: {reason}")
    print(f"\nSource JSON files were left untouched at {persistence._DATA_DIR}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner-email", required=True, help="Existing account whose workspace receives the documents.")
    parser.add_argument("--dry-run", action="store_true", help="Report what would happen without writing anything.")
    parser.add_argument("--only", nargs="+", metavar="ID", help="Import just these documents (full ids or id prefixes).")
    args = parser.parse_args()
    asyncio.run(migrate(args.owner_email, args.dry_run, only=args.only))


if __name__ == "__main__":
    main()
