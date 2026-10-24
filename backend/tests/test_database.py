from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError
from sqlalchemy import Numeric, inspect
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.auth.models import User
from app.config import DatabaseSettings
from app.products.models import Product


def test_postgres_password_special_characters_are_preserved():
    password = "synthetic@password:/with%characters?#"
    settings = DatabaseSettings(
        _env_file=None,
        database_url="",
        postgres_user="credit",
        postgres_password=password,
        postgres_host="db",
        postgres_db="credit",
    )
    url = make_url(settings.database_url)
    assert url.drivername == "postgresql+psycopg"
    assert url.password == password and url.host == "db"


def test_database_credentials_are_required():
    with pytest.raises(ValidationError, match="DATABASE_URL or POSTGRES_PASSWORD is required"):
        DatabaseSettings(_env_file=None, database_url="", postgres_password=None)


@pytest.mark.parametrize("offset", [3, -5])
def test_timezone_and_decimal_round_trip(env, offset):
    _, _, product_id, users, engine = env
    instant = datetime(2026, 10, 24, 18, 15, tzinfo=timezone(timedelta(hours=offset)))
    with Session(engine) as session, session.begin():
        session.get(User, users["client"]).created_at = instant
        session.get(Product, product_id).max_amount = Decimal("99999999999999.99")
    with Session(engine) as session:
        user = session.get(User, users["client"])
        assert user.created_at == instant.astimezone(UTC)
        assert user.created_at.utcoffset() == timedelta(0)
        assert session.get(Product, product_id).max_amount == Decimal("99999999999999.99")
    if engine.dialect.name == "postgresql":
        columns = {
            column["name"]: column["type"]
            for column in inspect(engine).get_columns("credit_products")
        }
        assert isinstance(columns["max_amount"], Numeric)
        assert columns["max_amount"].scale == 2
        assert columns["created_at"].timezone
