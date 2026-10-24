from app.common import fail
from app.database import now
from app.risk.dao import RiskPolicyDAO
from app.risk.models import RiskPolicy, RiskPolicyRevision
from app.risk.schemas import RiskPolicyRead, RiskRules


class RiskPolicyService:
    def __init__(self, session):
        self.session = session
        self.dao = RiskPolicyDAO(session)

    def get(self):
        policy = self.dao.get()
        return RiskPolicyRead(
            version=policy.version if policy else 0,
            rules=RiskRules.model_validate(policy.rules) if policy else RiskRules(),
        )

    def update(self, data, user):
        policy = self.dao.get()
        current_version = policy.version if policy else 0
        if current_version != data.expected_version:
            fail(409, "RISK_POLICY_VERSION_CONFLICT", current_version=current_version)
        rules = data.rules.model_dump(mode="json")
        if policy is None:
            policy = RiskPolicy(id=1, rules=rules)
            self.session.add(policy)
        else:
            policy.rules = rules
            policy.updated_at = now()
        self.session.flush()
        self.session.add(RiskPolicyRevision(version=policy.version, rules=rules, actor_id=user.id))
        self.session.flush()
        return self.get()
