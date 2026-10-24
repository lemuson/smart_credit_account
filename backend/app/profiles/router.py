from fastapi import APIRouter

from app.auth.dependencies import Client
from app.common import DB
from app.loans.obligations import credit_obligations
from app.profiles.schemas import ProfileRead, ProfileUpdate
from app.profiles.service import ProfileService

router = APIRouter(prefix="/profile", tags=["profile"])


@router.get("", response_model=ProfileRead)
def get_profile(db: DB, user: Client):
    profile = ProfileService(db).get(user.id)
    return {
        **ProfileRead.model_validate(profile).model_dump(),
        "credit_obligations": credit_obligations(db, user.id, profile.financials),
    }


@router.put("", response_model=ProfileRead)
def update_profile(data: ProfileUpdate, db: DB, user: Client):
    profile = ProfileService(db).update(user.id, data)
    return {
        **ProfileRead.model_validate(profile).model_dump(),
        "credit_obligations": credit_obligations(db, user.id, profile.financials),
    }
