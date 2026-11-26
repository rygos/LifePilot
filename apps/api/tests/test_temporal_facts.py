from uuid import uuid4
from sqlalchemy.orm import Session

from lifepilot.config import settings
from lifepilot.db import engine
from lifepilot.models import User
from lifepilot.security import hash_password


def account(client):
    name = "fact-" + uuid4().hex
    with Session(engine) as db:
        db.add(User(username=name, password_hash=hash_password("test-password")))
        db.commit()
    token = client.post("/api/auth/login", json={"username": name, "password": "test-password"}).json()["access_token"]
    return {"Authorization":"Bearer "+token}


def test_temporal_history_and_evidence(client, monkeypatch):
    monkeypatch.setattr(settings, "llm_base_url", "")
    auth, other = account(client), account(client)
    person = client.post("/api/people",headers=auth,json={"first_name":"Anna"}).json()["id"]
    capture = client.post("/api/captures",headers=auth,json={"original_text":"Anna wohnte ab 2015 in Köln."}).json()["id"]
    payload = {"person_id":person,"predicate":" Wohnort ","value":"Köln","valid_from":"2015-01-01","confidence":"high","source_capture_id":capture,"source_quote":"Anna wohnte ab 2015 in Köln."}
    path="/api/facts"
    assert client.post(path,headers=auth,json={**payload,"source_quote":"Falsches Zitat"}).status_code==422
    assert client.post(path,headers=auth,json={**payload,"source_quote":None}).status_code==422
    assert client.post(path,headers=auth,json={**payload,"valid_until":"2014-01-01"}).status_code==422
    assert client.post(path,headers=auth,json={**payload,"status":"confirmed"}).status_code==422
    assert client.post(path,headers=other,json=payload).status_code==404
    own_person=client.post("/api/people",headers=other,json={"first_name":"Andere"}).json()["id"]
    assert client.post(path,headers=other,json={**payload,"person_id":own_person}).status_code==404
    created=client.post(path,headers=auth,json=payload)
    assert created.status_code==201,created.text
    row=created.json()
    assert row["status"]=="proposed" and row["predicate"]=="wohnort"
    rid=row["id"]
    assert client.get(path+"?status=confirmed",headers=auth).json()==[]
    assert client.patch(f"{path}/{rid}/end",headers=auth,json={"valid_until":"2020-01-01"}).status_code==409
    assert client.patch(f"{path}/{rid}/status",headers=other,json={"status":"confirmed"}).status_code==404
    assert client.patch(f"{path}/{rid}/status",headers=auth,json={"status":"confirmed"}).status_code==200
    assert client.patch(f"{path}/{rid}/end",headers=auth,json={"valid_until":"2015-01-01"}).status_code==422
    assert client.patch(f"{path}/{rid}/end",headers=auth,json={"valid_until":"2020-01-01"}).status_code==200
    assert client.patch(f"{path}/{rid}/end",headers=auth,json={"valid_until":"2021-01-01"}).status_code==409
    next_fact=client.post(path,headers=auth,json={"person_id":person,"predicate":"Wohnort","value":"Bonn","valid_from":"2020-01-01"}).json()
    assert client.patch(f"{path}/{next_fact['id']}/status",headers=auth,json={"status":"confirmed"}).status_code==200
    for day,expected in [("2014-12-31",[]),("2019-12-31",["Köln"]),("2020-01-01",["Bonn"])]:
        data=client.get(path,headers=auth,params={"person_id":person,"predicate":"WOHNORT","status":"confirmed","as_of":day}).json()
        assert [x["value"] for x in data]==expected
    briefing=client.get("/api/briefing/person/"+person,headers=auth).json()
    assert [x["value"] for x in briefing["current_fact_candidates"]]==["Bonn"]
    assert client.get(path,headers=other).json()==[]
    assert client.get(path+"?person_id="+person,headers=other).status_code==404
    assert client.patch(f"{path}/{next_fact['id']}/status",headers=auth,json={"status":"rejected"}).status_code==200
    assert client.get("/api/briefing/person/"+person,headers=auth).json()["current_fact_candidates"]==[]
    assert len(client.get(path,headers=auth).json())==2
    assert client.get("/api/people/"+person,headers=auth).json()["address"]==""


def test_unknown_bounds_and_pagination(client):
    auth=account(client)
    person=client.post("/api/people",headers=auth,json={"first_name":"Thomas"}).json()["id"]
    path="/api/facts"
    for value in ("Lesen","Wandern"):
        row=client.post(path,headers=auth,json={"person_id":person,"predicate":"Hobby","value":value}).json()
        assert row["valid_from"] is None and row["valid_until"] is None
        assert client.patch(f"{path}/{row['id']}/status",headers=auth,json={"status":"confirmed"}).status_code==200
    data=client.get(path,headers=auth,params={"as_of":"2010-01-01","limit":1}).json()
    next_page=client.get(path,headers=auth,params={"as_of":"2010-01-01","limit":1,"offset":1}).json()
    assert len(data)==len(next_page)==1 and data[0]["id"]!=next_page[0]["id"]
    assert client.get(path,headers=auth,params={"limit":201}).status_code==422
