from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from lifepilot.config import settings
from lifepilot.db import engine
from lifepilot.models import CaptureKey, User
from lifepilot.security import hash_password
from lifepilot import shortcut_routes


def issue(client, auth, password="test-password", label="iPhone"):
    response = client.post("/api/shortcuts/keys", headers=auth, json={"label": label, "current_password": password, "expires_in_days": 30})
    assert response.status_code == 201, response.text
    assert response.headers["cache-control"] == "no-store"
    return response.json()


def test_shortcut_is_write_only_and_revocable(client, auth, monkeypatch):
    monkeypatch.setattr(settings, "llm_base_url", "")
    assert client.post("/api/shortcuts/keys", headers=auth, json={"label": "iPhone", "current_password": "wrong"}).status_code == 403
    key = issue(client, auth)
    token = key["token"]
    scoped = {"Authorization": "Bearer " + token}
    assert token.startswith("lp_capture_")
    with Session(engine) as db:
        row = db.get(CaptureKey, key["id"])
        assert row.secret_hash == shortcut_routes.digest(token) and token not in row.secret_hash
    listed = client.get("/api/shortcuts/keys", headers=auth)
    assert token not in listed.text and "secret_hash" not in listed.text
    assert client.get("/api/shortcuts/keys", headers=scoped).status_code == 401
    for path in ["/api/captures", "/api/people", "/api/profile", "/api/briefing/daily"]:
        assert client.get(path, headers=scoped).status_code == 401
    assert client.post("/api/captures", headers=scoped, json={"original_text": "X"}).status_code == 401
    assert client.post("/api/shortcuts/capture", headers=auth, json={"original_text": "X"}).status_code == 401
    assert client.post("/api/shortcuts/capture", headers=scoped, json={"original_text": "X", "parent_capture_id": str(uuid4())}).status_code == 422
    assert client.post("/api/shortcuts/capture", headers=scoped, json={"original_text": " "}).status_code == 422
    payload = {"original_text": "Per Siri notiert", "client_request_id": str(uuid4())}
    receipt = client.post("/api/shortcuts/capture", headers=scoped, json=payload)
    assert receipt.status_code == 201, receipt.text
    assert receipt.headers["cache-control"] == "no-store"
    assert set(receipt.json()) == {"id", "status"} and receipt.json()["status"] == "saved"
    assert client.post("/api/shortcuts/capture", headers=scoped, json=payload).json() == receipt.json()
    captures = client.get("/api/captures", headers=auth).json()
    assert sum(c["id"] == receipt.json()["id"] and c["original_text"] == payload["original_text"] for c in captures) == 1
    assert next(k for k in client.get("/api/shortcuts/keys", headers=auth).json() if k["id"] == key["id"])["last_used_at"]
    assert client.delete("/api/shortcuts/keys/" + key["id"], headers=scoped).status_code == 401
    assert client.delete("/api/shortcuts/keys/" + key["id"], headers=auth).status_code == 204
    assert client.post("/api/shortcuts/capture", headers=scoped, json=payload).status_code == 401


def test_expiry_rate_limit_password_change_and_isolation(client, auth, monkeypatch):
    username = "shortcut-" + uuid4().hex
    password = "initial-password-123"
    with Session(engine) as db:
        db.add(User(username=username, password_hash=hash_password(password)))
        db.commit()
    login = client.post("/api/auth/login", json={"username": username, "password": password}).json()
    other = {"Authorization": "Bearer " + login["access_token"]}
    key = issue(client, other, password)
    scoped = {"Authorization": "Bearer " + key["token"]}
    assert key["id"] not in {k["id"] for k in client.get("/api/shortcuts/keys", headers=auth).json()}
    assert client.delete("/api/shortcuts/keys/" + key["id"], headers=auth).status_code == 404
    monkeypatch.setattr(shortcut_routes, "REQUESTS_PER_HOUR", 1)
    payload = {"original_text": "Privat " + uuid4().hex}
    receipt = client.post("/api/shortcuts/capture", headers=scoped, json=payload)
    assert receipt.status_code == 201, receipt.text
    limited = client.post("/api/shortcuts/capture", headers=scoped, json=payload)
    assert limited.status_code == 429 and int(limited.headers["retry-after"]) > 0
    assert receipt.json()["id"] not in {c["id"] for c in client.get("/api/captures", headers=auth).json()}
    with Session(engine) as db:
        row = db.get(CaptureKey, key["id"])
        row.window_started_at = datetime.now(timezone.utc) - timedelta(hours=2)
        db.commit()
    assert client.post("/api/shortcuts/capture", headers=scoped, json=payload).status_code == 201
    with Session(engine) as db:
        row = db.get(CaptureKey, key["id"])
        row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
    assert client.post("/api/shortcuts/capture", headers=scoped, json=payload).status_code == 401
    key2 = issue(client, other, password, "Zweiter Schlüssel")
    scoped2 = {"Authorization": "Bearer " + key2["token"]}
    assert client.post("/api/auth/password", headers=other, json={"current_password": password, "new_password": "new-secure-password-456"}).status_code == 200
    assert client.post("/api/shortcuts/capture", headers=scoped2, json=payload).status_code == 401
    login2 = client.post("/api/auth/login", json={"username": username, "password": "new-secure-password-456"}).json()
    new_headers = {"Authorization": "Bearer " + login2["access_token"]}
    assert all(not k["active"] for k in client.get("/api/shortcuts/keys", headers=new_headers).json())
