from datetime import datetime, timezone, timedelta
from uuid import uuid4

from sqlalchemy.orm import Session

from lifepilot.config import settings
from lifepilot.db import engine
from lifepilot.models import User
from lifepilot.security import hash_password


def test_offline_capture_retry_preserves_timestamp_and_owner(client, auth, monkeypatch):
    monkeypatch.setattr(settings, "llm_base_url", "http://model.invalid/v1")
    monkeypatch.setattr(settings, "llm_model", "test")
    monkeypatch.setattr(settings, "redis_url", "redis://unused/0")
    jobs = []
    monkeypatch.setattr("lifepilot.capture_routes.enqueue_capture_job", lambda *args: jobs.append(args))
    owner = client.get("/api/auth/me", headers=auth).json()["id"]
    captured_at = (datetime.now(timezone.utc) - timedelta(days=2)).replace(microsecond=0)
    payload = {"original_text": "Offline notiert: gestern mit Anna gesprochen.", "source": "capture", "client_request_id": str(uuid4()), "captured_at": captured_at.isoformat(), "expected_owner_id": owner}
    first = client.post("/api/captures", headers=auth, json=payload)
    assert first.status_code == 201, first.text
    assert datetime.fromisoformat(first.json()["created_at"]).replace(tzinfo=timezone.utc) == captured_at
    repeat = client.post("/api/captures", headers=auth, json=payload)
    assert repeat.status_code == 201 and repeat.json()["id"] == first.json()["id"]
    assert len(jobs) == 1
    assert client.post("/api/captures", headers=auth, json={**payload, "original_text": "Anderer Inhalt"}).status_code == 409
    assert client.post("/api/captures", headers=auth, json={**payload, "client_request_id": "ungueltig"}).status_code == 422
    assert client.post("/api/captures", headers=auth, json={**payload, "captured_at": "2025-01-01T12:00:00"}).status_code == 422
    assert client.post("/api/captures", headers=auth, json={**payload, "captured_at": "2099-01-01T12:00:00Z"}).status_code == 422

    username = "offline-other-" + uuid4().hex
    with Session(engine) as db:
        db.add(User(username=username, password_hash=hash_password("test-password")))
        db.commit()
    token = client.post("/api/auth/login", json={"username": username, "password": "test-password"}).json()["access_token"]
    other = {"Authorization": "Bearer " + token}
    assert client.post("/api/captures", headers=other, json=payload).status_code == 409
    assert client.get("/api/captures", headers=other).json() == []
    second_owner = client.get("/api/auth/me", headers=other).json()["id"]
    separate = client.post("/api/captures", headers=other, json={**payload, "expected_owner_id": second_owner})
    assert separate.status_code == 201 and separate.json()["id"] != first.json()["id"]
    assert len(jobs) == 2
