from app.common import fail
from app.profiles.dao import ProfileDAO


class ProfileService:
    def __init__(self, session):
        self.dao = ProfileDAO(session)
        self.session = session

    def get(self, user_id):
        profile = self.dao.for_user(user_id)
        if not profile:
            fail(404, "PROFILE_NOT_FOUND")
        return profile

    def update(self, user_id, data):
        profile = self.get(user_id)
        profile.company = data.company.model_dump(mode="json")
        if data.financials is not None:
            profile.financials = data.financials.model_dump(mode="json")
        self.session.flush()
        return profile
