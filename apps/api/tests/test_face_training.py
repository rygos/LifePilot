from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy.orm import Session
from lifepilot.db import engine
from lifepilot.models import User, Person
from lifepilot.security import hash_password
from lifepilot import face_training


def account(client):
    name = "training-" + uuid4().hex
    with Session(engine) as db:
        user = User(username=name, password_hash=hash_password("test-password"))
        db.add(user); db.commit(); owner=user.id
    token=client.post("/api/auth/login",json={"username":name,"password":"test-password"}).json()["access_token"]
    return owner, {"Authorization":"Bearer "+token}


def person(owner, photo=True):
    with Session(engine) as db:
        row=Person(owner_id=owner,first_name="Anna",last_name="Test",nickname="Anni",organization="Verein",photo_key=uuid4().hex+".jpg" if photo else None)
        db.add(row);db.commit();return row.id


def test_schedule_pause_and_photo_change(client,monkeypatch,tmp_path):
    owner,auth=account(client)
    other,foreign=account(client)
    pid=person(owner)
    from lifepilot.config import settings
    monkeypatch.setattr(settings,"data_dir",str(tmp_path))
    (tmp_path/"people").mkdir()
    with Session(engine) as db:
        (tmp_path/"people"/db.get(Person,pid).photo_key).write_bytes(b"test-photo")
    no_photo=person(owner,False)
    outsider=person(other)
    current=datetime(2027,1,1,8,tzinfo=timezone.utc)
    monkeypatch.setattr(face_training,"now",lambda:current)
    path="/api/training/faces"
    def enroll(pid=pid,active=True):
        return client.post(path+"/enroll",headers=auth,json={"person_id":pid,"active":active})
    assert client.get(path,headers=auth).json()==[]
    assert client.get(path).status_code==401
    assert enroll(no_photo).status_code==422
    assert enroll(outsider).status_code==404
    response=enroll()
    assert response.status_code==200,response.text
    card=response.json()
    assert card["due"] and card["name"]=="Anna Test" and card["context"]=="Verein"
    assert "photo_key" not in card
    photo_url=path+"/"+card["id"]+"/photo?revision=0"
    image=client.get(photo_url,headers=auth)
    assert image.status_code==200 and image.content==b"test-photo" and "no-store" in image.headers["cache-control"]
    assert client.get(photo_url,headers=foreign).status_code==404
    assert enroll().json()["id"]==card["id"]
    assert len(client.get(path,headers=auth).json())==1
    assert client.get(path,headers=foreign).json()==[]
    url=path+"/"+card["id"]+"/review"
    def review(rating, revision):
        return client.post(url,headers=auth,json={"rating":rating,"revision":revision})
    assert client.post(url,headers=foreign,json={"rating":"good","revision":0}).status_code==404
    for rating,delay,level in [("good",timedelta(days=1),1),("good",timedelta(days=3),2),("easy",timedelta(days=14),4),("hard",timedelta(days=1),3),("again",timedelta(minutes=10),0)]:
        previous=card["revision"]
        result=review(rating,previous)
        assert result.status_code==200,result.text
        card=result.json()
        assert card["level"]==level
        assert datetime.fromisoformat(card["due_at"])==current+delay
        assert not card["due"]
        assert review(rating,previous).status_code==409
        assert review(rating,card["revision"]).status_code==409
        assert client.get(path,headers=auth,params={"due_only":True}).json()==[]
        current+=delay
    assert card["review_count"]==5
    paused=enroll(active=False).json()
    assert not paused["active"] and not paused["due"]
    assert review("good",paused["revision"]).status_code==409
    resumed=enroll().json()
    assert resumed["due"] and resumed["review_count"]==5
    with Session(engine) as db:
        row=db.get(Person,pid);row.photo_key=uuid4().hex+".jpg";db.commit()
    changed=client.get(path,headers=auth).json()[0]
    assert changed["photo_changed"] and not changed["available"]
    assert client.get(path+"/"+card["id"]+"/photo",headers=auth,params={"revision":changed["revision"]}).status_code==409
    assert review("good",changed["revision"]).status_code==409
    reset=enroll().json()
    assert reset["due"] and reset["review_count"]==0 and reset["level"]==0
    with Session(engine) as db:
        db.get(Person,pid).photo_key=None;db.commit()
    assert not client.get(path,headers=auth).json()[0]["available"]
    assert enroll().status_code==422
    assert client.delete("/api/people/"+pid,headers=auth).status_code==204
    assert client.get(path,headers=auth).json()==[]
