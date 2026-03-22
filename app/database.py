"""
Database
=========
SQLAlchemy setup. Works with SQLite (dev) and Supabase PostgreSQL (production).

Supabase: use the TRANSACTION POOLER URL (port 6543), not direct (port 5432).
Transaction mode is stateless — compatible with Vercel serverless.

Connection string:
  postgresql://postgres.[ref]:[password]@aws-0-[region].pooler.supabase.com:6543/postgres
"""

from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from app.config import get_settings

settings = get_settings()

_is_sqlite = settings.database_url.startswith("sqlite")

# Pool args only apply to PostgreSQL — SQLite uses a single file, pooling is irrelevant
_engine_kwargs = {"connect_args": {"check_same_thread": False}} if _is_sqlite else {
    "pool_size": 2,       # small pool: Supabase handles pooling on its side
    "max_overflow": 5,
    "pool_pre_ping": True,   # drop stale connections (important after Supabase free-tier pause)
    "pool_recycle": 300,     # recycle every 5 min
}

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
    """Create all tables. Called on app startup. Safe to call multiple times."""
    from app import models  # noqa — import triggers model registration
    Base.metadata.create_all(bind=engine)
