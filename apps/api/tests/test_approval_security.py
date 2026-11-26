from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from lifepilot import approval_policy
from lifepilot.db import engine
from lifepilot.models import ApprovalRequest, Person, Task, TemporalFact, User
from lifepilot.security import create_token
from lifepilot.temporal_facts import fact_value_key


def account():
    with Session(engine) as db:
        row=User(username="approval-"+uuid4().hex,password_hash="unused")
        db.add(row);db.commit()
        return row.id,{"Authorization":"Bearer "+create_token(row.id)}


def request(owner,operation,rid,payload=None):
    with Session(engine) as db:
        return approval_policy.queue(db,owner,operation,rid,"Test",payload)


def test_approval_expires_deduplicates_and_rejects_changed_resource(client,monkeypatch):
    owner,auth=account()
    _,other=account()
    tick=datetime(2027,1,1,tzinfo=timezone.utc)
    monkeypatch.setattr(approval_policy,"now",lambda:tick)
    # approval_routes imports the clock function directly.
    from lifepilot import approval_routes
    monkeypatch.setattr(approval_routes,"now",lambda:tick)
    tid=client.post("/api/tasks",headers=auth,json={"title":"Vorher"}).json()["id"]
    first=request(owner,"task_delete",tid)
    aid=first["approval_id"]
    assert request(owner,"task_delete",tid)["approval_id"]==aid
    assert client.post("/api/approvals/"+aid+"/approve",headers=other).status_code==404
    assert client.patch("/api/tasks/"+tid,headers=auth,json={"title":"Nachher"}).status_code==200
    assert client.post("/api/approvals/"+aid+"/approve",headers=auth).status_code==409
    second=request(owner,"task_delete",tid)["approval_id"]
    assert second!=aid
    assert client.post("/api/approvals/"+aid+"/approve",headers=auth).status_code==409
    tick+=timedelta(hours=24)
    assert client.get("/api/approvals",headers=auth).json()==[]
    assert client.post("/api/approvals/"+second+"/approve",headers=auth).status_code==409
    assert any(t["id"]==tid for t in client.get("/api/tasks",headers=auth).json())
    third=request(owner,"task_delete",tid)["approval_id"]
    assert client.post("/api/approvals/"+third+"/approve",headers=auth).status_code==200
    assert client.post("/api/approvals/"+third+"/approve",headers=auth).status_code==409
    assert not any(t["id"]==tid for t in client.get("/api/tasks",headers=auth).json())


def test_merge_blocks_new_dependencies_and_rejects_stale_plan(client):
    owner,auth=account()
    source=client.post("/api/people",headers=auth,json={"first_name":"Quelle","notes":"Notiz"}).json()["id"]
    target=client.post("/api/people",headers=auth,json={"first_name":"Ziel"}).json()["id"]
    tid=client.post("/api/tasks",headers=auth,json={"title":"Verknüpft","person_id":source}).json()["id"]
    approval=request(owner,"person_merge",source,{"target_id":target})["approval_id"]
    pending=client.get("/api/approvals",headers=auth).json()[0]
    assert pending["payload"]["linked_records"]==1 and pending["payload"]["target_id"]==target
    assert client.patch("/api/tasks/"+tid,headers=auth,json={"title":"Geändert","person_id":source}).status_code==200
    assert client.post("/api/approvals/"+approval+"/approve",headers=auth).status_code==409
    with Session(engine) as db:
        fact=TemporalFact(owner_id=owner,person_id=source,predicate="hobby",value="Lesen",value_key=fact_value_key("Lesen"))
        db.add(fact);db.commit();fid=fact.id
    with pytest.raises(HTTPException,match="temporal_facts"):
        request(owner,"person_merge",source,{"target_id":target})
    with Session(engine) as db:
        db.delete(db.get(TemporalFact,fid));db.commit()
    fresh=request(owner,"person_merge",source,{"target_id":target})["approval_id"]
    assert fresh!=approval
    assert client.post("/api/approvals/"+fresh+"/approve",headers=auth).status_code==200
    assert client.get("/api/people/"+source,headers=auth).status_code==404
    assert client.get("/api/people/"+target,headers=auth).json()["notes"]=="Notiz"
    assert next(t for t in client.get("/api/tasks",headers=auth).json() if t["id"]==tid)["person_id"]==target


def test_legacy_approval_and_self_person_are_not_executable(client):
    owner,auth=account()
    self_id=client.get("/api/profile",headers=auth).json()["self_person_id"]
    with pytest.raises(HTTPException,match="eigene Personenprofil"):
        request(owner,"person_delete",self_id)
    tid=client.post("/api/tasks",headers=auth,json={"title":"Legacy"}).json()["id"]
    with Session(engine) as db:
        legacy=ApprovalRequest(owner_id=owner,operation="task_delete",resource_id=tid)
        db.add(legacy);db.commit();aid=legacy.id
    assert client.get("/api/approvals",headers=auth).json()==[]
    assert client.post("/api/approvals/"+aid+"/approve",headers=auth).status_code==409


def test_pending_limit_reject_and_new_request(client,monkeypatch):
    owner,auth=account()
    monkeypatch.setattr(approval_policy,"MAX_PENDING",1)
    first=client.post("/api/tasks",headers=auth,json={"title":"Eins"}).json()["id"]
    second=client.post("/api/tasks",headers=auth,json={"title":"Zwei"}).json()["id"]
    aid=request(owner,"task_delete",first)["approval_id"]
    with pytest.raises(HTTPException,match="Zu viele offene Freigaben"):
        request(owner,"task_delete",second)
    assert client.post("/api/approvals/"+aid+"/reject",headers=auth).status_code==200
    assert client.post("/api/approvals/"+aid+"/approve",headers=auth).status_code==409
    assert request(owner,"task_delete",second)["status"]=="pending"
