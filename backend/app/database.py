from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import BigInteger, DateTime, MetaData, Numeric, create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, Session
from sqlalchemy.types import TypeDecorator


class FixedDecimal(TypeDecorator):
    """NUMERIC в PostgreSQL; целые единицы в локальных SQLite-тестах."""

    impl = BigInteger
    cache_ok = True

    def __init__(self, scale=2):
        self.scale = scale
        super().__init__()

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(Numeric(18, self.scale))
        return dialect.type_descriptor(BigInteger())

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        value = Decimal(value)
        scaled = value * (10**self.scale)
        if not value.is_finite() or scaled != scaled.to_integral_value():
            raise ValueError("invalid fixed decimal precision")
        result = int(scaled)
        if not -(2**63) <= result < 2**63:
            raise ValueError("fixed decimal outside storage range")
        return value if dialect.name == "postgresql" else result

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        decimal = (
            Decimal(value) if dialect.name == "postgresql" else Decimal(value) / (10**self.scale)
        )
        return decimal.quantize(Decimal(1).scaleb(-self.scale))


class UTCDateTime(TypeDecorator):
    impl = DateTime
    cache_ok = True

    def load_dialect_impl(self, dialect):
        return dialect.type_descriptor(DateTime(timezone=dialect.name == "postgresql"))

    def process_bind_param(self, value, dialect):
        if value is not None:
            if value.tzinfo is None:
                raise ValueError("timezone required")
            value = value.astimezone(UTC)
            return value if dialect.name == "postgresql" else value.replace(tzinfo=None)
        return value

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)


class Base(DeclarativeBase):
    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(column_0_label)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )


def now() -> datetime:
    return datetime.now(UTC)


def new_id() -> str:
    return str(uuid4())


def make_engine(url: str):
    parsed = make_url(url)
    if parsed.drivername in {"postgres", "postgresql"}:
        parsed = parsed.set(drivername="postgresql+psycopg")
    kwargs = (
        {"connect_args": {"check_same_thread": False, "timeout": 30}}
        if url.startswith("sqlite")
        else {}
    )
    engine = create_engine(parsed, pool_pre_ping=True, **kwargs)
    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def configure_sqlite(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")

    return engine


def get_session(request):
    with Session(request.app.state.engine, expire_on_commit=False) as session:
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
