"""Изолированные тестовые БД; существующие схемы PostgreSQL не изменяются."""

import os
import tempfile
from contextlib import contextmanager
from uuid import uuid4

from sqlalchemy.engine import make_url
from sqlalchemy.schema import CreateSchema, DropSchema

from app.config import DatabaseSettings
from app.database import make_engine


@contextmanager
def temporary_database():
    base_url = os.environ.get("TEST_DATABASE_URL")
    if not base_url and os.environ.get("TEST_POSTGRES") == "1":
        base_url = DatabaseSettings().database_url
    if not base_url:
        with tempfile.TemporaryDirectory(prefix="credit-test-") as directory:
            yield f"sqlite:///{directory}/test.db"
        return
    url = make_url(base_url)
    if url.get_backend_name() not in {"postgres", "postgresql"}:
        raise ValueError("TEST_DATABASE_URL must reference PostgreSQL")
    schema = "credit_test_" + uuid4().hex
    engine = make_engine(base_url)
    with engine.begin() as connection:
        connection.execute(CreateSchema(schema))
    try:
        options = f"{url.query.get('options', '')} -csearch_path={schema}".strip()
        yield url.update_query_dict({"options": options}).render_as_string(hide_password=False)
    finally:
        with engine.begin() as connection:
            connection.execute(DropSchema(schema, cascade=True))
        engine.dispose()
