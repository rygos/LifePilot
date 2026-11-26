from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from lifepilot import admin_routes, update_state
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


def test_admin_can_soft_delete_restore_and_permanently_delete_user(client: TestClient) -> None:
    admin_id, admin_headers = create_user(client, "admin")
    target_id, target_headers = create_user(client, "user")

    assert client.delete(f"/api/admin/users/{admin_id}", headers=admin_headers).status_code == 409
    assert client.delete(f"/api/admin/users/{target_id}").status_code == 401
    assert client.delete(f"/api/admin/users/{target_id}", headers=target_headers).status_code == 403

    deleted = client.delete(f"/api/admin/users/{target_id}", headers=admin_headers)
    assert deleted.status_code == 200
    assert deleted.json()["deleted_at"] is not None
    assert client.get("/api/auth/me", headers=target_headers).status_code == 401
    users = client.get("/api/admin/users", headers=admin_headers).json()
    deleted_user = next(user for user in users if user["id"] == target_id)
    assert deleted_user["deleted_at"]
    assert client.post("/api/auth/login", json={"username": deleted_user["username"], "password": "test-password-for-admin"}).status_code == 401

    restored = client.post(f"/api/admin/users/{target_id}/restore", headers=admin_headers)
    assert restored.status_code == 200
    assert restored.json()["deleted_at"] is None
    assert client.get("/api/auth/me", headers=target_headers).status_code == 401
    fresh = client.post("/api/auth/login", json={"username": deleted_user["username"], "password":"test-password-for-admin"})
    assert fresh.status_code == 200
    assert client.get("/api/auth/me",headers={"Authorization":"Bearer "+fresh.json()["access_token"]}).status_code == 200

    deleted_again = client.delete(f"/api/admin/users/{target_id}", headers=admin_headers)
    assert deleted_again.status_code == 200
    permanent = client.delete(f"/api/admin/users/{target_id}/permanent", headers=admin_headers)
    assert permanent.status_code == 204
    assert all(user["id"] != target_id for user in client.get("/api/admin/users", headers=admin_headers).json())


def test_soft_delete_cannot_remove_last_active_admin(client: TestClient) -> None:
    admin_id, admin_headers = create_user(client, "admin")
    other_admin_id, _ = create_user(client, "admin")
    assert client.delete(f"/api/admin/users/{other_admin_id}", headers=admin_headers).status_code == 200
    assert client.delete(f"/api/admin/users/{admin_id}", headers=admin_headers).status_code == 409


def test_app_update_is_admin_only_and_invokes_configured_webhook(client: TestClient, monkeypatch, tmp_path: Path) -> None:
    import json

    _, admin_headers = create_user(client, "admin")
    _, user_headers = create_user(client, "user")
    previous_url = settings.portainer_webhook_url

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            payload = {"sha": "c" * 40, "commit": {"message": "LifePilot-Update", "author": {"date": "2026-11-20T12:00:00Z"}}}
            body = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

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
        monkeypatch.setattr(admin_routes, "GITHUB_BRANCH_URL", f"http://127.0.0.1:{server.server_port}/commits/main")
        monkeypatch.setattr(settings, "data_dir", str(tmp_path))
        monkeypatch.setattr(update_state, "image_commit_sha", lambda: "b" * 40)
        response = client.post("/api/admin/app-update", headers=admin_headers)
        assert response.status_code == 202
        assert response.json()["status"] == "triggered"
        assert response.json()["target_commit"] == "c" * 12
        assert update_state.read_update_state().pending_commit == "c" * 40
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()
        monkeypatch.setattr(settings, "portainer_webhook_url", previous_url)


def test_app_update_status_reports_commit_messages_for_admin(client: TestClient, monkeypatch) -> None:
    _, admin_headers = create_user(client, "admin")
    _, user_headers = create_user(client, "user")
    monkeypatch.setattr(admin_routes, "current_commit_sha", lambda: "a" * 40)
    monkeypatch.setattr(admin_routes, "compare_github_commits", lambda _: admin_routes.GitUpdateComparison(
        available=True,
        update_available=True,
        ahead_by=2,
        latest_commit="b" * 12,
        commits=[admin_routes.UpdateCommit(sha="b" * 12, message="Neue mobile Navigation", date=None)],
    ))

    assert client.get("/api/admin/app-update").status_code == 401
    assert client.get("/api/admin/app-update", headers=user_headers).status_code == 403
    response = client.get("/api/admin/app-update", headers=admin_headers)

    assert response.status_code == 200
    assert response.json()["current_commit"] == "a" * 12
    assert response.json()["update_available"] is True
    assert response.json()["pending_update"] is False
    assert response.json()["monitor_configured"] is False
    assert response.json()["containers"] == []
    assert response.json()["commits"][0]["message"] == "Neue mobile Navigation"


def test_github_comparison_parses_newest_commit_subjects() -> None:
    import json

    from lifepilot import admin_routes

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path.endswith("/commits/main"):
                payload = {"sha": "c" * 40, "commit": {"message": "Letzter Stand", "author": {"date": "2026-11-20T12:00:00Z"}}}
            else:
                payload = {
                    "ahead_by": 2,
                    "commits": [
                        {"sha": "a" * 40, "commit": {"message": "Mobile Navigation\n\nWeitere Details", "author": {"date": "2026-11-20T10:00:00Z"}}},
                        {"sha": "b" * 40, "commit": {"message": "Git-Updates anzeigen", "author": {"date": "2026-11-20T11:00:00Z"}}},
                    ],
                }
            body = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    branch_url = admin_routes.GITHUB_BRANCH_URL
    compare_url = admin_routes.GITHUB_COMPARE_URL
    try:
        base_url = f"http://127.0.0.1:{server.server_port}/repos/rygos/LifePilot"
        admin_routes.GITHUB_BRANCH_URL = f"{base_url}/commits/main"
        admin_routes.GITHUB_COMPARE_URL = f"{base_url}/compare/{{base}}...main"

        comparison = admin_routes.compare_github_commits("d" * 40)

        assert comparison.available is True
        assert comparison.update_available is True
        assert comparison.ahead_by == 2
        assert comparison.latest_commit == "c" * 12
        assert [(commit.sha, commit.message) for commit in comparison.commits] == [
            ("a" * 12, "Mobile Navigation"),
            ("b" * 12, "Git-Updates anzeigen"),
        ]
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()
        admin_routes.GITHUB_BRANCH_URL = branch_url
        admin_routes.GITHUB_COMPARE_URL = compare_url
