from uuid import uuid4

from sqlalchemy.orm import Session

from lifepilot.db import engine
from lifepilot.models import User
from lifepilot.security import create_token, hash_password


def account():
    username="family-"+uuid4().hex
    with Session(engine) as db:
        user=User(username=username,password_hash=hash_password("test-password"))
        db.add(user);db.commit()
        return user.id,username,{"Authorization":"Bearer "+create_token(user.id)}


def test_family_permissions_snapshots_and_revocation(client):
    owner,owner_name,a=account()
    viewer,viewer_name,b=account()
    editor,editor_name,c=account()
    outsider,outsider_name,d=account()
    base="/api/family"
    def post(path,data=None,auth=a):
        return client.post(path,headers=auth,json=data)
    def get(path,auth=a):
        return client.get(path,headers=auth)
    def put(path,data,auth=a):
        return client.put(path,headers=auth,json=data)
    assert client.get(base).status_code==401
    response=post(base,{"name":"Unser Haushalt"})
    assert response.status_code==201,response.text
    space=response.json()
    path=base+"/"+space["id"]
    assert space["role"]=="owner"
    assert get(base,d).json()=={"spaces":[],"invitations":[]}
    assert post(path+"/invite",{"username":viewer_name,"role":"viewer"}).status_code==204
    assert post(path+"/invite",{"username":editor_name,"role":"editor"}).status_code==204
    assert post(path+"/invite",{"username":viewer_name}).status_code==409
    assert post(path+"/invite",{"username":owner_name}).status_code==404
    assert get(base,b).json()["spaces"]==[]
    assert get(base,b).json()["invitations"][0]["id"]==space["id"]
    for suffix in ("/members","/items","/shares"):
        assert get(path+suffix,b).status_code==404
        assert get(path+suffix,d).status_code==404
    assert post(path+"/accept",auth=d).status_code==404
    assert post(path+"/accept",auth=b).status_code==204
    assert post(path+"/accept",auth=c).status_code==204
    assert post(path+"/accept",auth=c).status_code==404
    assert get(base,b).json()["spaces"]==[{"id":space["id"],"name":space["name"],"role":"viewer"}]
    assert get(path+"/members",b).headers["cache-control"]=="private, no-store"
    assert post(path+"/invite",{"username":outsider_name},b).status_code==403
    assert post(path+"/items",{"kind":"task","title":"Nicht erlaubt"},b).status_code==403
    assert post(path+"/items",{"kind":"event","title":"Ohne Beginn"},c).status_code==422
    assert post(path+"/items",{"kind":"event","title":"Ohne Zeitzone","starts_at":"2027-01-01T10:00:00"},c).status_code==422
    data={"kind":"task","title":"Einkaufen","notes":"Milch","starts_at":"2027-01-01T10:00:00+01:00"}
    result=post(path+"/items",data,c)
    assert result.status_code==201,result.text
    item=result.json()
    assert item["starts_at"]=="2027-01-01T09:00:00+00:00"
    iid=item["id"]
    item_path=path+"/items/"+iid
    assert get(path+"/items",b).json()==[item]
    assert put(item_path,{**data,"revision":0,"status":"done"},b).status_code==403
    done=put(item_path,{**data,"revision":0,"status":"done"},c)
    assert done.status_code==200,done.text
    assert done.json()["revision"]==1 and done.json()["status"]=="done"
    assert put(item_path,{**data,"revision":0},c).status_code==409
    private_task=post("/api/tasks",{"title":"Nur privat","description":"Geheimer Text"}).json()
    task_id=private_task["id"]
    assert all(t["id"]!=task_id for t in get("/api/tasks",b).json())
    assert not any(t["title"]=="Einkaufen" for t in get("/api/tasks",a).json())
    own_memory=post("/api/memories",{"title":"Meine Notiz","content":"Privater Text"},c).json()
    memory_id=own_memory["id"]
    assert get(path+"/shares",b).json()==[]
    assert post(path+"/shares/preview",{"kind":"task","resource_id":task_id},c).status_code==404
    assert post(path+"/shares/preview",{"kind":"memory","resource_id":memory_id},b).status_code==403
    opts={"kind":"task","resource_id":task_id}
    preview=post(path+"/shares/preview",opts).json()
    assert preview["snapshot"]=={"title":"Nur privat"}
    assert post(path+"/shares",{**opts,"digest":"0"*64}).status_code==409
    shared=post(path+"/shares",{**opts,"digest":preview["digest"]})
    assert shared.status_code==201,shared.text
    sid=shared.json()["id"]
    assert post(path+"/shares",{**opts,"digest":preview["digest"]}).status_code==409
    received=get(path+"/shares",b).json()[0]
    assert received["snapshot"]=={"title":"Nur privat"} and not received["can_revoke"]
    assert "resource_id" not in received and "owner_id" not in received
    assert client.delete(path+"/shares/"+sid,headers=b).status_code==404
    opts={"kind":"memory","resource_id":memory_id,"include_notes":True}
    preview=post(path+"/shares/preview",opts,c).json()
    assert preview["snapshot"]=={"title":"Meine Notiz","notes":"Privater Text"}
    created=post(path+"/shares",{**opts,"digest":preview["digest"]},c)
    assert created.status_code==201,created.text
    assert get(path+"/shares",b).json()[0]["snapshot"]["notes"]=="Privater Text"
    assert client.delete("/api/memories/"+memory_id,headers=c).status_code==204
    # Explicit snapshots are independent of private originals.
    assert any(s["id"]==created.json()["id"] for s in get(path+"/shares",b).json())
    assert client.patch(path+"/members/"+editor,headers=a,json={"role":"viewer"}).status_code==204
    assert put(item_path,{**data,"revision":1},c).status_code==403
    assert client.delete(path+"/shares/"+created.json()["id"],headers=c).status_code==204
    assert client.delete(path+"/members/"+viewer,headers=a).status_code==204
    assert get(path+"/items",b).status_code==404
    assert get(path+"/shares",b).status_code==404
    assert post(path+"/leave",auth=c).status_code==204
    assert get(path+"/items",c).status_code==404
    assert get(path+"/items").json()[0]["id"]==iid
    assert client.delete(path+"/shares/"+sid,headers=a).status_code==204
    assert get(path+"/shares").json()==[]
    assert post(item_path+"/delete",{"revision":0}).status_code==409
    assert post(item_path+"/delete",{"revision":1}).status_code==204
    assert post(path+"/delete",{"password":"wrong"}).status_code==403
    assert post(path+"/delete",{"password":"test-password"}).status_code==204
    assert get(path+"/items").status_code==404
    assert any(t["id"]==task_id for t in get("/api/tasks").json())
