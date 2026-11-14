"""Programmatic Alembic helpers (used by startup, init_db and the data generator)."""
from __future__ import annotations

from alembic import command
from alembic.config import Config

from app.core.config import BASE_DIR, get_settings


def alembic_config(database_url: str | None = None) -> Config:
    cfg = Config(str(BASE_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BASE_DIR / "alembic"))
    url = database_url or get_settings().resolved_database_url
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return cfg


def run_migrations(database_url: str | None = None) -> None:
    """Upgrade the database to the latest revision (idempotent)."""
    command.upgrade(alembic_config(database_url), "head")
