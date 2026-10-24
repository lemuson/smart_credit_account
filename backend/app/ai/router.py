from uuid import UUID

from fastapi import APIRouter, Request
from pydantic import Field
from sqlalchemy import select

from app.ai.models import ChatJob
from app.ai.service import conversation_for, enqueue, new_conversation
from app.auth.dependencies import Client
from app.common import DB, Schema, fail

router = APIRouter(prefix="/chat", tags=["AI chat"])


class MessageCreate(Schema):
    request_id: UUID
    message: str = Field(min_length=1, max_length=8000)
    application_id: UUID | None = None


def job_response(job):
    return {
        "request_id": job.id,
        "conversation_id": job.conversation_id,
        "message": job.message,
        "status": job.status,
        "result": job.result,
    }


@router.post("/conversations", status_code=201)
def create_conversation(request: Request, db: DB, user: Client):
    if not request.app.state.settings.ai_enabled:
        fail(503, "AI_DISABLED")
    obj = new_conversation(db, user)
    return {"conversation_id": obj.id}


@router.post("/conversations/{conversation_id}/messages", status_code=202)
def send_message(
    conversation_id: UUID, data: MessageCreate, request: Request, db: DB, user: Client
):
    if not request.app.state.settings.ai_enabled:
        fail(503, "AI_DISABLED")
    return job_response(enqueue(db, user, conversation_id, data))


@router.get("/conversations/{conversation_id}/messages")
def history(conversation_id: UUID, db: DB, user: Client):
    conversation_for(db, conversation_id, user)
    rows = db.scalars(
        select(ChatJob)
        .where(ChatJob.conversation_id == str(conversation_id))
        .order_by(ChatJob.created_at.desc(), ChatJob.id.desc())
        .limit(100)
    ).all()
    return [job_response(row) for row in reversed(rows)]


@router.get("/requests/{request_id}")
def get_result(request_id: UUID, db: DB, user: Client):
    obj = db.get(ChatJob, str(request_id))
    if not obj:
        fail(404, "AI_REQUEST_NOT_FOUND")
    conversation_for(db, obj.conversation_id, user)
    return job_response(obj)
