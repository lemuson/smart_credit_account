from datetime import datetime

from sqlalchemy import JSON, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, UTCDateTime, now


class RiskPolicy(Base):
    __tablename__ = "risk_policy"
    id: Mapped[int] = mapped_column(primary_key=True)
    version: Mapped[int] = mapped_column(default=1)
    rules: Mapped[dict] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=now, onupdate=now)
    __mapper_args__ = {"version_id_col": version}


class RiskPolicyRevision(Base):
    __tablename__ = "risk_policy_revisions"
    version: Mapped[int] = mapped_column(primary_key=True)
    rules: Mapped[dict] = mapped_column(JSON)
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=now)
