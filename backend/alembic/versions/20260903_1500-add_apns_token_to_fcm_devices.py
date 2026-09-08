"""Store native APNs tokens for direct iOS delivery fallback.

Revision ID: f4a5b6c7d8e9
Revises: e3f4a5b6c7d8
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f4a5b6c7d8e9"
down_revision: Union[str, None] = "e3f4a5b6c7d8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "fcm_devices",
        sa.Column("apns_token", sa.String(length=200), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("fcm_devices", "apns_token")
