"""Read-only address book projection with separate CardDAV credentials."""
import re
import xml.etree.ElementTree as ET
from datetime import date
from hashlib import sha256
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from lifepilot.caldav_routes import D, CS, METHODS, MAX_RESOURCES, add_response, append_bounded, clean_text, fold, href, ical_text, read_xml, xml_response
from lifepilot.dav_auth import carddav_user
from lifepilot.db import get_db
from lifepilot.models import Person, User

A = "{urn:ietf:params:xml:ns:carddav}"
ET.register_namespace("A", "urn:ietf:params:xml:ns:carddav")
router = APIRouter(tags=["CardDAV"])
HEADERS = {"DAV": "1, addressbook", "Allow": "OPTIONS, GET, HEAD, PROPFIND, REPORT", "Cache-Control": "private, no-store", "Vary": "Authorization"}


def full_name(person):
    return " ".join(v for v in (person.first_name, person.last_name) if v).strip() or "Unbenannter Kontakt"


def contact_fields(person):
    # Deliberate allowlist: no notes, tags, relationships, photos, social accounts,
    # organization memberships, contact history or estimated age.
    fields = {
        "FN": [full_name(person)], "N": [person.last_name or "", person.first_name or ""],
        "EMAIL": [person.email], "TEL": [person.phone], "ADR": [person.address],
        "URL": [person.website], "NICKNAME": [person.nickname],
        "ORG": [person.organization], "TITLE": [person.job_title],
    }
    mapping = {"email":"EMAIL", "phone":"TEL", "address":"ADR", "website":"URL"}
    for method in sorted(person.contact_methods, key=lambda row: (row.method_type, row.value, row.id)):
        if method.owner_id == person.owner_id and method.method_type in mapping:
            fields[mapping[method.method_type]].append(method.value)
    return {k:list(dict.fromkeys(v for v in values if v and v.strip())) for k,values in fields.items()}


def card_data(person):
    fields = contact_fields(person)
    lines = ["BEGIN:VCARD", "VERSION:3.0", "UID:" + person.id,
             "N:" + ical_text(person.last_name or "") + ";" + ical_text(person.first_name or "") + ";;;",
             "FN:" + ical_text(full_name(person))]
    for name in ("NICKNAME", "EMAIL", "TEL", "URL", "ORG", "TITLE", "ADR"):
        for value in fields[name]:
            # Legacy address values are unstructured; keep the original in the street component.
            lines.append(name + ":" + (";;" + ical_text(value) + ";;;;" if name == "ADR" else ical_text(value)))
    if person.birthday and person.birthday_precision == "exact":
        try:
            lines.append("BDAY:" + date.fromisoformat(person.birthday).isoformat())
        except ValueError:
            pass
    lines.append("END:VCARD")
    data = "\r\n".join(fold(line) for line in lines) + "\r\n"
    if len(data.encode()) > 1024 * 1024:
        raise HTTPException(507, "Kontakt überschreitet die maximale Ressourcengröße")
    return data


def etag(person):
    return '"' + sha256(card_data(person).encode()).hexdigest() + '"'


def path_for(owner, kind):
    return {"root":"/carddav/", "principals":"/carddav/principals/", "principal":f"/carddav/principals/{owner.id}/",
            "addressbooks":"/carddav/addressbooks/", "home":f"/carddav/addressbooks/{owner.id}/",
            "book":f"/carddav/addressbooks/{owner.id}/lifepilot/"}[kind]


def card_path(owner, person):
    return path_for(owner, "book") + person.id + ".vcf"


def people(db, owner, ids=None):
    stmt = select(Person).where(Person.owner_id == owner.id, Person.is_self.is_(False))
    if ids is not None:
        stmt = stmt.where(Person.id.in_(ids))
    rows = list(db.scalars(stmt.order_by(Person.id).limit(MAX_RESOURCES + 1)))
    if len(rows) > MAX_RESOURCES:
        raise HTTPException(507, "Adressbuch überschreitet das Ressourcenlimit")
    return rows


def parse_card_id(owner, path):
    try:
        parsed = urlsplit(path)
        prefix = path_for(owner, "book")
        suffix = parsed.path[len(prefix):]
        if not parsed.path.startswith(prefix) or parsed.query or parsed.fragment or not re.fullmatch(r"[0-9a-f-]{36}\.vcf", suffix):
            return None
        return str(UUID(suffix[:-4]))
    except ValueError:
        return None


def resolve(db, owner, path):
    for kind in ("root","principals","principal","addressbooks","home","book"):
        if path.rstrip("/") == path_for(owner,kind).rstrip("/"):
            return kind,None
    pid = parse_card_id(owner,path)
    if pid:
        rows = people(db,owner,{pid})
        if rows:
            return "card",rows[0]
    return None,None


def properties(db,owner,kind,person,names):
    out = {}
    def node(tag):
        value = ET.Element(tag)
        out[tag] = value
        return value
    principal = path_for(owner,"principal")
    href(node(D+"current-user-principal"),principal)
    href(node(D+"owner"),principal)
    ET.SubElement(ET.SubElement(node(D+"current-user-privilege-set"),D+"privilege"),D+"read")
    resource = node(D+"resourcetype")
    if kind != "card":
        ET.SubElement(resource,D+"collection")
    if kind == "principal":
        ET.SubElement(resource,D+"principal")
        href(node(D+"principal-URL"),principal)
        href(node(A+"addressbook-home-set"),path_for(owner,"home"))
    if kind == "book":
        ET.SubElement(resource,A+"addressbook")
        node(A+"addressbook-description").text = "LifePilot-Kontakte (nur lesbar)"
        ET.SubElement(node(A+"supported-address-data"),A+"address-data-type",{"content-type":"text/vcard","version":"3.0"})
        node(A+"max-resource-size").text = str(1024*1024)
        reports = node(D+"supported-report-set")
        for tag in (A+"addressbook-query",A+"addressbook-multiget"):
            ET.SubElement(ET.SubElement(ET.SubElement(reports,D+"supported-report"),D+"report"),tag)
        if CS+"getctag" in names:
            node(CS+"getctag").text = sha256("".join(p.id+etag(p) for p in people(db,owner)).encode()).hexdigest()
    node(D+"displayname").text = clean_text(full_name(person)) if person else {"root":"LifePilot","principals":"Benutzer","principal":"LifePilot-Konto","addressbooks":"Adressbücher","home":"Meine Adressbücher","book":"LifePilot"}[kind]
    if person:
        data = card_data(person)
        node(D+"getcontenttype").text = "text/vcard; charset=utf-8"
        node(D+"getcontentlength").text = str(len(data.encode()))
        node(D+"getetag").text = '"' + sha256(data.encode()).hexdigest() + '"'
        if A+"address-data" in names:
            node(A+"address-data").text = data
    return out


def propfind(db,owner,kind,person,root,depth):
    if depth not in ("0","1"):
        raise HTTPException(403,"Nur Depth 0 und 1 werden unterstützt")
    if root is not None and root.tag != D+"propfind":
        raise HTTPException(400,"PROPFIND erwartet DAV:propfind")
    prop = root.find(D+"prop") if root is not None else None
    names = list(dict.fromkeys(e.tag for e in prop)) if prop is not None else None
    propname = root is not None and root.find(D+"propname") is not None
    include = root.find(D+"include") if root is not None else None
    extra = [e.tag for e in include] if include is not None and names is None else []
    if len((names or [])+extra)>100:
        raise HTTPException(400,"Zu viele Eigenschaften")
    targets = [(kind,person)]
    if depth=="1":
        targets.extend((child,None) for child in {"root":["principals","addressbooks"],"principals":["principal"],"addressbooks":["home"],"home":["book"]}.get(kind,[]))
        if kind=="book":
            targets.extend(("card",p) for p in people(db,owner))
    response = ET.Element(D+"multistatus")
    for resource,row in targets:
        props = properties(db,owner,resource,row,(names or [])+extra)
        selected = list(dict.fromkeys(list(props)+extra)) if names is None and extra else names
        add_response(response,card_path(owner,row) if row else path_for(owner,resource),props,selected,propname)
    return xml_response(response,HEADERS)


def filter_predicate(root):
    filt = root.find(A+"filter")
    if filt is None:
        return lambda person: True
    mode = filt.get("test","anyof")
    if mode not in ("anyof","allof"):
        raise HTTPException(403,"Nicht unterstützter Kontaktfilter")
    predicates = []
    for prop in filt:
        name = prop.get("name","").upper()
        test = prop.get("test","anyof")
        if prop.tag != A+"prop-filter" or name not in {"FN","N","EMAIL","TEL","NICKNAME","ORG","TITLE","ADR","URL"} or test not in ("anyof","allof"):
            raise HTTPException(403,"Nicht unterstützter Kontaktfilter")
        children = list(prop)
        if len(children)==1 and children[0].tag == A+"is-not-defined":
            predicates.append(lambda person,n=name: not contact_fields(person)[n])
            continue
        matches = []
        for child in children:
            comparison = child.get("match-type","contains")
            collation = child.get("collation","i;unicode-casemap")
            negate = child.get("negate-condition","no")
            if child.tag != A+"text-match" or list(child) or comparison not in ("contains","equals","starts-with","ends-with") or collation not in ("i;unicode-casemap","i;ascii-casemap") or negate not in ("yes","no"):
                raise HTTPException(403,"Nicht unterstützter Textfilter")
            needle = child.text or ""
            def match(value,needle=needle,comparison=comparison,collation=collation):
                normalize = str.casefold if collation=="i;unicode-casemap" else lambda text: text.translate(str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ","abcdefghijklmnopqrstuvwxyz"))
                value,needle = normalize(value),normalize(needle)
                if comparison=="equals": return value==needle
                if comparison=="starts-with": return value.startswith(needle)
                if comparison=="ends-with": return value.endswith(needle)
                return needle in value
            matches.append((match,negate=="yes"))
        def predicate(person,n=name,checks=matches,test=test):
            values = contact_fields(person)[n]
            if not values: return False
            results = [any(match(v) for v in values) != negate for match,negate in checks]
            return (all(results) if test=="allof" else any(results)) if results else True
        predicates.append(predicate)
    return lambda person: (all(p(person) for p in predicates) if mode=="allof" else any(p(person) for p in predicates)) if predicates else True


def report(db,owner,root):
    prop = root.find(D+"prop")
    names = list(dict.fromkeys(e.tag for e in prop)) if prop is not None else [D+"getetag",A+"address-data"]
    if len(names)>100:
        raise HTTPException(400,"Zu viele Eigenschaften")
    if prop is not None:
        for elem in prop:
            if elem.tag==A+"address-data" and (elem.get("version","3.0")!="3.0" or elem.get("content-type","text/vcard")!="text/vcard"):
                raise HTTPException(403,"Nur vCard 3.0 wird unterstützt")
            if elem.tag==A+"address-data" and list(elem):
                raise HTTPException(403,"Teilprojektionen von vCards werden noch nicht unterstützt")
    response = ET.Element(D+"multistatus")
    if root.tag==A+"addressbook-query":
        predicate = filter_predicate(root)
        # Reject query limits instead of silently returning a truncated address book.
        if root.find(A+"limit") is not None:
            raise HTTPException(403,"Abfragelimits werden nicht unterstützt")
        for person in people(db,owner):
            if predicate(person):
                add_response(response,card_path(owner,person),properties(db,owner,"card",person,names),names)
    elif root.tag==A+"addressbook-multiget":
        paths = [el.text or "" for el in root.findall(D+"href")]
        if len(paths)>MAX_RESOURCES:
            raise HTTPException(507,"Zu viele Kontakte")
        ids = {pid for path in paths if (pid:=parse_card_id(owner,path))}
        rows = {p.id:p for p in people(db,owner,ids)}
        for path in paths:
            person = rows.get(parse_card_id(owner,path))
            if person:
                add_response(response,card_path(owner,person),properties(db,owner,"card",person,names),names)
            else:
                item=ET.Element(D+"response")
                href(item,path)
                ET.SubElement(item,D+"status").text="HTTP/1.1 404 Not Found"
                append_bounded(response,item)
    else:
        raise HTTPException(403,"Dieser DAV-Report wird nicht unterstützt")
    return xml_response(response,HEADERS)


@router.api_route("/.well-known/carddav",methods=["GET","HEAD","OPTIONS","PROPFIND"])
def discover():
    return RedirectResponse("/carddav/",status_code=308,headers={"Cache-Control":"no-store"})


def handle(db,owner,path,method,headers,root):
    kind,person=resolve(db,owner,path)
    if not kind:
        raise HTTPException(404,"Adressbuchressource nicht gefunden")
    if method=="OPTIONS":
        return Response(status_code=200,headers=HEADERS)
    if method=="PROPFIND":
        return propfind(db,owner,kind,person,root,headers.get("depth","infinity"))
    if method=="REPORT" and kind=="book":
        return report(db,owner,root)
    if method in ("GET","HEAD") and person:
        data=card_data(person).encode()
        tag='"'+sha256(data).hexdigest()+'"'
        if headers.get("if-none-match") and (tag in [v.strip().removeprefix("W/") for v in headers["if-none-match"].split(",")] or headers["if-none-match"].strip()=="*"):
            return Response(status_code=304,headers={**HEADERS,"ETag":tag})
        return Response(data if method=="GET" else b"",media_type="text/vcard",headers={**HEADERS,"ETag":tag,"Content-Length":str(len(data))})
    raise HTTPException(405,"LifePilot-Adressbuch ist nur lesbar",headers=HEADERS)


@router.api_route("/carddav",methods=METHODS,include_in_schema=False)
@router.api_route("/carddav/{path:path}",methods=METHODS,include_in_schema=False)
async def carddav(request:Request,db:Session=Depends(get_db),owner:User=Depends(carddav_user)):
    method=request.method
    if method not in ("OPTIONS","GET","HEAD","PROPFIND","REPORT"):
        raise HTTPException(405,"LifePilot-Adressbuch ist nur lesbar",headers=HEADERS)
    root=await read_xml(request,method=="REPORT") if method in ("PROPFIND","REPORT") else None
    return await run_in_threadpool(handle,db,owner,request.url.path,method,request.headers,root)
