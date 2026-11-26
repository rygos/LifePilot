from pathlib import Path
from uuid import uuid4
import subprocess
import time

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select, text, update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from lifepilot.config import settings
from lifepilot.db import Base, engine
from lifepilot.main import organization_list, person_organizations, relationship_list
from lifepilot.models import (Attachment, Conversation, ConversationParticipant, FamilyShare, FamilySpace,
    Memory, Organization, Person, PersonContactMethod, PersonOrganization, Relationship, Task, User)
from lifepilot.security import create_token
from lifepilot.tenant_integrity_v1 import LINKS, OWNED_TABLES, preflight


def seed(db):
    a=User(username="tenant-a-"+uuid4().hex,password_hash="unused")
    b=User(username="tenant-b-"+uuid4().hex,password_hash="unused")
    db.add_all([a,b]);db.flush()
    pa=Person(owner_id=a.id,first_name="Eigener Kontakt")
    pb=Person(owner_id=b.id,first_name="Fremder Kontakt")
    oa=Organization(owner_id=a.id,name="Eigene Organisation",normalized_name="eigene")
    ob=Organization(owner_id=b.id,name="Fremde Organisation",normalized_name="fremde")
    ca=Conversation(owner_id=a.id,title="Eigenes Gespräch",original_note="Test")
    mb=Memory(owner_id=b.id,title="Fremde Erinnerung",content="Geheim")
    sb=FamilySpace(owner_id=b.id,name="Familie")
    db.add_all([pa,pb,oa,ob,ca,mb,sb]);db.flush()
    return a,b,pa,pb,oa,ob,ca,mb,sb


def rejected(db,row):
    with pytest.raises(IntegrityError,match="tenant_integrity"):
        with db.begin_nested():
            db.add(row);db.flush()


def exercise_guards(db):
    a,b,pa,pb,oa,ob,ca,mb,sb=seed(db)
    rejected(db,Task(owner_id=a.id,title="Fremder Bezug",person_id=pb.id))
    rejected(db,Task(owner_id=a.id,title="Fehlender Bezug",person_id=str(uuid4())))
    rejected(db,ConversationParticipant(owner_id=a.id,conversation_id=ca.id,person_id=pb.id))
    rejected(db,PersonContactMethod(owner_id=b.id,person_id=pa.id,method_type="email",value="hidden@example.org"))
    rejected(db,PersonOrganization(owner_id=a.id,person_id=pa.id,organization_id=ob.id))
    rejected(db,Attachment(owner_id=a.id,resource_type="memory",resource_id=mb.id,storage_key=uuid4().hex,file_name="test",content_type="text/plain",size_bytes=1))
    rejected(db,FamilyShare(owner_id=a.id,space_id=sb.id,kind="memory",resource_id=mb.id,snapshot={"title":"Test"}))
    valid=Task(owner_id=a.id,title="Eigener Bezug",person_id=pa.id)
    db.add(valid);db.flush()
    for values in ({"person_id":pb.id},{"owner_id":b.id}):
        with pytest.raises(IntegrityError,match="tenant_integrity"):
            with db.begin_nested():
                db.execute(update(Task).where(Task.id==valid.id).values(**values))
    db.execute(update(Task).where(Task.id==valid.id).values(person_id=None))
    db.flush()
    # A shared workspace is explicitly allowed to have a different owner.
    ma=Memory(owner_id=a.id,title="Eigene Erinnerung",content="Test")
    db.add(ma);db.flush()
    from lifepilot.models import FamilyMembership
    db.add(FamilyMembership(space_id=sb.id,user_id=a.id,role="editor",state="active"));db.flush()
    db.add(FamilyShare(owner_id=a.id,space_id=sb.id,kind="memory",resource_id=ma.id,snapshot={"title":"Test"}));db.flush()
    db.commit()


def test_frozen_guard_covers_current_owner_foreign_keys():
    expected={(t.name,f.parent.name,f.column.table.name,f.column.name)
        for t in Base.metadata.tables.values() if "owner_id" in t.c
        for f in t.foreign_keys if "owner_id" in f.column.table.c and f.column.table.name!="family_spaces"}
    assert set(LINKS)==expected
    assert set(OWNED_TABLES)=={t.name for t in Base.metadata.tables.values() if "owner_id" in t.c}


def test_database_guards_and_rest_denial(client):
    with Session(engine) as db:
        exercise_guards(db)
        a,b,pa,pb,oa,ob,ca,mb,sb=seed(db)
        db.commit()
        auth={"Authorization":"Bearer "+create_token(a.id)}
        foreign_person,foreign_org,own_person=pb.id,ob.id,pa.id
    assert client.post("/api/tasks",headers=auth,json={"title":"Fremd","person_id":foreign_person}).status_code==404
    assert client.post("/api/people/"+own_person+"/organizations",headers=auth,json={"organization_id":foreign_org}).status_code==404
    assert client.post("/api/conversations",headers=auth,json={"title":"Fremd","original_note":"Test","participant_ids":[foreign_person]}).status_code==404
    assert client.get("/api/people/"+foreign_person,headers=auth).status_code==404


def test_legacy_reads_and_preflight_are_non_destructive():
    # A separate unguarded in-memory legacy database, never the application DB.
    legacy=create_engine("sqlite://")
    Base.metadata.create_all(legacy)
    try:
        with Session(legacy) as db:
            a,b,pa,pb,oa,ob,ca,mb,sb=seed(db)
            db.add_all([
                PersonOrganization(owner_id=a.id,person_id=pb.id,organization_id=oa.id),
                PersonOrganization(owner_id=a.id,person_id=pa.id,organization_id=ob.id),
                PersonContactMethod(owner_id=b.id,person_id=pa.id,method_type="email",value="secret@example.org"),
                Relationship(owner_id=a.id,source_person_id=pa.id,target_person_id=pb.id,relationship_type="Fremd",confirmed=True),
            ])
            db.commit()
            assert organization_list(db,a)[0].members==[]
            assert person_organizations(pa.id,db,a)==[]
            assert db.scalar(select(Person).where(Person.id==pa.id)).contact_methods==[]
            assert relationship_list(db,a)==[]
        with legacy.begin() as connection:
            with pytest.raises(RuntimeError,match="person_organizations"):
                preflight(connection)
            assert connection.execute(text("SELECT count(*) FROM person_organizations")).scalar_one()==2
    finally:
        legacy.dispose()


def test_postgres_migration_and_guards(request,monkeypatch):
    if not request.config.getoption("--postgres-integration"):
        pytest.skip("Isolierter PostgreSQL-Test nur mit --postgres-integration")
    name="lifepilot-tenant-test-"+uuid4().hex[:12]
    password=uuid4().hex
    # Never attach an existing volume or network; bind a random loopback port.
    subprocess.run(["docker","run","--rm","-d","--name",name,"--pull=never",
        "-e","POSTGRES_PASSWORD="+password,"-e","POSTGRES_DB=lifepilot_test",
        "-p","127.0.0.1::5432","--tmpfs","/var/lib/postgresql/data",
        "docker.io/pgvector/pgvector:pg16"],check=True,capture_output=True,timeout=30)
    pg=None
    try:
        port=subprocess.check_output(["docker","port",name,"5432/tcp"],text=True,timeout=10).strip().rsplit(":",1)[1]
        url=f"postgresql+psycopg://postgres:{password}@127.0.0.1:{port}/lifepilot_test"
        pg=create_engine(url)
        for _ in range(40):
            try:
                with pg.connect() as connection:
                    connection.execute(text("SELECT 1"))
                break
            except OperationalError:
                time.sleep(.5)
        else:
            pytest.fail("Test-PostgreSQL nicht erreichbar")
        monkeypatch.setattr(settings,"database_url",url)
        config=Config(str(Path(__file__).resolve().parents[1]/"alembic.ini"))
        command.upgrade(config,"head")
        with Session(pg) as db:
            exercise_guards(db)
        # Exercise real approval locking and transactional person merge on PostgreSQL.
        from lifepilot.approval_policy import queue
        from lifepilot.approval_routes import approval_approve
        with Session(pg) as db:
            a,b,pa,pb,oa,ob,ca,mb,sb=seed(db)
            target=Person(owner_id=a.id,first_name="Merge target")
            db.add(target);db.flush()
            note=Memory(owner_id=a.id,person_id=pa.id,title="Keep",content="Kept")
            db.add(note);db.commit()
            source_id,target_id,note_id=pa.id,target.id,note.id
            aid=queue(db,a.id,"person_merge",source_id,"",{"target_id":target_id})["approval_id"]
            assert approval_approve(aid,db,a).status=="executed"
            db.expire_all()
            assert db.get(Person,source_id) is None
            assert db.get(Memory,note_id).person_id==target_id
        command.downgrade(config,"0054_login_budgets")
        # Verify upgrade works with valid existing rows and reinstalls guards.
        command.upgrade(config,"head")
        with Session(pg) as db:
            exercise_guards(db)
    finally:
        if pg is not None:
            pg.dispose()
        subprocess.run(["docker","rm","-f",name],check=False,capture_output=True,timeout=30)
