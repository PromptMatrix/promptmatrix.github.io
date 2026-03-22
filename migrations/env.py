"""
Alembic env.py
==============
Reads DATABASE_URL from the app config — no hardcoded credentials.

Usage:
  # Auto-generate a migration after changing models.py:
  alembic revision --autogenerate -m "describe what changed"

  # Apply all pending migrations:
  alembic upgrade head

  # Roll back one step:
  alembic downgrade -1

  # Check current state:
  alembic current
"""

from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context
import os
import sys

# Make the app importable from the migrations directory
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import get_settings
from app.database import Base
import app.models  # noqa — registers all models with Base.metadata

config = context.config
settings = get_settings()

# Override the sqlalchemy.url from alembic.ini with the live config value
config.set_main_option("sqlalchemy.url", settings.database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations without a live DB connection (generates SQL script)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against the live database."""
    # For Supabase transaction pooler, NullPool prevents connection reuse
    # issues in the migration context (which is not a web request)
    use_null_pool = "pooler.supabase.com" in settings.database_url

    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool if use_null_pool else pool.StaticPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
