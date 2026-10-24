from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import Field

from app.auth.dependencies import CurrentUser
from app.common import DB, Schema
from app.notifications.service import NotificationService

router = APIRouter(prefix="/notifications", tags=["notifications"])


class ReadNotifications(Schema):
    ids: list[UUID] = Field(default_factory=list, max_length=100)
    all: bool = False


@router.get("")
def notifications(
    db: DB, user: CurrentUser, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100)
):
    return NotificationService(db, user).list(offset, limit)


@router.post("/read")
def read_notifications(data: ReadNotifications, db: DB, user: CurrentUser):
    return NotificationService(db, user).mark_read(data.ids, data.all)
