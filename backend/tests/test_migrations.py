from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from app.database import make_engine


def test_migration_upgrade_check_downgrade_and_reupgrade(database_url, monkeypatch):
    url = database_url
    monkeypatch.setenv("DATABASE_URL", url)
    cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    command.upgrade(cfg, "head")
    command.check(cfg)
    engine = make_engine(url)
    assert {
        "users",
        "profiles",
        "credit_products",
        "applications",
        "loans",
        "documents",
        "check_runs",
        "clarifications",
        "audit_events",
    } <= set(inspect(engine).get_table_names())
    command.downgrade(cfg, "base")
    assert set(inspect(engine).get_table_names()) == {"alembic_version"}
    command.upgrade(cfg, "head")
    command.check(cfg)
    engine.dispose()
