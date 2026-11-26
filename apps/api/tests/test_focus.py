from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy.orm import Session
from lifepilot.db import engine
from lifepilot.models import FocusSession, User
from lifepilot.security import hash_password


def test_focus_lifecycle_and_isolation(client, auth):
    title = "Fokus-" + uuid4().hex
    task = client.post("/api/tasks", headers=auth, json={"title": title}).json()
    assert client.get("/api/focus/active", headers=auth).json() is None
    started = client.post("/api/focus/start", headers=auth, json={"task_id": task["id"], "planned_minutes": 10})
    assert started.status_code == 201, started.text
    sid = started.json()["id"]
    assert started.json()["started_at"].endswith("+00:00")
    assert client.get("/api/focus/active", headers=auth).json()["id"] == sid
    assert client.post("/api/focus/start", headers=auth, json={"task_id": task["id"]}).status_code == 409
    assert client.post("/api/focus/start", headers=auth, json={"task_id": task["id"], "planned_minutes": 181}).status_code == 422

    username = "focus-other-" + uuid4().hex
    with Session(engine) as db:
        db.add(User(username=username, password_hash=hash_password("test-password")))
        row = db.get(FocusSession, sid)
        row.started_at = datetime.now(timezone.utc) - timedelta(seconds=125)
        db.commit()
    token = client.post("/api/auth/login", json={"username": username, "password": "test-password"}).json()["access_token"]
    other = {"Authorization": "Bearer " + token}
    assert client.get("/api/focus/active", headers=other).json() is None
    assert client.get("/api/focus/history", headers=other).json() == []
    assert client.post("/api/focus/start", headers=other, json={"task_id": task["id"]}).status_code == 404
    assert client.post(f"/api/focus/{sid}/end", headers=other, json={"outcome": "finished"}).status_code == 404
    assert client.post(f"/api/focus/{sid}/end", headers=auth, json={"outcome": "interrupted", "checkpoint": {"next_step": " "}}).status_code == 422
    assert client.get("/api/focus/active", headers=auth).json()["id"] == sid
    ended = client.post(f"/api/focus/{sid}/end", headers=auth, json={"outcome": "interrupted", "checkpoint": {"next_step": "Datei öffnen", "progress": "Analyse beendet"}})
    assert ended.status_code == 200, ended.text
    data = ended.json()
    assert data["elapsed_seconds"] >= 125
    assert data["outcome"] == "interrupted"
    checkpoint = client.get(f"/api/checkpoints/{data['checkpoint_id']}", headers=auth).json()
    assert checkpoint["task_id"] == task["id"]
    assert checkpoint["next_step"] == "Datei öffnen"
    repeated = client.post(f"/api/focus/{sid}/end", headers=auth, json={"outcome": "interrupted", "checkpoint": {"next_step": "Nicht doppelt speichern"}})
    assert repeated.json()["checkpoint_id"] == data["checkpoint_id"]
    assert client.get("/api/focus/active", headers=auth).json() is None
    assert client.get(f"/api/focus/history?task_id={task['id']}", headers=auth).json()[0]["id"] == sid
    second = client.post("/api/focus/start", headers=auth, json={"task_id": task["id"]}).json()
    assert client.post(f"/api/focus/{second['id']}/end", headers=auth, json={"outcome": "finished", "checkpoint": {"next_step": "Nicht erlaubt"}}).status_code == 422
    assert client.post(f"/api/focus/{second['id']}/end", headers=auth, json={"outcome": "finished"}).status_code == 200
    assert any(t["id"] == task["id"] and t["status"] == "open" for t in client.get("/api/tasks", headers=auth).json())
