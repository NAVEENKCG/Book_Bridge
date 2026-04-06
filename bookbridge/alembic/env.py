import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool
from dotenv import load_dotenv

# Make sure the project root is on sys.path so models can be imported.
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

load_dotenv()

# This is the Alembic Config object, which provides access to the values
# within the .ini file in use.
config = context.config

# Override sqlalchemy.url from environment if set.
_db_url = os.getenv("DATABASE_URL", "sqlite:///./bookbridge.db")
config.set_main_option("sqlalchemy.url", _db_url)

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Import the metadata so Alembic knows about all models for autogenerate.
from database import Base  # noqa: E402
import models  # noqa: F401, E402 — registers all ORM classes with Base

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
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
    """Run migrations in 'online' mode."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
