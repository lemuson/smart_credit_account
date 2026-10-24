from fastapi import APIRouter

from app.auth.dependencies import Admin
from app.common import DB
from app.risk.schemas import RiskPolicyRead, RiskPolicyUpdate
from app.risk.service import RiskPolicyService

router = APIRouter(prefix="/admin/risk-policy", tags=["risk-policy"])


@router.get("", response_model=RiskPolicyRead)
def get_policy(db: DB, user: Admin):
    return RiskPolicyService(db).get()


@router.put("", response_model=RiskPolicyRead)
def update_policy(data: RiskPolicyUpdate, db: DB, user: Admin):
    return RiskPolicyService(db).update(data, user)


@router.get("/history")
def history(db: DB, user: Admin):
    return [
        {
            "version": item.version,
            "rules": item.rules,
            "actor_id": item.actor_id,
            "created_at": item.created_at,
        }
        for item in RiskPolicyService(db).dao.history()
    ]
