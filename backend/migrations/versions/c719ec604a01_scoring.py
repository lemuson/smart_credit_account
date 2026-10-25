"""Immutable scoring assessments, simulations and idempotency records."""

import sqlalchemy as sa
from alembic import op

from app.database import UTCDateTime

revision = "c719ec604a01"
down_revision = "b2610ac935ef"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "scoring_assessments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("profiles.id"), nullable=False),
        sa.Column(
            "application_id", sa.String(36), sa.ForeignKey("applications.id"), nullable=False
        ),
        sa.Column("application_version", sa.Integer(), nullable=False),
        sa.Column("features", sa.JSON(), nullable=False),
        sa.Column("feature_sha256", sa.String(64), nullable=False),
        sa.Column("response", sa.JSON(), nullable=False),
        sa.Column("diagnostics", sa.JSON(), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
    )
    for name in ("organization_id", "application_id"):
        op.create_index(f"ix_scoring_assessments_{name}", "scoring_assessments", [name])
    op.create_table(
        "scoring_what_ifs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("profiles.id"), nullable=False),
        sa.Column(
            "assessment_id", sa.String(36), sa.ForeignKey("scoring_assessments.id"), nullable=False
        ),
        sa.Column("features", sa.JSON(), nullable=False),
        sa.Column("response", sa.JSON(), nullable=False),
        sa.Column("diagnostics", sa.JSON(), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
    )
    for name in ("organization_id", "assessment_id"):
        op.create_index(f"ix_scoring_what_ifs_{name}", "scoring_what_ifs", [name])
    op.create_table(
        "scoring_requests",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("profiles.id"), nullable=False),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("key", sa.String(36), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("response", sa.JSON(), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.UniqueConstraint("organization_id", "user_id", "key"),
    )


def downgrade():
    op.drop_table("scoring_requests")
    op.drop_table("scoring_what_ifs")
    op.drop_table("scoring_assessments")
