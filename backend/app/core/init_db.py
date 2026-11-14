"""Initialise the database:  python -m app.core.init_db"""
from app.core.config import get_settings
from app.core.migrations import run_migrations


def main() -> None:
    url = get_settings().resolved_database_url
    run_migrations(url)
    print(f"Database ready: {url}")


if __name__ == "__main__":
    main()
