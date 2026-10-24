from sqlalchemy import select

from app.applications.models import Application
from app.feed.dao import FeedDAO
from app.feed.schemas import FeedRead
from app.profiles.service import ProfileService


class FeedService:
    def __init__(self, session):
        self.session = session

    def get(self, user):
        profile = ProfileService(self.session).get(user.id)
        industry = profile.company.get("industry", "")
        statuses = set(
            self.session.scalars(select(Application.status).where(Application.client_id == user.id))
        )
        return FeedRead(
            items=[
                item
                for item in FeedDAO().list()
                if (not item.industry_prefix or industry.startswith(item.industry_prefix))
                and (not item.application_status or item.application_status in statuses)
            ]
        )
