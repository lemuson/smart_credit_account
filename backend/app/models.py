"""Регистрация metadata для миграций."""

from app.ai.models import ChatJob, Conversation
from app.applications.models import Application, AuditEvent, CheckRun, Clarification, Document
from app.auth.models import User
from app.loans.models import Loan
from app.notifications.models import NotificationRead
from app.products.models import Product
from app.profiles.models import Profile
from app.risk.models import RiskPolicy, RiskPolicyRevision
from app.scoring.models import ScoringAssessment, ScoringRequest, ScoringWhatIf
from app.seed import SeedRun

__all__ = [
    "ChatJob",
    "Conversation",
    "Application",
    "AuditEvent",
    "CheckRun",
    "Clarification",
    "Document",
    "User",
    "Loan",
    "NotificationRead",
    "Product",
    "Profile",
    "RiskPolicy",
    "RiskPolicyRevision",
    "SeedRun",
    "ScoringAssessment",
    "ScoringRequest",
    "ScoringWhatIf",
]
