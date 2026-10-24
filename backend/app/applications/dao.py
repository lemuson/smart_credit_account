from sqlalchemy import select

from app.applications.models import (
    Application,
    AuditEvent,
    CheckRun,
    Clarification,
    Document,
    Status,
)
from app.auth.models import Role


class ApplicationDAO:
    def __init__(self, session):
        self.session = session

    def accessible(self, application_id, user):
        query = select(Application).where(Application.id == str(application_id))
        if user.role == Role.CLIENT:
            query = query.where(Application.client_id == user.id)
        return self.session.scalar(query)

    def list(self, user, status=None, offset=0, limit=50):
        query = select(Application)
        query = query.where(Application.status != Status.DRAFT)
        if user.role == Role.CLIENT:
            query = query.where(Application.client_id == user.id)
        if status:
            query = query.where(Application.status == status)
        return self.session.scalars(
            query.order_by(Application.created_at.desc(), Application.id.desc())
            .offset(offset)
            .limit(limit)
        ).all()

    def drafts(self, user):
        return self.session.scalars(
            select(Application)
            .where(
                Application.client_id == user.id,
                Application.status == Status.DRAFT,
                Application.data_revision > 1,
            )
            .order_by(Application.updated_at.desc(), Application.id.desc())
        ).all()

    def add(self, obj):
        self.session.add(obj)
        self.session.flush()
        return obj

    def documents(self, application_id):
        return self.session.scalars(
            select(Document)
            .where(Document.application_id == application_id)
            .order_by(Document.created_at, Document.id)
        ).all()

    def checks(self, application_id):
        return self.session.scalars(
            select(CheckRun)
            .where(CheckRun.application_id == application_id)
            .order_by(CheckRun.created_at, CheckRun.id)
        ).all()

    def clarifications(self, application_id):
        return self.session.scalars(
            select(Clarification)
            .where(Clarification.application_id == application_id)
            .order_by(Clarification.created_at, Clarification.id)
        ).all()

    def history(self, application_id):
        return self.session.scalars(
            select(AuditEvent)
            .where(AuditEvent.application_id == application_id)
            .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
        ).all()
