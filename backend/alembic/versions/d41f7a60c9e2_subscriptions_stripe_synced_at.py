"""subscriptions stripe synced at

PLAN-004 (Stripe flows): when Stripe was read for what a subscription row
holds. Webhooks handled at the same moment can write in either order; a read
older than the stored one is no longer written over it. Nullable, no default:
rows from before simply have no read recorded yet. No table is created, so
there is no RLS to enable.

Revision ID: d41f7a60c9e2
Revises: b8534d3c4256
Create Date: 2026-10-01 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd41f7a60c9e2'
down_revision: Union[str, Sequence[str], None] = 'b8534d3c4256'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('subscriptions', sa.Column('stripe_synced_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('subscriptions', 'stripe_synced_at')
