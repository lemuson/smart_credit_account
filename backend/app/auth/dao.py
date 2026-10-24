from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.models import User


class UserDAO:
    def __init__(self, session: Session):
        self.session = session

    def by_email(self, email: str):
        return self.session.scalar(select(User).where(User.email == email.lower()))

    def get(self, user_id: str):
        return self.session.get(User, user_id)

    def create(self, **values):
        user = User(**values)
        self.session.add(user)
        self.session.flush()
        return user
