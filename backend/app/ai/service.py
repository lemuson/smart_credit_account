from datetime import timedelta

import jwt
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.ai.contracts import ChatRequest, ChatResult, HistoryMessage, TrustedContext
from app.ai.models import ChatJob, Conversation
from app.applications.service import ApplicationService
from app.common import fail
from app.database import now
from app.profiles.service import ProfileService


def conversation_for(db, conversation_id, user):
    obj = db.get(Conversation, str(conversation_id))
    if not obj or obj.user_id != user.id:
        fail(404, "CONVERSATION_NOT_FOUND")
    return obj


def enqueue(db, user, conversation_id, data):
    conversation_for(db, conversation_id, user)
    existing = db.get(ChatJob, str(data.request_id))
    if existing:
        if (
            existing.conversation_id != str(conversation_id)
            or existing.message != data.message
            or existing.application_id
            != (str(data.application_id) if data.application_id else None)
        ):
            fail(409, "IDEMPOTENCY_KEY_REUSED")
        return existing
    if db.scalar(
        select(ChatJob.id).where(
            ChatJob.conversation_id == str(conversation_id),
            ChatJob.status.in_(["pending", "published"]),
        )
    ):
        fail(409, "CONVERSATION_BUSY")
    recent = db.scalar(
        select(func.count())
        .select_from(ChatJob)
        .join(Conversation)
        .where(
            Conversation.user_id == user.id,
            ChatJob.created_at > now() - timedelta(minutes=1),
        )
    )
    if recent >= 10:
        fail(429, "AI_RATE_LIMITED")
    if data.application_id:
        ApplicationService(db).get(data.application_id, user)
    obj = ChatJob(
        id=str(data.request_id),
        conversation_id=str(conversation_id),
        message=data.message,
        application_id=str(data.application_id) if data.application_id else None,
    )
    db.add(obj)
    db.flush()
    return obj


def build_request(db, job, settings):
    conversation = db.get(Conversation, job.conversation_id)
    history = []
    rows = db.scalars(
        select(ChatJob)
        .where(
            ChatJob.conversation_id == job.conversation_id,
            ChatJob.status.in_(["completed", "needs_clarification", "failed"]),
            ChatJob.id != job.id,
        )
        .order_by(ChatJob.created_at.desc(), ChatJob.id.desc())
        .limit(6)
    ).all()
    for previous in reversed(rows):
        history.append(HistoryMessage(role="user", content=previous.message))
        if previous.result["answer"].strip():
            history.append(
                HistoryMessage(role="assistant", content=previous.result["answer"][:8000])
            )
    issued = now()
    token = jwt.encode(
        {
            "sub": conversation.user_id,
            "organization_id": conversation.organization_id,
            "request_id": job.id,
            "iat": issued,
            "exp": issued + timedelta(minutes=10),
            "iss": "smart-credit",
            "aud": "smart-credit-ai-tools",
        },
        settings.jwt_secret.get_secret_value(),
        algorithm="HS256",
    )
    return ChatRequest(
        request_id=job.id,
        conversation_id=job.conversation_id,
        user_id=conversation.user_id,
        organization_id=conversation.organization_id,
        message=job.message,
        history=history,
        application_id=job.application_id,
        trusted_context=TrustedContext(
            subject=conversation.user_id, authorization=f"Bearer {token}"
        ),
        created_at=job.created_at,
    )


def accept_result(engine, body):
    result = ChatResult.model_validate_json(body)
    with Session(engine) as db, db.begin():
        job = db.scalar(
            select(ChatJob).where(ChatJob.id == str(result.request_id)).with_for_update()
        )
        if not job or job.conversation_id != str(result.conversation_id):
            return False
        if job.result is not None:
            return True
        db.execute(
            update(ChatJob)
            .where(
                ChatJob.id == job.id,
                ChatJob.status.in_(["pending", "published"]),
            )
            .values(result=result.model_dump(mode="json"), status=result.status)
        )
    return True


def new_conversation(db, user):
    profile = ProfileService(db).get(user.id)
    obj = Conversation(user_id=user.id, organization_id=profile.id)
    db.add(obj)
    db.flush()
    return obj
