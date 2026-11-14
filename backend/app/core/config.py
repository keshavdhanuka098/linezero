"""Application settings (environment / .env driven)."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

BASE_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    app_name: str = "LineZero API"
    app_version: str = "0.2.0"
    database_url: str = "sqlite:///./data/linezero.db"
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    cors_origins: str = "http://localhost:3000,http://localhost:5173"
    debug: bool = False
    auto_migrate: bool = True
    # Optional Gemini integration for Digital Twin explanations. Read from the GEMINI_API_KEY environment variable.
    # Never logged or returned by the API; the twin works fully without it.
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-2.0-flash"
    gemini_timeout_s: float = 20.0

    @property
    def cors_origin_list(self) -> list[str]:
        raw = self.cors_origins.strip()
        if raw.startswith("["):
            return [str(o) for o in json.loads(raw)]
        return [o.strip() for o in raw.split(",") if o.strip()]

    @property
    def resolved_database_url(self) -> str:
        return resolve_database_url(self.database_url)


def resolve_database_url(url: str) -> str:
    """Make relative SQLite file paths absolute (relative to backend/) and create the folder."""
    parsed = make_url(url)
    if parsed.get_backend_name() == "sqlite" and parsed.database and parsed.database != ":memory:":
        path = Path(parsed.database)
        if not path.is_absolute():
            path = BASE_DIR / path
        path.parent.mkdir(parents=True, exist_ok=True)
        parsed = parsed.set(database=str(path))
    return parsed.render_as_string(hide_password=False)


@lru_cache
def get_settings() -> Settings:
    return Settings()
