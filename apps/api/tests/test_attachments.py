from io import BytesIO
from pathlib import Path
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

from sqlalchemy.orm import Session

from lifepilot.config import settings
from lifepilot.db import engine
from lifepilot.models import Attachment, User
from lifepilot.security import create_token


def test_attachment_download_is_private_and_parent_delete_removes_file(client, auth, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    memory = client.post("/api/memories", headers=auth, json={"title": "Anhangstest", "content": "Originalnotiz"}).json()

    uploaded = client.post(
        "/api/attachments",
        headers=auth,
        data={"resource_type": "memory", "resource_id": memory["id"]},
        files={"file": ("../../vertraulich.txt", b"private LifePilot document", "text/plain")},
    )
    assert uploaded.status_code == 201
    attachment = uploaded.json()
    assert attachment["file_name"] == "vertraulich.txt"
    assert attachment["size_bytes"] == len(b"private LifePilot document")
    with Session(engine) as db:
        owner_id = db.query(User).filter_by(username="testuser").one().id
    stored_files = list((Path(settings.data_dir) / "attachments" / owner_id).iterdir())
    assert len(stored_files) == 1
    stored_path = stored_files[0]
    assert stored_path.read_bytes() == b"private LifePilot document"

    listed = client.get("/api/attachments", headers=auth, params={"resource_type": "memory", "resource_id": memory["id"]})
    assert listed.status_code == 200 and listed.json()[0]["id"] == attachment["id"]
    downloaded = client.get(f"/api/attachments/{attachment['id']}/download", headers=auth)
    assert downloaded.status_code == 200
    assert downloaded.content == b"private LifePilot document"
    assert downloaded.headers["content-disposition"].startswith("attachment;")
    assert downloaded.headers["x-content-type-options"] == "nosniff"

    with Session(engine) as db:
        other_user = User(username=f"attachment-owner-{uuid4()}", password_hash="unused")
        db.add(other_user)
        db.commit()
        other_token = create_token(other_user.id)
    other_headers = {"Authorization": f"Bearer {other_token}"}
    assert client.get("/api/attachments", headers=other_headers, params={"resource_type": "memory", "resource_id": memory["id"]}).status_code == 404
    assert client.get(f"/api/attachments/{attachment['id']}/download", headers=other_headers).status_code == 404

    deleted = client.delete(f"/api/memories/{memory['id']}", headers=auth)
    assert deleted.status_code == 204
    assert not stored_path.exists()
    with Session(engine) as db:
        assert db.get(Attachment, attachment["id"]) is None


def test_attachment_upload_rejects_unlisted_file_types(client, auth):
    person = client.post("/api/people", headers=auth, json={"first_name": "Upload", "last_name": "Test"}).json()
    response = client.post(
        "/api/attachments",
        headers=auth,
        data={"resource_type": "person", "resource_id": person["id"]},
        files={"file": ("payload.html", b"<script>bad()</script>", "text/html")},
    )
    assert response.status_code == 415
    assert response.json()["detail"] == "Dieser Dateityp wird nicht unterstützt"


def test_attachment_upload_accepts_open_document_and_ooxml_container_signatures(client, auth, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    person = client.post("/api/people", headers=auth, json={"first_name": "Dokument", "last_name": "Test"}).json()
    for filename, required_member in (("sitzung.docx", "[Content_Types].xml"), ("protokoll.odt", "mimetype")):
        package = BytesIO()
        with ZipFile(package, "w", ZIP_DEFLATED) as archive:
            archive.writestr(required_member, "application/test-document")
        response = client.post(
            "/api/attachments",
            headers=auth,
            data={"resource_type": "person", "resource_id": person["id"]},
            files={"file": (filename, package.getvalue(), "application/zip")},
        )
        assert response.status_code == 201
