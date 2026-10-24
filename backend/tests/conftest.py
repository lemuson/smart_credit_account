from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.auth.models import Role
from app.auth.schemas import Register
from app.auth.service import AuthService
from app.config import Settings
from app.database import make_engine
from app.main import create_app
from app.products.schemas import ProductCreate
from app.products.service import ProductService
from examples.test_database import temporary_database

PASSWORD = "test-password-123"


def test_inn(group="good"):
    for n in range(770000000, 770010000):
        digits = str(n)
        check = (
            sum(
                int(x) * weight
                for x, weight in zip(digits, [2, 4, 10, 3, 5, 9, 4, 6, 8], strict=True)
            )
            % 11
            % 10
        )
        inn = digits + str(check)
        suffix = int(inn[-2:])
        if (
            (group == "good" and 1 <= suffix < 80)
            or (group == "warning" and 80 <= suffix < 90)
            or (group == "bad" and suffix >= 90)
        ):
            return inn
    raise AssertionError("no fixture INN")


def company(group="good"):
    return {
        "name": "Учебное ООО",
        "inn": test_inn(group),
        "registration_date": "2020-01-01",
        "address": "Демонстрационный адрес",
        "industry": "62.01",
    }


def financials(**overrides):
    return {
        "annual_revenue": "24000000.00",
        "monthly_expenses": "500000.00",
        "monthly_debt_payments": "0.00",
        "outstanding_debt": "0.00",
        "credit_history": "good",
        "overdue_days": 0,
        "has_collateral": False,
        **overrides,
    }


@pytest.fixture
def database_url():
    with temporary_database() as url:
        yield url


@pytest.fixture
def env(database_url, monkeypatch):
    url = database_url
    monkeypatch.setenv("DATABASE_URL", url)
    cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    command.upgrade(cfg, "head")
    engine = make_engine(url)
    with Session(engine) as session, session.begin():
        users = {}
        for name, role in [
            ("client", Role.CLIENT),
            ("other", Role.CLIENT),
            ("officer", Role.MANAGER),
            ("officer2", Role.MANAGER),
            ("admin", Role.ADMIN),
        ]:
            users[name] = (
                AuthService(session)
                .register(Register(email=f"{name}@example.com", password=PASSWORD), role)
                .id
            )
        product_id = (
            ProductService(session)
            .create(
                ProductCreate(
                    name="Демонстрационный кредит",
                    purposes=["working_capital", "equipment"],
                    min_amount="100000",
                    max_amount="10000000",
                    min_term_months=6,
                    max_term_months=60,
                    annual_rate="18",
                    min_business_age_months=6,
                    min_annual_revenue="300000",
                    max_debt_burden="0.70",
                    required_documents=["registration", "financial_statements"],
                )
            )
            .id
        )
    settings = Settings(database_url=url, jwt_secret="test-secret-" * 4, max_document_bytes=1024)
    with TestClient(create_app(settings, engine)) as api:
        headers = {}
        for name in users:
            response = api.post(
                "/api/v1/auth/login", json={"email": f"{name}@example.com", "password": PASSWORD}
            )
            assert response.status_code == 200, response.text
            headers[name] = {"Authorization": f"Bearer {response.json()['access_token']}"}
        yield api, headers, product_id, users, engine
    engine.dispose()


class Flow:
    def __init__(self, env):
        self.api, self.headers, self.product_id, self.users, self.engine = env
        self.id = None

    @property
    def base(self):
        return f"/api/v1/client/applications/{self.id}"

    def get(self, who="client"):
        path = self.base if who == "client" else f"/api/v1/bank/applications/{self.id}/dossier"
        response = self.api.get(path, headers=self.headers[who])
        assert response.status_code == 200, response.text
        return response.json()

    def version(self):
        return self.get()["version"]

    def action(self, action, who="client", **data):
        prefix = "/api/v1/client/applications" if who == "client" else "/api/v1/bank/applications"
        return self.api.post(
            f"{prefix}/{self.id}/{action}",
            headers=self.headers[who],
            json={"expected_version": self.version(), **data},
        )

    def create(self, group="good", finance=None):
        response = self.api.post(
            "/api/v1/auth/company",
            headers=self.headers["client"],
            json={"company": company(group), "financials": finance or financials()},
        )
        assert response.status_code == 200, response.text
        response = self.api.post(
            "/api/v1/client/applications",
            headers=self.headers["client"],
            json={
                "product_id": self.product_id,
                "purpose": "working_capital",
                "amount": "1000000",
                "term_months": 24,
            },
        )
        assert response.status_code == 201, response.text
        self.id = response.json()["id"]
        return response.json()

    def upload(self, kind="registration"):
        response = self.api.post(
            self.base + "/documents",
            headers=self.headers["client"],
            data={"kind": kind, "expected_version": self.version()},
            files={"file": ("sample.pdf", b"%PDF-1.7\nsynthetic fixture", "application/pdf")},
        )
        assert response.status_code == 201, response.text
        return response.json()

    def submit_and_take(self):
        self.upload()
        self.upload("financial_statements")
        response = self.action("submit", confirmed=True)
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "SUBMITTED"
        response = self.action("take-to-work", "officer")
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "PRIMARY_REVIEW"

    def approve(self):
        self.submit_and_take()
        response = self.action("run-external-checks", "officer")
        assert response.status_code == 200, response.text
        response = self.action(
            "pass-to-auto-analysis", "officer", comment="Комплектность проверена"
        )
        assert response.status_code == 200, response.text
        return response.json()


@pytest.fixture
def flow(env):
    return Flow(env)
