from fastapi import APIRouter

from app.auth.dependencies import Client
from app.common import DB
from app.feed.schemas import FeedRead
from app.feed.service import FeedService

router = APIRouter(prefix="/client/feed", tags=["feed"])


@router.get("", response_model=FeedRead)
def feed(db: DB, user: Client):
    return FeedService(db).get(user)
