"""document versions compressed data

PERF-004: a version's document state is stored zlib-compressed in
`compressed_data` (bytea), about 5x smaller than the JSON. Schema only, so the
upgrade is quick and renders in offline (--sql) mode: rows already written keep
their uncompressed `data`, which the app still reads (DocumentVersion.data), so
`data` becomes nullable and a check makes every row hold exactly one of the two.
No table is created, so there is no RLS to enable.

The downgrade decompresses every compressed row back into `data` before the
column goes, so no version is lost; it needs a live connection for that.

Revision ID: b8534d3c4256
Revises: 85211092fe4c
Create Date: 2026-10-01 09:00:00.000000

"""
import json
import zlib
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import Text
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'b8534d3c4256'
down_revision: Union[str, Sequence[str], None] = '85211092fe4c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), 'postgresql')
_ONE_COPY = 'ck_document_versions_one_copy'


# batch_alter_table: plain ALTER TABLE on Postgres; on SQLite (the migration
# tests) it rebuilds the table, since SQLite can't change a column's NULL in place.
def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('document_versions') as batch:
        batch.add_column(sa.Column('compressed_data', sa.LargeBinary(), nullable=True))
        batch.alter_column('data', existing_type=_JSON, nullable=True)
        batch.create_check_constraint(op.f(_ONE_COPY), '(data IS NULL) <> (compressed_data IS NULL)')


def downgrade() -> None:
    """Downgrade schema."""
    if op.get_context().as_sql:
        raise RuntimeError("This downgrade decompresses stored versions, so it needs a database connection (not --sql).")
    versions = sa.table(
        'document_versions', sa.column('id', sa.String()), sa.column('data', _JSON), sa.column('compressed_data', sa.LargeBinary())
    )
    bind = op.get_bind()
    ids = bind.execute(sa.select(versions.c.id).where(versions.c.compressed_data.is_not(None))).scalars().all()
    # One row at a time: a version can be megabytes once decompressed.
    for version_id in ids:
        compressed = bind.execute(sa.select(versions.c.compressed_data).where(versions.c.id == version_id)).scalar_one()
        bind.execute(
            versions.update()
            .where(versions.c.id == version_id)
            .values(data=json.loads(zlib.decompress(compressed)), compressed_data=None)
        )

    with op.batch_alter_table('document_versions') as batch:
        batch.drop_constraint(op.f(_ONE_COPY), type_='check')
        batch.alter_column('data', existing_type=_JSON, nullable=False)
        batch.drop_column('compressed_data')
