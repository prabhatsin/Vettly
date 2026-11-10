import os
from fastapi.testclient import TestClient

from app.db.session import get_db
from app.main import app as fastapi_app
import pytest
from dotenv import dotenv_values
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import ENV_FILE
from app.db.base import Base
import app.models  # noqa: F401
from app.routers.applications import get_plan_prewarm
from app.routers.employer import get_scoring_enqueue


TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL") or dotenv_values(ENV_FILE)["TEST_DATABASE_URL"]


@pytest.fixture(scope="session")
def engine():
    engine = create_engine(TEST_DATABASE_URL)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture()
def db(engine):
    connection = engine.connect()
    transaction = connection.begin()
    session = sessionmaker(bind=connection, autoflush=False, expire_on_commit=False)()
    yield session
    session.close()
    transaction.rollback()
    connection.close()



@pytest.fixture()
def client(db):
    def override_get_db():
        yield db

    fastapi_app.dependency_overrides[get_db] = override_get_db
    fastapi_app.dependency_overrides[get_plan_prewarm] = lambda: (lambda application_id: None)
    fastapi_app.dependency_overrides[get_scoring_enqueue] = lambda: (lambda application_id: None)
    yield TestClient(fastapi_app)
    fastapi_app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def temp_upload_dir(tmp_path, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "upload_dir", str(tmp_path))
    return tmp_path