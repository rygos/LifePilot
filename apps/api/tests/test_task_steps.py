import json
from uuid import uuid4

from sqlalchemy.orm import Session

from lifepilot.config import settings
from lifepilot.db import engine
from lifepilot.models import User
from lifepilot.security import hash_password


def test_steps_preview_and_confirmation(client, auth, monkeypatch):
    from lifepilot import task_steps
    task = client.post("/api/tasks", headers=auth, json={"title": "Unterlagen vorbereiten"}).json()
    path = f"/api/tasks/{task['id']}/steps"
    monkeypatch.setattr(settings, "llm_base_url", "")
    assert client.post(path + "/draft", headers=auth).status_code == 503
    monkeypatch.setattr(settings, "llm_base_url", "http://model.invalid")
    monkeypatch.setattr(settings, "llm_model", "test")
    content = {"steps": [{"title": "Ordner öffnen", "estimated_minutes": 2}, {"title": "Dateien prüfen", "estimated_minutes": 5}]}

    class Response:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def read(self, size):
            return json.dumps({"choices": [{"message": {"content": json.dumps(content)}}]}).encode()

    monkeypatch.setattr(task_steps, "urlopen", lambda *args, **kwargs: Response())
    draft = client.post(path + "/draft", headers=auth)
    assert draft.status_code == 200, draft.text
    assert client.get(path, headers=auth).json() == []
    accepted = client.post(path, headers=auth, json=draft.json())
    assert accepted.status_code == 201, accepted.text
    steps = accepted.json()
    assert [s["position"] for s in steps] == [1, 2]
    assert client.post(path, headers=auth, json=draft.json()).status_code == 409
    assert client.post(path, headers=auth, json={"steps": [{"title": " ", "estimated_minutes": 5}]}).status_code == 422
    assert client.patch(path + "/" + steps[0]["id"], headers=auth, json={"completed": True}).json()["completed_at"]
    assert client.patch(path + "/" + steps[0]["id"], headers=auth, json={"completed": False}).json()["completed_at"] is None
    content["steps"][0]["estimated_minutes"] = 999
    assert client.post(path + "/draft", headers=auth).status_code == 502

    username = "steps-" + uuid4().hex
    with Session(engine) as db:
        db.add(User(username=username, password_hash=hash_password("test-password")))
        db.commit()
    token = client.post("/api/auth/login", json={"username": username, "password": "test-password"}).json()["access_token"]
    other = {"Authorization": "Bearer " + token}
    assert client.get(path, headers=other).status_code == 404
    assert client.post(path + "/draft", headers=other).status_code == 404
    assert client.post(path, headers=other, json=draft.json()).status_code == 404
    assert client.patch(path + "/" + steps[0]["id"], headers=other, json={"completed": True}).status_code == 404
    assert client.patch(f"/api/tasks/{task['id']}/complete", headers=auth).status_code == 200
    assert client.post(path, headers=auth, json={"steps": [{"title": "Neu"}]}).status_code == 409
