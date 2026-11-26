"""Bounded read-only projection of explicitly stored links."""
from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from lifepilot.db import get_db
from lifepilot.models import (
    Person, Relationship, UserPersonRelationship, Organization, PersonOrganization,
    Conversation, ConversationParticipant, ConversationProject, Project, Event, EventParticipant,
    Memory, MemoryProject, Commitment, TemporalFact, Task, User, Place, PlaceEntry,
)
from lifepilot.security import current_user

router = APIRouter(prefix="/api/graph", tags=["Wissensgraph"])
Kind = Literal["person","organization","conversation","project","event","memory","commitment","fact","task","place","place_entry"]
MODELS = {"person":Person,"organization":Organization,"conversation":Conversation,"project":Project,
          "event":Event,"memory":Memory,"commitment":Commitment,"fact":TemporalFact,"task":Task,"place":Place,"place_entry":PlaceEntry}


class Node(BaseModel):
    id: str
    kind: Kind
    resource_id: str
    label: str
    status: str | None = None


class Edge(BaseModel):
    id: str
    source: str
    target: str
    label: str
    resource_type: str
    resource_id: str
    valid_from: str | None = None
    valid_until: str | None = None
    confirmed: bool | None = None


class GraphOut(BaseModel):
    root: str
    nodes: list[Node]
    edges: list[Edge]
    truncated: bool


# Each relation is queried in both directions, and both endpoints must belong
# to the requesting account. Link rows never grant access to an endpoint.
# (link model, source kind, source column, target kind, target column, label)
LINKS = (
    (Relationship, "person","source_person_id","person","target_person_id","relationship"),
    (PersonOrganization,"person","person_id","organization","organization_id","membership"),
    (ConversationParticipant,"person","person_id","conversation","conversation_id","Gesprächsteilnahme"),
    (ConversationProject,"conversation","conversation_id","project","project_id","Projektbezug"),
    (EventParticipant,"person","person_id","event","event_id","Teilnahme"),
    (Memory,"person","person_id","memory","id","Erinnerung"),
    (MemoryProject,"memory","memory_id","project","project_id","Projektbezug"),
    (Task,"person","person_id","task","id","Aufgabe"),
    (Task,"task","id","project","project_id","Projektbezug"),
    (Commitment,"person","person_id","commitment","id","Verpflichtung"),
    (Commitment,"commitment","id","project","project_id","Projektbezug"),
    (Commitment,"commitment","id","conversation","conversation_id","Gesprächsbezug"),
    (TemporalFact,"person","person_id","fact","id","fact"),
    (PlaceEntry,"place","place_id","place_entry","id","Ortseintrag"),
    (PlaceEntry,"place_entry","id","person","person_id","Personenbezug"),
    (PlaceEntry,"place_entry","id","event","event_id","Ereignisbezug"),
    (PlaceEntry,"place_entry","id","conversation","conversation_id","Gesprächsbezug"),
    (PlaceEntry,"place_entry","id","memory","memory_id","Erinnerungsbezug"),
)


def key(kind, rid):
    return f"{kind}:{rid}"


def node_for(kind, row):
    if kind == "person":
        label = " ".join(filter(None,(row.first_name,row.last_name)))
    elif kind in ("project","organization","place"):
        label = row.name
    elif kind == "fact":
        label = f"{row.predicate}: {row.value}"
    else:
        label = row.title
    return Node(id=key(kind,row.id),kind=kind,resource_id=row.id,label=label[:240] or "Unbenannt",status=getattr(row,"status",None))


def owned_rows(db, owner, kind, ids):
    model = MODELS[kind]
    stmt = select(model).where(model.owner_id == owner, model.id.in_(ids))
    if kind == "fact":
        stmt = stmt.where(model.status != "rejected")
    return {row.id:row for row in db.scalars(stmt)}


def iso(value):
    return value.isoformat() if isinstance(value,(date,datetime)) else None


def graph(db: Session, owner: str, root_kind: Kind, root_id: str, depth=1, limit=60, kinds=None, include_unconfirmed=False):
    if not 1 <= depth <= 2 or not 2 <= limit <= 100:
        raise HTTPException(422,"Ungültige Graphgröße")
    allowed = set(kinds) if kinds else set(MODELS)
    allowed.add(root_kind)
    root_row = owned_rows(db,owner,root_kind,[root_id]).get(root_id)
    if root_row is None or (root_kind=="fact" and root_row.status!="confirmed" and not include_unconfirmed):
        raise HTTPException(404,"Graphwurzel nicht gefunden")
    root = node_for(root_kind,root_row)
    nodes = {root.id:root}
    edges = {}
    frontier = {root_kind:{root_id}}
    truncated = False
    edge_limit = limit * 3
    self_id = db.scalar(select(Person.id).where(Person.owner_id == owner, Person.is_self.is_(True)))

    def add_links(rows, sk, tk, sc, tc, label, resource_type, next_frontier):
        nonlocal truncated
        if len(rows)>edge_limit:
            truncated=True
        rows=rows[:edge_limit]
        sources=owned_rows(db,owner,sk,{getattr(row,sc) for row in rows if getattr(row,sc)})
        targets=owned_rows(db,owner,tk,{getattr(row,tc) for row in rows if getattr(row,tc)})
        for row in rows:
            sid,tid=getattr(row,sc),getattr(row,tc)
            if sid not in sources or tid not in targets:
                continue
            src,dst=key(sk,sid),key(tk,tid)
            if src==dst:
                continue
            confirmed=getattr(row,"confirmed",None)
            if resource_type=="temporal_facts":
                confirmed=row.status=="confirmed"
            if confirmed is False and not include_unconfirmed:
                continue
            rid=getattr(row,"id",None) or f"{sid}:{tid}"
            eid=f"{resource_type}:{rid}:{src}:{dst}"
            if eid in edges:
                continue
            additions=[(kind,entity,nid) for kind,entity,nid in ((sk,sources[sid],src),(tk,targets[tid],dst)) if nid not in nodes]
            if len(nodes)+len(additions)>limit or len(edges)>=edge_limit:
                truncated=True
                continue
            for kind,entity,nid in additions:
                nodes[nid]=node_for(kind,entity)
                next_frontier.setdefault(kind,set()).add(entity.id)
            caption = row.relationship_type if label=="relationship" else (row.role or "Mitgliedschaft") if label=="membership" else row.predicate if label=="fact" else label
            edges[eid]=Edge(id=eid,source=src,target=dst,label=caption[:160],resource_type=resource_type,resource_id=rid,
                             valid_from=iso(getattr(row,"valid_from",None)),valid_until=iso(getattr(row,"valid_until",None)),confirmed=confirmed)

    for _ in range(depth):
        next_frontier={}
        for model,sk,sc,tk,tc,label in LINKS:
            if sk not in allowed or tk not in allowed:
                continue
            clauses=[]
            if frontier.get(sk): clauses.append(getattr(model,sc).in_(frontier[sk]))
            if frontier.get(tk): clauses.append(getattr(model,tc).in_(frontier[tk]))
            if not clauses: continue
            stmt=select(model).where(model.owner_id==owner,or_(*clauses),getattr(model,sc).is_not(None),getattr(model,tc).is_not(None))
            if model is Relationship and not include_unconfirmed:
                stmt=stmt.where(model.confirmed.is_(True))
            if model is TemporalFact:
                stmt=stmt.where(model.status!="rejected" if include_unconfirmed else model.status=="confirmed")
            rows=list(db.scalars(stmt.order_by(getattr(model,sc),getattr(model,tc),*([model.id] if hasattr(model,"id") else [])).limit(edge_limit+1)))
            add_links(rows,sk,tk,sc,tc,label,model.__tablename__,next_frontier)
        if self_id and "person" in allowed and frontier.get("person"):
            ids=frontier["person"]
            stmt=select(UserPersonRelationship).where(UserPersonRelationship.owner_id==owner)
            if self_id not in ids:
                stmt=stmt.where(UserPersonRelationship.person_id.in_(ids))
            if not include_unconfirmed:
                stmt=stmt.where(UserPersonRelationship.confirmed.is_(True))
            rows=list(db.scalars(stmt.order_by(UserPersonRelationship.id).limit(edge_limit+1)))
            # Small adapter for the implicit account self-person endpoint.
            from types import SimpleNamespace
            adapted=[SimpleNamespace(self_id=self_id,person_id=row.person_id,id=row.id,relationship_type=row.relationship_type,
                       confirmed=row.confirmed,valid_from=row.valid_from,valid_until=row.valid_until) for row in rows]
            add_links(adapted,"person","person","self_id","person_id","relationship","user_person_relationships",next_frontier)
        frontier=next_frontier
        if not frontier: break
    return GraphOut(root=root.id,nodes=list(nodes.values()),edges=list(edges.values()),truncated=truncated)


@router.get("",response_model=GraphOut)
def get_graph(root_kind: Kind, root_id: str, depth: int=Query(1,ge=1,le=2), limit: int=Query(60,ge=2,le=100), kinds: list[Kind] | None=Query(None), include_unconfirmed: bool=False, db: Session=Depends(get_db), user: User=Depends(current_user)):
    return graph(db,user.id,root_kind,root_id,depth,limit,kinds,include_unconfirmed)
