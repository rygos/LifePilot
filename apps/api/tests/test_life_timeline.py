from datetime import date, datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from lifepilot.db import engine
from lifepilot.models import (User, Person, Conversation, ConversationParticipant, Event, EventParticipant,
    Memory, JournalEntry, JournalEntryPerson, PersonCallLog, PersonLifeEvent, TemporalFact, Loan)
from lifepilot.security import hash_password
from lifepilot.temporal_facts import fact_value_key


def account(client):
    name = "timeline-" + uuid4().hex
    with Session(engine) as db:
        row = User(username=name,password_hash=hash_password("test-password"),timezone_name="Europe/Berlin")
        db.add(row); db.commit(); owner=row.id
    token=client.post("/api/auth/login",json={"username":name,"password":"test-password"}).json()["access_token"]
    return owner,{"Authorization":"Bearer "+token}


def test_timeline_order_timezone_filters_and_pagination(client):
    owner,auth=account(client)
    foreign,other=account(client)
    evening=datetime(2025,1,2,23,30,tzinfo=timezone.utc)
    morning=datetime(2025,1,3,8,tzinfo=timezone.utc)
    with Session(engine) as db:
        person=Person(owner_id=owner,first_name="Anna")
        outsider=Person(owner_id=foreign,first_name="Foreign secret")
        db.add_all([person,outsider]);db.flush()
        conversation=Conversation(owner_id=owner,title="Gespräch",original_note="Secret conversation body",occurred_at=evening)
        event=Event(owner_id=owner,title="Termin",starts_at=morning,record_type="appointment")
        journal=JournalEntry(owner_id=owner,title="Tagebuch",content="Secret journal body",entry_date=date(2025,1,3))
        fact=TemporalFact(owner_id=owner,person_id=person.id,predicate="wohnort",value="Bonn",value_key=fact_value_key("Bonn"),valid_from=date(2020,1,1),valid_until=date(2025,1,3),status="confirmed")
        loan=Loan(owner_id=owner,item_name="Buch",borrower_person_id=person.id,lent_at=evening,returned_at=morning)
        db.add_all([conversation,event,journal,fact,loan,
                    PersonCallLog(owner_id=owner,person_id=person.id,occurred_at=morning),
                    PersonLifeEvent(owner_id=owner,person_id=person.id,title="Biografie",occurred_at=evening,date_precision="day",confirmed=True),
                    Memory(owner_id=owner,person_id=person.id,title="Erinnerung",content="Secret memory body",occurred_at=evening),
                    Memory(owner_id=foreign,person_id=outsider.id,title="Foreign memory",content="secret",occurred_at=morning)])
        db.flush()
        db.add_all([ConversationParticipant(owner_id=owner,conversation_id=conversation.id,person_id=person.id),
                    EventParticipant(owner_id=owner,event_id=event.id,person_id=person.id),
                    JournalEntryPerson(owner_id=owner,entry_id=journal.id,person_id=person.id)])
        db.commit()
        with pytest.raises(IntegrityError,match="tenant_integrity"):
            with db.begin_nested():
                db.add(ConversationParticipant(owner_id=owner,conversation_id=conversation.id,person_id=outsider.id))
                db.flush()
        pid,foreign_pid=person.id,outsider.id
    def read(**params):
        result=client.get("/api/timeline",headers=auth,params=params)
        assert result.status_code==200,result.text
        return result.json()
    full=read(person_id=pid,start="2025-01-03",end="2025-01-03")
    assert full["timezone"]=="Europe/Berlin"
    items=full["items"]
    assert len(items)==9
    assert {r["kind"] for r in items}=={"conversation","event","journal","fact","loan","call","life_event","memory"}
    assert all(r["day"]=="2025-01-03" for r in items)
    assert all(r["people"]==[{"id":pid,"name":"Anna"}] for r in items)
    assert items[0]["occurred_at"]=="2025-01-03T08:00:00Z"
    assert next(r for r in items if r["kind"]=="life_event")["occurred_at"] is None
    assert next(r for r in items if r["kind"]=="fact")["occurrence"]=="end"
    assert next(r for r in items if r["kind"]=="event")["status"]=="appointment"
    assert "Secret" not in str(full) and "Foreign" not in str(full)
    assert read(start="2025-01-02",end="2025-01-02")["items"]==[]
    fact_items=read(kinds=["fact"])["items"]
    assert [r["occurrence"] for r in fact_items]==["end","start"]
    assert [r["day"] for r in fact_items]==["2025-01-03","2020-01-01"]
    page=[]; offset=0
    while offset is not None:
        response=read(person_id=pid,start="2025-01-03",end="2025-01-03",limit=2,offset=offset)
        page.extend(response["items"]);offset=response["next_offset"]
    assert page==items
    assert len({r["id"] for r in page})==len(page)
    assert client.get("/api/timeline",headers=other,params={"person_id":pid}).status_code==404
    assert client.get("/api/timeline",headers=auth,params={"person_id":foreign_pid}).status_code==404
    assert client.get("/api/timeline").status_code==401
    assert client.get("/api/timeline",headers=auth,params={"start":"2025-01-04","end":"2025-01-03"}).status_code==422


def test_undated_and_unconfirmed_are_separate(client):
    owner,auth=account(client)
    with Session(engine) as db:
        person=Person(owner_id=owner,first_name="Thomas")
        db.add(person);db.flush()
        db.add_all([
            Conversation(owner_id=owner,title="Ohne Datum",original_note="Test"),
            PersonLifeEvent(owner_id=owner,person_id=person.id,title="Ungefähres Ereignis",date_precision="approximate",confirmed=True),
            PersonLifeEvent(owner_id=owner,person_id=person.id,title="Unbestätigtes Ereignis",date_precision="unknown",confirmed=False),
            TemporalFact(owner_id=owner,person_id=person.id,predicate="hobby",value="Lesen",value_key=fact_value_key("Lesen"),status="confirmed"),
            TemporalFact(owner_id=owner,person_id=person.id,predicate="hobby",value="Wandern",value_key=fact_value_key("Wandern"),status="proposed",valid_from=date(2020,1,1)),
            TemporalFact(owner_id=owner,person_id=person.id,predicate="hobby",value="Verworfen",value_key=fact_value_key("Verworfen"),status="rejected"),
        ])
        db.commit()
    assert client.get("/api/timeline",headers=auth).json()["items"]==[]
    undated=client.get("/api/timeline",headers=auth,params={"mode":"undated"}).json()["items"]
    assert len(undated)==3
    assert all(r["day"] is None and r["occurred_at"] is None for r in undated)
    assert {r["title"] for r in undated}=={"Ohne Datum","Ungefähres Ereignis","hobby: Lesen"}
    assert len(client.get("/api/timeline",headers=auth,params={"mode":"undated","include_unconfirmed":True}).json()["items"])==4
    proposed=client.get("/api/timeline",headers=auth,params={"include_unconfirmed":True}).json()["items"]
    assert len(proposed)==1 and proposed[0]["status"]=="proposed"
    assert client.get("/api/timeline",headers=auth,params={"mode":"undated","start":"2025-01-01"}).status_code==422
