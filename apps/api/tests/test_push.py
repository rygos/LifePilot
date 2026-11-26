from datetime import datetime, timedelta, time, timezone
from uuid import uuid4

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from sqlalchemy import select
from sqlalchemy.orm import Session

from lifepilot.config import settings
from lifepilot.db import engine
from lifepilot.models import Commitment, PushSubscription, Reminder, Routine, RoutineStep, RoutineCompletion, Task, User
from lifepilot.push_keys import encode
from lifepilot.push_routes import endpoint_allowed
from lifepilot import push_worker
from lifepilot.security import hash_password


def enable(monkeypatch):
    key = ec.generate_private_key(ec.SECP256R1())
    private = encode(key.private_bytes(serialization.Encoding.DER, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    monkeypatch.setattr(settings, "push_vapid_private_key", private)
    monkeypatch.setattr(settings, "push_vapid_subject", "mailto:test@example.org")


def data():
    key = ec.generate_private_key(ec.SECP256R1()).public_key()
    return {"endpoint": "https://fcm.googleapis.com/fcm/send/" + uuid4().hex,
            "keys": {"p256dh": encode(key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)), "auth": encode(b"a"*16)}, "label": "Testgerät"}


def account(client):
    username = "push-" + uuid4().hex
    with Session(engine) as db:
        user = User(username=username, password_hash=hash_password("test-password"), timezone_name="UTC")
        db.add(user); db.commit(); owner = user.id
    token = client.post("/api/auth/login", json={"username": username, "password": "test-password"}).json()["access_token"]
    return owner, {"Authorization": "Bearer " + token}


def test_registration_security(client, auth, monkeypatch):
    monkeypatch.setattr(settings, "push_vapid_private_key", "")
    assert client.get("/api/push/status", headers=auth).json() == {"enabled": False, "public_key": None}
    assert client.post("/api/push/devices", headers=auth, json=data()).status_code == 503
    enable(monkeypatch)
    status = client.get("/api/push/status", headers=auth).json()
    assert status["enabled"] and len(status["public_key"]) == 87
    assert client.get("/api/push/status").status_code == 401
    payload = data()
    for endpoint in ["http://fcm.googleapis.com/x", "https://fcm.googleapis.com.evil.test/x", "https://127.0.0.1/x", "https://fcm.googleapis.com@localhost/x", "https://fcm.googleapis.com:444/x", "https://fcm.googleapis.com/x#fragment"]:
        assert not endpoint_allowed(endpoint)
        assert client.post("/api/push/devices", headers=auth, json={**payload, "endpoint": endpoint}).status_code == 422
    assert endpoint_allowed("https://web.push.apple.com/Q")
    assert endpoint_allowed("https://updates.push.services.mozilla.com/wpush/v2/Q")
    assert client.post("/api/push/devices", headers=auth, json={**payload, "keys":{"p256dh": "invalid", "auth": "bad"}}).status_code == 422
    response = client.post("/api/push/devices", headers=auth, json=payload)
    assert response.status_code == 201, response.text
    row = response.json()
    assert row["active"] and "endpoint" not in row and "keys" not in row
    assert client.post("/api/push/devices", headers=auth, json=payload).json()["id"] == row["id"]
    owner, other = account(client)
    assert client.get("/api/push/devices", headers=other).json() == []
    assert client.post("/api/push/devices", headers=other, json=payload).status_code == 409
    assert client.delete("/api/push/devices/"+row["id"], headers=other).status_code == 404
    assert client.delete("/api/push/devices/"+row["id"], headers=auth).status_code == 204


def test_delivery_quiet_hours_snooze_and_retry(client, monkeypatch):
    enable(monkeypatch)
    owner_id, auth = account(client)
    one = client.post("/api/push/devices", headers=auth, json=data()).json()["id"]
    two = client.post("/api/push/devices", headers=auth, json=data()).json()["id"]
    now = datetime.now(timezone.utc).replace(hour=9, minute=0, second=0, microsecond=0) + timedelta(days=1)
    calls = []
    result = {one: 201, two: 503}
    def send(device):
        calls.append(device.id)
        return result[device.id]
    monkeypatch.setattr(push_worker, "send_push", send)
    with Session(engine) as db:
        owner = db.get(User, owner_id)
        owner.quiet_hours_start = time(8)
        owner.quiet_hours_end = time(10)
        reminder = Reminder(owner_id=owner_id, title="Private Erinnerung", due_at=now - timedelta(minutes=10))
        db.add(reminder)
        db.commit()
        rid = reminder.id
        assert push_worker.dispatch_due_push(db, now) == 0
        assert calls == []
        now = now.replace(hour=10)
        assert push_worker.dispatch_due_push(db, now) == 1
        assert set(calls) == {one, two}
        assert db.get(PushSubscription, one).last_sent_at is not None
        assert db.get(PushSubscription, two).failure_count == 1
        result[two] = 201
        assert push_worker.dispatch_due_push(db, now + timedelta(minutes=1)) == 0
        assert push_worker.dispatch_due_push(db, now + timedelta(minutes=2)) == 1
        assert calls.count(one) == 1 and calls.count(two) == 2
        # A snooze hides the reminder until the new deadline; it can then notify again.
        db.get(Reminder, rid).snoozed_until = now + timedelta(minutes=5)
        db.commit()
        assert push_worker.dispatch_due_push(db, now + timedelta(minutes=3)) == 0
        assert push_worker.dispatch_due_push(db, now + timedelta(minutes=5)) == 2
        db.get(Reminder, rid).state = "done"
        db.add(Commitment(owner_id=owner_id, title="Private Zusage", direction="outgoing", due_at=now))
        db.commit()
        result[two] = 410
        assert push_worker.dispatch_due_push(db, now + timedelta(minutes=6)) == 1
        assert db.get(PushSubscription, two) is None
        owner = db.get(User, owner_id)
        owner.token_version += 1
        db.commit()
        db.add(Reminder(owner_id=owner_id, title="Neue Erinnerung", due_at=now))
        db.commit()
        assert push_worker.dispatch_due_push(db, now + timedelta(minutes=7)) == 0
        assert db.get(PushSubscription, one).last_sent_at is not None
    assert "Private" not in str(push_worker.PAYLOAD)


def test_due_routines_and_completed_tasks(client):
    owner_id, _ = account(client)
    now = datetime(2027, 1, 4, 7, 30, tzinfo=timezone.utc)
    with Session(engine) as db:
        owner = db.get(User, owner_id)
        routine = Routine(owner_id=owner_id, title="Morgenroutine", weekdays=[0], window_start=time(7), window_end=time(8))
        task = Task(owner_id=owner_id, title="Fertig", status="done")
        db.add_all([routine, task]); db.flush()
        step = RoutineStep(routine_id=routine.id, title="Schritt", position=1)
        db.add_all([step, Reminder(owner_id=owner_id, title="Fertig", due_at=now, task_id=task.id)])
        db.commit()
        assert push_worker.due_keys(db, owner, now) == {f"routine:{routine.id}:2027-01-04"}
        assert push_worker.due_keys(db, owner, now.replace(hour=9)) == set()
        db.add(RoutineCompletion(step_id=step.id, local_date=now.date()))
        db.commit()
        assert push_worker.due_keys(db, owner, now) == set()
