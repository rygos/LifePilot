import os
from pathlib import Path
import pytest

db_path = Path("/tmp/lifepilot-test.db")
db_path.unlink(missing_ok=True)
os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
os.environ["SECRET_KEY"] = "test-secret-key-with-adequate-length"
os.environ["LIFE_PILOT_BOOTSTRAP_USERNAME"] = "testuser"
os.environ["LIFE_PILOT_BOOTSTRAP_PASSWORD"] = "test-password"

from fastapi.testclient import TestClient
from lifepilot.main import app
from lifepilot.db import Base, engine
from lifepilot.models import Gift, Loan, Memory, Person, Task, User
from lifepilot.security import hash_password

@pytest.fixture(scope="module")
def client():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with __import__("sqlalchemy").orm.Session(engine) as db:
        db.add(User(username="testuser", password_hash=hash_password("test-password")))
        db.commit()
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client

@pytest.fixture()
def auth(client):
    response = client.post("/api/auth/login", json={"username": "testuser", "password": "test-password"})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}

def test_auth_people_memories_tasks_search_and_persistence(client, auth):
    assert client.get("/api/people").status_code == 401
    person = client.post("/api/people", headers=auth, json={"first_name": "Martin", "birthday": "1988-04-02", "notes": "Karnevalsverein"})
    assert person.status_code == 201
    person_id = person.json()["id"]
    memory = client.post("/api/memories", headers=auth, json={"title": "Bohrmaschine", "content": "Martin hat mir seine Bohrmaschine geliehen.", "person_id": person_id, "occurred_at": "2026-11-16T10:00:00Z"})
    assert memory.status_code == 201
    assert memory.json()["occurred_at"].startswith("2026-11-16")
    task = client.post("/api/tasks", headers=auth, json={"title": "Martin zurückrufen", "person_id": person_id})
    assert task.status_code == 201
    assert client.get("/api/search?q=Bohrmaschine", headers=auth).json()["memories"][0]["id"] == memory.json()["id"]
    assert client.get("/api/people", headers=auth).json()[0]["id"] == person_id
    assert client.patch(f"/api/tasks/{task.json()['id']}/complete", headers=auth).json()["status"] == "done"

def test_relationship_validation_and_cross_user_isolation(client, auth):
    first = client.post("/api/people", headers=auth, json={"first_name": "Martin"}).json()
    second = client.post("/api/people", headers=auth, json={"first_name": "Lea"}).json()
    relation = client.post("/api/relationships", headers=auth, json={"source_person_id": first["id"], "target_person_id": second["id"], "relationship_type": "Elternteil"})
    assert relation.status_code == 201
    assert relation.json()["source_person_id"] == first["id"]
    assert client.post("/api/relationships", headers=auth, json={"source_person_id": first["id"], "target_person_id": first["id"], "relationship_type": "kennt"}).status_code == 422
    other_token = client.post("/api/auth/login", json={"username": "other", "password": "other-password"})
    assert other_token.status_code == 401
    assert client.get(f"/api/people/{first['id']}", headers={"Authorization": "Bearer invalid"}).status_code == 401

def test_relationships_and_profile_fields_are_readable_and_editable(client, auth):
    martin = client.post("/api/people", headers=auth, json={"first_name": "Martin", "nickname": "Marty", "address": "Hauptstraße 4", "website": "https://example.org", "job_title": "Gärtner", "organization": "Verein"}).json()
    lea = client.post("/api/people", headers=auth, json={"first_name": "Lea"}).json()
    relation = client.post("/api/relationships", headers=auth, json={"source_person_id": martin["id"], "target_person_id": lea["id"], "relationship_type": "Vater von"})
    assert relation.status_code == 201
    visible = client.get(f"/api/relationships?person_id={lea['id']}", headers=auth).json()
    assert visible[0]["source_person_name"] == "Martin"
    assert visible[0]["target_person_name"] == "Lea"
    assert client.get(f"/api/people/{martin['id']}", headers=auth).json()["address"] == "Hauptstraße 4"
    profile = client.patch("/api/profile", headers=auth, json={"full_name": "Alex Beispiel", "nickname": "Alex", "address": "Parkweg 1", "email": "alex@example.org"})
    assert profile.status_code == 200
    assert client.get("/api/profile", headers=auth).json()["full_name"] == "Alex Beispiel"
    assert client.delete(f"/api/relationships/{relation.json()['id']}", headers=auth).status_code == 204
    assert client.get(f"/api/relationships?person_id={lea['id']}", headers=auth).json() == []

def test_mcp_tools_are_registered():
    from lifepilot.main import mcp
    assert mcp is not None
    names = {tool.name for tool in mcp._tool_manager.list_tools()}
    assert {"person_create_tool", "person_search_tool", "memory_capture_tool", "memory_search_tool"} <= names

def test_conversations_loans_gifts_and_owner_boundaries(client, auth):
    martin = client.post("/api/people", headers=auth, json={"first_name": "Martin"}).json()
    lea = client.post("/api/people", headers=auth, json={"first_name": "Lea"}).json()
    note = client.post("/api/memories", headers=auth, json={"title": "Wunsch", "content": "Anna mag Bücher", "person_id": martin["id"]}).json()
    conversation = client.post("/api/conversations", headers=auth, json={"title": "Treffen im Verein", "original_note": "Martin erzählte von Lea.", "participant_ids": [martin["id"], lea["id"]], "occurred_at": "2026-11-16T18:00:00Z", "location": "Vereinsheim"})
    assert conversation.status_code == 201
    assert conversation.json()["original_note"] == "Martin erzählte von Lea."
    assert set(client.get(f"/api/conversations?person_id={lea['id']}", headers=auth).json()[0]["participant_ids"]) == {martin["id"], lea["id"]}
    assert client.get("/api/search?q=Vereinsheim", headers=auth).json()["conversations"][0]["id"] == conversation.json()["id"]
    assert client.post("/api/conversations", headers=auth, json={"title": "Fremd", "original_note": "x", "participant_ids": ["foreign-id"]}).status_code == 404
    loan = client.post("/api/loans", headers=auth, json={"item_name": "Bohrmaschine", "lender_person_id": martin["id"], "borrower_person_id": lea["id"], "source_memory_id": note["id"]})
    assert loan.status_code == 201
    assert len(client.get("/api/loans", headers=auth).json()) == 1
    assert client.patch(f"/api/loans/{loan.json()['id']}/return", headers=auth).json()["returned_at"] is not None
    assert client.get("/api/loans", headers=auth).json() == []
    gift = client.post("/api/gifts", headers=auth, json={"person_id": martin["id"], "title": "Roman", "occasion": "Geburtstag", "budget": 25, "source_memory_id": note["id"]})
    assert gift.status_code == 201
    assert client.get(f"/api/gifts?person_id={martin['id']}", headers=auth).json()[0]["id"] == gift.json()["id"]
    assert client.get("/api/search?q=Bohrmaschine", headers=auth).json()["loans"][0]["id"] == loan.json()["id"]
    assert client.get("/api/conversations", headers={"Authorization": "Bearer invalid"}).status_code == 401

def test_events_scheduler_notifications_and_reminder_actions(client, auth):
    from datetime import datetime, timedelta, timezone
    from sqlalchemy.orm import Session
    from lifepilot.scheduler import schedule_due_items
    event = client.post("/api/events", headers=auth, json={"title": "Arzttermin", "location": "Praxis", "starts_at": "2026-11-16T10:00:00Z"})
    assert event.status_code == 201
    assert client.post("/api/events", headers=auth, json={"title": "Falsch", "starts_at": "2026-11-16T10:00:00Z", "ends_at": "2026-11-15T10:00:00Z"}).status_code == 422
    with Session(engine) as db:
        task = Task(owner_id=db.query(User).filter_by(username="testuser").one().id, title="internal")
        task.due_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.add(task); db.commit()
        created = schedule_due_items(db)
        assert created >= 1
        assert schedule_due_items(db) == 0
    due = client.get("/api/notifications", headers=auth)
    assert any(item["title"] == "internal" for item in due.json())
    reminder = next(item for item in due.json() if item["title"] == "internal")
    action = client.patch(f"/api/reminders/{reminder['id']}", headers=auth, json={"state": "scheduled", "snoozed_until": "2026-11-17T12:00:00Z"})
    assert action.status_code == 200
    assert action.json()["snoozed_until"] is not None
    task_reminder = client.post("/api/tasks", headers=auth, json={"title": "Abschließbare Aufgabe", "due_at": "2026-11-16T08:00:00Z"}).json()
    with Session(engine) as db:
        created = schedule_due_items(db)
        assert created == 1
    linked = client.get("/api/reminders", headers=auth).json()
    linked_reminder = next(item for item in linked if item["task_id"] == task_reminder["id"])
    assert client.patch(f"/api/tasks/{task_reminder['id']}/complete", headers=auth).json()["status"] == "done"
    updated_reminders = client.get("/api/reminders", headers=auth).json()
    assert next(item for item in updated_reminders if item["id"] == linked_reminder["id"])["state"] == "done"
