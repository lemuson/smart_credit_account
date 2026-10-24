from datetime import timedelta

import jwt
from pwdlib import PasswordHash
from sqlalchemy.orm import Session

from app.auth.dao import UserDAO
from app.auth.models import Role
from app.auth.schemas import Token
from app.common import fail
from app.database import now
from app.profiles.models import Profile

password_hash = PasswordHash.recommended()
DUMMY_HASH = password_hash.hash("dummy-password-for-timing")


class AuthService:
    def __init__(self, session: Session):
        self.dao = UserDAO(session)
        self.session = session

    def register(self, data, role=Role.CLIENT):
        email = str(data.email).lower()
        if self.dao.by_email(email):
            fail(409, "EMAIL_ALREADY_REGISTERED")
        user = self.dao.create(
            email=email, password_hash=password_hash.hash(data.password), role=role
        )
        if role == Role.CLIENT:
            self.session.add(Profile(user_id=user.id))
            self.session.flush()
        return user

    def login(self, data, settings):
        user = self.dao.by_email(str(data.email))
        valid = password_hash.verify(data.password, user.password_hash if user else DUMMY_HASH)
        if not valid or not user or not user.active:
            fail(401, "INVALID_CREDENTIALS")
        issued = now()
        token = jwt.encode(
            {
                "sub": user.id,
                "iat": issued,
                "exp": issued + timedelta(minutes=settings.token_minutes),
                "iss": "smart-credit",
                "aud": "smart-credit-api",
            },
            settings.jwt_secret.get_secret_value(),
            algorithm="HS256",
        )
        return Token(access_token=token, expires_in=settings.token_minutes * 60)
