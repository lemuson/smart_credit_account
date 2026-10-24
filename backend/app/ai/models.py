from datetime import datetime

from sqlalchemy import JSON, ForeignKey, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, UTCDateTime, new_id, now


class Conversation(Base):
    __tablename__ = "ai_conversations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    organization_id: Mapped[str] = mapped_column(ForeignKey("profiles.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=now)


class ChatJob(Base):
    """Durable outbox; result is the transactional inbox keyed by request_id."""

    __tablename__ = "ai_chat_jobs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("ai_conversations.id"), index=True)
    message: Mapped[str] = mapped_column(Text)
    application_id: Mapped[str | None] = mapped_column(ForeignKey("applications.id"))
    status: Mapped[str] = mapped_column(String(30), default="pending")
    result: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=now)
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    __table_args__ = (
        Index(
            "uq_ai_active_conversation",
            "conversation_id",
            unique=True,
            sqlite_where=text("status IN ('pending', 'published')"),
            postgresql_where=text("status IN ('pending', 'published')"),
        ),
    )
