from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy.orm import Session
from lifepilot.db import engine
from lifepilot.models import FocusSession, User
from lifepilot.security import hash_password


def test_companion_checkins_and_isolation(client, auth):
    task = client.post("/api/tasks", headers=auth, json={"title": "Dokument prüfen"}).json()
    assert client.post(f"/api/tasks/{task['id']}/steps", headers=auth, json={"steps": [{"title": "Dokument öffnen"}, {"title": "Abschnitt lesen"}]}).status_code == 201
    started = client.post("/api/focus/start", headers=auth, json={"task_id": task["id"], "planned_minutes": 20, "companion_interval_minutes": 5, "companion_goal": "Ein Abschnitt"})
    assert started.status_code == 201, started.text
    sid = started.json()["id"]
    path = f"/api/focus/{sid}"
    assert started.json()["companion_interval_minutes"] == 5
    initial = client.get(path + "/companion", headers=auth).json()
    assert initial["goal"] == "Ein Abschnitt"
    assert initial["suggested_next_step"] == "Dokument öffnen"
    assert initial["checkins"] == []
    started_at = datetime.fromisoformat(started.json()["started_at"])
    assert datetime.fromisoformat(initial["next_due_at"]) == started_at + timedelta(minutes=5)

    payload = {"request_id": str(uuid4()), "state": "blocked", "note": "Datei fehlt", "next_step": "Datei suchen"}
    first = client.post(path + "/checkins", headers=auth, json=payload)
    assert first.status_code == 200, first.text
    data = first.json()
    assert data["suggested_next_step"] == "Datei suchen"
    assert data["checkins"][0]["note"] == "Datei fehlt"
    assert datetime.fromisoformat(data["next_due_at"]) == datetime.fromisoformat(data["checkins"][0]["created_at"]) + timedelta(minutes=5)
    repeat = client.post(path + "/checkins", headers=auth, json=payload)
    assert repeat.status_code == 200 and len(repeat.json()["checkins"]) == 1
    invalid = {"request_id": str(uuid4()), "state": "skip", "note": "Nicht zulässig"}
    assert client.post(path + "/checkins", headers=auth, json=invalid).status_code == 422
    skip = client.post(path + "/checkins", headers=auth, json={"request_id": str(uuid4()), "state": "skip"})
    assert skip.status_code == 200
    assert len(skip.json()["checkins"]) == 2
    assert skip.json()["suggested_next_step"] == "Datei suchen"

    username = "companion-other-" + uuid4().hex
    with Session(engine) as db:
        db.add(User(username=username, password_hash=hash_password("test-password")))
        db.commit()
    token = client.post("/api/auth/login", json={"username": username, "password": "test-password"}).json()["access_token"]
    other = {"Authorization": "Bearer " + token}
    assert client.get(path + "/companion", headers=other).status_code == 404
    assert client.post(path + "/checkins", headers=other, json=payload).status_code == 404
    assert client.post(path + "/end", headers=auth, json={"outcome": "finished"}).status_code == 200
    assert client.get(path + "/companion", headers=auth).json()["next_due_at"] is None
    assert client.post(path + "/checkins", headers=auth, json={"request_id": str(uuid4()), "state": "on_track"}).status_code == 409
    assert client.post(path + "/checkins", headers=auth, json=payload).status_code == 200


def test_companion_is_optional_and_stops_scheduling(client, auth):
    task = client.post("/api/tasks", headers=auth, json={"title": "Kurze Aufgabe"}).json()
    assert client.post("/api/focus/start", headers=auth, json={"task_id": task["id"], "companion_interval_minutes": 1}).status_code == 422
    row = client.post("/api/focus/start", headers=auth, json={"task_id": task["id"], "planned_minutes": 2, "companion_interval_minutes": 5}).json()
    path = f"/api/focus/{row['id']}"
    assert client.get(path + "/companion", headers=auth).json()["next_due_at"] is None
    assert client.post(path + "/end", headers=auth, json={"outcome": "finished"}).status_code == 200
    row = client.post("/api/focus/start", headers=auth, json={"task_id": task["id"]}).json()
    path = f"/api/focus/{row['id']}"
    assert client.get(path + "/companion", headers=auth).json()["interval_minutes"] is None
    assert client.post(path + "/checkins", headers=auth, json={"request_id": str(uuid4()), "state": "on_track"}).status_code == 409
    assert client.post(path + "/end", headers=auth, json={"outcome": "finished"}).status_code == 200
