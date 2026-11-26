from datetime import datetime, timedelta, time, timezone
from uuid import uuid4

from sqlalchemy.orm import Session
from lifepilot.config import settings
from lifepilot.db import engine
from lifepilot.models import User, Reminder, Commitment, Routine, RoutineStep, RoutineCompletion, FocusSession, Task, CaptureKey
from lifepilot.security import hash_password
from lifepilot import home_assistant_routes, routine_routes, shortcut_routes


def account(client):
    username = "ha-" + uuid4().hex
    with Session(engine) as db:
        row = User(username=username, password_hash=hash_password("test-password"), timezone_name="UTC")
        db.add(row)
        db.commit()
        owner = row.id
    token = client.post("/api/auth/login", json={"username":username,"password":"test-password"}).json()["access_token"]
    return owner, {"Authorization":"Bearer "+token}


def key(client, auth, scope):
    response = client.post("/api/shortcuts/keys", headers=auth, json={"label":"HA test","scope":scope,"current_password":"test-password"})
    assert response.status_code == 201, response.text
    result = response.json()
    assert result["scope"] == scope
    return result, {"Authorization":"Bearer "+result["token"]}


def test_status_is_aggregate_scoped_and_respects_quiet_hours(client, monkeypatch):
    owner, auth = account(client)
    other, other_auth = account(client)
    status_key, status = key(client, auth, "ha:status")
    _, capture = key(client, auth, "capture:write")
    _, foreign_status = key(client, other_auth, "ha:status")
    path = "/api/home-assistant/status"
    now = datetime(2027, 1, 4, 10, 0, tzinfo=timezone.utc)

    class FixedTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return now if tz is not None else now.replace(tzinfo=None)

    monkeypatch.setattr(home_assistant_routes, "datetime", FixedTime)
    monkeypatch.setattr(routine_routes, "local_now", lambda user: now)
    monkeypatch.setattr(settings, "llm_base_url", "")
    with Session(engine) as db:
        routine = Routine(owner_id=owner,title="Private routine",weekdays=[0],window_start=time(9),window_end=time(11))
        task = Task(owner_id=owner,title="Private task")
        db.add_all([routine, task])
        db.flush()
        step = RoutineStep(routine_id=routine.id,title="Private step",position=1)
        db.add_all([
            step,
            Reminder(owner_id=owner,title="Private reminder",due_at=now-timedelta(minutes=1)),
            Reminder(owner_id=owner,title="Later",due_at=now+timedelta(hours=1)),
            Reminder(owner_id=owner,title="Snoozed",due_at=now-timedelta(hours=1),snoozed_until=now+timedelta(hours=1)),
            Commitment(owner_id=owner,title="Private commitment",direction="incoming",due_at=now),
            FocusSession(owner_id=owner,task_id=task.id,task_title=task.title,planned_minutes=25,started_at=now),
            Reminder(owner_id=other,title="Foreign",due_at=now),
        ])
        db.commit()
        step_id = step.id
    assert client.get(path).status_code == 401
    assert client.get(path,headers=auth).status_code == 401
    assert client.get(path,headers=capture).status_code == 401
    assert client.post("/api/shortcuts/capture",headers=status,json={"original_text":"No"}).status_code == 401
    for url in ["/api/people","/api/captures","/api/routines","/api/shortcuts/keys","/api/briefing/daily"]:
        assert client.get(url,headers=status).status_code == 401
    r = client.get(path,headers=status)
    assert r.status_code == 200, r.text
    assert r.headers["cache-control"] == "no-store"
    assert r.json() == {"notification_pending":True,"quiet_hours":False,"due_reminders":1,"due_commitments":1,"due_routines":1,"routine_steps_open":1,"focus_active":True}
    assert "Private" not in r.text and owner not in r.text
    assert client.get(path,headers=foreign_status).json()["due_reminders"] == 1
    assert client.get(path,headers=foreign_status).json()["due_commitments"] == 0
    with Session(engine) as db:
        row = db.get(User,owner)
        row.quiet_hours_start = time(9)
        row.quiet_hours_end = time(11)
        db.add(RoutineCompletion(step_id=step_id,local_date=now.date()))
        db.commit()
    quiet = client.get(path,headers=status).json()
    assert quiet["quiet_hours"] and not quiet["notification_pending"]
    assert quiet["due_routines"] == 0 and quiet["routine_steps_open"] == 0
    payload = {"original_text":"Manuell ausgewähltes HA-Ereignis","client_request_id":str(uuid4())}
    first = client.post("/api/shortcuts/capture",headers=capture,json=payload)
    assert first.status_code == 201,first.text
    assert client.post("/api/shortcuts/capture",headers=capture,json=payload).json() == first.json()
    assert client.delete("/api/shortcuts/keys/"+status_key["id"],headers=other_auth).status_code == 404
    assert client.delete("/api/shortcuts/keys/"+status_key["id"],headers=auth).status_code == 204
    assert client.get(path,headers=status).status_code == 401


def test_status_key_rate_limit_and_password_version(client, monkeypatch):
    owner, auth = account(client)
    issued, status = key(client,auth,"ha:status")
    assert issued["token"].startswith("lp_status_")
    monkeypatch.setattr(shortcut_routes,"STATUS_REQUESTS_PER_HOUR",1)
    path="/api/home-assistant/status"
    assert client.get(path,headers=status).status_code == 200
    limited = client.get(path,headers=status)
    assert limited.status_code == 429 and int(limited.headers["retry-after"]) > 0
    with Session(engine) as db:
        db.get(CaptureKey,issued["id"]).window_started_at = datetime.now(timezone.utc)-timedelta(hours=2)
        db.commit()
    assert client.get(path,headers=status).status_code == 200
    assert client.post("/api/auth/password",headers=auth,json={"current_password":"test-password","new_password":"new-test-password-123"}).status_code == 200
    assert client.get(path,headers=status).status_code == 401
