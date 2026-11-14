import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.database import get_db, make_engine, make_session_factory
from app.main import create_app
from app.models import Base


@pytest.fixture
def engine(tmp_path):
    """A brand-new SQLite file per test -> fully isolated, FK enforcement on."""
    eng = make_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def db(engine):
    with make_session_factory(engine)() as session:
        yield session


@pytest.fixture
def client(engine):
    factory = make_session_factory(engine)
    app = create_app()

    def override_get_db():
        with factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def _no_auto_migrate(monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "auto_migrate", False)
