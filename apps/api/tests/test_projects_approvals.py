def test_projects_and_approval_decisions_are_owner_scoped(client, auth):
    from lifepilot.security import create_token

    created = client.post("/api/projects", headers=auth, json={"name": "Haus renovieren", "description": "Küche zuerst"})
    assert created.status_code == 201
    project_id = created.json()["id"]
    assert client.get(f"/api/projects/{project_id}", headers=auth).json()["id"] == project_id
    assert client.get("/api/projects?q=Küche", headers=auth).json()[0]["id"] == project_id
    changed = client.patch(f"/api/projects/{project_id}", headers=auth, json={"status": "paused"})
    assert changed.status_code == 200 and changed.json()["status"] == "paused"

    from sqlalchemy.orm import Session
    from lifepilot.db import engine
    from lifepilot.models import ApprovalRequest, User
    from lifepilot.security import hash_password

    with Session(engine) as db:
        second = User(username="approval-private-user", password_hash=hash_password("unused"))
        db.add(second)
        db.flush()
        approval = ApprovalRequest(owner_id=second.id, operation="project_delete", resource_id=project_id)
        db.add(approval)
        db.commit()
        approval_id = approval.id
        second_token = create_token(second.id)

    foreign_headers = {"Authorization": f"Bearer {second_token}"}
    assert client.get("/api/projects", headers=foreign_headers).json() == []
    assert client.get(f"/api/projects/{project_id}", headers=foreign_headers).status_code == 404
    assert client.get("/api/approvals", headers=auth).json() == []
    assert client.post(f"/api/approvals/{approval_id}/approve", headers=auth).status_code == 404
    assert client.post(f"/api/approvals/{approval_id}/reject", headers=foreign_headers).status_code == 200
    assert client.get(f"/api/projects?q=Haus", headers=auth).json()[0]["id"] == project_id
