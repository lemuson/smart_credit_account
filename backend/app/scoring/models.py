from datetime import datetime

from sqlalchemy import JSON, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, UTCDateTime, new_id, now


class ScoringAssessment(Base):
    __tablename__ = "scoring_assessments"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organization_id: Mapped[str] = mapped_column(ForeignKey("profiles.id"), index=True)
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id"), index=True)
    application_version: Mapped[int]
    features: Mapped[dict] = mapped_column(JSON)
    feature_sha256: Mapped[str] = mapped_column(String(64))
    response: Mapped[dict] = mapped_column(JSON)
    diagnostics: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=now)


class ScoringWhatIf(Base):
    __tablename__ = "scoring_what_ifs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organization_id: Mapped[str] = mapped_column(ForeignKey("profiles.id"), index=True)
    assessment_id: Mapped[str] = mapped_column(ForeignKey("scoring_assessments.id"), index=True)
    features: Mapped[dict] = mapped_column(JSON)
    response: Mapped[dict] = mapped_column(JSON)
    diagnostics: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=now)


class ScoringRequest(Base):
    __tablename__ = "scoring_requests"
    __table_args__ = (UniqueConstraint("organization_id", "user_id", "key"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organization_id: Mapped[str] = mapped_column(ForeignKey("profiles.id"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    key: Mapped[str] = mapped_column(String(36))
    fingerprint: Mapped[str] = mapped_column(String(64))
    response: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=now)
