from datetime import datetime

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, UTCDateTime, now


class NotificationRead(Base):
    __tablename__ = "notification_reads"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    event_id: Mapped[str] = mapped_column(ForeignKey("audit_events.id"), primary_key=True)
    read_at: Mapped[datetime] = mapped_column(UTCDateTime, default=now)
