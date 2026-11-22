from uuid import uuid4

from sqlalchemy.orm import Session

from lifepilot.db import engine
from lifepilot.models import AuditEvent, User
from lifepilot.security import create_token


def test_journal_entries_are_dated_linked_searchable_and_private(client, auth):
    suffix = str(uuid4())
    person = client.post("/api/people", headers=auth, json={"first_name": f"Tagebuch-{suffix}"}).json()
    project = client.post("/api/projects", headers=auth, json={"name": f"Projekt-{suffix}"}).json()
    event = client.post("/api/events", headers=auth, json={"title": f"Treffen-{suffix}", "record_type": "experience", "starts_at": "2026-11-20T17:00:00+01:00", "participant_ids": [person["id"]]}).json()

    created = client.post(
        "/api/journal",
        headers=auth,
        json={
            "entry_date": "2026-11-20",
            "title": "Ein guter Tag",
            "content": f"Wir haben über Kaffee gesprochen {suffix}.",
            "mood": "dankbar",
            "person_ids": [person["id"]],
            "project_ids": [project["id"]],
            "event_ids": [event["id"]],
        },
    )
    assert created.status_code == 201
    entry = created.json()
    assert entry["person_ids"] == [person["id"]]
    assert entry["project_ids"] == [project["id"]]
    assert entry["event_ids"] == [event["id"]]
    assert entry["mood"] == "dankbar"

    filtered = client.get("/api/journal", headers=auth, params={"from_date": "2026-11-20", "to_date": "2026-11-20", "q": suffix})
    assert filtered.status_code == 200 and [row["id"] for row in filtered.json()] == [entry["id"]]
    changed = client.patch(f"/api/journal/{entry['id']}", headers=auth, json={"mood": None, "person_ids": []})
    assert changed.status_code == 200
    assert changed.json()["mood"] is None and changed.json()["person_ids"] == []
    assert client.post("/api/journal", headers=auth, json={"entry_date": "2026-11-20", "content": "Falscher Bezug", "person_ids": [str(uuid4())]}).status_code == 404

    with Session(engine) as db:
        other = User(username=f"journal-private-{suffix}", password_hash="unused")
        db.add(other)
        db.commit()
        other_headers = {"Authorization": f"Bearer {create_token(other.id)}"}
        assert client.get(f"/api/journal/{entry['id']}", headers=other_headers).status_code == 404
        assert client.patch(f"/api/journal/{entry['id']}", headers=other_headers, json={"title": "Fremdzugriff"}).status_code == 404

    assert client.delete(f"/api/journal/{entry['id']}", headers=auth).status_code == 204
    assert client.get(f"/api/journal/{entry['id']}", headers=auth).status_code == 404
    with Session(engine) as db:
        assert db.query(AuditEvent).filter_by(resource_type="journal_entries", resource_id=entry["id"], action="delete").count() == 1
