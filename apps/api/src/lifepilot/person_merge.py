"""Conservative person merge: explicit reviewed plan, no silent cascading loss."""
from sqlalchemy import and_, delete, or_, select, update
from fastapi import HTTPException

from lifepilot.approval_policy import fingerprint
from lifepilot.db import Base
from lifepilot.models import Attachment, Person

# Only these references are supported for reassignment. Any other inbound
# reference to the source blocks the merge until a dedicated migration exists.
ALLOWED = {"memories","tasks","loans","gifts","conversation_participants",
           "event_participants","relationships","user_person_relationships"}
FIELDS = ("nickname","email","phone","address","website","job_title","organization")
MAX_LINKS = 500


def conflict(message):
    raise HTTPException(409,message)


def plan_merge(db,owner,source_id,target_id):
    if source_id==target_id:
        conflict("Quell- und Zielperson müssen verschieden sein")
    person=Person.__table__
    rows=list(db.execute(select(person).where(person.c.id.in_([source_id,target_id]),person.c.owner_id==owner)
        .order_by(person.c.id).with_for_update()).mappings())
    if len(rows)!=2:
        raise HTTPException(404,"Person nicht gefunden")
    by_id={row["id"]:dict(row) for row in rows}
    source,target=by_id[source_id],by_id[target_id]
    if source["is_self"] or target["is_self"]:
        conflict("Eigenes Personenprofil kann nicht zusammengeführt werden")
    if any(source[k] for k in ("photo_key","tags","is_favorite","last_contact_at","contact_interval_days",
                               "how_met","birthday","birthday_month","birthday_day","birthday_approximate_age")) or source["birthday_precision"]!="unknown" or source["gender"]!="unspecified":
        conflict("Zusammenführung erweiterter Profile noch nicht unterstützt")
    changes={}
    for field in FIELDS:
        if source[field] and target[field] and source[field]!=target[field]:
            conflict("Widersprüchliches Profilfeld: "+field)
        if source[field] and not target[field]:
            changes[field]=source[field]
    if source["notes"]:
        changes["notes"]="\n\n".join(v for v in (target["notes"],source["notes"]) if v)
    if db.scalar(select(Attachment.id).where(Attachment.resource_type=="person",Attachment.resource_id==source_id).limit(1)):
        conflict("Zusammenführung mit Anhängen noch nicht unterstützt")
    # Derive incoming FK references from current metadata, so newly introduced
    # tables cannot silently lose a source-person association.
    links=[]
    remaining=MAX_LINKS
    for name,table in sorted(Base.metadata.tables.items()):
        columns=sorted({fk.parent.name for fk in table.foreign_keys if fk.column.table.name=="people"})
        if not columns:
            continue
        condition=or_(*(table.c[c]==source_id for c in columns))
        if name not in ALLOWED or "owner_id" not in table.c:
            if db.execute(select(1).select_from(table).where(condition).limit(1)).first():
                conflict("Nicht unterstützte Personenverknüpfung: "+name)
            continue
        found=list(db.execute(select(table).where(condition).order_by(*table.primary_key.columns).limit(remaining+1).with_for_update()).mappings())
        remaining-=len(found)
        if remaining<0:
            conflict("Zu viele Verknüpfungen für eine sichere Zusammenführung")
        for row in found:
            if row["owner_id"]!=owner:
                conflict("Kontofremde Personenverknüpfung")
            replacement={c:target_id for c in columns if row[c]==source_id}
            after={**row,**replacement}
            if name=="relationships" and after["source_person_id"]==after["target_person_id"]:
                conflict("Zusammenführung würde eine Selbstbeziehung erzeugen")
            if name=="loans" and after["lender_person_id"]==after["borrower_person_id"]:
                conflict("Zusammenführung würde Verleiher und Entleiher gleichsetzen")
            if name in ("event_participants","conversation_participants"):
                pk=and_(*(c==after[c.name] for c in table.primary_key.columns))
                if db.execute(select(1).select_from(table).where(pk).limit(1)).first():
                    conflict("Doppelte Teilnahme muss vor der Zusammenführung geklärt werden")
            if name=="user_person_relationships":
                if db.execute(select(1).select_from(table).where(table.c.owner_id==owner,table.c.person_id==target_id,
                        table.c.relationship_type==row["relationship_type"]).limit(1)).first():
                    conflict("Doppelte persönliche Beziehung muss zuerst geklärt werden")
            if name=="relationships":
                if db.execute(select(1).select_from(table).where(table.c.owner_id==owner,
                        table.c.id!=row["id"],or_(
                        and_(table.c.source_person_id==after["source_person_id"],table.c.target_person_id==after["target_person_id"],table.c.relationship_type==after["relationship_type"]),
                        and_(table.c.source_person_id==after["target_person_id"],table.c.target_person_id==after["source_person_id"],table.c.relationship_type==after["inverse_relationship_type"]))).limit(1)).first():
                    conflict("Doppelte Beziehung muss zuerst geklärt werden")
            links.append({"table":name,"row":dict(row),"changes":replacement})
    version=fingerprint({"source":source,"target":target,"links":links})
    source_name=" ".join([source["first_name"],source["last_name"]]).strip()
    target_name=" ".join([target["first_name"],target["last_name"]]).strip()
    label=source_name[:115]+" → "+target_name[:115]
    return {"version":version,"label":label,"changes":changes,"links":links,"source_id":source_id,"target_id":target_id,"source_name":source_name,"target_name":target_name}


def apply_merge(db,owner,plan):
    """Caller holds locks and commits together with the approval decision."""
    for link in plan["links"]:
        table=Base.metadata.tables[link["table"]]
        condition=and_(table.c.owner_id==owner,*(c==link["row"][c.name] for c in table.primary_key.columns))
        if db.execute(update(table).where(condition).values(**link["changes"])).rowcount!=1:
            conflict("Personenverknüpfung wurde geändert")
    person=Person.__table__
    if plan["changes"]:
        db.execute(update(person).where(person.c.id==plan["target_id"],person.c.owner_id==owner).values(**plan["changes"]))
    if db.execute(delete(person).where(person.c.id==plan["source_id"],person.c.owner_id==owner)).rowcount!=1:
        conflict("Quellperson wurde geändert")
