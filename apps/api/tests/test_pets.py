from uuid import uuid4

from sqlalchemy.orm import Session

from lifepilot.db import engine
from lifepilot.models import AuditEvent, User
from lifepilot.security import create_token


def test_pet_profiles_link_people_and_events_and_enforce_owner_boundaries(client, auth):
    suffix = str(uuid4())
    person = client.post("/api/people", headers=auth, json={"first_name": f"Tiermensch-{suffix}"}).json()
    event = client.post("/api/events", headers=auth, json={"title": f"Tiertermin-{suffix}", "record_type": "experience", "starts_at": "2026-11-22T10:00:00Z", "participant_ids": [person["id"]]}).json()
    created = client.post(
        "/api/pets",
        headers=auth,
        json={
            "name": f"Milo-{suffix}",
            "species": "Hund",
            "breed": "Mischling",
            "sex": "male",
            "birthday": "2021-04-12",
            "is_neutered": True,
            "person_links": [{"person_id": person["id"], "relationship_type": "owner"}],
            "event_ids": [event["id"]],
        },
    )
    assert created.status_code == 201
    pet = created.json()
    assert pet["person_links"] == [{"person_id": person["id"], "relationship_type": "owner"}]
    assert pet["event_ids"] == [event["id"]]

    assert client.get("/api/pets", headers=auth, params={"q": f"Milo-{suffix}"}).json()[0]["id"] == pet["id"]
    updated = client.patch(f"/api/pets/{pet['id']}", headers=auth, json={"notes": "Liebt lange Spaziergänge", "birthday": None, "person_links": [{"person_id": person["id"], "relationship_type": "caretaker"}]})
    assert updated.status_code == 200
    assert updated.json()["birthday"] is None
    assert updated.json()["notes"] == "Liebt lange Spaziergänge"
    assert updated.json()["person_links"][0]["relationship_type"] == "caretaker"
    assert client.post("/api/pets", headers=auth, json={"name": "Fremdes Haustier", "species": "Katze", "person_links": [{"person_id": str(uuid4())}]}).status_code == 404
    assert client.patch(f"/api/pets/{pet['id']}", headers=auth, json={"sex": None}).status_code == 422

    with Session(engine) as db:
        other = User(username=f"pet-private-{suffix}", password_hash="unused")
        db.add(other)
        db.commit()
        other_headers = {"Authorization": f"Bearer {create_token(other.id)}"}
        assert client.get(f"/api/pets/{pet['id']}", headers=other_headers).status_code == 404
        assert client.patch(f"/api/pets/{pet['id']}", headers=other_headers, json={"name": "Fremd"}).status_code == 404

    assert client.delete(f"/api/pets/{pet['id']}", headers=auth).status_code == 204
    assert client.get(f"/api/pets/{pet['id']}", headers=auth).status_code == 404
    with Session(engine) as db:
        assert db.query(AuditEvent).filter_by(resource_type="pets", resource_id=pet["id"], action="delete").count() == 1
