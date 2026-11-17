from datetime import datetime, timedelta


def next_recurrence_at(
    due_at: datetime,
    interval_days: int,
    repeat_until: datetime | None,
    now: datetime | None = None,
) -> datetime | None:
    interval = timedelta(days=interval_days)
    next_due_at = due_at + interval
    current_time = now or datetime.now(due_at.tzinfo)
    if next_due_at <= current_time:
        missed_intervals = (current_time - next_due_at) // interval + 1
        next_due_at += interval * missed_intervals
    if repeat_until is not None and next_due_at > repeat_until:
        return None
    return next_due_at
