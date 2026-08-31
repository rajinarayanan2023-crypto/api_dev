from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings

settings = get_settings()


class Base(DeclarativeBase):
    pass


# pool_pre_ping guards against stale connections after the Postgres server
# restarts or an idle connection is dropped by a proxy/firewall.
# asyncpg takes SSL as a connect kwarg ("ssl"), not a "sslmode" DSN query
# param like psycopg2/libpq — see Settings.postgres_sslmode.
_connect_args = {}
if settings.postgres_sslmode != "disable":
    _connect_args["ssl"] = settings.postgres_sslmode

engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    connect_args=_connect_args,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
