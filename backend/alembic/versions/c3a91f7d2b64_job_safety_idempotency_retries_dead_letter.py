"""job safety: idempotency keys, retries, dead letter

Background jobs (JOB-001): a client's Idempotency-Key (unique per user, so two
concurrent duplicates can't both create a job), how many times a job was retried,
and the dead letter -- a job that failed after its last attempt, kept with its
reason. No new table, so no RLS statement is needed: processing_jobs already has it.

Revision ID: c3a91f7d2b64
Revises: 85211092fe4c
Create Date: 2026-10-01 09:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c3a91f7d2b64'
down_revision: Union[str, Sequence[str], None] = '85211092fe4c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# batch_alter_table: plain ALTER TABLE on Postgres; on SQLite (the migration
# tests) it rebuilds the table.
def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('processing_jobs') as batch:
        batch.add_column(sa.Column('retry_count', sa.Integer(), server_default='0', nullable=False))
        # sa.false(), not text('0'): Postgres won't take an integer default for a boolean.
        batch.add_column(sa.Column('dead_letter', sa.Boolean(), server_default=sa.false(), nullable=False))
        batch.add_column(sa.Column('failure_reason', sa.String(length=200), nullable=True))
        batch.add_column(sa.Column('idempotency_key', sa.String(length=128), nullable=True))
        batch.add_column(sa.Column('request_fingerprint', sa.String(length=64), nullable=True))
        batch.create_index('uq_processing_jobs_created_by_idempotency_key', ['created_by', 'idempotency_key'], unique=True)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('processing_jobs') as batch:
        batch.drop_index('uq_processing_jobs_created_by_idempotency_key')
        for column in ('request_fingerprint', 'idempotency_key', 'failure_reason', 'dead_letter', 'retry_count'):
            batch.drop_column(column)
