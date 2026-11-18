from io import BytesIO

from PIL import Image
from sqlalchemy.orm import Session
from uuid import uuid4

from lifepilot.config import settings
from lifepilot.db import engine
from lifepilot.models import User
from lifepilot.security import hash_password


def _jpeg() -> bytes:
    output = BytesIO()
    Image.new("RGB", (12, 8), color="green").save(output, format="JPEG")
    return output.getvalue()


def _second_user(client) -> dict[str, str]:
    username = f"other-{uuid4().hex[:10]}"
    with Session(engine) as db:
        db.add(User(username=username, password_hash=hash_password("another-password")))
        db.commit()
    response = client.post("/api/auth/login", json={"username": username, "password": "another-password"})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_person_photo_upload_is_persisted_and_owner_scoped(client, auth, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    person = client.post("/api/people", json={"first_name": "Foto", "last_name": "Person", "birthday": "1990-01-01"}, headers=auth).json()

    uploaded = client.post(f"/api/people/{person['id']}/photo", files={"file": ("avatar.png", _jpeg(), "image/png")}, headers=auth)
    assert uploaded.status_code == 200
    assert uploaded.json()["photo_key"].endswith(".jpg")

    photo = client.get(f"/api/people/{person['id']}/photo", headers=auth)
    assert photo.status_code == 200
    assert photo.headers["content-type"] == "image/jpeg"
    assert photo.content.startswith(b"\xff\xd8")

    other_auth = _second_user(client)
    assert client.get(f"/api/people/{person['id']}/photo", headers=other_auth).status_code == 404
    assert client.post(f"/api/people/{person['id']}/photo", files={"file": ("fake.jpg", b"not an image", "image/jpeg")}, headers=auth).status_code == 415


def test_club_memberships_include_self_and_are_owner_scoped(client, auth):
    self_profile = client.get("/api/profile", headers=auth).json()["self_person_id"]
    contact = client.post("/api/people", json={"first_name": "Vereins", "last_name": "Freund"}, headers=auth).json()
    organization = client.post("/api/organizations", json={"name": "Turnverein Beispiel", "organization_type": "club"}, headers=auth)
    assert organization.status_code == 201

    for person_id, role in ((self_profile, "Vorstand"), (contact["id"], "Trainer")):
        membership = client.post(f"/api/people/{person_id}/organizations", json={"organization_id": organization.json()["id"], "role": role}, headers=auth)
        assert membership.status_code == 201

    person_memberships = client.get(f"/api/people/{self_profile}/organizations", headers=auth)
    assert person_memberships.status_code == 200
    assert person_memberships.json()[0]["role"] == "Vorstand"
    organization_members = client.get("/api/organizations", headers=auth).json()[0]["members"]
    assert {member["person_id"] for member in organization_members} == {self_profile, contact["id"]}

    other_auth = _second_user(client)
    assert client.post(f"/api/people/{self_profile}/organizations", json={"organization_id": organization.json()["id"]}, headers=other_auth).status_code == 404
    assert client.get("/api/organizations", headers=other_auth).json() == []


def test_person_photo_delete_removes_reference(client, auth, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    person = client.post("/api/people", json={"first_name": "Löschen"}, headers=auth).json()
    upload = client.post(f"/api/people/{person['id']}/photo", files={"file": ("avatar.jpg", _jpeg(), "image/jpeg")}, headers=auth)
    assert upload.status_code == 200
    removed = client.delete(f"/api/people/{person['id']}/photo", headers=auth)
    assert removed.status_code == 200
    assert removed.json()["photo_key"] is None
    assert client.get(f"/api/people/{person['id']}/photo", headers=auth).status_code == 404
