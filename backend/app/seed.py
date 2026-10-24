"""Однократное заполнение локального демонстрационного стенда."""

from datetime import datetime

from sqlalchemy import String, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Mapped, mapped_column

from app.auth.dao import UserDAO
from app.auth.models import Role
from app.auth.schemas import Register
from app.auth.service import AuthService
from app.database import Base, UTCDateTime, now
from app.products.models import Product
from app.products.schemas import ProductCreate
from app.products.service import ProductService
from app.profiles.schemas import ProfileUpdate
from app.profiles.service import ProfileService

SEED_KEY = "demo-data-v1"
DEMO_PASSWORD = "Demo-credit-123!"
DEMO_USERS = (
    ("client@example.com", Role.CLIENT),
    ("officer@example.com", Role.MANAGER),
    ("admin@example.com", Role.ADMIN),
)


class SeedRun(Base):
    __tablename__ = "seed_runs"
    name: Mapped[str] = mapped_column(String(100), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=now)


def seed_demo_data(session) -> bool:
    """Вызывается в транзакции; при ошибке данные и отметка откатываются вместе."""
    insert = pg_insert if session.bind.dialect.name == "postgresql" else sqlite_insert
    # Уникальный ключ сериализует и параллельные запуски до commit/rollback первого.
    claimed = session.scalar(
        insert(SeedRun)
        .values(name=SEED_KEY, created_at=now())
        .on_conflict_do_nothing(index_elements=[SeedRun.name])
        .returning(SeedRun.name)
    )
    if claimed is None:
        return False

    products = []
    for name, purposes, rate, max_amount, max_term in (
        (
            "Демо: развитие бизнеса",
            ["working_capital", "equipment", "expansion", "refinancing"],
            "18",
            "10000000",
            60,
        ),
        ("Демо: оборотный капитал", ["working_capital"], "19.5", "5000000", 36),
        ("Демо: оборудование", ["equipment"], "17", "15000000", 84),
    ):
        product = session.scalar(select(Product).where(Product.name == name).order_by(Product.id))
        if product is None:
            product = ProductService(session).create(
                ProductCreate(
                    name=name,
                    purposes=purposes,
                    min_amount="100000",
                    max_amount=max_amount,
                    min_term_months=6,
                    max_term_months=max_term,
                    annual_rate=rate,
                    min_business_age_months=6,
                    min_annual_revenue="300000",
                    max_debt_burden="0.70",
                    required_documents=["registration", "financial_statements", "bank_statement"],
                )
            )
        products.append(product)

    for email, role in DEMO_USERS:
        # Совпадение email не даёт права менять существующие пароль, роль или профиль.
        if UserDAO(session).by_email(email) is not None:
            continue
        user = AuthService(session).register(Register(email=email, password=DEMO_PASSWORD), role)
        if role == Role.CLIENT:
            ProfileService(session).update(
                user.id,
                ProfileUpdate(
                    company={
                        "name": "ООО «Демо Бизнес»",
                        "inn": "7700000009",
                        "registration_date": "2020-01-01",
                        "address": "Учебный адрес, дом 1",
                        "industry": "62.01",
                    },
                    financials={
                        "annual_revenue": "24000000.00",
                        "monthly_expenses": "500000.00",
                        "monthly_debt_payments": "0.00",
                        "outstanding_debt": "0.00",
                        "credit_history": "good",
                        "overdue_days": 0,
                        "has_collateral": False,
                    },
                ),
            )
    return True
