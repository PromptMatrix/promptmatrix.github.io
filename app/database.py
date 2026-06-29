from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import get_settings

# SCALE-TODO: This module uses synchronous SQLAlchemy (create_engine / SessionLocal).
# Under concurrent load on a real Postgres backend, every DB call blocks a
# thread in uvicorn's default threadpool (40 threads).  At ~200+ concurrent
# prompt-serve requests the pool exhausts and latency spikes.
#
# Migration path (non-breaking, can be done per-router):
#   1. pip install sqlalchemy[asyncio] asyncpg
#   2. Replace create_engine() with create_async_engine()
#   3. Replace sessionmaker() with async_sessionmaker()
#   4. Change `def get_db()` to `async def get_db()` with AsyncSession
#   5. Prefix all db.query()/.first()/.all() calls with `await`
#      (or use select() + scalars() idiom)
#
# The serve hot-path in app/serve/router.py is the highest-priority target
# because it is called on every LLM request.  The management API (evals,
# prompts, auth) can be migrated incrementally afterward.

settings = get_settings()
_is_sqlite = settings.database_url.startswith("sqlite")
_engine_kwargs = (
    {"connect_args": {"check_same_thread": False}}
    if _is_sqlite
    else {
        "pool_size": 2,
        "max_overflow": 5,
        "pool_pre_ping": True,
        "pool_recycle": 300,
    }
)

engine = create_engine(settings.database_url, **_engine_kwargs)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_tables():
    Base.metadata.create_all(bind=engine)
