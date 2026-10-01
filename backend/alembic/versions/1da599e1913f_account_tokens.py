"""account tokens

Single-use tokens the app e-mails: password reset (ACCT-002) and address
verification (ACCT-003). Only each token's SHA-256 is stored.

Revision ID: 1da599e1913f
Revises: 85211092fe4c
Create Date: 2026-10-01 15:24:53.319808

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1da599e1913f'
down_revision: Union[str, Sequence[str], None] = '85211092fe4c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('account_tokens',
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('purpose', sa.String(length=32), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('email', sa.String(length=320), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_account_tokens_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_account_tokens')),
    sa.UniqueConstraint('token_hash', name=op.f('uq_account_tokens_token_hash'))
    )
    op.create_index('ix_account_tokens_user_id_purpose', 'account_tokens', ['user_id', 'purpose'], unique=False)
    if op.get_bind().dialect.name == 'postgresql':  # every table keeps RLS on (see 4cbc55236361)
        op.execute('ALTER TABLE account_tokens ENABLE ROW LEVEL SECURITY')


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_account_tokens_user_id_purpose', table_name='account_tokens')
    op.drop_table('account_tokens')
