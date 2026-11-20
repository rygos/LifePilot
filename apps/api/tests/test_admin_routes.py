from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from lifepilot.config import settings
from lifepilot.db import engine
from lifepilot.models import User
from lifepilot.security import hash_password


def create_user(client: TestClient, role: str) -> tuple[str, dict[str, str]]:
    username = f"admin-test-{uuid4().hex}"
    with Session(engine) as db:
        user = User(username=username, password_hash=hash_password("test-password-for-admin"), role=role)
        db.add(user)
        db.commit()
        user_id = user.id
    login = client.post("/api/auth/login", json={"username": username, "password": "test-password-for-admin"})
    assert login.status_code == 200
    return user_id, {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_non_admin_cannot_list_or_change_roles(client: TestClient) -> None:
    _, user_headers = create_user(client, "user")
    target_id, _ = create_user(client, "user")

    assert client.get("/api/admin/users", headers=user_headers).status_code == 403
    denied = client.patch(f"/api/admin/users/{target_id}/role", headers=user_headers, json={"role": "admin"})
    assert denied.status_code == 403


def test_admin_can_promote_user_without_removing_last_admin(client: TestClient) -> None:
    admin_id, admin_headers = create_user(client, "admin")
    target_id, target_headers = create_user(client, "user")

    promoted = client.patch(f"/api/admin/users/{target_id}/role", headers=admin_headers, json={"role": "admin"})
    assert promoted.status_code == 200
    assert promoted.json()["role"] == "admin"
    assert "password_hash" not in promoted.json()

    demoted = client.patch(f"/api/admin/users/{admin_id}/role", headers=admin_headers, json={"role": "user"})
    assert demoted.status_code == 200
    last_admin = client.patch(f"/api/admin/users/{target_id}/role", headers=target_headers, json={"role": "user"})
    assert last_admin.status_code == 409
    assert last_admin.json()["detail"] == "Mindestens ein Administrator muss bestehen bleiben"


def test_app_update_is_admin_only_and_invokes_configured_webhook(client: TestClient, monkeypatch) -> None:
    _, admin_headers = create_user(client, "admin")
    _, user_headers = create_user(client, "user")
    previous_url = settings.portainer_webhook_url

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            self.send_response(204)
            self.end_headers()

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        assert client.post("/api/admin/app-update").status_code == 401
        assert client.post("/api/admin/app-update", headers=user_headers).status_code == 403
        monkeypatch.setattr(settings, "portainer_webhook_url", "")
        assert client.post("/api/admin/app-update", headers=admin_headers).status_code == 503
        monkeypatch.setattr(settings, "portainer_webhook_url", f"http://127.0.0.1:{server.server_port}/webhook")
        response = client.post("/api/admin/app-update", headers=admin_headers)
        assert response.status_code == 202
        assert response.json()["status"] == "triggered"
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()
        monkeypatch.setattr(settings, "portainer_webhook_url", previous_url)
