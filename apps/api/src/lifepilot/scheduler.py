import time
import logging
from sqlalchemy import select
from sqlalchemy.orm import Session
from lifepilot.db import engine
from lifepilot.models import Event, Reminder, Task

logger = logging.getLogger(__name__)

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

def run_scheduler(interval_seconds: int = 60) -> None:
    while True:
        try:
            with Session(engine) as db:
                schedule_due_items(db)
        except Exception:
            logger.exception("Erinnerungsplanung ist fehlgeschlagen")
            time.sleep(min(interval_seconds, 10))
        time.sleep(interval_seconds)

if __name__ == "__main__":
    run_scheduler()
