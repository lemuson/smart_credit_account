from datetime import datetime

from sqlalchemy import JSON, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, UTCDateTime, new_id, now


class Profile(Base):
    __tablename__ = "profiles"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), unique=True)
    company: Mapped[dict] = mapped_column(JSON, default=dict)
    financials: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=now, onupdate=now)
    version: Mapped[int] = mapped_column(default=1)
    __mapper_args__ = {"version_id_col": version}
