from sqlalchemy import select

from app.risk.models import RiskPolicy, RiskPolicyRevision


class RiskPolicyDAO:
    def __init__(self, session):
        self.session = session

    def get(self):
        return self.session.get(RiskPolicy, 1)

    def history(self):
        return self.session.scalars(
            select(RiskPolicyRevision).order_by(RiskPolicyRevision.version)
        ).all()
