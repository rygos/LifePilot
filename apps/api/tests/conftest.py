import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

db_path = Path("/tmp/lifepilot-test.db")
db_path.unlink(missing_ok=True)
os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
os.environ["SECRET_KEY"] = "test-secret-key-with-adequate-length"
os.environ["LIFE_PILOT_BOOTSTRAP_USERNAME"] = "testuser"
os.environ["LIFE_PILOT_BOOTSTRAP_PASSWORD"] = "test-password"
os.environ["LOGIN_PEER_PER_MINUTE"] = "1000"
os.environ["LOGIN_GLOBAL_PER_MINUTE"] = "2000"

from lifepilot.db import Base, engine
from lifepilot.main import app
from lifepilot.models import User
from lifepilot.security import hash_password


@pytest.fixture(scope="session")
def client() -> TestClient:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with Session(engine) as db:
        db.add(User(username="testuser", password_hash=hash_password("test-password")))
        db.commit()
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


@pytest.fixture()
def auth(client: TestClient) -> dict[str, str]:
    response = client.post("/api/auth/login", json={"username": "testuser", "password": "test-password"})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def pytest_addoption(parser):
    parser.addoption("--postgres-integration", action="store_true", default=False,
                     help="Run disposable local PostgreSQL integration tests using the installed pgvector image")
