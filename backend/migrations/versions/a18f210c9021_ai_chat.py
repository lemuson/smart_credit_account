"""Durable AI conversations, outbox and result inbox."""

import sqlalchemy as sa
from alembic import op

from app.database import UTCDateTime

revision = "a18f210c9021"
down_revision = "9b734e204a16"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "ai_conversations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("profiles.id"), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
    )
    op.create_index("ix_ai_conversations_user_id", "ai_conversations", ["user_id"])
    op.create_table(
        "ai_chat_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "conversation_id", sa.String(36), sa.ForeignKey("ai_conversations.id"), nullable=False
        ),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("application_id", sa.String(36), sa.ForeignKey("applications.id")),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("result", sa.JSON()),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("published_at", UTCDateTime()),
    )
    op.create_index("ix_ai_chat_jobs_conversation_id", "ai_chat_jobs", ["conversation_id"])
    op.create_index(
        "uq_ai_active_conversation",
        "ai_chat_jobs",
        ["conversation_id"],
        unique=True,
        sqlite_where=sa.text("status IN ('pending', 'published')"),
        postgresql_where=sa.text("status IN ('pending', 'published')"),
    )


def downgrade():
    op.drop_table("ai_chat_jobs")
    op.drop_table("ai_conversations")
