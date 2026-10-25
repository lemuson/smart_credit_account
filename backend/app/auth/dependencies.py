import re
import secrets
from typing import Annotated

import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.ai.models import ChatJob, Conversation
from app.auth.dao import UserDAO
from app.auth.models import Role, User
from app.common import DB, fail
from app.profiles.service import ProfileService

bearer = HTTPBearer(auto_error=False)


def current_user(
    request: Request,
    db: DB,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
):
    if not credentials:
        fail(401, "AUTHENTICATION_REQUIRED")
    try:
        payload = jwt.decode(
            credentials.credentials,
            request.app.state.settings.jwt_secret.get_secret_value(),
            algorithms=["HS256"],
            audience="smart-credit-api",
            issuer="smart-credit",
            options={"require": ["exp", "iat", "sub"]},
        )
    except jwt.InvalidAudienceError:
        return delegated_user(request, db, credentials.credentials)
    except jwt.InvalidTokenError:
        fail(401, "INVALID_TOKEN")
    user = UserDAO(db).get(payload["sub"])
    if not user or not user.active:
        fail(401, "INVALID_TOKEN")
    return user


CurrentUser = Annotated[User, Depends(current_user)]


def require_client(user: CurrentUser):
    if user.role != Role.CLIENT:
        fail(403, "CLIENT_REQUIRED")
    return user


def require_manager(user: CurrentUser):
    if user.role != Role.MANAGER:
        fail(403, "MANAGER_REQUIRED")
    return user


Client = Annotated[User, Depends(require_client)]
Manager = Annotated[User, Depends(require_manager)]


def require_admin(user: CurrentUser):
    if user.role != Role.ADMIN:
        fail(403, "ADMIN_REQUIRED")
    return user


Admin = Annotated[User, Depends(require_admin)]


def delegated_user(request, db, token):
    settings = request.app.state.settings
    service_token = settings.ai_service_token
    if (
        not settings.ai_enabled
        or not service_token
        or not secrets.compare_digest(
            request.headers.get("X-Service-Token", ""), service_token.get_secret_value()
        )
    ):
        fail(401, "INVALID_SERVICE_IDENTITY")
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret.get_secret_value(),
            algorithms=["HS256"],
            audience="smart-credit-ai-tools",
            issuer="smart-credit",
            options={"require": ["exp", "iat", "sub", "organization_id", "request_id"]},
        )
    except jwt.InvalidTokenError:
        fail(401, "INVALID_TOKEN")
    path = request.url.path
    allowed = (
        request.method == "GET"
        and (
            path in {"/api/v1/profile", "/api/v1/credit-products/search"}
            or re.fullmatch(r"/api/v1/credit-products/[0-9a-f-]{36}(/required-documents)?", path)
            or re.fullmatch(r"/api/v1/applications/[0-9a-f-]{36}/status", path)
            or re.fullmatch(r"/api/v1/scoring/assessments/[0-9a-f-]{36}", path)
        )
    ) or (
        request.method == "POST"
        and re.fullmatch(r"/api/v1/applications/[0-9a-f-]{36}/validate", path)
    )
    if not allowed:
        fail(403, "AI_SCOPE_REQUIRED")
    user = UserDAO(db).get(payload["sub"])
    if not user or not user.active or user.role != Role.CLIENT:
        fail(401, "INVALID_TOKEN")
    profile = ProfileService(db).get(user.id)
    job = db.get(ChatJob, payload["request_id"])
    conversation = db.get(Conversation, job.conversation_id) if job else None
    if (
        not conversation
        or job.result is not None
        or conversation.user_id != user.id
        or conversation.organization_id != profile.id
        or payload["organization_id"] != profile.id
        or request.headers.get("X-User-ID") != user.id
        or request.headers.get("X-Organization-ID") != profile.id
        or request.headers.get("X-Request-ID") != job.id
    ):
        fail(403, "AI_CONTEXT_MISMATCH")
    request.state.ai_delegated = True
    return user
