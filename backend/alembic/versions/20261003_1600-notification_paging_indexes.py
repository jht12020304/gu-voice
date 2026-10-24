"""Index notification paging and unread counts without blocking table writes."""
from alembic import op
import sqlalchemy as sa

revision = "smoothness_20261003"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade():
    with op.get_context().autocommit_block():
        op.create_index("ix_notifications_user_created_id", "notifications",
                        ["user_id", "created_at", "id"], postgresql_concurrently=True)
        op.create_index("ix_notifications_user_unread", "notifications", ["user_id"],
                        postgresql_where=sa.text("is_read = false"), postgresql_concurrently=True)


def downgrade():
    with op.get_context().autocommit_block():
        op.drop_index("ix_notifications_user_unread", table_name="notifications", postgresql_concurrently=True)
        op.drop_index("ix_notifications_user_created_id", table_name="notifications", postgresql_concurrently=True)
