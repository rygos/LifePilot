from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from lifepilot.db import engine
from lifepilot.models import Person, Reminder, User


def test_person_can_store_month_day_birthday_without_inventing_birth_year(client, auth):
    response = client.post(
        "/api/people",
        headers=auth,
        json={
            "first_name": "Mara",
            "birthday_precision": "month_day",
            "birthday_month": 2,
            "birthday_day": 29,
        },
    )
    assert response.status_code == 201
    person = response.json()
    assert person["birthday"] is None
    assert person["birthday_precision"] == "month_day"
    assert person["birthday_month"] == 2
    assert person["birthday_day"] == 29

    invalid = client.post(
        "/api/people",
        headers=auth,
        json={"first_name": "Ungültig", "birthday_precision": "month_day", "birthday_month": 2, "birthday_day": 30},
    )
    assert invalid.status_code == 422


def test_create_relationship_and_person_in_one_request(client, auth):
    source = client.post("/api/people", headers=auth, json={"first_name": "Alex", "gender": "female"})
    assert source.status_code == 201
    response = client.post(
        "/api/relationships/with-new-person",
        headers=auth,
        json={
            "source_person_id": source.json()["id"],
            "relationship_type": "parent",
            "new_person": {"first_name": "Jamie", "gender": "unspecified"},
        },
    )
    assert response.status_code == 201
    result = response.json()
    assert result["person"]["first_name"] == "Jamie"
    assert result["relationship"]["source_person_id"] == source.json()["id"]
    assert result["relationship"]["target_person_id"] == result["person"]["id"]

    relationships = client.get(f"/api/relationships?person_id={result['person']['id']}", headers=auth)
    assert relationships.status_code == 200
    assert len(relationships.json()) == 1


def test_call_log_updates_last_contact_and_persists_contact_followup(client, auth):
    response = client.post(
        "/api/people",
        headers=auth,
        json={"first_name": "Robin", "contact_interval_days": 30},
    )
    assert response.status_code == 201
    person_id = response.json()["id"]
    occurred_at = datetime.now(timezone.utc) - timedelta(days=1)
    call = client.post(
        f"/api/people/{person_id}/calls",
        headers=auth,
        json={"occurred_at": occurred_at.isoformat(), "duration_minutes": 12, "notes": "  Kurz gesprochen  "},
    )
    assert call.status_code == 201
    assert call.json()["notes"] == "Kurz gesprochen"

    calls = client.get(f"/api/people/{person_id}/calls", headers=auth)
    assert calls.status_code == 200
    assert [item["id"] for item in calls.json()] == [call.json()["id"]]
    with Session(engine) as db:
        person = db.scalar(select(Person).where(Person.id == person_id))
        owner = db.scalar(select(User).where(User.username == "testuser"))
        reminder = db.scalar(select(Reminder).where(Reminder.contact_person_id == person_id))
        assert person is not None and person.last_contact_at is not None
        assert owner is not None
        assert reminder is not None
        assert reminder.owner_id == owner.id
        assert reminder.due_at.date() == (occurred_at + timedelta(days=30)).date()


def test_month_day_birthday_without_year_gets_annual_reminder(client, auth):
    response = client.post(
        "/api/people",
        headers=auth,
        json={"first_name": "Februar", "birthday_precision": "month_day", "birthday_month": 2, "birthday_day": 29},
    )
    assert response.status_code == 201
    person_id = response.json()["id"]

    from lifepilot.scheduler import _schedule_birthday_reminders

    with Session(engine) as db:
        assert _schedule_birthday_reminders(db, datetime(2027, 2, 1, tzinfo=timezone.utc)) >= 1
        reminder = db.scalar(select(Reminder).where(Reminder.birthday_person_id == person_id))
        assert reminder is not None
        assert reminder.birthday_year == 2027
        assert reminder.title == "Geburtstag von Februar"

