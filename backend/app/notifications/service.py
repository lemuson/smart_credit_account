from sqlalchemy import exists, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.applications.models import Application, AuditEvent
from app.auth.models import Role
from app.common import fail
from app.notifications.models import NotificationRead

CLIENT_TITLES = {
    "APPLICATION_SUBMITTED": "Заявка принята",
    "ASSIGNED_TO_OFFICER": "Заявка взята в работу",
    "CLARIFICATION_REQUESTED": "Нужно уточнить сведения",
    "CLARIFICATION_REPLIED": "Ответ сотруднику отправлен",
    "PRIMARY_REVIEW_REJECTED": "Получено решение по заявке",
    "AUTOMATIC_DECISION": "Получено решение по заявке",
    "OFFER_DECLINED": "Предложение отклонено",
    "CONTRACT_GENERATED": "Договор готов к подписанию",
    "DEMO_CONTRACT_SIGNED": "Кредит оформлен",
}
OFFICER_TITLES = {
    "APPLICATION_SUBMITTED": "Новая заявка на рассмотрение",
    "CLARIFICATION_REPLIED": "Клиент ответил на уточнение",
    "DEMO_CONTRACT_SIGNED": "Клиент подписал договор",
}


class NotificationService:
    def __init__(self, db, user):
        self.db, self.user = db, user
        if user.role not in {Role.CLIENT, Role.MANAGER}:
            fail(403, "FORBIDDEN")
        self.titles = CLIENT_TITLES if user.role == Role.CLIENT else OFFICER_TITLES

    def events(self):
        query = select(AuditEvent).join(Application).where(AuditEvent.action.in_(self.titles))
        if self.user.role == Role.CLIENT:
            return query.where(Application.client_id == self.user.id)
        return query.where(
            or_(
                Application.assigned_manager_id.is_(None),
                Application.assigned_manager_id == self.user.id,
            )
        )

    def read_exists(self):
        return exists().where(
            NotificationRead.user_id == self.user.id, NotificationRead.event_id == AuditEvent.id
        )

    def list(self, offset=0, limit=50):
        query = self.events()
        unread = self.db.scalar(
            select(func.count()).select_from(query.where(~self.read_exists()).subquery())
        )
        rows = self.db.scalars(
            query.order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
            .offset(offset)
            .limit(limit)
        ).all()
        read_ids = set(
            self.db.scalars(
                select(NotificationRead.event_id).where(
                    NotificationRead.user_id == self.user.id,
                    NotificationRead.event_id.in_([event.id for event in rows]),
                )
            )
        )
        return {
            "unread_count": unread,
            "items": [
                {
                    "id": event.id,
                    "application_id": event.application_id,
                    "title": self.titles[event.action],
                    "status": event.to_status,
                    "created_at": event.created_at,
                    "read": event.id in read_ids,
                }
                for event in rows
            ],
        }

    def mark_read(self, ids, all_items=False):
        query = self.events().where(~self.read_exists())
        if not all_items:
            query = query.where(AuditEvent.id.in_([str(item) for item in ids]))
        rows = self.db.scalars(query).all()
        insert = pg_insert if self.db.bind.dialect.name == "postgresql" else sqlite_insert
        # Повторные и параллельные отметки не создают дубликаты.
        for event in rows:
            self.db.execute(
                insert(NotificationRead)
                .values(
                    user_id=self.user.id,
                    event_id=event.id,
                )
                .on_conflict_do_nothing(index_elements=["user_id", "event_id"])
            )
        self.db.flush()
        return self.list()
