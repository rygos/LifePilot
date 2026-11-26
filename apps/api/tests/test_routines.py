from datetime import datetime, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from lifepilot import routine_routes
from lifepilot.db import engine
from lifepilot.models import User
from lifepilot.security import hash_password


def test_routine_daily_progress_and_history(client, auth, monkeypatch):
    clock = [datetime(2027, 1, 4, 7, 30, tzinfo=ZoneInfo("Europe/Berlin"))]
    monkeypatch.setattr(routine_routes, "local_now", lambda user: clock[0])
    payload = {"title": "Morgenroutine", "weekdays": [0, 1, 2, 3, 4], "window_start": "07:00", "window_end": "08:00", "steps": [{"title": "Wasser trinken"}, {"title": "Tagesplan ansehen"}]}
    response = client.post("/api/routines", headers=auth, json=payload)
    assert response.status_code == 201, response.text
    row = response.json()
    rid, sid = row["id"], row["steps"][0]["id"]
    path = f"/api/routines/{rid}"
    assert row["scheduled_today"] and row["window_state"] == "active"
    assert row["local_date"] == "2027-01-04"
    assert not row["steps"][0]["completed"]
    complete = {"local_date": "2027-01-04", "completed": True}
    done = client.patch(f"{path}/steps/{sid}/completion", headers=auth, json=complete)
    assert done.status_code == 200 and done.json()["steps"][0]["completed"]
    assert client.patch(f"{path}/steps/{sid}/completion", headers=auth, json=complete).status_code == 200
    history = client.get(path + "/history", headers=auth).json()
    assert len(history) == 1 and history[0]["title"] == "Wasser trinken"
    assert client.patch(f"{path}/steps/{sid}/completion", headers=auth, json={**complete, "completed": False}).status_code == 200
    assert client.get(path + "/history", headers=auth).json() == []
    assert client.patch(f"{path}/steps/{sid}/completion", headers=auth, json=complete).status_code == 200
    assert any(r["id"] == rid and r["steps"][0]["completed"] for r in client.get("/api/briefing/daily", headers=auth).json()["today_routines"])
    clock[0] = datetime(2027, 1, 5, 9, 0, tzinfo=ZoneInfo("Europe/Berlin"))
    rows = client.get("/api/routines?today_only=true", headers=auth).json()
    row = next(r for r in rows if r["id"] == rid)
    assert row["window_state"] == "past" and not row["steps"][0]["completed"]
    assert client.patch(f"{path}/steps/{sid}/completion", headers=auth, json=complete).status_code == 409
    assert len(client.get(path + "/history", headers=auth).json()) == 1
    clock[0] = datetime(2027, 1, 9, 9, 0, tzinfo=ZoneInfo("Europe/Berlin"))
    assert rid not in {r["id"] for r in client.get("/api/routines?today_only=true", headers=auth).json()}
    assert client.patch(f"{path}/steps/{sid}/completion", headers=auth, json={"local_date": "2027-01-09", "completed": True}).status_code == 409
    assert client.patch(f"{path}/steps/{sid}/archive", headers=auth, json={"archived": True}).status_code == 200
    second = row["steps"][1]["id"]
    assert client.patch(f"{path}/steps/{second}/archive", headers=auth, json={"archived": True}).status_code == 409
    assert client.post(path + "/steps", headers=auth, json={"title": "Fenster öffnen"}).status_code == 201
    assert client.patch(path + "/archive", headers=auth, json={"archived": True}).status_code == 200
    assert rid not in {r["id"] for r in client.get("/api/routines", headers=auth).json()}
    assert rid in {r["id"] for r in client.get("/api/routines?include_archived=true", headers=auth).json()}
    assert client.patch(path + "/archive", headers=auth, json={"archived": False}).status_code == 200
    assert client.put(path, headers=auth, json={"title": "Neue Routine", "weekdays": [5, 6]}).status_code == 200
    assert rid in {r["id"] for r in client.get("/api/routines?today_only=true", headers=auth).json()}


def test_routine_validation_and_isolation(client, auth):
    data = {"title": "Privat", "weekdays": [0, 1, 2, 3, 4, 5, 6], "steps": [{"title": "Ein Schritt"}]}
    for invalid in [{"weekdays": [0, 0]}, {"weekdays": [7]}, {"steps": []}, {"window_start": "22:00", "window_end": "06:00"}, {"window_start": "07:00"}, {"title": " "}]:
        assert client.post("/api/routines", headers=auth, json={**data, **invalid}).status_code == 422
    row = client.post("/api/routines", headers=auth, json=data).json()
    path = f"/api/routines/{row['id']}"
    sid = row["steps"][0]["id"]
    username = "routine-other-" + uuid4().hex
    with Session(engine) as db:
        db.add(User(username=username, password_hash=hash_password("test-password")))
        db.commit()
    token = client.post("/api/auth/login", json={"username": username, "password": "test-password"}).json()["access_token"]
    other = {"Authorization": "Bearer " + token}
    assert client.get("/api/routines", headers=other).json() == []
    assert client.get(path + "/history", headers=other).status_code == 404
    assert client.put(path, headers=other, json={"title": "Fremd", "weekdays": [0]}).status_code == 404
    assert client.post(path + "/steps", headers=other, json={"title": "Fremd"}).status_code == 404
    assert client.patch(path + "/archive", headers=other, json={"archived": True}).status_code == 404
    assert client.patch(f"{path}/steps/{sid}/completion", headers=other, json={"local_date": row["local_date"], "completed": True}).status_code == 404
