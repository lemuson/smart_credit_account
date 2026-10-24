from datetime import datetime
from typing import Annotated

from pydantic import EmailStr, StringConstraints

from app.auth.models import Role
from app.common import Schema


class Register(Schema):
    email: EmailStr
    password: Annotated[
        str, StringConstraints(strip_whitespace=False, min_length=10, max_length=128)
    ]


class Login(Schema):
    email: EmailStr
    password: Annotated[
        str, StringConstraints(strip_whitespace=False, min_length=1, max_length=128)
    ]


class UserRead(Schema):
    id: str
    email: EmailStr
    role: Role
    active: bool
    created_at: datetime


class Token(Schema):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class AdminUserCreate(Register):
    role: Role


class UserActive(Schema):
    active: bool


class MeRead(UserRead):
    companies: list[dict]
