from uuid import uuid4

from sqlalchemy.orm import Session
from lifepilot.db import engine
from lifepilot.models import Memory, PlaceEntry, User
from lifepilot.security import create_token


def account():
    with Session(engine) as db:
        user=User(username="place-"+uuid4().hex,password_hash="unused")
        db.add(user)
        db.commit()
        return {"Authorization":"Bearer "+create_token(user.id)}


def test_place_entries_search_graph_timeline_and_archive(client):
    auth,other=account(),account()
    pid=client.post("/api/people",headers=auth,json={"first_name":"Anna"}).json()["id"]
    foreign=client.post("/api/people",headers=other,json={"first_name":"Fremd"}).json()["id"]
    memory=client.post("/api/memories",headers=auth,json={"title":"Erinnerung","content":"Ausflug"}).json()["id"]
    base="/api/places"
    payload={"name":"Café Test","category":"Restaurant","address":"Teststraße 1","latitude":50.8,"longitude":6.5,"notes":"Empfehlenswert"}
    assert client.get(base).status_code==401
    for extra in ({"name":" "},{"latitude":None},{"longitude":181},{"latitude":91},{"archived":True}):
        assert client.post(base,headers=auth,json={**payload,**extra}).status_code==422
    result=client.post(base,headers=auth,json=payload)
    assert result.status_code==201,result.text
    place=result.json()
    aid=place["id"]
    path=base+"/"+aid
    assert place["latitude"]==50.8 and not place["archived"]
    assert client.get(base,headers=other).json()==[]
    assert client.get(path,headers=other).status_code==404
    assert client.put(path,headers=other,json=payload).status_code==404
    assert client.delete(path,headers=other).status_code==404
    entry={"kind":"meeting","title":"Kennenlernen","notes":"Gemeinsamer Kaffee","occurred_on":"2024-05-03","person_id":pid,"memory_id":memory}
    assert client.post(path+"/entries",headers=auth,json={**entry,"person_id":foreign}).status_code==404
    assert client.post(path+"/entries",headers=other,json=entry).status_code==404
    response=client.post(path+"/entries",headers=auth,json=entry)
    assert response.status_code==201,response.text
    eid=response.json()["id"]
    undated=client.post(path+"/entries",headers=auth,json={"kind":"recommendation","title":"Nochmal besuchen"})
    assert undated.status_code==201,undated.text
    for q in ("Café","restaurant","Teststraße","Kennenlernen","Kaffee"):
        assert [row["id"] for row in client.get(base,headers=auth,params={"q":q}).json()]==[aid]
    assert client.get(base,headers=auth,params={"person_id":pid}).json()[0]["id"]==aid
    assert client.get(base,headers=auth,params={"person_id":foreign}).status_code==404
    assert client.get(path+"/entries",headers=auth,params={"kind":"meeting"}).json()[0]["id"]==eid
    assert client.get(path+"/entries",headers=other).status_code==404
    assert client.delete(path+"/entries/"+eid,headers=other).status_code==404
    graph=client.get("/api/graph",headers=auth,params={"root_kind":"person","root_id":pid,"depth":2}).json()
    assert "place:"+aid in {n["id"] for n in graph["nodes"]}
    assert "place_entry:"+eid in {n["id"] for n in graph["nodes"]}
    dated=client.get("/api/timeline",headers=auth,params={"kinds":["place_entry"],"person_id":pid}).json()["items"]
    assert len(dated)==1 and dated[0]["day"]=="2024-05-03" and dated[0]["status"]=="meeting"
    assert dated[0]["occurred_at"] is None
    unknown=client.get("/api/timeline",headers=auth,params={"kinds":["place_entry"],"mode":"undated"}).json()["items"]
    assert len(unknown)==1 and unknown[0]["day"] is None
    edited=client.put(path,headers=auth,json={**payload,"name":"Café Neu","latitude":None,"longitude":None})
    assert edited.status_code==200,edited.text
    assert edited.json()["latitude"] is None
    assert client.patch(path+"/archive",headers=auth,json={"archived":True}).json()["archived"]
    assert client.get(base,headers=auth).json()==[]
    assert client.get(base,headers=auth,params={"archived":True}).json()[0]["id"]==aid
    assert client.post(path+"/entries",headers=auth,json=entry).status_code==409
    assert len(client.get(path+"/entries",headers=auth).json())==2
    assert not client.patch(path+"/archive",headers=auth,json={"archived":False}).json()["archived"]
    assert client.delete(path+"/entries/"+eid,headers=auth).status_code==204
    assert len(client.get(path+"/entries",headers=auth).json())==1
    assert client.delete(path,headers=auth).status_code==204
    assert client.get(path,headers=auth).status_code==404
    assert client.get("/api/people/"+pid,headers=auth).status_code==200
    assert client.get("/api/timeline",headers=auth,params={"kinds":["place_entry"],"mode":"undated"}).json()["items"]==[]
    with Session(engine) as db:
        assert db.get(Memory,memory) is not None
        assert db.get(PlaceEntry,undated.json()["id"]) is None
