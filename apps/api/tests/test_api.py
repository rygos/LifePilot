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
from lifepilot.models import Conversation, ConversationParticipant, Gift, Loan, Memory, Person, User
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
