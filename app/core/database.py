from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings
from app.core.s3 import delete_object

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


def queue_file_deletion(session: AsyncSession, key: str) -> None:
    """Defers an irreversible storage delete (e.g. a replaced/removed bill
    photo) until this request's transaction has actually committed — see
    get_db's own comment for why deleting any earlier is unsafe. Callers
    that build several keys over the course of a request can call this once
    per key as they go; nothing happens with them until commit succeeds.
    """
    session.info.setdefault("pending_file_deletions", []).append(key)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
            # Anything queued via queue_file_deletion (session.info is a
            # plain per-session dict SQLAlchemy already provides for this)
            # only runs now, with the commit actually confirmed — deleting a
            # storage object is irreversible and can't be rolled back the
            # way the transaction above it can. Running this any earlier
            # (e.g. right after a flush(), which only sends pending SQL
            # without committing it) risked the commit failing afterward:
            # the DB change rolls back while the file stays deleted, leaving
            # a row that points at nothing.
            for key in session.info.get("pending_file_deletions", ()):
                delete_object(key)
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
