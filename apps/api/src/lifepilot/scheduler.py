import time as time_module
import logging
from typing import Final
from datetime import date, datetime, time as datetime_time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from redis import Redis
from rq import Queue, Retry
from sqlalchemy import or_, select
from sqlalchemy.orm import Session
from lifepilot.config import settings
from lifepilot.db import engine
from lifepilot.models import Event, Person, Reminder, Task, User

logger = logging.getLogger(__name__)
SCHEDULER_LOCK_KEY: Final = "lifepilot:scheduler:leader"
SCHEDULE_EXECUTION_LOCK_KEY: Final = "lifepilot:scheduler:execution"
SCHEDULE_QUEUE_NAME: Final = "lifepilot"
BIRTHDAY_REMINDER_DAYS: Final = 7


def _schedule_birthday_reminders(db: Session, now: datetime) -> int:
    created = 0
    people = db.execute(
        select(Person, User)
        .join(User, User.id == Person.owner_id)
        .where(Person.is_self.is_(False), or_(Person.birthday.is_not(None), Person.birthday_precision == "month_day"))
    ).all()
    for person, owner in people:
        if person.birthday_precision in {"exact", "unknown"} and person.birthday:
            try:
                birth_date = date.fromisoformat(person.birthday)
            except ValueError:
                continue
            month, day = birth_date.month, birth_date.day
        elif person.birthday_precision == "month_day" and person.birthday_month and person.birthday_day:
            month, day = person.birthday_month, person.birthday_day
        else:
            continue
        try:
            zone = ZoneInfo(owner.timezone_name)
        except ZoneInfoNotFoundError:
            zone = timezone.utc
        local_today = now.astimezone(zone).date()
        try:
            occurrence = date(local_today.year, month, day)
        except ValueError:
            occurrence = date(local_today.year, 2, 28)
        if occurrence < local_today:
            try:
                occurrence = date(local_today.year + 1, month, day)
            except ValueError:
                occurrence = date(local_today.year + 1, 2, 28)
        reminder_date = max(local_today, occurrence - timedelta(days=BIRTHDAY_REMINDER_DAYS))
        due_at = datetime.combine(reminder_date, datetime_time(9), tzinfo=zone).astimezone(timezone.utc)
        reminder = db.scalar(
            select(Reminder).where(
                Reminder.birthday_person_id == person.id,
                Reminder.birthday_year == occurrence.year,
            )
        )
        title = f"Geburtstag von {person.first_name} {person.last_name}".strip()
        if reminder is None:
            db.add(Reminder(
                owner_id=owner.id,
                title=title,
                due_at=due_at,
                birthday_person_id=person.id,
                birthday_year=occurrence.year,
            ))
            created += 1
        elif reminder.state == "scheduled":
            reminder.title = title
            reminder.due_at = due_at
    return created

def sync_contact_followup(db: Session, person: Person, owner: User, reactivate_muted: bool = False) -> None:
    reminder = db.scalar(select(Reminder).where(Reminder.contact_person_id == person.id))
    if person.contact_interval_days is None:
        if reminder is not None and reminder.state == "scheduled":
            reminder.state = "muted"
        return
    if person.last_contact_at is None:
        return
    if reminder is not None and reminder.state == "muted" and not reactivate_muted:
        return
    try:
        zone = ZoneInfo(owner.timezone_name)
    except ZoneInfoNotFoundError:
        zone = timezone.utc
    last_contact = person.last_contact_at
    if last_contact.tzinfo is None:
        last_contact = last_contact.replace(tzinfo=timezone.utc)
    due_date = last_contact.astimezone(zone).date() + timedelta(days=person.contact_interval_days)
    due_at = datetime.combine(due_date, datetime_time(9), tzinfo=zone).astimezone(timezone.utc)
    title = f"Bei {person.first_name} {person.last_name} melden".strip()
    if reminder is None:
        db.add(Reminder(owner_id=owner.id, title=title, due_at=due_at, contact_person_id=person.id))
    else:
        reminder.title = title
        reminder.due_at = due_at
        reminder.state = "scheduled"
        reminder.snoozed_until = None

def schedule_due_items(db: Session) -> int:
    created = 0
    tasks = db.scalars(select(Task).where(Task.status == "open", Task.due_at.is_not(None))).all()
    for task in tasks:
        existing = db.scalar(select(Reminder.id).where(Reminder.task_id == task.id))
        if existing is None:
            db.add(Reminder(owner_id=task.owner_id, title=task.title, due_at=task.due_at, task_id=task.id))
            created += 1
    events = db.scalars(select(Event).where(Event.record_type == "appointment", Event.starts_at >= datetime.now(timezone.utc))).all()
    for event in events:
        existing = db.scalar(select(Reminder.id).where(Reminder.event_id == event.id))
        if existing is None:
            db.add(Reminder(owner_id=event.owner_id, title=event.title, due_at=event.starts_at, event_id=event.id))
            created += 1
    created += _schedule_birthday_reminders(db, datetime.now(timezone.utc))
    contacts = db.execute(select(Person, User).join(User, User.id == Person.owner_id).where(Person.contact_interval_days.is_not(None))).all()
    for person, owner in contacts:
        sync_contact_followup(db, person, owner)
    from lifepilot.trash_routes import cleanup_expired
    cleanup_expired(db)
    db.commit()
    return created

def enqueue_schedule_job(redis_client: Redis, queue_name: str = SCHEDULE_QUEUE_NAME):
    queue = Queue(queue_name, connection=redis_client)
    return queue.enqueue(
        "lifepilot.scheduler.schedule_due_items_job",
        job_timeout=300,
        result_ttl=3600,
        failure_ttl=86400,
        retry=Retry(max=3, interval=[15, 60, 180]),
        description="Fällige Erinnerungen planen",
    )

def schedule_due_items_job() -> int:
    redis_client = Redis.from_url(settings.redis_url)
    try:
        lock = redis_client.lock(SCHEDULE_EXECUTION_LOCK_KEY, timeout=300, blocking_timeout=0)
        if not lock.acquire(blocking=False):
            return 0
        try:
            with Session(engine) as db:
                return schedule_due_items(db)
        finally:
            lock.release()
    finally:
        redis_client.close()

def run_scheduling_cycle(redis_client: Redis | None = None) -> bool:
    if redis_client is None:
        with Session(engine) as db:
            schedule_due_items(db)
        return True

    lock = redis_client.lock(SCHEDULER_LOCK_KEY, timeout=300, blocking_timeout=0)
    if not lock.acquire(blocking=False):
        return False
    try:
        enqueue_schedule_job(redis_client)
    finally:
        lock.release()
    return True

def run_scheduler(interval_seconds: int = 60) -> None:
    redis_client = Redis.from_url(settings.redis_url) if settings.redis_url else None
    while True:
        try:
            run_scheduling_cycle(redis_client)
        except Exception:
            logger.exception("Erinnerungsplanung ist fehlgeschlagen")
            time_module.sleep(min(interval_seconds, 10))
        time_module.sleep(interval_seconds)

if __name__ == "__main__":
    run_scheduler()
