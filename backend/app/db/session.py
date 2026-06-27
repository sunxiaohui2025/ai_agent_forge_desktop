from __future__ import annotations
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import event, BigInteger
from sqlalchemy.ext.compiler import compiles
from ..core.config import settings


# SQLite only auto-increments an `INTEGER PRIMARY KEY`; a BIGINT PK will NOT
# autoincrement. Several tables (Message/AuditLog/CallLog/TaskRun/...) use
# BigInteger PKs, so render BigInteger as INTEGER on SQLite to preserve
# autoincrement behavior. Harmless: SQLite INTEGER is a 64-bit signed int.
@compiles(BigInteger, "sqlite")
def _compile_bigint_sqlite(element, compiler, **kw):  # noqa: ANN001
    return "INTEGER"


class Base(DeclarativeBase):
    pass


_is_sqlite = settings.DATABASE_URL.startswith("sqlite")

if _is_sqlite:
    # SQLite (desktop mode): allow cross-thread use; pool_pre_ping is a no-op.
    engine = create_async_engine(
        settings.DATABASE_URL,
        echo=False,
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, _record):  # noqa: ANN001
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")   # concurrent read/write
        cur.execute("PRAGMA foreign_keys=ON")    # enforce FK cascades
        cur.execute("PRAGMA busy_timeout=5000")  # wait on locks
        cur.close()
else:
    # Postgres (legacy server mode).
    engine = create_async_engine(settings.DATABASE_URL, echo=False, pool_pre_ping=True)

SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session
