"""sessions last used and known browsers

ACCT-006: `sessions.last_used_at`, so a user's list of sessions says when each was
last used. ACCT-007: `known_browsers`, the browsers a user has signed in from (the
SHA-256 of each one's device cookie), so a sign-in from another one is e-mailed.
Both are schema only: old sessions show no last use until their next request.

Revision ID: b4b303454a89
Revises: b8534d3c4256
Create Date: 2026-10-01 15:23:16.783152

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b4b303454a89'
down_revision: Union[str, Sequence[str], None] = 'b8534d3c4256'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('known_browsers',
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('device_hash', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_known_browsers_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_known_browsers')),
    sa.UniqueConstraint('user_id', 'device_hash', name=op.f('uq_known_browsers_user_id'))
    )
    if op.get_bind().dialect.name == 'postgresql':  # every table keeps RLS on (see 4cbc55236361)
        op.execute('ALTER TABLE known_browsers ENABLE ROW LEVEL SECURITY')
    op.add_column('sessions', sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('sessions') as batch:  # SQLite drops a column by copying the table
        batch.drop_column('last_used_at')
    op.drop_table('known_browsers')
