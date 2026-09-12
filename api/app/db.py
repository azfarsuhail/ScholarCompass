from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from .config import settings


class Base(DeclarativeBase):
    pass


# Neon specifics:
#  * pool stays small -- 512MB container and Neon caps connections.
#  * statement_cache_size=0 is REQUIRED on Neon's *pooled* endpoint. It runs
#    PgBouncer in transaction mode, where asyncpg's prepared statements leak
#    across pooled backends and fail with DuplicatePreparedStatementError.
#  * pool_recycle beats Neon's idle-connection timeout on scale-to-zero.
engine = create_async_engine(
    settings().database_url,
    pool_size=5,
    max_overflow=5,
    pool_pre_ping=True,
    pool_recycle=280,
    connect_args={"statement_cache_size": 0, "prepared_statement_cache_size": 0},
)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as s:
        yield s
