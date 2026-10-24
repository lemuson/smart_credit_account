"""Регистрация metadata для миграций."""

from app.applications.models import Application, AuditEvent, CheckRun, Clarification, Document
from app.auth.models import User
from app.loans.models import Loan
from app.products.models import Product
from app.profiles.models import Profile
from app.risk.models import RiskPolicy, RiskPolicyRevision
from app.seed import SeedRun

__all__ = [
    "Application",
    "AuditEvent",
    "CheckRun",
    "Clarification",
    "Document",
    "User",
    "Loan",
    "Product",
    "Profile",
    "RiskPolicy",
    "RiskPolicyRevision",
    "SeedRun",
]
