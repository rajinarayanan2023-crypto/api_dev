from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from app.core.config import get_settings
from app.core.database import Base

# Importing app.models registers every mapped class on Base.metadata so
# autogenerate can see them.
import app.models  # noqa: F401

config = context.config
settings = get_settings()

# Not routed through config.set_main_option/get_main_option — a password
# containing a literal '%' (from URL-quoting special characters) trips
# configparser's interpolation, so the URL is built and used directly here
# instead of round-tripping through alembic.ini.
DATABASE_URL = settings.sync_database_url

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_engine(DATABASE_URL, poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
