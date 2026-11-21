from uuid import uuid4
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from lifepilot.db import engine
from lifepilot.models import Person, Reminder, User
from lifepilot.security import create_token


def test_person_favorites_labels_and_how_we_met_are_persisted_and_searchable(client, auth):
    created = client.post(
        "/api/people",
        headers=auth,
        json={
            "first_name": "Mara",
            "last_name": "Beispiel",
            "how_met": "Beim Sommerfest im Sportverein",
            "tags": [" Verein ", "familie", "verein", ""],
        },
    )
    assert created.status_code == 201
    person = created.json()
    assert person["how_met"] == "Beim Sommerfest im Sportverein"
    assert person["tags"] == ["Verein", "familie"]
    assert person["is_favorite"] is False
    assert client.get("/api/people?q=Sportverein", headers=auth).json()[0]["id"] == person["id"]
    assert client.get("/api/people?q=familie", headers=auth).json()[0]["id"] == person["id"]

    contact = client.post(f"/api/people/{person['id']}/contact-methods", headers=auth, json={"method_type": "email", "label": " Arbeit ", "value": " mara@example.org "})
    assert contact.status_code == 201
    assert contact.json()["label"] == "Arbeit" and contact.json()["value"] == "mara@example.org"
    contact_id = contact.json()["id"]
    other_contact = client.post(f"/api/people/{person['id']}/contact-methods", headers=auth, json={"method_type": "email", "label": "Privat", "value": "mara@example.org"})
    assert other_contact.status_code == 201
    assert client.post(f"/api/people/{person['id']}/contact-methods", headers=auth, json={"method_type": "email", "label": "Arbeit", "value": "mara@example.org"}).status_code == 409
    assert client.patch(f"/api/contact-methods/{other_contact.json()['id']}", headers=auth, json={"method_type": "email", "label": "Arbeit", "value": "mara@example.org"}).status_code == 409
    assert client.get("/api/people?q=mara@example.org", headers=auth).json()[0]["id"] == person["id"]
    assert client.patch(f"/api/contact-methods/{contact_id}", headers=auth, json={"method_type": "messaging", "label": "Signal", "value": "mara-signal"}).json()["value"] == "mara-signal"
    assert client.get(f"/api/people/{person['id']}", headers=auth).json()["contact_methods"][0]["value"] == "mara-signal"

    added = client.patch(f"/api/people/{person['id']}/favorite", headers=auth)
    assert added.status_code == 200
    assert added.json()["is_favorite"] is True
    removed = client.patch(f"/api/people/{person['id']}/favorite", headers=auth)
    assert removed.json()["is_favorite"] is False

    with Session(engine) as db:
        other_user = User(username=f"private-{uuid4().hex}", password_hash="unused")
        db.add(other_user)
        db.commit()
        other_token = create_token(other_user.id)
    assert client.patch(f"/api/people/{person['id']}/favorite", headers={"Authorization": f"Bearer {other_token}"}).status_code == 404
    assert client.get(f"/api/people/{person['id']}/contact-methods", headers={"Authorization": f"Bearer {other_token}"}).status_code == 404
    assert client.delete(f"/api/contact-methods/{contact_id}", headers={"Authorization": f"Bearer {other_token}"}).status_code == 404
    assert client.delete(f"/api/contact-methods/{contact_id}", headers=auth).status_code == 204


def test_birthday_reminders_are_annual_timezone_aware_and_deduplicated(client, auth):
    with Session(engine) as db:
        owner = db.query(User).filter_by(username="testuser").one()
        person = Person(owner_id=owner.id, first_name="Geburtstag", last_name="Kontakt", birthday="2000-11-08")
        leap_day = Person(owner_id=owner.id, first_name="Schalttag", birthday="2000-02-29")
        db.add_all([person, leap_day])
        db.commit()
        person_id = person.id
        leap_day_id = leap_day.id

    from lifepilot.scheduler import _schedule_birthday_reminders

    with Session(engine) as db:
        now = datetime(2026, 11, 1, 8, tzinfo=timezone.utc)
        assert _schedule_birthday_reminders(db, now) == 2
        db.commit()
        reminder = db.query(Reminder).filter_by(birthday_person_id=person_id, birthday_year=2026).one()
        assert reminder.title == "Geburtstag von Geburtstag Kontakt"
        assert reminder.due_at.date().isoformat() == "2026-11-01"
        assert _schedule_birthday_reminders(db, now) == 0
        db.commit()

        next_year = datetime(2027, 2, 20, 8, tzinfo=timezone.utc)
        assert _schedule_birthday_reminders(db, next_year) == 1
        db.commit()
        leap_reminder = db.query(Reminder).filter_by(birthday_person_id=leap_day_id, birthday_year=2027).one()
        assert leap_reminder.due_at.date().isoformat() == "2027-02-21"
