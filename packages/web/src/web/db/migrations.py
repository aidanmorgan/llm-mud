"""Database migration utilities for LLM-MUD Web."""

import os
from pathlib import Path

from alembic import command
from alembic.config import Config


def get_alembic_config() -> Config:
    """Get Alembic configuration."""
    # Find the alembic.ini file
    package_dir = Path(__file__).parent.parent.parent.parent
    alembic_ini = package_dir / "alembic.ini"

    if not alembic_ini.exists():
        raise FileNotFoundError(
            f"alembic.ini not found at {alembic_ini}. "
            "Make sure you're running from the correct directory."
        )

    config = Config(str(alembic_ini))

    # Allow DATABASE_URL environment variable to override
    db_url = os.getenv("DATABASE_URL")
    if db_url:
        config.set_main_option("sqlalchemy.url", db_url)

    return config


def run_migrations(target: str = "head") -> None:
    """
    Run database migrations up to the specified target.

    Args:
        target: Migration target (default: "head" for latest)
    """
    config = get_alembic_config()
    command.upgrade(config, target)


def downgrade_migrations(target: str = "-1") -> None:
    """
    Downgrade database migrations.

    Args:
        target: Migration target (default: "-1" for one step back)
    """
    config = get_alembic_config()
    command.downgrade(config, target)


def get_current_revision() -> str:
    """Get the current migration revision."""
    from alembic.runtime.migration import MigrationContext
    from sqlalchemy import create_engine

    config = get_alembic_config()
    url = config.get_main_option("sqlalchemy.url")

    engine = create_engine(url)
    with engine.connect() as connection:
        context = MigrationContext.configure(connection)
        return context.get_current_revision()


def stamp_database(revision: str = "head") -> None:
    """
    Stamp the database with a specific revision without running migrations.

    Useful for marking an existing database as being at a specific version.

    Args:
        revision: Revision to stamp (default: "head")
    """
    config = get_alembic_config()
    command.stamp(config, revision)


def create_migration(message: str, autogenerate: bool = False) -> str:
    """
    Create a new migration file.

    Args:
        message: Migration description
        autogenerate: Whether to auto-generate from model changes

    Returns:
        Path to the created migration file
    """
    config = get_alembic_config()

    if autogenerate:
        return command.revision(config, message=message, autogenerate=True)
    else:
        return command.revision(config, message=message)


def check_migrations_needed() -> bool:
    """
    Check if there are pending migrations.

    Returns:
        True if migrations are needed, False if database is up to date
    """
    from alembic.runtime.migration import MigrationContext
    from alembic.script import ScriptDirectory
    from sqlalchemy import create_engine

    config = get_alembic_config()
    url = config.get_main_option("sqlalchemy.url")

    engine = create_engine(url)
    with engine.connect() as connection:
        context = MigrationContext.configure(connection)
        current_rev = context.get_current_revision()

    script = ScriptDirectory.from_config(config)
    head_rev = script.get_current_head()

    return current_rev != head_rev
