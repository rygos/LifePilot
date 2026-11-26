from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from lifepilot.db import engine
from lifepilot.models import User
from lifepilot.security import hash_password


def test_password_change_requires_current_password_and_replaces_credentials(client: TestClient) -> None:
    username = f"password-change-{uuid4().hex}"
    initial_password = "initial-secure-password-123"
    updated_password = "updated-secure-password-456"

    with Session(engine) as db:
        db.add(User(username=username, password_hash=hash_password(initial_password)))
        db.commit()

    login = client.post("/api/auth/login", json={"username": username, "password": initial_password})
    assert login.status_code == 200
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    payload = {"current_password": initial_password, "new_password": updated_password}

    assert client.post("/api/auth/password", json=payload).status_code == 401
    assert client.post(
        "/api/auth/password",
        headers=headers,
        json={"current_password": initial_password, "new_password": initial_password},
    ).status_code == 422
    rejected = client.post(
        "/api/auth/password",
        headers=headers,
        json={"current_password": "incorrect-password", "new_password": updated_password},
    )
    assert rejected.status_code == 400
    assert client.post("/api/auth/login", json={"username": username, "password": initial_password}).status_code == 200

    changed = client.post("/api/auth/password", headers=headers, json=payload)
    assert changed.status_code == 200
    assert changed.json() == {"status": "password_changed"}
    assert client.get("/api/profile", headers=headers).status_code == 401
    assert client.post("/api/auth/login", json={"username": username, "password": initial_password}).status_code == 401
    new_login = client.post("/api/auth/login", json={"username": username, "password": updated_password})
    assert new_login.status_code == 200
    headers = {"Authorization": f"Bearer {new_login.json()['access_token']}"}
    assert client.post(
        "/api/auth/password",
        headers=headers,
        json={"current_password": updated_password, "new_password": "short"},
    ).status_code == 422
