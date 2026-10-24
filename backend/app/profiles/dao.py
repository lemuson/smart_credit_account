from sqlalchemy import select
from sqlalchemy.orm import Session

from app.profiles.models import Profile


class ProfileDAO:
    def __init__(self, session: Session):
        self.session = session

    def for_user(self, user_id):
        return self.session.scalar(select(Profile).where(Profile.user_id == user_id))
