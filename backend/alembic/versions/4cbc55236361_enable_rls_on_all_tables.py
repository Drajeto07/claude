"""enable rls on all tables

Supabase exposes `public` tables through its REST/GraphQL Data API to anyone
holding the project's public anon key. RLS with no policies denies that path;
the backend connects as the table owner, which bypasses RLS, so it is unaffected.
Every later migration that creates a table must enable RLS on it the same way
(tests/test_db_migration.py fails otherwise).

Revision ID: 4cbc55236361
Revises: 361677e33e9c
Create Date: 2026-09-24 09:44:40.168445

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '4cbc55236361'
down_revision: Union[str, Sequence[str], None] = '361677e33e9c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLES = (
    "alembic_version",
    "users",
    "workspaces",
    "workspace_members",
    "sessions",
    "documents",
    "document_versions",
    "document_assets",
    "templates",
    "template_versions",
    "formatting_profiles",
    "processing_jobs",
    "export_jobs",
    "subscriptions",
    "usage_records",
)


def _is_postgres() -> bool:
    # get_context().dialect also works in offline (--sql) mode; get_bind() is None there.
    return op.get_context().dialect.name == "postgresql"


def upgrade() -> None:
    """Upgrade schema."""
    if not _is_postgres():
        return
    for table in _TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    """Downgrade schema."""
    if not _is_postgres():
        return
    for table in _TABLES:
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
