from uuid import uuid4
from sqlalchemy.orm import Session
from lifepilot.db import engine
from lifepilot.models import User
from lifepilot.security import hash_password


def test_commitments_and_checkpoints(client, auth):
    person = client.post("/api/people", headers=auth, json={"first_name": "Verpflichtungstest"}).json()
    outgoing = client.post("/api/commitments", headers=auth, json={"title": "Unterlagen senden", "direction": "outgoing", "person_id": person["id"], "due_at": "2027-01-01T12:00:00+01:00"})
    assert outgoing.status_code == 201, outgoing.text
    assert outgoing.json()["due_at"].startswith("2027-01-01T11:00:00")
    incoming = client.post("/api/commitments", headers=auth, json={"title": "Rückmeldung erhalten", "direction": "incoming"})
    assert incoming.status_code == 201, incoming.text
    cid = incoming.json()["id"]
    waiting = client.get("/api/commitments?direction=incoming", headers=auth).json()
    assert cid in {r["id"] for r in waiting}
    assert client.patch(f"/api/commitments/{cid}/status", headers=auth, json={"status": "done"}).status_code == 200
    assert cid not in {r["id"] for r in client.get("/api/commitments", headers=auth).json()}
    assert cid in {r["id"] for r in client.get("/api/commitments?status=done", headers=auth).json()}
    checkpoint = client.post("/api/checkpoints", headers=auth, json={"title": "Projekt", "progress": "Analyse abgeschlossen", "next_step": "Tests schreiben"})
    assert checkpoint.status_code == 201, checkpoint.text
    wid = checkpoint.json()["id"]
    assert client.get(f"/api/checkpoints/{wid}", headers=auth).json()["next_step"] == "Tests schreiben"
    assert client.put(f"/api/checkpoints/{wid}", headers=auth, json={"title": "Projekt", "next_step": "Tests ausführen"}).status_code == 200
    assert client.patch(f"/api/checkpoints/{wid}/archive", headers=auth, json={"archived": True}).status_code == 200
    assert wid not in {r["id"] for r in client.get("/api/checkpoints", headers=auth).json()}
    assert wid in {r["id"] for r in client.get("/api/checkpoints?archived=true", headers=auth).json()}
    assert client.post("/api/checkpoints", headers=auth, json={"title": "Test", "next_step": "   "}).status_code == 422
    assert client.post("/api/commitments", headers=auth, json={"title": "Test", "direction": "incoming", "due_at": "2027-01-01T12:00:00"}).status_code == 422

    username = "commitment-other-" + uuid4().hex
    with Session(engine) as db:
        db.add(User(username=username, password_hash=hash_password("test-password")))
        db.commit()
    login = client.post("/api/auth/login", json={"username": username, "password": "test-password"})
    other = {"Authorization": "Bearer " + login.json()["access_token"]}
    assert client.get("/api/commitments?status=all", headers=other).json() == []
    assert client.patch(f"/api/commitments/{cid}/status", headers=other, json={"status": "open"}).status_code == 404
    assert client.get(f"/api/checkpoints/{wid}", headers=other).status_code == 404
    assert client.patch(f"/api/checkpoints/{wid}/archive", headers=other, json={"archived": False}).status_code == 404
    assert client.post("/api/commitments", headers=other, json={"title": "Fremd", "direction": "outgoing", "person_id": person["id"]}).status_code == 404
