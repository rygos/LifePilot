"""Independent delivery loop; uses existing reminder schedules without mutating them."""
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from lifepilot.config import settings
from lifepilot.db import engine
from lifepilot.models import Commitment, Event, PushSubscription, Reminder, Routine, Task, User
from lifepilot.push_keys import configured_public_key
from lifepilot.push_routes import endpoint_allowed
from lifepilot.routine_routes import routine_output
from lifepilot.services import is_quiet_hours

logger = logging.getLogger(__name__)
PAYLOAD = {"title": "LifePilot", "body": "Du hast offene Erinnerungen. Öffne LifePilot für Details.", "tag": "lifepilot-reminders"}
BATCH_SIZE = 20


def utc(value: datetime):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def due_keys(db: Session, owner: User, now: datetime) -> set[str]:
    reminders = db.scalars(select(Reminder).where(
        Reminder.owner_id == owner.id, Reminder.state == "scheduled",
        or_(and_(Reminder.snoozed_until.is_(None), Reminder.due_at <= now), Reminder.snoozed_until <= now),
        or_(Reminder.task_id.is_(None), select(Task.id).where(Task.id == Reminder.task_id, Task.owner_id == owner.id, Task.status == "open").exists()),
        or_(Reminder.event_id.is_(None), select(Event.id).where(Event.id == Reminder.event_id, Event.owner_id == owner.id, Event.record_type == "appointment").exists()),
    )).all()
    keys = {f"reminder:{r.id}:{utc(r.snoozed_until or r.due_at).isoformat()}" for r in reminders}
    commitments = db.scalars(select(Commitment).where(Commitment.owner_id == owner.id, Commitment.status == "open", Commitment.due_at <= now)).all()
    keys.update(f"commitment:{r.id}:{utc(r.due_at).isoformat()}" for r in commitments)
    try:
        current = now.astimezone(ZoneInfo(owner.timezone_name))
    except ZoneInfoNotFoundError:
        current = now.astimezone(timezone.utc)
    clock = current.time().replace(tzinfo=None)
    routines = db.scalars(select(Routine).where(Routine.owner_id == owner.id, Routine.archived.is_(False), Routine.window_start <= clock, Routine.window_end > clock)).all()
    for routine in routines:
        if current.weekday() not in routine.weekdays:
            continue
        output = routine_output(db, routine, current)
        if any(not step.completed for step in output.steps):
            keys.add(f"routine:{routine.id}:{current.date().isoformat()}")
    return keys


def send_push(device: PushSubscription) -> int:
    # Import lazily so deployments without configured push continue normally.
    from pywebpush import WebPushException, webpush
    from requests import Session as HttpSession

    class NoRedirectSession(HttpSession):
        def request(self, method, url, **kwargs):
            if not endpoint_allowed(url):
                raise ValueError("Unsupported push endpoint")
            kwargs["allow_redirects"] = False
            return super().request(method, url, **kwargs)

    if not endpoint_allowed(device.endpoint):
        return 410
    with NoRedirectSession() as session:
        try:
            result = webpush(
                subscription_info={"endpoint": device.endpoint, "keys": {"p256dh": device.p256dh, "auth": device.auth}},
                data=json.dumps(PAYLOAD, ensure_ascii=False),
                vapid_private_key=settings.push_vapid_private_key,
                vapid_claims={"sub": settings.push_vapid_subject},
                ttl=60, timeout=5, requests_session=session,
            )
            return result.status_code
        except WebPushException as exc:
            return exc.response.status_code if exc.response is not None else 503


def dispatch_due_push(db: Session, now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    public = configured_public_key()
    if not public:
        return 0
    # Row locks prevent simultaneous sends by multiple workers on PostgreSQL.
    ids = list(db.scalars(select(PushSubscription.id).where(
        PushSubscription.next_check_at <= now,
    ).order_by(PushSubscription.next_check_at, PushSubscription.id).limit(BATCH_SIZE)))
    db.commit()
    sent = 0
    for device_id in ids:
        device = db.scalar(select(PushSubscription).where(
            PushSubscription.id == device_id, PushSubscription.next_check_at <= now,
        ).with_for_update(skip_locked=True).execution_options(populate_existing=True))
        if device is None:
            db.rollback()
            continue
        owner = db.scalar(select(User).where(User.id == device.owner_id, User.deleted_at.is_(None)))
        if owner is None or owner.token_version != device.token_version or device.vapid_public_key != public:
            # Keep invalid devices visible in settings; don't poll them every minute.
            device.next_check_at = now + timedelta(days=1)
            db.commit()
            continue
        device.next_check_at = now + timedelta(minutes=1)
        if is_quiet_hours(owner, now):
            db.commit()
            continue
        keys = due_keys(db, owner, now)
        previous = set(device.sent_keys or [])
        # Remove no-longer-due occurrences, so a later snooze can notify again.
        device.sent_keys = sorted(previous & keys)
        if not keys - previous:
            db.commit()
            continue
        try:
            status = send_push(device)
        except Exception:
            # Provider exception strings may contain endpoint tokens; never log them.
            status = 503
        if 200 <= status < 300:
            device.sent_keys = sorted(keys)
            device.last_sent_at = now
            device.failure_count = 0
            sent += 1
        elif status in (404, 410):
            db.delete(device)
        else:
            device.failure_count += 1
            device.next_check_at = now + timedelta(minutes=min(360, 2 ** min(device.failure_count, 9)))
            logger.warning("Push delivery failed (HTTP %s); retry scheduled", status)
        db.commit()
    return sent


def run():
    logging.basicConfig(level=logging.INFO)
    if not configured_public_key():
        logger.info("Web Push disabled: VAPID configuration missing or invalid")
    while True:
        try:
            with Session(engine) as db:
                dispatch_due_push(db)
        except Exception:
            logger.error("Push delivery cycle failed")
        time.sleep(60)


if __name__ == "__main__":
    run()
