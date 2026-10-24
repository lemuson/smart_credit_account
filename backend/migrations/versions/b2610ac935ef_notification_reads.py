"""Persistent per-user notification read state."""

import sqlalchemy as sa
from alembic import op

from app.database import UTCDateTime

revision = "b2610ac935ef"
down_revision = "a18f210c9021"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "notification_reads",
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("event_id", sa.String(36), sa.ForeignKey("audit_events.id"), primary_key=True),
        sa.Column("read_at", UTCDateTime(), nullable=False),
    )


def downgrade():
    op.drop_table("notification_reads")
