"""users email verified at

When a user's address was confirmed by a link sent to it (ACCT-003).

Revision ID: 0417f0f393fc
Revises: 1da599e1913f
Create Date: 2026-10-01 15:48:43.098296

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0417f0f393fc'
down_revision: Union[str, Sequence[str], None] = '1da599e1913f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('users', sa.Column('email_verified_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('users') as batch:
        batch.drop_column('email_verified_at')
