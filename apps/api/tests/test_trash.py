from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from lifepilot.config import settings
from lifepilot.db import engine
from lifepilot.models import ApprovalRequest, FocusSession, InventoryLoan, JournalEntryPerson, Reminder, Task, TrashEntry, User, WorkCheckpoint
from lifepilot.security import create_token, hash_password
from lifepilot import trash_routes


def account():
    with Session(engine) as db:
        user=User(username="trash-"+uuid4().hex,password_hash=hash_password("test-password"))
        db.add(user); db.commit()
        return user.id,{"Authorization":"Bearer "+create_token(user.id)}


def test_task_restore_and_approval_are_atomic(client,monkeypatch):
    owner,auth=account()
    _,other=account()
    current=datetime(2027,1,1,10,tzinfo=timezone.utc)
    monkeypatch.setattr(trash_routes,"now",lambda:current)
    monkeypatch.setattr(settings,"trash_retention_days",7)
    task=client.post("/api/tasks",headers=auth,json={"title":"Testaufgabe"}).json()
    tid=task["id"]
    steps=client.post("/api/tasks/"+tid+"/steps",headers=auth,json={"steps":[{"title":"Erster Schritt"}]}).json()
    assert steps[0]["title"]=="Erster Schritt"
    with Session(engine) as db:
        reminder=Reminder(owner_id=owner,task_id=tid,title="Test",due_at=current,state="muted")
        checkpoint=WorkCheckpoint(owner_id=owner,task_id=tid,title="Zwischenstand",next_step="Weiter")
        pending=ApprovalRequest(owner_id=owner,operation="task_delete",resource_id=tid,resource_label="Testaufgabe")
        db.add_all([reminder,checkpoint,pending]);db.commit()
        rid,cid,approval=reminder.id,checkpoint.id,pending.id
    assert client.delete("/api/tasks/"+tid,headers=other).status_code==404
    assert client.delete("/api/tasks/"+tid,headers=auth).status_code==204
    listing=client.get("/api/trash",headers=auth).json()
    assert listing["retention_days"]==7 and len(listing["items"])==1
    entry=listing["items"][0]; eid=entry["id"]
    assert entry["resource_id"]==tid and entry["related_records"]==3
    assert "snapshot" not in entry
    assert datetime.fromisoformat(entry["expires_at"])==current+timedelta(days=7)
    assert client.get("/api/trash",headers=other).json()["items"]==[]
    assert client.post("/api/trash/"+eid+"/restore",headers=other).status_code==404
    assert client.get("/api/tasks/"+tid+"/steps",headers=auth).status_code==404
    with Session(engine) as db:
        assert db.get(Task,tid) is None and db.get(Reminder,rid) is None
        assert db.get(WorkCheckpoint,cid).task_id is None
        assert db.get(ApprovalRequest,approval).status=="rejected"
    assert client.post("/api/approvals/"+approval+"/approve",headers=auth).status_code==409
    restored=client.post("/api/trash/"+eid+"/restore",headers=auth)
    assert restored.status_code==200,restored.text
    assert restored.json()["resource_id"]==tid
    assert client.get("/api/tasks/"+tid+"/steps",headers=auth).json()==steps
    with Session(engine) as db:
        assert db.get(Reminder,rid).state=="muted"
        assert db.get(WorkCheckpoint,cid).task_id==tid
        pending=ApprovalRequest(owner_id=owner,operation="task_delete",resource_id=tid,resource_label="Testaufgabe")
        db.add(pending);db.commit();aid=pending.id
    assert client.post("/api/trash/"+eid+"/restore",headers=auth).status_code==404
    approved=client.post("/api/approvals/"+aid+"/approve",headers=auth)
    assert approved.status_code==200,approved.text
    assert approved.json()["status"]=="executed"
    entry=client.get("/api/trash",headers=auth).json()["items"][0]
    assert entry["resource_id"]==tid
    assert client.post("/api/trash/"+entry["id"]+"/purge",headers=auth,json={"password":"wrong"}).status_code==403
    assert client.post("/api/trash/"+entry["id"]+"/purge",headers=auth,json={"password":"test-password"}).status_code==204
    assert client.post("/api/trash/"+entry["id"]+"/restore",headers=auth).status_code==404


def test_place_restore_preserves_inventory_and_rejects_conflict(client):
    _,auth=account()
    place=client.post("/api/places",headers=auth,json={"name":"Werkstatt"}).json()
    pid=place["id"]
    place_entry=client.post("/api/places/"+pid+"/entries",headers=auth,json={"kind":"visit","title":"Besuch","occurred_on":"2024-05-01"}).json()
    item=client.post("/api/inventory",headers=auth,json={"name":"Hammer"}).json()
    item_path="/api/inventory/"+item["id"]
    assert client.post(item_path+"/move",headers=auth,json={"revision":0,"place_id":pid,"location_detail":"Regal"}).status_code==200
    assert client.delete("/api/places/"+pid,headers=auth).status_code==204
    entry=client.get("/api/trash",headers=auth).json()["items"][0]
    assert entry["related_records"]==2
    assert client.get(item_path,headers=auth).json()["place_id"] is None
    restored=client.post("/api/trash/"+entry["id"]+"/restore",headers=auth)
    assert restored.status_code==200,restored.text
    assert client.get("/api/places/"+pid+"/entries",headers=auth).json()[0]["id"]==place_entry["id"]
    moved=client.get(item_path,headers=auth).json()
    assert moved["place_id"]==pid and moved["location_detail"]=="Regal"
    assert client.delete("/api/places/"+pid,headers=auth).status_code==204
    entry=client.get("/api/trash",headers=auth).json()["items"][0]
    changed=client.get(item_path,headers=auth).json()
    assert client.post(item_path+"/move",headers=auth,json={"revision":changed["revision"],"location_detail":"Neues Regal"}).status_code==200
    conflict=client.post("/api/trash/"+entry["id"]+"/restore",headers=auth)
    assert conflict.status_code==409,conflict.text
    assert client.get("/api/places/"+pid,headers=auth).status_code==404
    assert client.get(item_path,headers=auth).json()["location_detail"]=="Neues Regal"
    assert client.get("/api/trash",headers=auth).json()["items"][0]["id"]==entry["id"]


def test_journal_links_loan_conflict_and_expiry(client,monkeypatch):
    owner,auth=account()
    current=datetime(2027,1,1,10,tzinfo=timezone.utc)
    monkeypatch.setattr(trash_routes,"now",lambda:current)
    monkeypatch.setattr(settings,"trash_retention_days",1)
    person=client.post("/api/people",headers=auth,json={"first_name":"Test"}).json()["id"]
    journal=client.post("/api/journal",headers=auth,json={"entry_date":"2024-01-01","title":"Test","content":"Private Notiz","person_ids":[person]}).json()
    jid=journal["id"]
    assert client.delete("/api/journal/"+jid,headers=auth).status_code==204
    eid=client.get("/api/trash",headers=auth).json()["items"][0]["id"]
    assert client.post("/api/trash/"+eid+"/restore",headers=auth).status_code==200
    assert client.get("/api/journal/"+jid,headers=auth).json()["person_ids"]==[person]
    item=client.post("/api/inventory",headers=auth,json={"name":"Hammer"}).json()["id"]
    loan=client.post("/api/loans",headers=auth,json={"item_name":"Hammer","borrower_person_id":person}).json()["id"]
    assert client.post("/api/inventory/"+item+"/loans/link",headers=auth,json={"revision":0,"loan_id":loan}).status_code==200
    assert client.delete("/api/loans/"+loan,headers=auth).status_code==204
    entry=client.get("/api/trash",headers=auth).json()["items"][0]
    with Session(engine) as db:
        assert db.get(InventoryLoan,loan) is None
    second=client.post("/api/loans",headers=auth,json={"item_name":"Hammer neu","borrower_person_id":person}).json()["id"]
    assert client.post("/api/inventory/"+item+"/loans/link",headers=auth,json={"revision":1,"loan_id":second}).status_code==200
    assert client.post("/api/trash/"+entry["id"]+"/restore",headers=auth).status_code==409
    assert client.patch("/api/loans/"+second+"/return",headers=auth).status_code==200
    result=client.post("/api/trash/"+entry["id"]+"/restore",headers=auth)
    assert result.status_code==200,result.text
    assert client.get("/api/inventory/"+item,headers=auth).json()["open_loan"]["id"]==loan
    gift=client.post("/api/gifts",headers=auth,json={"person_id":person,"title":"Geschenk"}).json()["id"]
    assert client.delete("/api/gifts/"+gift,headers=auth).status_code==204
    eid=client.get("/api/trash",headers=auth).json()["items"][0]["id"]
    current+=timedelta(days=1)
    assert client.get("/api/trash",headers=auth).json()["items"]==[]
    assert client.post("/api/trash/"+eid+"/restore",headers=auth).status_code==404
    with Session(engine) as db:
        trash_routes.cleanup_expired(db)
        db.commit()
        assert db.get(TrashEntry,eid) is None
