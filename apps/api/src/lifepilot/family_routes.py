"""Separate family workspaces. Never broaden private resource queries."""
import hashlib
import json
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from lifepilot.db import get_db
from lifepilot.models import AuditEvent, Event, FamilyItem, FamilyMembership, FamilyShare, FamilySpace, InventoryItem, Memory, Task, User
from lifepilot.security import current_user, verify_password

router = APIRouter(prefix="/api/family", tags=["Familienbereiche"])
Role = Literal["viewer","editor"]
Kind = Literal["note","task","event","inventory"]
ShareKind = Literal["memory","task","event","inventory"]
MODELS = {"memory":Memory,"task":Task,"event":Event,"inventory":InventoryItem}
MAX_SPACES, MAX_MEMBERS, MAX_CONTENT = 10, 20, 500


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid",str_strip_whitespace=True)


class SpaceIn(Input):
    name: str = Field(min_length=1,max_length=120)


class InviteIn(Input):
    username: str = Field(min_length=1,max_length=120)
    role: Role = "viewer"


class RoleIn(Input):
    role: Role


class ItemIn(Input):
    kind: Kind
    title: str = Field(min_length=1,max_length=240)
    notes: str = Field(default="",max_length=10000)
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    location: str = Field(default="",max_length=500)
    status: Literal["open","done"] = "open"

    @field_validator("starts_at","ends_at")
    @classmethod
    def normalize_time(cls,value):
        if value is not None:
            if value.tzinfo is None:
                raise ValueError("Zeitpunkt benötigt eine Zeitzone")
            return value.astimezone(timezone.utc)
        return value

    @model_validator(mode="after")
    def validate_kind(self):
        if self.kind=="event" and self.starts_at is None:
            raise ValueError("Termin benötigt einen Beginn")
        if self.ends_at and (self.kind!="event" or self.starts_at is None or self.ends_at<self.starts_at):
            raise ValueError("Ungültiges Terminende")
        if self.starts_at and self.kind not in ("task","event"):
            raise ValueError("Zeitpunkt nur für Aufgaben oder Termine")
        if self.status=="done" and self.kind!="task":
            raise ValueError("Erledigt ist nur für Aufgaben verfügbar")
        return self


class ItemUpdate(ItemIn):
    revision: int = Field(ge=0)


class RevisionIn(Input):
    revision: int = Field(ge=0)


class SharePreview(Input):
    kind: ShareKind
    resource_id: str = Field(min_length=1,max_length=36)
    include_notes: bool = False
    include_details: bool = False


class ShareIn(SharePreview):
    digest: str = Field(pattern=r"^[a-f0-9]{64}$")


class PasswordIn(BaseModel):
    model_config=ConfigDict(extra="forbid")
    password: str = Field(min_length=1,max_length=1024)


def private_response(response:Response):
    response.headers["Cache-Control"]="private, no-store"


def audit(db,actor,action,table,rid):
    db.add(AuditEvent(owner_id=actor,action=action,resource_type=table,resource_id=rid,source="web"))


def utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def stamp(value):
    return utc(value).isoformat() if value is not None else None


def active_user(db,uid):
    return db.scalar(select(User.id).where(User.id==uid,User.deleted_at.is_(None))) is not None


def access(db,actor,sid,level="read",lock=False):
    # Lock the space before all modifications; membership changes and writes serialize.
    if not active_user(db,actor):
        raise HTTPException(404,"Familienbereich nicht gefunden")
    stmt=select(FamilySpace).join(User,User.id==FamilySpace.owner_id).where(FamilySpace.id==sid,User.deleted_at.is_(None))
    if lock:
        stmt=stmt.with_for_update(of=FamilySpace)
    space=db.scalar(stmt.execution_options(populate_existing=True))
    if space is None:
        raise HTTPException(404,"Familienbereich nicht gefunden")
    if space.owner_id==actor:
        return space,"owner"
    member=db.scalar(select(FamilyMembership).where(FamilyMembership.space_id==sid,FamilyMembership.user_id==actor,FamilyMembership.state=="active").execution_options(populate_existing=True))
    if member is None:
        raise HTTPException(404,"Familienbereich nicht gefunden")
    if level=="owner" or (level=="write" and member.role!="editor"):
        raise HTTPException(403,"Keine Berechtigung für diese Aktion")
    return space,member.role


def space_view(space,role):
    return {"id":space.id,"name":space.name,"role":role}


def list_spaces(db,actor):
    if not active_user(db,actor):
        return []
    rows=db.execute(select(FamilySpace,FamilyMembership.role).join(User,User.id==FamilySpace.owner_id)
        .outerjoin(FamilyMembership,(FamilyMembership.space_id==FamilySpace.id)&(FamilyMembership.user_id==actor)&(FamilyMembership.state=="active"))
        .where(User.deleted_at.is_(None),or_(FamilySpace.owner_id==actor,FamilyMembership.user_id==actor)).order_by(FamilySpace.name,FamilySpace.id))
    return [space_view(space,"owner" if space.owner_id==actor else role) for space,role in rows]


def invite_list(db,actor):
    return [{"id":space.id,"name":space.name,"invited_by":username,"role":member.role}
        for space,member,username in db.execute(select(FamilySpace,FamilyMembership,User.username)
            .join(FamilyMembership,FamilyMembership.space_id==FamilySpace.id).join(User,User.id==FamilySpace.owner_id)
            .where(FamilyMembership.user_id==actor,FamilyMembership.state=="pending",User.deleted_at.is_(None))
            .order_by(FamilyMembership.invited_at.desc()).limit(100))]


def members(db,actor,sid):
    space,role=access(db,actor,sid)
    owner=db.scalar(select(User.username).where(User.id==space.owner_id))
    result=[{"user_id":space.owner_id,"username":owner,"role":"owner","state":"active"}]
    stmt=select(FamilyMembership,User.username).join(User,User.id==FamilyMembership.user_id).where(
        FamilyMembership.space_id==sid,User.deleted_at.is_(None))
    if role!="owner":
        stmt=stmt.where(FamilyMembership.state=="active")
    for member,username in db.execute(stmt.order_by(User.username)):
        result.append({"user_id":member.user_id,"username":username,"role":member.role,"state":member.state})
    return result


def remove_membership(db,sid,uid):
    db.execute(delete(FamilyShare).where(FamilyShare.space_id==sid,FamilyShare.owner_id==uid))
    db.execute(delete(FamilyMembership).where(FamilyMembership.space_id==sid,FamilyMembership.user_id==uid))


def create_space(db,actor,data):
    db.execute(select(User.id).where(User.id==actor,User.deleted_at.is_(None)).with_for_update()).first()
    if db.scalar(select(func.count()).select_from(FamilySpace).where(FamilySpace.owner_id==actor))>=MAX_SPACES:
        raise HTTPException(409,"Maximal zehn eigene Familienbereiche")
    row=FamilySpace(owner_id=actor,name=data.name)
    db.add(row);db.flush()
    audit(db,actor,"create","family_spaces",row.id)
    db.commit()
    return space_view(row,"owner")


def add_invitation(db,actor,sid,data):
    space,_=access(db,actor,sid,"owner",True)
    target=db.scalar(select(User.id).where(User.username==data.username,User.deleted_at.is_(None)))
    if target is None or target==actor:
        raise HTTPException(404,"Einladung an dieses Konto nicht möglich")
    if db.get(FamilyMembership,(sid,target)):
        raise HTTPException(409,"Konto bereits Mitglied oder eingeladen")
    if db.scalar(select(func.count()).select_from(FamilyMembership).where(FamilyMembership.space_id==sid))>=MAX_MEMBERS:
        raise HTTPException(409,"Maximal 20 weitere Mitglieder und Einladungen")
    # Bound invitations per recipient, including across spaces.
    db.execute(select(User.id).where(User.id==target).with_for_update()).first()
    if db.scalar(select(func.count()).select_from(FamilyMembership).where(FamilyMembership.user_id==target))>=100:
        raise HTTPException(409,"Einladungslimit dieses Kontos erreicht")
    db.add(FamilyMembership(space_id=sid,user_id=target,role=data.role))
    audit(db,actor,"invite","family_spaces",sid)
    db.commit()


def respond_invitation(db,actor,sid,accept):
    space=db.scalar(select(FamilySpace).join(User,User.id==FamilySpace.owner_id).where(
        FamilySpace.id==sid,User.deleted_at.is_(None)).with_for_update(of=FamilySpace))
    row=db.get(FamilyMembership,(sid,actor),populate_existing=True)
    if space is None or row is None or row.state!="pending":
        raise HTTPException(404,"Einladung nicht gefunden")
    if accept:
        row.state="active"
    else:
        db.delete(row)
    audit(db,actor,"accept" if accept else "reject","family_spaces",sid)
    db.commit()


def item_view(row):
    return {"id":row.id,"kind":row.kind,"title":row.title,"notes":row.notes,"starts_at":stamp(row.starts_at),
        "ends_at":stamp(row.ends_at),"location":row.location,"status":row.status,"revision":row.revision,"created_at":stamp(row.created_at)}


def items(db,actor,sid,limit=50,offset=0):
    access(db,actor,sid)
    if not 1<=limit<=100 or offset<0:
        raise HTTPException(422,"Ungültige Seitengröße")
    return [item_view(row) for row in db.scalars(select(FamilyItem).where(FamilyItem.space_id==sid)
        .order_by(FamilyItem.created_at.desc(),FamilyItem.id).limit(limit).offset(offset))]


def create_item(db,actor,sid,data):
    access(db,actor,sid,"write",True)
    if db.scalar(select(func.count()).select_from(FamilyItem).where(FamilyItem.space_id==sid))>=MAX_CONTENT:
        raise HTTPException(409,"Maximal 500 gemeinsame Einträge")
    row=FamilyItem(space_id=sid,created_by=actor,**data.model_dump())
    db.add(row);db.flush()
    audit(db,actor,"create","family_items",row.id)
    db.commit()
    return item_view(row)


def item_for_write(db,actor,sid,iid,revision):
    access(db,actor,sid,"write",True)
    row=db.scalar(select(FamilyItem).where(FamilyItem.space_id==sid,FamilyItem.id==iid).with_for_update().execution_options(populate_existing=True))
    if row is None:
        raise HTTPException(404,"Gemeinsamer Eintrag nicht gefunden")
    if row.revision!=revision:
        raise HTTPException(409,"Eintrag wurde geändert. Bitte aktualisieren.")
    return row


def preview(db,actor,data):
    model=MODELS[data.kind]
    row=db.scalar(select(model).where(model.id==data.resource_id,model.owner_id==actor))
    if row is None:
        raise HTTPException(404,"Privater Eintrag nicht gefunden")
    result={"title":row.name if data.kind=="inventory" else row.title}
    if data.include_notes:
        result["notes"]=(row.content if data.kind=="memory" else row.notes if data.kind=="inventory" else row.description)
        if len(result["notes"])>10000:
            raise HTTPException(422,"Text zu lang. Bitte einen gemeinsamen Eintrag mit ausgewähltem Auszug erstellen.")
    if data.include_details:
        if data.kind=="task":
            result.update(status=row.status,due_at=stamp(row.due_at))
        elif data.kind=="event":
            result.update(starts_at=stamp(row.starts_at),ends_at=stamp(row.ends_at),location=row.location,record_type=row.record_type)
        elif data.kind=="inventory":
            result.update(category=row.category,location=row.location_detail)
        elif data.kind=="memory":
            result.update(occurred_at=stamp(row.occurred_at))
    encoded=json.dumps({"kind":data.kind,"resource_id":data.resource_id,"snapshot":result},ensure_ascii=False,sort_keys=True,separators=(",",":"))
    return result,hashlib.sha256(encoded.encode()).hexdigest()


def share_view(row,actor,role,username):
    return {"id":row.id,"kind":row.kind,"snapshot":row.snapshot,"shared_by":username,
        "can_revoke":row.owner_id==actor or role=="owner","created_at":stamp(row.created_at)}


def shares(db,actor,sid,limit=50,offset=0):
    space,role=access(db,actor,sid)
    if not 1<=limit<=100 or offset<0:
        raise HTTPException(422,"Ungültige Seitengröße")
    active_member=select(FamilyMembership.user_id).where(FamilyMembership.space_id==sid,FamilyMembership.state=="active",FamilyMembership.user_id==FamilyShare.owner_id).exists()
    stmt=select(FamilyShare,User.username).join(User,User.id==FamilyShare.owner_id).where(FamilyShare.space_id==sid,
        User.deleted_at.is_(None),or_(FamilyShare.owner_id==space.owner_id,active_member))
    return [share_view(row,actor,role,username) for row,username in db.execute(stmt.order_by(FamilyShare.created_at.desc(),FamilyShare.id).limit(limit).offset(offset))]


def share(db,actor,sid,data):
    _,role=access(db,actor,sid,"write",True)
    snapshot,digest=preview(db,actor,data)
    if digest!=data.digest:
        raise HTTPException(409,"Vorschau geändert. Bitte erneut prüfen.")
    existing=db.scalar(select(FamilyShare).where(FamilyShare.space_id==sid,FamilyShare.owner_id==actor,FamilyShare.kind==data.kind,FamilyShare.resource_id==data.resource_id))
    if existing:
        raise HTTPException(409,"Eintrag bereits geteilt. Alte Freigabe zuerst widerrufen.")
    if db.scalar(select(func.count()).select_from(FamilyShare).where(FamilyShare.space_id==sid))>=MAX_CONTENT:
        raise HTTPException(409,"Maximal 500 Freigaben")
    row=FamilyShare(space_id=sid,owner_id=actor,kind=data.kind,resource_id=data.resource_id,snapshot=snapshot)
    db.add(row);db.flush()
    audit(db,actor,"share","family_shares",row.id)
    username=db.scalar(select(User.username).where(User.id==actor))
    db.commit()
    return share_view(row,actor,role,username)


@router.get("",dependencies=[Depends(private_response)])
def get_spaces(db:Session=Depends(get_db),user:User=Depends(current_user)):
    return {"spaces":list_spaces(db,user.id),"invitations":invite_list(db,user.id)}


@router.post("",status_code=201,dependencies=[Depends(private_response)])
def post_space(data:SpaceIn,db:Session=Depends(get_db),user:User=Depends(current_user)):
    return create_space(db,user.id,data)


@router.post("/{sid}/invite",status_code=204)
def invite(sid:str,data:InviteIn,db:Session=Depends(get_db),user:User=Depends(current_user)):
    add_invitation(db,user.id,sid,data)


@router.post("/{sid}/accept",status_code=204)
def accept(sid:str,db:Session=Depends(get_db),user:User=Depends(current_user)):
    respond_invitation(db,user.id,sid,True)


@router.post("/{sid}/decline",status_code=204)
def decline(sid:str,db:Session=Depends(get_db),user:User=Depends(current_user)):
    respond_invitation(db,user.id,sid,False)


@router.get("/{sid}/members",dependencies=[Depends(private_response)])
def get_members(sid:str,db:Session=Depends(get_db),user:User=Depends(current_user)):
    return members(db,user.id,sid)


@router.patch("/{sid}/members/{uid}",status_code=204)
def change_role(sid:str,uid:str,data:RoleIn,db:Session=Depends(get_db),user:User=Depends(current_user)):
    access(db,user.id,sid,"owner",True)
    row=db.get(FamilyMembership,(sid,uid),populate_existing=True)
    if row is None:
        raise HTTPException(404,"Mitglied nicht gefunden")
    row.role=data.role
    audit(db,user.id,"update","family_spaces",sid)
    db.commit()


@router.delete("/{sid}/members/{uid}",status_code=204)
def remove_member(sid:str,uid:str,db:Session=Depends(get_db),user:User=Depends(current_user)):
    access(db,user.id,sid,"owner",True)
    if db.get(FamilyMembership,(sid,uid)) is None:
        raise HTTPException(404,"Mitglied nicht gefunden")
    remove_membership(db,sid,uid)
    audit(db,user.id,"revoke","family_spaces",sid)
    db.commit()


@router.post("/{sid}/leave",status_code=204)
def leave(sid:str,db:Session=Depends(get_db),user:User=Depends(current_user)):
    _,role=access(db,user.id,sid,lock=True)
    if role=="owner":
        raise HTTPException(409,"Eigentümer kann den Bereich nicht verlassen")
    remove_membership(db,sid,user.id)
    audit(db,user.id,"leave","family_spaces",sid)
    db.commit()


@router.post("/{sid}/delete",status_code=204)
def delete_space(sid:str,data:PasswordIn,db:Session=Depends(get_db),user:User=Depends(current_user)):
    space,_=access(db,user.id,sid,"owner",True)
    if not verify_password(data.password,user.password_hash):
        raise HTTPException(403,"Passwort ist nicht korrekt")
    for model in (FamilyItem,FamilyShare,FamilyMembership):
        db.execute(delete(model).where(model.space_id==sid))
    db.delete(space)
    audit(db,user.id,"delete","family_spaces",sid)
    db.commit()


@router.get("/{sid}/items",dependencies=[Depends(private_response)])
def get_items(sid:str,limit:int=Query(50,ge=1,le=100),offset:int=Query(0,ge=0),db:Session=Depends(get_db),user:User=Depends(current_user)):
    return items(db,user.id,sid,limit,offset)


@router.post("/{sid}/items",status_code=201,dependencies=[Depends(private_response)])
def post_item(sid:str,data:ItemIn,db:Session=Depends(get_db),user:User=Depends(current_user)):
    return create_item(db,user.id,sid,data)


@router.put("/{sid}/items/{iid}",dependencies=[Depends(private_response)])
def update_item(sid:str,iid:str,data:ItemUpdate,db:Session=Depends(get_db),user:User=Depends(current_user)):
    row=item_for_write(db,user.id,sid,iid,data.revision)
    for field,value in data.model_dump(exclude={"revision"}).items():
        setattr(row,field,value)
    row.revision+=1
    audit(db,user.id,"update","family_items",iid)
    db.commit()
    return item_view(row)


@router.post("/{sid}/items/{iid}/delete",status_code=204)
def delete_item(sid:str,iid:str,data:RevisionIn,db:Session=Depends(get_db),user:User=Depends(current_user)):
    row=item_for_write(db,user.id,sid,iid,data.revision)
    db.delete(row)
    audit(db,user.id,"delete","family_items",iid)
    db.commit()


@router.post("/{sid}/shares/preview",dependencies=[Depends(private_response)])
def preview_share(sid:str,data:SharePreview,db:Session=Depends(get_db),user:User=Depends(current_user)):
    access(db,user.id,sid,"write")
    snapshot,digest=preview(db,user.id,data)
    return {"snapshot":snapshot,"digest":digest}


@router.get("/{sid}/shares",dependencies=[Depends(private_response)])
def get_shares(sid:str,limit:int=Query(50,ge=1,le=100),offset:int=Query(0,ge=0),db:Session=Depends(get_db),user:User=Depends(current_user)):
    return shares(db,user.id,sid,limit,offset)


@router.post("/{sid}/shares",status_code=201,dependencies=[Depends(private_response)])
def post_share(sid:str,data:ShareIn,db:Session=Depends(get_db),user:User=Depends(current_user)):
    return share(db,user.id,sid,data)


@router.delete("/{sid}/shares/{share_id}",status_code=204)
def revoke_share(sid:str,share_id:str,db:Session=Depends(get_db),user:User=Depends(current_user)):
    _,role=access(db,user.id,sid,lock=True)
    row=db.scalar(select(FamilyShare).where(FamilyShare.space_id==sid,FamilyShare.id==share_id))
    if row is None or (row.owner_id!=user.id and role!="owner"):
        raise HTTPException(404,"Freigabe nicht gefunden")
    db.delete(row)
    audit(db,user.id,"revoke","family_shares",share_id)
    db.commit()
