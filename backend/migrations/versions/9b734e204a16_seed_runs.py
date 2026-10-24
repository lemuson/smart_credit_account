"""Persistent marker for one-time demo initialization.

Revision ID: 9b734e204a16
Revises: 6e0592cfecaf
"""

import sqlalchemy as sa
from alembic import op

from app.database import UTCDateTime

revision = "9b734e204a16"
down_revision = "6e0592cfecaf"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "seed_runs",
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.PrimaryKeyConstraint("name", name=op.f("pk_seed_runs")),
    )


def downgrade():
    op.drop_table("seed_runs")
