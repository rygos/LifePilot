import time
import logging
from typing import Final
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from redis import Redis
from rq import Queue, Retry
from sqlalchemy import select
from sqlalchemy.orm import Session
from lifepilot.config import settings
from lifepilot.db import engine
from lifepilot.models import Event, Person, Reminder, Task, User

logger = logging.getLogger(__name__)
SCHEDULER_LOCK_KEY: Final = "lifepilot:scheduler:leader"
SCHEDULE_EXECUTION_LOCK_KEY: Final = "lifepilot:scheduler:execution"
SCHEDULE_QUEUE_NAME: Final = "lifepilot"
BIRTHDAY_REMINDER_DAYS: Final = 7


def _birthday_in_year(birthday: date, year: int) -> date:
    try:
        return birthday.replace(year=year)
    except ValueError:
        return date(year, 2, 28)


def _schedule_birthday_reminders(db: Session, now: datetime) -> int:
    created = 0
    people = db.execute(
        select(Person, User)
        .join(User, User.id == Person.owner_id)
        .where(Person.is_self.is_(False), Person.birthday.is_not(None))
    ).all()
    for person, owner in people:
        try:
            birth_date = date.fromisoformat(person.birthday or "")
        except ValueError:
            continue
        try:
            zone = ZoneInfo(owner.timezone_name)
        except ZoneInfoNotFoundError:
            zone = timezone.utc
        local_today = now.astimezone(zone).date()
        occurrence = _birthday_in_year(birth_date, local_today.year)
        if occurrence < local_today:
            occurrence = _birthday_in_year(birth_date, local_today.year + 1)
        reminder_date = max(local_today, occurrence - timedelta(days=BIRTHDAY_REMINDER_DAYS))
        due_at = datetime.combine(reminder_date, time(9), tzinfo=zone).astimezone(timezone.utc)
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
    if created:
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
            time.sleep(min(interval_seconds, 10))
        time.sleep(interval_seconds)

if __name__ == "__main__":
    run_scheduler()
