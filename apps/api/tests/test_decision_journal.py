from datetime import date
from uuid import uuid4

from sqlalchemy.orm import Session
from lifepilot.config import settings
from lifepilot.db import engine
from lifepilot.models import User
from lifepilot.security import create_token
from lifepilot import decision_journal


def account():
    with Session(engine) as db:
        user = User(username="decision-"+uuid4().hex,password_hash="unused")
        db.add(user)
        db.commit()
        return {"Authorization":"Bearer "+create_token(user.id)}


def test_decisions_review_history_and_due(client,monkeypatch,tmp_path):
    monkeypatch.setattr(settings,"data_dir",str(tmp_path))
    day=date(2027,1,10)
    monkeypatch.setattr(decision_journal,"local_today",lambda user:day)
    auth,other=account(),account()
    person=client.post("/api/people",headers=auth,json={"first_name":"Anna"}).json()["id"]
    foreign=client.post("/api/people",headers=other,json={"first_name":"Fremd"}).json()["id"]
    memory=client.post("/api/memories",headers=auth,json={"title":"Notiz","content":"Beleg"}).json()["id"]
    project=client.post("/api/projects",headers=auth,json={"name":"Projekt"}).json()["id"]
    attachment=client.post("/api/attachments",headers=auth,data={"resource_type":"memory","resource_id":memory},files={"file":("beleg.txt",b"Beleg")}).json()["id"]
    path="/api/decisions"
    payload={"title":"Serverwahl","decided_on":"2027-01-01","choice":"Option A","rationale":"Geringere Betriebskosten","expected_outcome":"Kosten sinken","alternatives":[{"title":"Option B","pros":"Mehr Kapazität","cons":"Teurer"}],"review_on":"2027-01-10","person_id":person,"project_id":project,"memory_id":memory,"attachment_id":attachment}
    assert client.get(path).status_code==401
    for extra,code in [({"person_id":foreign},404),({"decided_on":"2027-01-11","review_on":None},422),({"review_on":"2026-12-31"},422),({"rationale":"   "},422),({"status":"closed"},422)]:
        assert client.post(path,headers=auth,json={**payload,**extra}).status_code==code
    response=client.post(path,headers=auth,json=payload)
    assert response.status_code==201,response.text
    entry=response.json()
    eid=entry["id"]
    assert entry["revision"]==0 and entry["status"]=="open"
    assert client.get(path,headers=other).json()==[]
    assert client.get(path+"/"+eid,headers=other).status_code==404
    assert client.get(path+"/"+eid+"/reviews",headers=other).status_code==404
    assert client.get(path,headers=auth,params={"due_only":True}).json()==[entry]
    assert client.get(path,headers=auth,params={"person_id":person,"project_id":project}).json()==[entry]
    assert client.get(path,headers=auth,params={"person_id":foreign}).status_code==404
    briefing=client.get("/api/briefing/daily",headers=auth)
    assert briefing.status_code==200,briefing.text
    assert briefing.json()["due_decisions"]==[{"id":eid,"title":"Serverwahl","review_on":"2027-01-10"}]
    review_path=path+"/"+eid+"/reviews"
    review={"revision":0,"assessment":"as_expected","outcome":"Kosten gesunken","lessons":"Vergleich lohnt sich","next_review_on":"2027-02-01"}
    assert client.post(review_path,headers=other,json=review).status_code==404
    assert client.post(review_path,headers=auth,json={**review,"closed":True}).status_code==422
    assert client.post(review_path,headers=auth,json={**review,"next_review_on":"2027-01-10"}).status_code==422
    first=client.post(review_path,headers=auth,json=review)
    assert first.status_code==201,first.text
    updated=first.json()["decision"]
    assert updated["revision"]==1 and updated["review_on"]=="2027-02-01"
    for key in ("choice","rationale","alternatives","expected_outcome","decided_on","attachment_id"):
        assert updated[key]==entry[key]
    assert client.post(review_path,headers=auth,json=review).status_code==409
    assert client.get(path,headers=auth,params={"due_only":True}).json()==[]
    day=date(2027,2,1)
    assert client.get(path,headers=auth,params={"due_only":True}).json()[0]["id"]==eid
    closed=client.post(review_path,headers=auth,json={"revision":1,"assessment":"better","outcome":"Mehr erreicht","closed":True})
    assert closed.status_code==201,closed.text
    assert closed.json()["decision"]["status"]=="closed"
    assert closed.json()["decision"]["review_on"] is None
    history=client.get(review_path,headers=auth).json()
    assert [r["revision"] for r in history]==[2,1]
    assert history[1]["lessons"]=="Vergleich lohnt sich"
    assert client.get(path,headers=auth,params={"status":"closed"}).json()[0]["id"]==eid
    assert client.get(path,headers=auth,params={"due_only":True}).json()==[]
    reopened=client.post(review_path,headers=auth,json={"revision":2,"assessment":"unclear","outcome":"Neue Umstände","next_review_on":"2027-03-01"})
    assert reopened.status_code==201,reopened.text
    assert reopened.json()["decision"]["status"]=="open"
    assert client.get(review_path,headers=auth,params={"limit":1,"offset":1}).json()[0]["revision"]==2
    assert client.delete("/api/attachments/"+attachment,headers=auth).status_code==204
