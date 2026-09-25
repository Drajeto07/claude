"""processing jobs: stage, progress, payload, result; drop export_jobs

Background jobs (корекции.docx §52): every piece of heavy work -- imports, AI
formatting, exports, reading a reference document -- is one `processing_jobs`
row with its stage and real progress, its input and result, who started it and
how many times it was attempted. Exports are jobs like the rest, so the separate
`export_jobs` table, which nothing ever wrote to, goes.

Revision ID: 5f5c3a367f6f
Revises: 74e891504d93
Create Date: 2026-09-25 11:42:46.967360

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import Text
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '5f5c3a367f6f'
down_revision: Union[str, Sequence[str], None] = '74e891504d93'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), 'postgresql')


# batch_alter_table: plain ALTER TABLE on Postgres; on SQLite (the migration
# tests) it rebuilds the table, since SQLite can't add a foreign key in place.
def upgrade() -> None:
    """Upgrade schema."""
    op.drop_index(op.f('ix_export_jobs_document_id'), table_name='export_jobs')
    op.drop_index(op.f('ix_export_jobs_result_asset_id'), table_name='export_jobs')
    op.drop_index(op.f('ix_export_jobs_workspace_id'), table_name='export_jobs')
    op.drop_table('export_jobs')

    with op.batch_alter_table('processing_jobs') as batch:
        batch.add_column(sa.Column('created_by', sa.String(length=36), nullable=True))
        batch.add_column(sa.Column('stage', sa.String(length=30), nullable=True))
        batch.add_column(sa.Column('progress', sa.Integer(), server_default='0', nullable=False))
        batch.add_column(sa.Column('payload', _JSON, nullable=True))
        batch.add_column(sa.Column('input_key', sa.String(length=500), nullable=True))
        batch.add_column(sa.Column('result', _JSON, nullable=True))
        batch.add_column(sa.Column('attempts', sa.Integer(), server_default='0', nullable=False))
        batch.create_index('ix_processing_jobs_created_by', ['created_by'], unique=False)
        batch.create_foreign_key(
            'fk_processing_jobs_created_by_users', 'users', ['created_by'], ['id'], ondelete='SET NULL'
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('processing_jobs') as batch:
        batch.drop_constraint('fk_processing_jobs_created_by_users', type_='foreignkey')
        batch.drop_index('ix_processing_jobs_created_by')
        for column in ('attempts', 'result', 'input_key', 'payload', 'progress', 'stage', 'created_by'):
            batch.drop_column(column)

    op.create_table('export_jobs',
    sa.Column('workspace_id', sa.VARCHAR(length=36), nullable=False),
    sa.Column('document_id', sa.VARCHAR(length=36), nullable=False),
    sa.Column('format', sa.VARCHAR(length=20), nullable=False),
    sa.Column('status', sa.VARCHAR(length=20), nullable=False),
    sa.Column('result_asset_id', sa.VARCHAR(length=36), nullable=True),
    sa.Column('error_message', sa.VARCHAR(length=2000), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.VARCHAR(length=36), nullable=False),
    sa.ForeignKeyConstraint(['document_id'], ['documents.id'], name=op.f('fk_export_jobs_document_id_documents'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['result_asset_id'], ['document_assets.id'], name=op.f('fk_export_jobs_result_asset_id_document_assets'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_export_jobs_workspace_id_workspaces'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_export_jobs'))
    )
    op.create_index(op.f('ix_export_jobs_workspace_id'), 'export_jobs', ['workspace_id'], unique=False)
    op.create_index(op.f('ix_export_jobs_result_asset_id'), 'export_jobs', ['result_asset_id'], unique=False)
    op.create_index(op.f('ix_export_jobs_document_id'), 'export_jobs', ['document_id'], unique=False)
    if op.get_bind().dialect.name == 'postgresql':  # every table keeps RLS on (see 4cbc55236361)
        op.execute('ALTER TABLE export_jobs ENABLE ROW LEVEL SECURITY')
