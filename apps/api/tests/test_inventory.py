from datetime import date
from uuid import uuid4
from sqlalchemy.orm import Session

from lifepilot.config import settings
from lifepilot.db import engine
from lifepilot.models import User
from lifepilot.security import create_token
from lifepilot import inventory_routes


def account():
    with Session(engine) as db:
        user=User(username="inventory-"+uuid4().hex,password_hash="unused")
        db.add(user);db.commit()
        return {"Authorization":"Bearer "+create_token(user.id)}


def test_inventory_location_maintenance_loans_and_privacy(client,monkeypatch,tmp_path):
    monkeypatch.setattr(settings,"data_dir",str(tmp_path))
    monkeypatch.setattr(inventory_routes,"today",lambda user:date(2027,1,10))
    auth,foreign=account(),account()
    def post(path,payload,headers=auth):
        return client.post(path,headers=headers,json=payload)
    pid=post("/api/people",{"first_name":"Anna"}).json()["id"]
    outsider=post("/api/people",{"first_name":"Andere"},foreign).json()["id"]
    place=post("/api/places",{"name":"Werkstatt"}).json()["id"]
    foreign_place=post("/api/places",{"name":"Andere Werkstatt"},foreign).json()["id"]
    mid=post("/api/memories",{"title":"Rechnung","content":"Beleg"}).json()["id"]
    attachment=client.post("/api/attachments",headers=auth,data={"resource_type":"memory","resource_id":mid},files={"file":("beleg.txt",b"Rechnung")}).json()["id"]
    base="/api/inventory"
    payload={"name":"Bohrmaschine","category":"Werkzeug","serial_number":"A-001","ownership":"own","purchase_on":"2025-01-20","warranty_until":"2027-01-20","receipt_attachment_id":attachment,"maintenance_interval_days":30,"next_maintenance_on":"2027-01-09"}
    assert client.get(base).status_code==401
    for extra,code in [({"ownership":"other","owner_person_id":outsider},404),({"owner_person_id":pid},422),({"maintenance_interval_days":0},422),({"purchase_on":"2027-01-11"},422),({"warranty_until":"2024-01-01"},422),({"name":" "},422)]:
        assert post(base,{**payload,**extra}).status_code==code
    response=post(base,payload)
    assert response.status_code==201,response.text
    item=response.json()
    item_id=item["id"];path=base+"/"+item_id
    assert item["revision"]==0 and item["place_id"] is None
    assert client.get(path,headers=foreign).status_code==404
    assert client.get(base,headers=foreign).json()==[]
    assert post(path+"/move",{"revision":0,"place_id":foreign_place}).status_code==404
    assert post(path+"/move",{"revision":0,"place_id":place},foreign).status_code==404
    moved=post(path+"/move",{"revision":0,"place_id":place,"location_detail":"Regal 2","occurred_on":"2027-01-05","note":"Abgelegt"})
    assert moved.status_code==200,moved.text
    assert moved.json()["place_name"]=="Werkstatt" and moved.json()["revision"]==1
    assert post(path+"/move",{"revision":0,"location_detail":"Falscher Ort"}).status_code==409
    assert client.get(base,headers=auth,params={"q":"Regal 2","place_id":place}).json()[0]["id"]==item_id
    assert client.get(base,headers=auth,params={"q":"Werkstatt"}).json()[0]["id"]==item_id
    assert client.get(base,headers=auth,params={"place_id":foreign_place}).status_code==404
    due=client.get("/api/briefing/daily",headers=auth).json()["due_inventory"]
    assert due==[{"id":item_id,"name":"Bohrmaschine","maintenance_on":"2027-01-09","warranty_until":"2027-01-20"}]
    assert post(path+"/maintenance",{"revision":1,"occurred_on":"2027-01-11","note":"Wartung"}).status_code==422
    serviced=post(path+"/maintenance",{"revision":1,"occurred_on":"2027-01-10","note":"Gereinigt"})
    assert serviced.status_code==200,serviced.text
    assert serviced.json()["next_maintenance_on"]=="2027-02-09"
    assert post(path+"/maintenance",{"revision":2,"occurred_on":"2027-01-09","note":"Alt"}).status_code==409
    loan=post("/api/loans",{"item_name":"Bohrer","borrower_person_id":pid}).json()["id"]
    second=post("/api/loans",{"item_name":"Anderer Eintrag","borrower_person_id":pid}).json()["id"]
    foreign_loan=post("/api/loans",{"item_name":"Fremd","borrower_person_id":outsider},foreign).json()["id"]
    assert post(path+"/loans/link",{"revision":2,"loan_id":foreign_loan}).status_code==404
    linked=post(path+"/loans/link",{"revision":2,"loan_id":loan})
    assert linked.status_code==200,linked.text
    assert linked.json()["open_loan"]["id"]==loan and linked.json()["location_detail"]=="Regal 2"
    assert post(path+"/loans/link",{"revision":3,"loan_id":second}).status_code==409
    another=post(base,{"name":"Zweite Maschine"}).json()["id"]
    assert post(base+"/"+another+"/loans/link",{"revision":0,"loan_id":loan}).status_code==409
    assert client.patch(path+"/archive",headers=auth,json={"revision":3,"archived":True}).status_code==409
    assert client.patch("/api/loans/"+loan+"/return",headers=auth).status_code==200
    after=client.get(path,headers=auth).json()
    assert after["open_loan"] is None and after["location_detail"]=="Regal 2"
    assert client.get(path+"/loans",headers=auth).json()[0]["returned_at"] is not None
    assert post(path+"/loans/link",{"revision":3,"loan_id":second}).status_code==200
    assert post(path+"/loans/unlink",{"revision":4,"loan_id":second}).status_code==200
    assert any(r["id"]==second for r in client.get("/api/loans",headers=auth).json())
    history=client.get(path+"/history",headers=auth).json()
    assert [r["kind"] for r in history]==["loan_link","loan_link","loan_link","maintenance","location"]
    assert history[-1]["details"]["after"]["place_name"]=="Werkstatt"
    assert client.get(path+"/history",headers=foreign).status_code==404
    assert client.get(path+"/loans",headers=foreign).status_code==404
    updated=client.put(path,headers=auth,json={**payload,"revision":5,"name":"Bohrmaschine 2","next_maintenance_on":"2027-02-09"})
    assert updated.status_code==200,updated.text
    assert updated.json()["location_detail"]=="Regal 2"
    assert client.patch(path+"/archive",headers=auth,json={"revision":6,"archived":True}).status_code==200
    assert client.get(base,headers=auth,params={"due_only":True}).json()==[]
    assert client.get("/api/briefing/daily",headers=auth).json()["due_inventory"]==[]
    assert post(path+"/move",{"revision":7,"location_detail":"Keller"}).status_code==409
    assert client.patch(path+"/archive",headers=auth,json={"revision":7,"archived":False}).status_code==200
    assert client.delete("/api/attachments/"+attachment,headers=auth).status_code==204
    assert client.get(path,headers=auth).json()["receipt_attachment_id"] is None
