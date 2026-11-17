import os
import pytest
from lifepilot.db import engine
from lifepilot.models import Gift, Loan, Memory, Person, Task, User
from lifepilot.security import hash_password
from sqlalchemy.orm import Session

def test_auth_people_memories_tasks_search_and_persistence(client, auth):
    assert client.get("/api/people").status_code == 401
    person = client.post("/api/people", headers=auth, json={"first_name": "Martin", "birthday": "1988-04-02", "notes": "Karnevalsverein"})
    assert person.status_code == 201
    person_id = person.json()["id"]
    memory = client.post("/api/memories", headers=auth, json={"title": "Bohrmaschine", "content": "Martin hat mir seine Bohrmaschine geliehen.", "person_id": person_id, "occurred_at": "2026-11-16T10:00:00Z"})
    assert memory.status_code == 201
    assert memory.json()["occurred_at"].startswith("2026-11-16")
    task = client.post("/api/tasks", headers=auth, json={"title": "Martin zurückrufen", "person_id": person_id})
    assert task.status_code == 201
    assert client.get("/api/search?q=Bohrmaschine", headers=auth).json()["memories"][0]["id"] == memory.json()["id"]
    assert any(person["id"] == person_id for person in client.get("/api/people", headers=auth).json())
    assert client.patch(f"/api/tasks/{task.json()['id']}/complete", headers=auth).json()["status"] == "done"

def test_relationship_validation_and_cross_user_isolation(client, auth):
    first = client.post("/api/people", headers=auth, json={"first_name": "Martin"}).json()
    second = client.post("/api/people", headers=auth, json={"first_name": "Lea"}).json()
    relation = client.post("/api/relationships", headers=auth, json={"source_person_id": first["id"], "target_person_id": second["id"], "relationship_type": "Elternteil"})
    assert relation.status_code == 201
    assert relation.json()["source_person_id"] == first["id"]
    assert client.post("/api/relationships", headers=auth, json={"source_person_id": first["id"], "target_person_id": first["id"], "relationship_type": "kennt"}).status_code == 422
    other_token = client.post("/api/auth/login", json={"username": "other", "password": "other-password"})
    assert other_token.status_code == 401
    assert client.get(f"/api/people/{first['id']}", headers={"Authorization": "Bearer invalid"}).status_code == 401

def test_relationships_and_profile_fields_are_readable_and_editable(client, auth):
    martin = client.post("/api/people", headers=auth, json={"first_name": "Martin", "nickname": "Marty", "address": "Hauptstraße 4", "website": "https://example.org", "job_title": "Gärtner", "organization": "Verein"}).json()
    lea = client.post("/api/people", headers=auth, json={"first_name": "Lea"}).json()
    relation = client.post("/api/relationships", headers=auth, json={"source_person_id": martin["id"], "target_person_id": lea["id"], "relationship_type": "Vater von", "inverse_relationship_type": "Tochter von"})
    assert relation.status_code == 201
    visible = client.get(f"/api/relationships?person_id={lea['id']}", headers=auth).json()
    assert visible[0]["source_person_name"] == "Martin"
    assert visible[0]["target_person_name"] == "Lea"
    assert visible[0]["inverse_relationship_type"] == "Tochter von"
    duplicate = client.post("/api/relationships", headers=auth, json={"source_person_id": lea["id"], "target_person_id": martin["id"], "relationship_type": "Tochter von", "inverse_relationship_type": "Vater von"})
    assert duplicate.status_code == 409
    assert client.get(f"/api/people/{martin['id']}", headers=auth).json()["address"] == "Hauptstraße 4"
    profile = client.patch("/api/profile", headers=auth, json={"full_name": "Alex Beispiel", "nickname": "Alex", "address": "Parkweg 1", "email": "alex@example.org"})
    assert profile.status_code == 200
    assert client.get("/api/profile", headers=auth).json()["full_name"] == "Alex Beispiel"
    assert client.delete(f"/api/relationships/{relation.json()['id']}", headers=auth).status_code == 204
    assert client.get(f"/api/relationships?person_id={lea['id']}", headers=auth).json() == []

def test_owner_relationships_can_be_managed_without_ai_and_stay_private(client, auth):
    person = client.post("/api/people", headers=auth, json={"first_name": "Kristin", "last_name": "OwnerRelation"}).json()
    created = client.post(f"/api/people/{person['id']}/owner-relationships", headers=auth, json={"relationship_type": "Arbeitskollegin", "valid_from": "2026-01-01T00:00:00Z"})
    assert created.status_code == 201
    assert created.json()["relationship_type"] == "Arbeitskollegin"
    briefing = client.get(f"/api/briefing/person/{person['id']}", headers=auth)
    assert briefing.json()["owner_relationships"][0]["id"] == created.json()["id"]
    assert briefing.json()["owner_relationships"][0]["valid_from"].startswith("2026-01-01")
    duplicate = client.post(f"/api/people/{person['id']}/owner-relationships", headers=auth, json={"relationship_type": "Arbeitskollegin"})
    assert duplicate.status_code == 201 and duplicate.json()["id"] == created.json()["id"]
    assert duplicate.json()["valid_from"].startswith("2026-01-01")
    assert client.post(f"/api/people/{person['id']}/owner-relationships", headers=auth, json={"relationship_type": "Kollegin", "valid_from": "2026-02-01T00:00:00Z", "valid_until": "2026-01-01T00:00:00Z"}).status_code == 422

    other_user = User(username="owner-relationship-other", password_hash=hash_password("relationship-password"))
    with Session(engine) as db:
        db.add(other_user)
        db.commit()
    other_token = client.post("/api/auth/login", json={"username": "owner-relationship-other", "password": "relationship-password"}).json()["access_token"]
    other_auth = {"Authorization": f"Bearer {other_token}"}
    assert client.post(f"/api/people/{person['id']}/owner-relationships", headers=other_auth, json={"relationship_type": "Kollegin"}).status_code == 404
    assert client.delete(f"/api/owner-relationships/{created.json()['id']}", headers=other_auth).status_code == 404
    assert client.delete(f"/api/owner-relationships/{created.json()['id']}", headers=auth).status_code == 204
    assert client.get(f"/api/briefing/person/{person['id']}", headers=auth).json()["owner_relationships"] == []

def test_conversations_loans_gifts_and_owner_boundaries(client, auth):
    martin = client.post("/api/people", headers=auth, json={"first_name": "Martin"}).json()
    lea = client.post("/api/people", headers=auth, json={"first_name": "Lea"}).json()
    note = client.post("/api/memories", headers=auth, json={"title": "Wunsch", "content": "Anna mag Bücher", "person_id": martin["id"]}).json()
    conversation = client.post("/api/conversations", headers=auth, json={"title": "Treffen im Verein", "original_note": "Martin erzählte von Lea.", "participant_ids": [martin["id"], lea["id"]], "occurred_at": "2026-11-16T18:00:00Z", "location": "Vereinsheim"})
    assert conversation.status_code == 201
    assert conversation.json()["original_note"] == "Martin erzählte von Lea."
    assert set(client.get(f"/api/conversations?person_id={lea['id']}", headers=auth).json()[0]["participant_ids"]) == {martin["id"], lea["id"]}
    assert client.get("/api/search?q=Vereinsheim", headers=auth).json()["conversations"][0]["id"] == conversation.json()["id"]
    assert client.post("/api/conversations", headers=auth, json={"title": "Fremd", "original_note": "x", "participant_ids": ["foreign-id"]}).status_code == 404
    loan = client.post("/api/loans", headers=auth, json={"item_name": "Bohrmaschine", "lender_person_id": martin["id"], "borrower_person_id": lea["id"], "source_memory_id": note["id"]})
    assert loan.status_code == 201
    assert len(client.get("/api/loans", headers=auth).json()) == 1
    assert client.patch(f"/api/loans/{loan.json()['id']}/return", headers=auth).json()["returned_at"] is not None
    assert client.get("/api/loans", headers=auth).json() == []
    gift = client.post("/api/gifts", headers=auth, json={"person_id": martin["id"], "title": "Roman", "occasion": "Geburtstag", "budget": 25, "source_memory_id": note["id"]})
    assert gift.status_code == 201
    assert client.get(f"/api/gifts?person_id={martin['id']}", headers=auth).json()[0]["id"] == gift.json()["id"]
    assert client.get("/api/search?q=Bohrmaschine", headers=auth).json()["loans"][0]["id"] == loan.json()["id"]
    assert client.get("/api/conversations", headers={"Authorization": "Bearer invalid"}).status_code == 401

def test_task_and_conversation_edits_keep_owner_scoped_revision_history(client, auth):
    person = client.post("/api/people", headers=auth, json={"first_name": "Maya", "last_name": "Revisionstest"}).json()
    task = client.post("/api/tasks", headers=auth, json={"title": "Projekt 6012", "person_id": person["id"]}).json()
    changed_task = client.patch(f"/api/tasks/{task['id']}", headers=auth, json={"title": "OAS Umzüge", "person_id": person["id"], "priority": 1})
    assert changed_task.status_code == 200 and changed_task.json()["title"] == "OAS Umzüge"
    task_history = client.get(f"/api/tasks/{task['id']}/history", headers=auth)
    assert [row["revision"] for row in task_history.json()] == [2, 1]
    assert task_history.json()[0]["snapshot"]["fields"]["title"] == "OAS Umzüge"

    conversation = client.post("/api/conversations", headers=auth, json={"title": "Erstnotiz", "original_note": "Wir sprachen über das Projekt.", "participant_ids": [person["id"]]}).json()
    changed_conversation = client.patch(f"/api/conversations/{conversation['id']}", headers=auth, json={"title": "Projektbesprechung", "summary": "Projekt 6012"})
    assert changed_conversation.status_code == 200 and changed_conversation.json()["title"] == "Projektbesprechung"
    conversation_history = client.get(f"/api/conversations/{conversation['id']}/history", headers=auth)
    assert [row["revision"] for row in conversation_history.json()] == [2, 1]
    assert conversation_history.json()[0]["snapshot"]["fields"]["participant_ids"] == [person["id"]]

    other_user = User(username="revision-private-user", password_hash=hash_password("revision-password"))
    with Session(engine) as db:
        db.add(other_user)
        db.commit()
    other_token = client.post("/api/auth/login", json={"username": "revision-private-user", "password": "revision-password"}).json()["access_token"]
    assert client.get(f"/api/tasks/{task['id']}/history", headers={"Authorization": f"Bearer {other_token}"}).status_code == 404

def test_events_scheduler_notifications_and_reminder_actions(client, auth):
    from datetime import datetime, timedelta, timezone
    from sqlalchemy.orm import Session
    from lifepilot.scheduler import schedule_due_items
    event = client.post("/api/events", headers=auth, json={"title": "Arzttermin", "location": "Praxis", "starts_at": "2026-11-16T10:00:00Z"})
    assert event.status_code == 201
    assert client.post("/api/events", headers=auth, json={"title": "Falsch", "starts_at": "2026-11-16T10:00:00Z", "ends_at": "2026-11-15T10:00:00Z"}).status_code == 422
    with Session(engine) as db:
        task = Task(owner_id=db.query(User).filter_by(username="testuser").one().id, title="internal")
        task.due_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.add(task); db.commit()
        created = schedule_due_items(db)
        assert created >= 1
        assert schedule_due_items(db) == 0
    due = client.get("/api/notifications", headers=auth)
    assert any(item["title"] == "internal" for item in due.json())
    reminder = next(item for item in due.json() if item["title"] == "internal")
    action = client.patch(f"/api/reminders/{reminder['id']}", headers=auth, json={"state": "scheduled", "snoozed_until": "2026-11-17T12:00:00Z"})
    assert action.status_code == 200
    assert action.json()["snoozed_until"] is not None
    task_reminder = client.post("/api/tasks", headers=auth, json={"title": "Abschließbare Aufgabe", "due_at": "2026-11-16T08:00:00Z"}).json()
    with Session(engine) as db:
        created = schedule_due_items(db)
        assert created == 1
    linked = client.get("/api/reminders", headers=auth).json()
    linked_reminder = next(item for item in linked if item["task_id"] == task_reminder["id"])
    assert client.patch(f"/api/tasks/{task_reminder['id']}/complete", headers=auth).json()["status"] == "done"
    updated_reminders = client.get("/api/reminders", headers=auth).json()
    assert next(item for item in updated_reminders if item["id"] == linked_reminder["id"])["state"] == "done"

def test_recurring_tasks_and_quiet_hours(client, auth):
    from datetime import datetime, time, timedelta, timezone
    from zoneinfo import ZoneInfo
    from lifepilot.services import is_quiet_hours

    owner = User(timezone_name="Europe/Berlin", quiet_hours_start=time(22), quiet_hours_end=time(7))
    assert is_quiet_hours(owner, datetime(2026, 11, 17, 23, tzinfo=timezone.utc))
    assert not is_quiet_hours(owner, datetime(2026, 11, 17, 6, tzinfo=timezone.utc))

    now = datetime.now(timezone.utc)
    invalid = client.post("/api/tasks", headers=auth, json={"title": "Ungültige Wiederholung", "repeat_interval_days": 2})
    assert invalid.status_code == 422
    created = client.post("/api/tasks", headers=auth, json={"title": "Pflanzen gießen", "due_at": (now - timedelta(days=5)).isoformat(), "repeat_interval_days": 2, "repeat_until": (now + timedelta(days=10)).isoformat()})
    assert created.status_code == 201
    assert client.patch(f"/api/tasks/{created.json()['id']}/complete", headers=auth).status_code == 200
    tasks = client.get("/api/tasks?status=open", headers=auth).json()
    successor = next(task for task in tasks if task["title"] == "Pflanzen gießen")
    assert successor["repeat_interval_days"] == 2
    assert successor["due_at"].endswith("+00:00") or successor["due_at"].endswith("Z")
    successor_due = datetime.fromisoformat(successor["due_at"].replace("Z", "+00:00"))
    assert successor_due.replace(tzinfo=timezone.utc) > now
    before = len(tasks)
    client.patch(f"/api/tasks/{created.json()['id']}/complete", headers=auth)
    assert len(client.get("/api/tasks?status=open", headers=auth).json()) == before

    due = client.post("/api/tasks", headers=auth, json={"title": "Ruhezeit-Prüfung", "due_at": (now - timedelta(minutes=2)).isoformat()}).json()
    from sqlalchemy.orm import Session
    from lifepilot.scheduler import schedule_due_items
    with Session(engine) as db:
        schedule_due_items(db)
    local_now = now.astimezone(ZoneInfo("Europe/Berlin"))
    start = (local_now - timedelta(minutes=1)).strftime("%H:%M")
    end = (local_now + timedelta(minutes=1)).strftime("%H:%M")
    profile = client.patch("/api/profile", headers=auth, json={"timezone_name": "Europe/Berlin", "quiet_hours_start": start, "quiet_hours_end": end})
    assert profile.status_code == 200
    assert client.get("/api/notifications", headers=auth).json() == []
    invalid_zone = client.patch("/api/profile", headers=auth, json={"timezone_name": "Mars/Olympus"})
    assert invalid_zone.status_code == 422
    client.patch("/api/profile", headers=auth, json={"quiet_hours_start": None, "quiet_hours_end": None})
    notifications = client.get("/api/notifications", headers=auth).json()
    assert any(item["title"] == "Ruhezeit-Prüfung" and item["task_id"] == due["id"] for item in notifications)

def test_event_reschedule_updates_existing_reminder(client, auth):
    from datetime import datetime, timedelta, timezone

    start = datetime.now(timezone.utc) + timedelta(days=3)
    end = start + timedelta(hours=2)
    event = client.post("/api/events", headers=auth, json={"title": "Zahnarzt", "starts_at": start.isoformat(), "ends_at": end.isoformat()})
    assert event.status_code == 201
    reminder = client.post("/api/reminders", headers=auth, json={"title": "Zahnarzt", "due_at": start.isoformat(), "event_id": event.json()["id"]})
    assert reminder.status_code == 201
    new_start = start + timedelta(days=1)
    changed = client.patch(f"/api/events/{event.json()['id']}", headers=auth, json={"starts_at": new_start.isoformat(), "title": "Kontrolle"})
    assert changed.status_code == 200, changed.text
    assert changed.json()["title"] == "Kontrolle"
    updated = next(item for item in client.get("/api/reminders", headers=auth).json() if item["id"] == reminder.json()["id"])
    assert updated["title"] == "Kontrolle"
    assert updated["due_at"].endswith("+00:00") or updated["due_at"].endswith("Z")
    reminder_due = datetime.fromisoformat(updated["due_at"].replace("Z", "+00:00"))
    assert reminder_due.replace(tzinfo=timezone.utc) == new_start
    with __import__("sqlalchemy").orm.Session(engine) as db:
        from lifepilot.models import Event
        stored = db.get(Event, event.json()["id"])
        assert stored is not None and stored.ends_at is not None
        assert stored.ends_at.replace(tzinfo=timezone.utc) - stored.starts_at.replace(tzinfo=timezone.utc) == timedelta(hours=2)

@pytest.mark.skipif(not os.getenv("REDIS_URL"), reason="REDIS_URL ist für den RQ-Integrationstest nicht gesetzt")
def test_rq_worker_processes_scheduler_job_with_retries(client, auth):
    from uuid import uuid4
    from redis import Redis
    from redis.exceptions import RedisError
    from rq import Queue, Worker
    from rq.job import Job
    from lifepilot.scheduler import enqueue_schedule_job

    redis_url = os.environ["REDIS_URL"]
    redis_client = Redis.from_url(redis_url)
    try:
        redis_client.ping()
    except RedisError as error:
        pytest.skip(f"Redis ist für den RQ-Integrationstest nicht erreichbar: {error}")

    task_response = client.post("/api/tasks", headers=auth, json={"title": "RQ-Worker-Prüfung", "due_at": "2026-11-20T09:00:00Z"})
    assert task_response.status_code == 201, task_response.text
    task = task_response.json()
    queue_name = f"lifepilot-test-{uuid4().hex}"
    queue = Queue(queue_name, connection=redis_client)
    try:
        job = enqueue_schedule_job(redis_client, queue_name=queue_name)
        assert job.retries_left == 3
        assert job.retry_intervals == [15, 60, 180]

        assert Worker([queue], connection=redis_client).work(burst=True, with_scheduler=True)
        finished = Job.fetch(job.id, connection=redis_client)
        assert finished.get_status(refresh=True) == "finished"
        assert finished.return_value() >= 1
        reminders = client.get("/api/reminders", headers=auth).json()
        assert any(reminder["task_id"] == task["id"] for reminder in reminders)
    finally:
        queue.delete(delete_jobs=True)
        redis_client.close()


def test_daily_and_person_briefings_include_owned_sources(client, auth):
    from datetime import datetime, timedelta, timezone
    from zoneinfo import ZoneInfo

    from sqlalchemy.orm import Session

    from lifepilot.db import engine
    from lifepilot.models import User

    profile = client.patch("/api/profile", headers=auth, json={"timezone_name": "Europe/Berlin"})
    assert profile.status_code == 200
    now = datetime.now(timezone.utc)
    local_today = now.astimezone(ZoneInfo("Europe/Berlin")).date()
    event_time = datetime.combine(local_today, datetime.min.time(), tzinfo=ZoneInfo("Europe/Berlin")) + timedelta(hours=12)
    martin = client.post("/api/people", headers=auth, json={"first_name": "Martin"}).json()
    memory = client.post("/api/memories", headers=auth, json={"title": "Kaffee", "content": "Martin bevorzugt Hafermilch.", "person_id": martin["id"], "occurred_at": (now - timedelta(days=1)).isoformat()}).json()
    conversation = client.post("/api/conversations", headers=auth, json={"title": "Vereinstreffen", "original_note": "Martin berichtet vom Umzug.", "participant_ids": [martin["id"]], "occurred_at": (now - timedelta(days=2)).isoformat()}).json()
    task = client.post("/api/tasks", headers=auth, json={"title": "Martin zurückrufen", "person_id": martin["id"], "due_at": (now + timedelta(days=1)).isoformat()}).json()
    client.post("/api/loans", headers=auth, json={"item_name": "Bohrmaschine", "borrower_person_id": martin["id"]})
    client.post("/api/gifts", headers=auth, json={"person_id": martin["id"], "title": "Kochbuch", "occasion": "Geburtstag"})
    reminder_response = client.post("/api/reminders", headers=auth, json={"title": "Martin antworten", "due_at": (now + timedelta(days=2)).isoformat(), "task_id": task["id"]})
    assert reminder_response.status_code == 201, reminder_response.text
    reminder = reminder_response.json()
    lea = client.post("/api/people", headers=auth, json={"first_name": "Lea"}).json()
    relationship = client.post("/api/relationships", headers=auth, json={"source_person_id": martin["id"], "target_person_id": lea["id"], "relationship_type": "Vater von", "inverse_relationship_type": "Tochter von"}).json()
    event = client.post("/api/events", headers=auth, json={"title": "Mittagessen", "starts_at": event_time.isoformat(), "participant_ids": [martin["id"]]}).json()
    future_event_time = datetime.combine(local_today + timedelta(days=1), datetime.min.time(), tzinfo=ZoneInfo("Europe/Berlin")) + timedelta(hours=12)
    future_event = client.post("/api/events", headers=auth, json={"title": "Kaffee", "starts_at": future_event_time.isoformat(), "participant_ids": [martin["id"]]}).json()

    daily = client.get("/api/briefing/daily", headers=auth)
    assert daily.status_code == 200
    assert daily.json()["date"] == local_today.isoformat()
    assert event["id"] in {row["id"] for row in daily.json()["today_events"]}
    assert task["id"] in {row["id"] for row in daily.json()["open_tasks"]}
    assert reminder["id"] in {row["id"] for row in daily.json()["upcoming_reminders"]}

    context = client.get(f"/api/briefing/person/{martin['id']}", headers=auth)
    assert context.status_code == 200
    result = context.json()
    assert result["person"]["id"] == martin["id"]
    assert result["memories"][0]["id"] == memory["id"]
    assert result["conversations"][0]["id"] == conversation["id"]
    assert result["open_tasks"][0]["id"] == task["id"]
    assert result["open_loans"][0]["item_name"] == "Bohrmaschine"
    assert result["gift_ideas"][0]["title"] == "Kochbuch"
    assert future_event["id"] in {row["id"] for row in result["upcoming_events"]}
    assert result["relationships"][0]["id"] == relationship["id"]
    with Session(engine) as db:
        other_owner = User(username="briefing-other", password_hash="unused")
        db.add(other_owner)
        db.commit()
        from lifepilot.security import create_token

        other_auth = {"Authorization": f"Bearer {create_token(other_owner.id)}"}
    assert client.get(f"/api/briefing/person/{martin['id']}", headers=other_auth).status_code == 404
