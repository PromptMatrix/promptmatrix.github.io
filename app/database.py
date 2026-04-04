from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from app.config import get_settings

settings = get_settings()
_is_sqlite = settings.database_url.startswith("sqlite")
_engine_kwargs = {"connect_args": {"check_same_thread": False}} if _is_sqlite else {
    "pool_size": 2,
    "max_overflow": 5,
    "pool_pre_ping": True,
    "pool_recycle": 300,
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
    Base.metadata.create_all(bind=engine)
