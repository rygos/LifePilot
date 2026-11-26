from uuid import uuid4
from datetime import datetime, timezone, date

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from lifepilot.db import engine
from lifepilot.models import (User, Person, Relationship, Organization, PersonOrganization, Conversation,
    ConversationParticipant, ConversationProject, Project, Task, Commitment, TemporalFact, Event,
    EventParticipant, Memory, MemoryProject, UserPersonRelationship)
from lifepilot.security import hash_password
from lifepilot.temporal_facts import fact_value_key


def account(client):
    name = "graph-" + uuid4().hex
    with Session(engine) as db:
        user = User(username=name,password_hash=hash_password("test-password"))
        db.add(user)
        db.commit()
        oid=user.id
    token=client.post("/api/auth/login",json={"username":name,"password":"test-password"}).json()["access_token"]
    return oid,{"Authorization":"Bearer "+token}


def test_graph_explicit_links_and_depth(client):
    owner,auth=account(client)
    foreign,other=account(client)
    with Session(engine) as db:
        a=Person(owner_id=owner,first_name="Anna",last_name="Test")
        b=Person(owner_id=owner,first_name="Thomas")
        outsider=Person(owner_id=foreign,first_name="Foreign Secret")
        org=Organization(owner_id=owner,name="Verein",normalized_name="verein")
        project=Project(owner_id=owner,name="Projekt")
        conversation=Conversation(owner_id=owner,title="Gespräch",original_note="Private body")
        event=Event(owner_id=owner,title="Treffen",starts_at=datetime.now(timezone.utc))
        memory=Memory(owner_id=owner,title="Notiz",content="Secret content")
        db.add_all([a,b,outsider,org,project,conversation,event,memory]);db.flush()
        memory.person_id=a.id
        task=Task(owner_id=owner,title="Aufgabe",person_id=a.id,project_id=project.id)
        commitment=Commitment(owner_id=owner,title="Zusage",direction="incoming",person_id=a.id,conversation_id=conversation.id)
        fact=TemporalFact(owner_id=owner,person_id=a.id,predicate="wohnort",value="Bonn",value_key=fact_value_key("Bonn"),status="confirmed",valid_from=date(2020,1,1))
        proposed=TemporalFact(owner_id=owner,person_id=a.id,predicate="hobby",value="Lesen",value_key=fact_value_key("Lesen"),status="proposed")
        rejected=TemporalFact(owner_id=owner,person_id=a.id,predicate="wohnort",value="Falsch",value_key=fact_value_key("Falsch"),status="rejected")
        db.add_all([task,commitment,fact,proposed,rejected,
            Relationship(owner_id=owner,source_person_id=b.id,target_person_id=a.id,relationship_type="Kollege",confirmed=True),
            PersonOrganization(owner_id=owner,person_id=a.id,organization_id=org.id,role="Mitglied"),
            ConversationParticipant(owner_id=owner,person_id=a.id,conversation_id=conversation.id),
            ConversationProject(owner_id=owner,conversation_id=conversation.id,project_id=project.id),
            EventParticipant(owner_id=owner,person_id=a.id,event_id=event.id),
            MemoryProject(owner_id=owner,memory_id=memory.id,project_id=project.id),
        ])
        db.commit()
        with pytest.raises(IntegrityError,match="tenant_integrity"):
            with db.begin_nested():
                db.add(Relationship(owner_id=owner,source_person_id=a.id,target_person_id=outsider.id,relationship_type="Foreign leak",confirmed=True))
                db.flush()
        ids={k:v.id for k,v in locals().copy().items() if isinstance(v,(Person,Organization,Project,Conversation,Event,Memory,Task,Commitment,TemporalFact))}
    def read(**extra):
        response=client.get("/api/graph",headers=auth,params={"root_kind":"person","root_id":ids["a"],**extra})
        assert response.status_code==200,response.text
        return response.json()
    direct=read()
    assert direct["root"]=="person:"+ids["a"]
    assert {n["kind"] for n in direct["nodes"]}=={"person","organization","conversation","event","memory","commitment","fact","task"}
    assert ids["project"] not in {n["resource_id"] for n in direct["nodes"]}
    assert ids["outsider"] not in str(direct) and "Foreign leak" not in str(direct)
    assert "Private body" not in str(direct) and "Secret content" not in str(direct)
    edge=next(e for e in direct["edges"] if e["resource_type"]=="relationships")
    assert edge["source"]=="person:"+ids["b"] and edge["target"]==direct["root"]
    fact_edge=next(e for e in direct["edges"] if e["resource_type"]=="temporal_facts")
    assert fact_edge["valid_from"]=="2020-01-01"
    expanded=read(depth=2)
    assert "project:"+ids["project"] in {n["id"] for n in expanded["nodes"]}
    assert len({e["id"] for e in expanded["edges"]})==len(expanded["edges"])
    for edge in expanded["edges"]:
        assert edge["source"] in {n["id"] for n in expanded["nodes"]}
        assert edge["target"] in {n["id"] for n in expanded["nodes"]}
    assert ids["proposed"] not in str(expanded)
    uncertain=read(include_unconfirmed=True)
    assert ids["proposed"] in str(uncertain) and ids["rejected"] not in str(uncertain)
    assert any(e["confirmed"] is False for e in uncertain["edges"])
    filtered=read(kinds=["organization"])
    assert {n["kind"] for n in filtered["nodes"]}=={"person","organization"}
    limited=read(limit=2)
    assert len(limited["nodes"])==2 and limited["truncated"]
    assert client.get("/api/graph",headers=other,params={"root_kind":"person","root_id":ids["a"]}).status_code==404
    assert client.get("/api/graph",headers=auth,params={"root_kind":"person","root_id":ids["outsider"]}).status_code==404
    assert client.get("/api/graph",headers=auth,params={"root_kind":"person","root_id":ids["a"],"depth":3}).status_code==422
    assert client.get("/api/graph",params={"root_kind":"person","root_id":ids["a"]}).status_code==401
    project_graph=client.get("/api/graph",headers=auth,params={"root_kind":"project","root_id":ids["project"]}).json()
    assert {"project","conversation","task","memory"}=={n["kind"] for n in project_graph["nodes"]}


def test_graph_self_relationship(client):
    owner,auth=account(client)
    with Session(engine) as db:
        self_person=Person(owner_id=owner,first_name="Ich",is_self=True)
        # Login may already have created a self profile.
        from sqlalchemy import select
        existing=db.scalar(select(Person).where(Person.owner_id==owner,Person.is_self.is_(True)))
        if existing is not None:
            self_person=existing
        else:
            db.add(self_person)
        contact=Person(owner_id=owner,first_name="Kontakt")
        db.add(contact);db.flush()
        db.add(UserPersonRelationship(owner_id=owner,person_id=contact.id,relationship_type="Freund",confirmed=True))
        db.commit()
        sid,cid=self_person.id,contact.id
    result=client.get("/api/graph",headers=auth,params={"root_kind":"person","root_id":cid}).json()
    assert {"person:"+sid,"person:"+cid}=={n["id"] for n in result["nodes"]}
    assert result["edges"][0]["label"]=="Freund"
