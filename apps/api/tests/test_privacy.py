from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from lifepilot.db import engine
from lifepilot.models import User
from lifepilot.security import create_token


@dataclass(frozen=True, slots=True)
class PrivateDataset:
    other_headers: dict[str, str]
    marker: str
    person_id: str
    related_person_id: str
    memory_id: str
    conversation_id: str
    task_id: str
    relationship_id: str
    loan_id: str
    gift_id: str
    event_id: str
    project_id: str


@pytest.fixture
def private_dataset(client: TestClient, auth: dict[str, str]) -> PrivateDataset:
    marker = f"private-{uuid4().hex}"
    person = client.post("/api/people", headers=auth, json={"first_name": marker})
    related = client.post("/api/people", headers=auth, json={"first_name": "Related"})
    assert person.status_code == related.status_code == 201
    person_id = person.json()["id"]
    related_person_id = related.json()["id"]
    memory = client.post("/api/memories", headers=auth, json={"title": marker, "content": f"{marker} memory", "person_id": person_id})
    conversation = client.post("/api/conversations", headers=auth, json={"title": marker, "original_note": f"{marker} conversation", "participant_ids": [person_id]})
    task = client.post("/api/tasks", headers=auth, json={"title": marker, "person_id": person_id})
    relationship = client.post("/api/relationships", headers=auth, json={"source_person_id": person_id, "target_person_id": related_person_id, "relationship_type": "knows"})
    loan = client.post("/api/loans", headers=auth, json={"item_name": marker, "borrower_person_id": person_id})
    gift = client.post("/api/gifts", headers=auth, json={"person_id": person_id, "title": marker})
    event = client.post("/api/events", headers=auth, json={"title": marker, "starts_at": (datetime.now(timezone.utc) + timedelta(days=2)).isoformat(), "participant_ids": [person_id]})
    project = client.post("/api/projects", headers=auth, json={"name": marker})
    assert all(response.status_code == 201 for response in (memory, conversation, task, relationship, loan, gift, event, project))
    with Session(engine) as db:
        other = User(username=f"privacy-{uuid4().hex}", password_hash="unused")
        db.add(other)
        db.commit()
        other_headers = {"Authorization": f"Bearer {create_token(other.id)}"}
    return PrivateDataset(
        other_headers=other_headers,
        marker=marker,
        person_id=person_id,
        related_person_id=related_person_id,
        memory_id=memory.json()["id"],
        conversation_id=conversation.json()["id"],
        task_id=task.json()["id"],
        relationship_id=relationship.json()["id"],
        loan_id=loan.json()["id"],
        gift_id=gift.json()["id"],
        event_id=event.json()["id"],
        project_id=project.json()["id"],
    )


def test_search_and_collection_routes_only_return_the_authenticated_owners_records(client: TestClient, private_dataset: PrivateDataset) -> None:
    headers = private_dataset.other_headers
    person_id = private_dataset.person_id
    paths = (
        f"/api/people?q={private_dataset.marker}",
        f"/api/memories?person_id={person_id}",
        f"/api/conversations?person_id={person_id}",
        "/api/tasks?status=open",
        f"/api/loans?person_id={person_id}",
        f"/api/gifts?person_id={person_id}",
        f"/api/events?person_id={person_id}",
        f"/api/projects?q={private_dataset.marker}",
        "/api/captures",
    )
    for path in paths:
        response = client.get(path, headers=headers)
        assert response.status_code == 200, path
        assert response.json() == [], path


def test_hybrid_search_does_not_disclose_foreign_resources(client: TestClient, private_dataset: PrivateDataset) -> None:
    response = client.get(f"/api/search?q={private_dataset.marker}", headers=private_dataset.other_headers)

    assert response.status_code == 200
    results = response.json()
    result_ids = {row["id"] for resource in results.values() if isinstance(resource, list) for row in resource if isinstance(row, dict) and "id" in row}
    private_ids = {
        private_dataset.person_id,
        private_dataset.related_person_id,
        private_dataset.memory_id,
        private_dataset.conversation_id,
        private_dataset.task_id,
        private_dataset.relationship_id,
        private_dataset.loan_id,
        private_dataset.gift_id,
        private_dataset.project_id,
    }
    assert result_ids.isdisjoint(private_ids)
    assert private_dataset.marker not in response.text


def test_foreign_resource_ids_cannot_read_or_mutate_records(client: TestClient, auth: dict[str, str], private_dataset: PrivateDataset) -> None:
    headers = private_dataset.other_headers
    person_read = client.get(f"/api/people/{private_dataset.person_id}", headers=headers)
    project_read = client.get(f"/api/projects/{private_dataset.project_id}", headers=headers)
    context_read = client.get(f"/api/briefing/person/{private_dataset.person_id}", headers=headers)
    relation_read = client.get(f"/api/relationships?person_id={private_dataset.person_id}", headers=headers)
    assert [response.status_code for response in (person_read, project_read, context_read, relation_read)] == [404, 404, 404, 404]

    person_update = client.patch(f"/api/people/{private_dataset.person_id}", headers=headers, json={"first_name": "Stolen"})
    project_update = client.patch(f"/api/projects/{private_dataset.project_id}", headers=headers, json={"name": "Stolen"})
    task_complete = client.patch(f"/api/tasks/{private_dataset.task_id}/complete", headers=headers)
    assert [response.status_code for response in (person_update, project_update, task_complete)] == [404, 404, 404]
    assert client.get(f"/api/people/{private_dataset.person_id}", headers=auth).json()["first_name"] == private_dataset.marker
    assert client.get(f"/api/projects/{private_dataset.project_id}", headers=auth).json()["name"] == private_dataset.marker
    owner_tasks = client.get("/api/tasks?status=open", headers=auth).json()
    assert next(task for task in owner_tasks if task["id"] == private_dataset.task_id)["status"] == "open"
