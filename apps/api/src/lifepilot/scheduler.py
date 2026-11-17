import time
import logging
from typing import Final
from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from lifepilot.config import settings
from lifepilot.db import engine
from lifepilot.models import Event, Reminder, Task

logger = logging.getLogger(__name__)
SCHEDULER_LOCK_KEY: Final = "lifepilot:scheduler:leader"

def schedule_due_items(db: Session) -> int:
    created = 0
    tasks = db.scalars(select(Task).where(Task.status == "open", Task.due_at.is_not(None))).all()
    for task in tasks:
        existing = db.scalar(select(Reminder.id).where(Reminder.task_id == task.id))
        if existing is None:
            db.add(Reminder(owner_id=task.owner_id, title=task.title, due_at=task.due_at, task_id=task.id))
            created += 1
    events = db.scalars(select(Event)).all()
    for event in events:
        existing = db.scalar(select(Reminder.id).where(Reminder.event_id == event.id))
        if existing is None:
            db.add(Reminder(owner_id=event.owner_id, title=event.title, due_at=event.starts_at, event_id=event.id))
            created += 1
    if created:
        db.commit()
    return created

def run_scheduling_cycle(redis_client: Redis | None = None) -> bool:
    if redis_client is None:
        with Session(engine) as db:
            schedule_due_items(db)
        return True

    lock = redis_client.lock(SCHEDULER_LOCK_KEY, timeout=300, blocking_timeout=0)
    if not lock.acquire(blocking=False):
        return False
    try:
        with Session(engine) as db:
            schedule_due_items(db)
    finally:
        lock.release()
    return True

def run_scheduler(interval_seconds: int = 60) -> None:
    redis_client = Redis.from_url(settings.redis_url, decode_responses=True) if settings.redis_url else None
    while True:
        try:
            run_scheduling_cycle(redis_client)
        except (RedisError, SQLAlchemyError):
            logger.exception("Erinnerungsplanung ist fehlgeschlagen")
            time.sleep(min(interval_seconds, 10))
        time.sleep(interval_seconds)

if __name__ == "__main__":
    run_scheduler()
