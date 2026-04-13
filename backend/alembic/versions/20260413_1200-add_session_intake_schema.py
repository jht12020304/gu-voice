"""add_session_intake_schema

Revision ID: 8e3e8a4d5f01
Revises: c98fa7840c8c
Create Date: 2026-04-13 12:00:00.000000+08:00

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "8e3e8a4d5f01"
down_revision: Union[str, None] = "c98fa7840c8c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "sessions",
        sa.Column("intake_data", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "sessions",
        sa.Column("intake_completed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("sessions", "intake_completed_at")
    op.drop_column("sessions", "intake_data")
