def test_next_action_and_briefings(client, auth):
    from uuid import uuid4
    prefix = uuid4().hex
    def task(title, **planning):
        row = client.post("/api/tasks", headers=auth, json={"title": prefix + title})
        assert row.status_code == 201, row.text
        tid = row.json()["id"]
        if planning:
            saved = client.patch(f"/api/tasks/{tid}/planning", headers=auth, json=planning)
            assert saved.status_code == 200, saved.text
        return tid
    easy = task("easy", estimated_minutes=5, mental_effort="low", start_friction="low", work_context="computer", next_step="Dokument öffnen")
    hard = task("hard", estimated_minutes=5, mental_effort="high", work_context="computer")
    long = task("long", estimated_minutes=90, mental_effort="low", work_context="computer")
    phone = task("phone", estimated_minutes=5, mental_effort="low", work_context="phone")
    unknown = task("unknown")
    response = client.get("/api/planning/next-actions?minutes=10&energy=low&context=computer", headers=auth)
    assert response.status_code == 200, response.text
    result = response.json()
    ids = {r["task"]["id"] for r in result["recommended"]}
    assert easy in ids
    assert not ids.intersection({hard, long, phone, unknown})
    assert unknown in {r["id"] for r in result["needs_details"]} or len(result["needs_details"]) == 10
    assert client.patch(f"/api/tasks/{easy}/planning", headers=auth, json={"estimated_minutes": 0}).status_code == 422
    assert client.patch(f"/api/tasks/{easy}/planning", headers=auth, json={"next_step": "Datei öffnen"}).json()["estimated_minutes"] == 5
    assert client.patch(f"/api/tasks/{easy}/planning", headers=auth, json={"mental_effort": "invalid"}).status_code == 422
    person = client.post("/api/people", headers=auth, json={"first_name": prefix}).json()
    commitment = client.post("/api/commitments", headers=auth, json={"title": prefix+"Versprechen", "direction": "incoming", "person_id": person["id"], "due_at": "2020-01-01T12:00:00Z"}).json()
    checkpoint = client.post("/api/checkpoints", headers=auth, json={"title": prefix+"Arbeit", "next_step": "Weiterarbeiten"}).json()
    daily = client.get("/api/briefing/daily", headers=auth)
    assert daily.status_code == 200, daily.text
    assert commitment["id"] in {r["id"] for r in daily.json()["open_commitments"]}
    assert checkpoint["id"] in {r["id"] for r in daily.json()["active_checkpoints"]}
    personal = client.get(f"/api/briefing/person/{person['id']}", headers=auth)
    assert personal.status_code == 200, personal.text
    assert commitment["id"] in {r["id"] for r in personal.json()["open_commitments"]}
    assert client.patch(f"/api/commitments/{commitment['id']}/status", headers=auth, json={"status": "done"}).status_code == 200
    assert client.get(f"/api/briefing/person/{person['id']}", headers=auth).json()["open_commitments"] == []


def test_task_planning_is_owner_scoped(client, auth):
    from uuid import uuid4
    from sqlalchemy.orm import Session
    from lifepilot.db import engine
    from lifepilot.models import User
    from lifepilot.security import hash_password
    row = client.post("/api/tasks", headers=auth, json={"title": "Private Planung"}).json()
    username = "planning-" + uuid4().hex
    with Session(engine) as db:
        db.add(User(username=username, password_hash=hash_password("test-password")))
        db.commit()
    token = client.post("/api/auth/login", json={"username": username, "password": "test-password"}).json()["access_token"]
    other = {"Authorization": "Bearer " + token}
    assert client.patch(f"/api/tasks/{row['id']}/planning", headers=other, json={"estimated_minutes": 10}).status_code == 404
    assert client.get("/api/planning/next-actions", headers=other).json() == {"recommended": [], "needs_details": []}
