from uuid import uuid4

from sqlalchemy.orm import Session

from lifepilot.db import engine
from lifepilot.models import User
from lifepilot.security import create_token


def test_person_favorites_labels_and_how_we_met_are_persisted_and_searchable(client, auth):
    created = client.post(
        "/api/people",
        headers=auth,
        json={
            "first_name": "Mara",
            "last_name": "Beispiel",
            "how_met": "Beim Sommerfest im Sportverein",
            "tags": [" Verein ", "familie", "verein", ""],
        },
    )
    assert created.status_code == 201
    person = created.json()
    assert person["how_met"] == "Beim Sommerfest im Sportverein"
    assert person["tags"] == ["Verein", "familie"]
    assert person["is_favorite"] is False
    assert client.get("/api/people?q=Sportverein", headers=auth).json()[0]["id"] == person["id"]
    assert client.get("/api/people?q=familie", headers=auth).json()[0]["id"] == person["id"]

    added = client.patch(f"/api/people/{person['id']}/favorite", headers=auth)
    assert added.status_code == 200
    assert added.json()["is_favorite"] is True
    removed = client.patch(f"/api/people/{person['id']}/favorite", headers=auth)
    assert removed.json()["is_favorite"] is False

    with Session(engine) as db:
        other_user = User(username=f"private-{uuid4().hex}", password_hash="unused")
        db.add(other_user)
        db.commit()
        other_token = create_token(other_user.id)
    assert client.patch(f"/api/people/{person['id']}/favorite", headers={"Authorization": f"Bearer {other_token}"}).status_code == 404
