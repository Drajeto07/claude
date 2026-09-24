"""Manual-only end-to-end check of DATABASE_URL (backend/.env).

Run explicitly from backend/:

    .\\venv\\Scripts\\python.exe -m scripts.verify_database

Uses the app's own engine, so it exercises the exact driver/URL/TLS settings the
running app will. Leaves nothing behind: the write check is always rolled back.
"""

import asyncio
from pathlib import Path
from uuid import uuid4

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text

from app.db.models import Workspace
from app.db.session import get_engine, get_session_factory
from app.models.document import Document, DocumentMetadata
from app.repositories.document_repository import DocumentRepository

_ALEMBIC_INI = Path(__file__).resolve().parent.parent / "alembic.ini"


async def main() -> None:
    engine = get_engine()
    print(f"Connecting to {engine.url.render_as_string(hide_password=True)}")
    async with engine.connect() as conn:
        db_head = (await conn.execute(text("select version_num from alembic_version"))).scalar_one()
        server = f"{conn.dialect.name} {'.'.join(map(str, conn.dialect.server_version_info))}"
    print(f"Server: {server}")

    code_head = ScriptDirectory.from_config(Config(str(_ALEMBIC_INI))).get_current_head()
    verdict = "OK" if db_head == code_head else "OUT OF DATE -- run: python -m alembic upgrade head"
    print(f"Schema: database {db_head}, code {code_head} -> {verdict}")

    async with get_session_factory()() as session:
        workspace = Workspace(name="verify_database", slug=f"verify-database-{uuid4()}")
        session.add(workspace)
        await session.flush()
        repo = DocumentRepository(session)
        document = Document(metadata=DocumentMetadata(title="Проверка на връзката"))
        await repo.create(workspace.id, document)
        session.expunge_all()  # make get() read the row back from the database
        fetched = await repo.get(document.id)
        await session.rollback()
    ok = fetched is not None and fetched.metadata.title == document.metadata.title
    print(f"Repository round-trip (rolled back): {'OK' if ok else 'FAILED'}")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
