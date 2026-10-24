from fastapi import APIRouter

from app.auth.dependencies import Client
from app.common import DB
from app.profiles.schemas import ProfileRead, ProfileUpdate
from app.profiles.service import ProfileService

router = APIRouter(prefix="/profile", tags=["profile"])


@router.get("", response_model=ProfileRead)
def get_profile(db: DB, user: Client):
    return ProfileService(db).get(user.id)


@router.put("", response_model=ProfileRead)
def update_profile(data: ProfileUpdate, db: DB, user: Client):
    return ProfileService(db).update(user.id, data)
