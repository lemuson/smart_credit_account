from typing import Annotated

import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.auth.dao import UserDAO
from app.auth.models import Role, User
from app.common import DB, fail

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
