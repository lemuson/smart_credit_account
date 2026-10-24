from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.applications.models import Application, AuditEvent
from app.auth.models import Role, User
from app.auth.schemas import Register
from app.auth.service import AuthService
from app.config import Settings
from app.database import make_engine
from app.main import create_app
from app.products.models import Product
from app.products.schemas import ProductCreate
from app.products.service import ProductService
from app.profiles.models import Profile
from app.seed import DEMO_PASSWORD, DEMO_USERS, SeedRun, seed_demo_data


@pytest.fixture
def seed_engine(database_url, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", database_url)
    command.upgrade(Config(str(Path(__file__).resolve().parents[1] / "alembic.ini")), "head")
    engine = make_engine(database_url)
    yield engine
    engine.dispose()


def counts(session):
    return tuple(
        session.scalar(select(func.count()).select_from(model))
        for model in (User, Profile, Product, Application, SeedRun)
    )


def test_seed_once_and_login(seed_engine, database_url):
    with Session(seed_engine) as session, session.begin():
        assert seed_demo_data(session)
        assert counts(session) == (3, 1, 3, 1, 1)
        user = session.scalar(select(User).where(User.email == "client@example.com"))
        user.active = False
        product = session.scalar(select(Product).limit(1))
        product.name = "Изменённый продукт"
        product.active = False
        profile = session.scalar(select(Profile))
        profile.company = {**profile.company, "name": "Изменённая компания"}
        session.execute(delete(AuditEvent))
        session.delete(session.scalar(select(Application)))
    with Session(seed_engine) as session, session.begin():
        assert not seed_demo_data(session)
        assert counts(session) == (3, 1, 3, 0, 1)
        assert session.scalar(select(Profile)).company["name"] == "Изменённая компания"
        assert session.scalar(select(Product).where(Product.name == "Изменённый продукт"))
        assert not session.scalar(select(User).where(User.email == "client@example.com")).active
        session.scalar(select(User).where(User.email == "client@example.com")).active = True
    settings = Settings(database_url=database_url, jwt_secret="seed-test-secret-" * 4)
    with TestClient(create_app(settings, seed_engine)) as api:
        for email, role in DEMO_USERS:
            result = api.post(
                "/api/v1/auth/login", json={"email": email, "password": DEMO_PASSWORD}
            )
            assert result.status_code == 200, result.text
            me = api.get(
                "/api/v1/auth/me",
                headers={"Authorization": f"Bearer {result.json()['access_token']}"},
            )
            assert me.status_code == 200
            assert me.json()["role"] == role


def test_seed_rollback_can_retry(seed_engine):
    with pytest.raises(RuntimeError), Session(seed_engine) as session, session.begin():
        assert seed_demo_data(session)
        raise RuntimeError("simulate failed initialization")
    with Session(seed_engine) as session, session.begin():
        assert counts(session) == (0, 0, 0, 0, 0)
        assert seed_demo_data(session)
        assert counts(session) == (3, 1, 3, 1, 1)


def test_seed_preserves_existing_account_and_product(seed_engine):
    with Session(seed_engine) as session, session.begin():
        user = AuthService(session).register(
            Register(email="admin@example.com", password="existing-password-123"), Role.CLIENT
        )
        original = (user.id, user.password_hash, user.role)
        # Имитируем каталог, созданный прежней командой seed-products.
        product = ProductService(session).create(
            ProductCreate(
                name="Демо: развитие бизнеса",
                purposes=["working_capital"],
                min_amount="100000",
                max_amount="1000000",
                min_term_months=12,
                max_term_months=24,
                annual_rate="21",
                min_business_age_months=12,
                min_annual_revenue="500000",
                max_debt_burden="0.5",
                required_documents=["registration"],
                active=False,
            )
        )
        assert seed_demo_data(session)
        assert (user.id, user.password_hash, user.role) == original
        assert not product.active
        assert str(product.annual_rate) == "21"
        assert counts(session) == (3, 2, 3, 1, 1)


def test_concurrent_seed_runs(seed_engine):
    barrier = Barrier(2)

    def run():
        with Session(seed_engine) as session, session.begin():
            barrier.wait(timeout=10)
            return seed_demo_data(session)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: run(), range(2)))
    assert sorted(results) == [False, True]
    with Session(seed_engine) as session:
        assert counts(session) == (3, 1, 3, 1, 1)
