"""Read-only chronological projection of explicit dates from existing resources."""
from datetime import date, datetime, time, timezone, timedelta
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import or_, select, null
from sqlalchemy.orm import Session

from lifepilot.db import get_db
from lifepilot.models import (
    Person, Conversation, ConversationParticipant, Event, EventParticipant,
    JournalEntry, JournalEntryPerson, Memory, PersonLifeEvent, PersonCallLog,
    TemporalFact, Loan, User,
)
from lifepilot.security import current_user

router = APIRouter(prefix="/api/timeline", tags=["Lebenschronik"])
Kind = Literal["conversation", "event", "memory", "journal", "life_event", "call", "fact", "loan"]
Mode = Literal["dated", "undated"]
MAX_OFFSET = 2000


class TimelinePerson(BaseModel):
    id: str
    name: str


class TimelineItem(BaseModel):
    id: str
    kind: Kind
    resource_id: str
    title: str
    occurrence: str
    day: date | None = None
    occurred_at: datetime | None = None
    date_precision: str
    status: str | None = None
    people: list[TimelinePerson] = []
    people_truncated: bool = False


class TimelineOut(BaseModel):
    items: list[TimelineItem]
    next_offset: int | None
    window_limited: bool = False
    timezone: str


# model, kind, occurrence, date column, title, direct person columns, join model/link column
SOURCES = (
    (Conversation, "conversation", "occurred", "occurred_at", "title", (), ConversationParticipant, "conversation_id"),
    (Event, "event", "start", "starts_at", "title", (), EventParticipant, "event_id"),
    (Memory, "memory", "occurred", "occurred_at", "title", ("person_id",), None, None),
    (JournalEntry, "journal", "entry", "entry_date", "title", (), JournalEntryPerson, "entry_id"),
    (PersonLifeEvent, "life_event", "occurred", "occurred_at", "title", ("person_id",), None, None),
    (PersonCallLog, "call", "occurred", "occurred_at", None, ("person_id",), None, None),
    (TemporalFact, "fact", "start", "valid_from", "value", ("person_id",), None, None),
    (TemporalFact, "fact", "end", "valid_until", "value", ("person_id",), None, None),
    (Loan, "loan", "lent", "lent_at", "item_name", ("lender_person_id","borrower_person_id"), None, None),
    (Loan, "loan", "returned", "returned_at", "item_name", ("lender_person_id","borrower_person_id"), None, None),
)


def utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def timeline(db: Session, owner: str, person_id=None, kinds=None, start=None, end=None,
             mode: Mode="dated", include_unconfirmed=False, limit=50, offset=0):
    if not 1 <= limit <= 100 or not 0 <= offset <= MAX_OFFSET:
        raise HTTPException(422, "Ungültige Seitengröße")
    if start and end and start > end:
        raise HTTPException(422, "Beginn darf nicht nach Ende liegen")
    if mode == "undated" and (start or end):
        raise HTTPException(422, "Undatierte Einträge können nicht nach Datum gefiltert werden")
    # Avoid date arithmetic overflow and timezone conversion at calendar extremes.
    if any(value and not 2 <= value.year <= 9998 for value in (start, end)):
        raise HTTPException(422, "Datumsbereich außerhalb des unterstützten Kalenders")
    user = db.get(User, owner)
    if user is None:
        raise HTTPException(404, "Konto nicht gefunden")
    try:
        zone = ZoneInfo(user.timezone_name)
    except (ZoneInfoNotFoundError, ValueError):
        zone = ZoneInfo("UTC")
    if person_id and db.scalar(select(Person.id).where(Person.owner_id==owner, Person.id==person_id)) is None:
        raise HTTPException(404, "Person nicht gefunden")
    allowed = set(kinds) if kinds else {source[1] for source in SOURCES}
    candidates = []
    size = offset + limit + 1

    for model, kind, occurrence, date_col, title_col, direct_cols, link, link_col in SOURCES:
        if kind not in allowed:
            continue
        when = getattr(model, date_col)
        day_only = model in (JournalEntry, TemporalFact)
        columns = [model.id, when.label("when"), (getattr(model,title_col) if title_col else null()).label("title"),
                   *[getattr(model,c) for c in direct_cols]]
        if model is PersonLifeEvent:
            columns += [model.date_precision, model.confirmed]
        elif model is TemporalFact:
            columns += [model.predicate, model.status]
        elif model is Event:
            columns += [model.record_type]
        stmt = select(*columns).where(model.owner_id==owner)
        if person_id:
            if direct_cols:
                stmt = stmt.where(or_(*[getattr(model,c)==person_id for c in direct_cols]))
            elif link is not None:
                stmt = stmt.where(select(link.person_id).where(link.owner_id==owner,link.person_id==person_id,
                                    getattr(link,link_col)==model.id).exists())
        if model is PersonLifeEvent and not include_unconfirmed:
            stmt = stmt.where(model.confirmed.is_(True))
        if model is TemporalFact:
            stmt = stmt.where(model.status!="rejected" if include_unconfirmed else model.status=="confirmed")
        if mode=="undated":
            if model in (Event, JournalEntry, PersonCallLog, Loan):
                continue
            if model is TemporalFact:
                if occurrence=="end":
                    continue
                stmt=stmt.where(model.valid_from.is_(None),model.valid_until.is_(None))
            elif model is PersonLifeEvent:
                stmt=stmt.where(or_(when.is_(None),model.date_precision.not_in(("exact","day"))))
            else:
                stmt=stmt.where(when.is_(None))
            stmt=stmt.order_by(model.id)
        else:
            stmt=stmt.where(when.is_not(None))
            if model is PersonLifeEvent:
                stmt=stmt.where(model.date_precision.in_(("exact","day")))
            if start:
                lower=start if day_only else datetime.combine(start,time.min,zone).astimezone(timezone.utc)
                stmt=stmt.where(when>=lower)
            if end:
                upper=end+timedelta(days=1)
                upper=upper if day_only else datetime.combine(upper,time.min,zone).astimezone(timezone.utc)
                stmt=stmt.where(when<upper)
            stmt=stmt.order_by(when.desc(),model.id)
        for row in db.execute(stmt.limit(size)).mappings():
            value=row["when"] if mode=="dated" else None
            instant=utc(value) if isinstance(value,datetime) else None
            day=instant.astimezone(zone).date() if instant else value
            precision=row.get("date_precision","day" if day_only else "exact") if value is not None or model is PersonLifeEvent else "unknown"
            if value is None and precision in ("exact","day"):
                precision="unknown"
            status=row.get("status",row.get("record_type"))
            if model is PersonLifeEvent:
                status="confirmed" if row["confirmed"] else "proposed"
            label=row["title"] or ("Telefonat" if model is PersonCallLog else "Tagebucheintrag" if model is JournalEntry else "Ohne Titel")
            if model is TemporalFact:
                label=f"{row['predicate']}: {label}"
            actual_occurrence="unknown" if mode=="undated" and model is TemporalFact else occurrence
            item=TimelineItem(id=f"{kind}:{row['id']}:{actual_occurrence}",kind=kind,resource_id=row["id"],
                title=label[:300],occurrence=actual_occurrence,day=day,occurred_at=instant if precision=="exact" else None,
                date_precision=precision,status=status)
            # Sort day-only values at midnight local, not midnight UTC. For equal timestamps
            # sort by stable resource key. No date is fabricated for undated entries.
            order=instant or (datetime.combine(day,time.min,zone).astimezone(timezone.utc) if day else None)
            candidates.append((item,order,[row[c] for c in direct_cols if row[c]],link,link_col))
    # Stable tie-break: descending occurrence time, ascending unique resource key.
    candidates.sort(key=lambda x:x[0].id)
    if mode=="dated":
        candidates.sort(key=lambda x:x[1],reverse=True)
    page=candidates[offset:offset+limit]
    # Resolve only visible person labels. Never trust link rows to authorize a person.
    person_sets=[]
    all_ids=set()
    for item,_,direct,link,link_col in page:
        ids=set(direct)
        if link is not None:
            rows=list(db.scalars(select(link.person_id).join(Person,Person.id==link.person_id).where(
                link.owner_id==owner,Person.owner_id==owner,getattr(link,link_col)==item.resource_id).order_by(link.person_id).limit(21)))
            item.people_truncated=len(rows)>20
            ids.update(rows[:20])
            if person_id:
                ids.add(person_id)
        person_sets.append(ids)
        all_ids.update(ids)
    labels={}
    if all_ids:
        for pid,first,last in db.execute(select(Person.id,Person.first_name,Person.last_name).where(Person.owner_id==owner,Person.id.in_(all_ids))):
            labels[pid]=TimelinePerson(id=pid,name=" ".join(filter(None,(first,last))) or "Unbenannt")
    for (item,*_),ids in zip(page,person_sets):
        item.people=[labels[pid] for pid in sorted(ids) if pid in labels]
    more=len(candidates)>offset+limit
    following=offset+limit
    return TimelineOut(items=[entry[0] for entry in page],next_offset=following if more and following<=MAX_OFFSET else None,
                       window_limited=more and following>MAX_OFFSET,timezone=zone.key)


@router.get("",response_model=TimelineOut)
def get_timeline(person_id: str | None=None,kinds: list[Kind] | None=Query(None),
                 start: date | None=None,end: date | None=None,mode: Mode="dated",
                 include_unconfirmed: bool=False,limit: int=Query(50,ge=1,le=100),offset: int=Query(0,ge=0,le=MAX_OFFSET),
                 db: Session=Depends(get_db),user: User=Depends(current_user)):
    return timeline(db,user.id,person_id,kinds,start,end,mode,include_unconfirmed,limit,offset)
