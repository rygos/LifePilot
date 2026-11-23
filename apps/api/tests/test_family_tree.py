from sqlalchemy.orm import Session

from lifepilot.db import engine
from lifepilot.models import Person, User
from lifepilot.security import hash_password


def _person(client, auth, first_name: str) -> dict:
    response = client.post("/api/people", headers=auth, json={"first_name": first_name, "last_name": "Diagrammlinie"})
    assert response.status_code == 201, response.text
    return response.json()


def _relationship(client, auth, source: dict, target: dict, relation: str, confirmed: bool = True) -> dict:
    response = client.post("/api/relationships", headers=auth, json={
        "source_person_id": source["id"], "target_person_id": target["id"],
        "relationship_type": relation, "confirmed": confirmed,
    })
    assert response.status_code == 201, response.text
    return response.json()


def test_family_tree_includes_connected_generations_and_excludes_non_family(client, auth):
    grandparent = _person(client, auth, "Baum-Großeltern")
    parent = _person(client, auth, "Baum-Eltern")
    root = _person(client, auth, "Baum-Ausgangspunkt")
    spouse = _person(client, auth, "Baum-Partner")
    child = _person(client, auth, "Baum-Kind")
    friend = _person(client, auth, "Baum-Freund")
    _relationship(client, auth, grandparent, parent, "parent")
    _relationship(client, auth, root, parent, "child")
    _relationship(client, auth, spouse, root, "spouse", confirmed=False)
    _relationship(client, auth, root, child, "parent")
    _relationship(client, auth, root, friend, "friend")

    response = client.get(f"/api/people/{root['id']}/family-tree", headers=auth)
    assert response.status_code == 200, response.text
    payload = response.json()
    ids = {item["id"] for item in payload["people"]}
    assert ids == {grandparent["id"], parent["id"], root["id"], spouse["id"], child["id"]}
    spouse_edge = next(edge for edge in payload["relationships"] if edge["source_person_id"] == spouse["id"])
    assert spouse_edge["confirmed"] is False
    assert len(payload["relationships"]) == 4


def test_family_tree_is_scoped_to_authenticated_owner(client, auth):
    with Session(engine) as db:
        user = User(username="family-tree-private", password_hash=hash_password("private-password"))
        db.add(user)
        db.flush()
        foreign = Person(owner_id=user.id, first_name="Privat", last_name="Familie")
        db.add(foreign)
        db.commit()
        foreign_id = foreign.id
    login = client.post("/api/auth/login", json={"username": "family-tree-private", "password": "private-password"})
    assert login.status_code == 200
    foreign_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    response = client.get(f"/api/people/{foreign_id}/family-tree", headers=auth)
    assert response.status_code == 404
    visible_to_owner = client.get(f"/api/people/{foreign_id}/family-tree", headers=foreign_headers)
    assert visible_to_owner.status_code == 200
    assert visible_to_owner.json()["people"][0]["first_name"] == "Privat"
