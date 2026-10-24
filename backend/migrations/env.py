from alembic import context

from app import models  # noqa: F401
from app.config import DatabaseSettings
from app.database import Base, make_engine

config = context.config
url = DatabaseSettings().database_url
target_metadata = Base.metadata

if context.is_offline_mode():
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = make_engine(url)
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            render_as_batch=url.startswith("sqlite"),
        )
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()
