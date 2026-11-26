"""Read-only CalDAV projection of LifePilot appointments."""
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from hashlib import sha256
from urllib.parse import urlsplit
from uuid import UUID

from anyio import fail_after
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from lifepilot.dav_auth import dav_user
from lifepilot.db import get_db
from lifepilot.models import Event, User
from lifepilot.shortcut_routes import utc

router = APIRouter(tags=["CalDAV"])
D = "{DAV:}"
C = "{urn:ietf:params:xml:ns:caldav}"
CS = "{http://calendarserver.org/ns/}"
ET.register_namespace("D", "DAV:")
ET.register_namespace("C", "urn:ietf:params:xml:ns:caldav")
ET.register_namespace("CS", "http://calendarserver.org/ns/")
MAX_RESOURCES = 2000
MAX_XML_BYTES = 65536
MAX_RESPONSE_BYTES = 16 * 1024 * 1024
DAV_HEADERS = {"DAV": "1, calendar-access", "Allow": "OPTIONS, GET, HEAD, PROPFIND, REPORT", "Cache-Control": "private, no-store", "Vary": "Authorization"}


def clean_text(value: str):
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]", "", value)


def ical_text(value: str):
    return clean_text(value).replace("\\", "\\\\").replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\\n").replace(";", "\\;").replace(",", "\\,")


def stamp(value: datetime):
    return utc(value).strftime("%Y%m%dT%H%M%SZ")


def fold(line: str):
    # RFC 5545: fold by UTF-8 octets, never inside a codepoint.
    lines = []
    part = ""
    size = 0
    for char in line:
        count = len(char.encode("utf-8"))
        if size + count > 75:
            lines.append(part)
            part, size = " ", 1
        part += char
        size += count
    lines.append(part)
    return "\r\n".join(lines)


def calendar_data(event: Event):
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//LifePilot//CalDAV//DE", "CALSCALE:GREGORIAN", "BEGIN:VEVENT",
             f"UID:{event.id}@lifepilot", f"DTSTAMP:{stamp(event.created_at)}", f"DTSTART:{stamp(event.starts_at)}",
             "SUMMARY:" + ical_text(event.title)]
    if event.ends_at and utc(event.ends_at) > utc(event.starts_at):
        lines.append("DTEND:" + stamp(event.ends_at))
    if event.description:
        lines.append("DESCRIPTION:" + ical_text(event.description))
    if event.location or event.location_address:
        lines.append("LOCATION:" + ical_text(", ".join(v for v in (event.location, event.location_address) if v)))
    lines.extend(["END:VEVENT", "END:VCALENDAR"])
    data = "\r\n".join(fold(line) for line in lines) + "\r\n"
    if len(data.encode()) > 1024 * 1024:
        raise HTTPException(507, "Ein Termin überschreitet die maximale Kalenderressourcengröße")
    return data


def etag(event):
    return '"' + sha256(calendar_data(event).encode()).hexdigest() + '"'


def path_for(owner, kind):
    return {"root": "/dav/", "principals": "/dav/principals/", "principal": f"/dav/principals/{owner.id}/",
            "calendars": "/dav/calendars/", "home": f"/dav/calendars/{owner.id}/",
            "calendar": f"/dav/calendars/{owner.id}/lifepilot/"}[kind]


def event_path(owner, event):
    return path_for(owner, "calendar") + event.id + ".ics"


def select_events(db, owner, start=None, end=None, ids=None):
    stmt = select(Event).where(Event.owner_id == owner.id, Event.record_type == "appointment")
    if ids is not None:
        stmt = stmt.where(Event.id.in_(ids))
    if start is not None:
        stmt = stmt.where(or_(and_(Event.ends_at > Event.starts_at, Event.ends_at > start), and_(or_(Event.ends_at.is_(None), Event.ends_at <= Event.starts_at), Event.starts_at >= start)))
    if end is not None:
        stmt = stmt.where(Event.starts_at < end)
    rows = list(db.scalars(stmt.order_by(Event.id).limit(MAX_RESOURCES + 1)))
    if len(rows) > MAX_RESOURCES:
        raise HTTPException(507, "Zu viele Termine. Bitte einen kleineren Zeitraum abfragen.")
    return rows


def resolve(db, owner, path):
    for kind in ("root", "principals", "principal", "calendars", "home", "calendar"):
        if path.rstrip("/") == path_for(owner, kind).rstrip("/"):
            return kind, None
    prefix = path_for(owner, "calendar")
    if path.startswith(prefix) and re.fullmatch(r"[0-9a-f-]{36}\.ics", path[len(prefix):]):
        try:
            eid = str(UUID(path[len(prefix):-4]))
        except ValueError:
            return None, None
        event = db.scalar(select(Event).where(Event.id == eid, Event.owner_id == owner.id, Event.record_type == "appointment"))
        if event:
            return "event", event
    return None, None


def href(node, path):
    ET.SubElement(node, D + "href").text = path


def properties(db, owner, kind, event, names):
    out = {}
    def node(tag):
        element = ET.Element(tag)
        out[tag] = element
        return element
    principal = path_for(owner, "principal")
    href(node(D + "current-user-principal"), principal)
    href(node(D + "owner"), principal)
    privilege = ET.SubElement(node(D + "current-user-privilege-set"), D + "privilege")
    ET.SubElement(privilege, D + "read")
    resource = node(D + "resourcetype")
    if kind != "event":
        ET.SubElement(resource, D + "collection")
    if kind == "principal":
        ET.SubElement(resource, D + "principal")
    if kind == "calendar":
        ET.SubElement(resource, C + "calendar")
    node(D + "displayname").text = clean_text(event.title) if event else {"root":"LifePilot", "principals":"Benutzer", "principal":"LifePilot-Konto", "calendars":"Kalender", "home":"Meine Kalender", "calendar":"LifePilot"}[kind]
    if kind == "principal":
        href(node(D + "principal-URL"), principal)
        href(node(C + "calendar-home-set"), path_for(owner, "home"))
    if kind == "calendar":
        node(C + "calendar-description").text = "LifePilot-Termine (nur lesbar)"
        components = node(C + "supported-calendar-component-set")
        ET.SubElement(components, C + "comp", {"name": "VEVENT"})
        data = node(C + "supported-calendar-data")
        ET.SubElement(data, C + "calendar-data", {"content-type":"text/calendar", "version":"2.0"})
        reports = node(D + "supported-report-set")
        for tag in (C + "calendar-query", C + "calendar-multiget"):
            ET.SubElement(ET.SubElement(ET.SubElement(reports, D + "supported-report"), D + "report"), tag)
        if CS + "getctag" in names:
            node(CS + "getctag").text = sha256("".join(e.id + etag(e) for e in select_events(db, owner)).encode()).hexdigest()
    if event:
        data = calendar_data(event)
        node(D + "getcontenttype").text = "text/calendar; charset=utf-8"
        node(D + "getcontentlength").text = str(len(data.encode()))
        node(D + "getetag").text = etag(event)
        if C + "calendar-data" in names:
            node(C + "calendar-data").text = data
    return out


def add_response(root, path, props, names, propname=False):
    response = ET.Element(D + "response")
    href(response, path)
    selected = list(props) if names is None else names
    for found, status in ((True, "200 OK"), (False, "404 Not Found")):
        group = [name for name in selected if (name in props) == found]
        if not group:
            continue
        propstat = ET.SubElement(response, D + "propstat")
        prop = ET.SubElement(propstat, D + "prop")
        for name in group:
            prop.append(props[name] if found and not propname else ET.Element(name))
        ET.SubElement(propstat, D + "status").text = "HTTP/1.1 " + status
    append_bounded(root, response)


def append_bounded(root, response):
    size = int(root.attrib.get("_size", "0")) + len(ET.tostring(response, encoding="utf-8"))
    if size > MAX_RESPONSE_BYTES:
        raise HTTPException(507, "Kalenderantwort zu groß")
    root.set("_size", str(size))
    root.append(response)


def xml_response(root):
    root.attrib.pop("_size", None)
    data = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    if len(data) > MAX_RESPONSE_BYTES:
        raise HTTPException(507, "Kalenderantwort zu groß")
    return Response(data, status_code=207, media_type="application/xml", headers=DAV_HEADERS)


async def read_xml(request, required=False):
    raw = bytearray()
    try:
        with fail_after(15):
            async for chunk in request.stream():
                if len(raw) + len(chunk) > MAX_XML_BYTES:
                    raise HTTPException(413, "DAV-Anfrage zu groß")
                raw.extend(chunk)
    except TimeoutError:
        raise HTTPException(408, "DAV-Anfrage hat zu lange gedauert") from None
    if not raw.strip() and not required:
        return None
    try:
        value = raw.decode("utf-8-sig")
        if "<!" in value or "\x00" in value:
            raise ValueError("XML declarations not supported")
        root = ET.fromstring(value)
        if sum(1 for _ in root.iter()) > 5000:
            raise ValueError("Too many XML elements")
        return root
    except (ValueError, UnicodeError, ET.ParseError):
        raise HTTPException(400, "Ungültige DAV-XML-Anfrage") from None


def propfind(db, owner, kind, event, root, depth):
    if depth not in ("0", "1"):
        raise HTTPException(403, "Nur Depth 0 und 1 werden unterstützt")
    if root is not None and root.tag != D + "propfind":
        raise HTTPException(400, "PROPFIND erwartet DAV:propfind")
    prop = root.find(D + "prop") if root is not None else None
    names = list(dict.fromkeys(e.tag for e in prop)) if prop is not None else None
    propname = root is not None and root.find(D + "propname") is not None
    if names is not None and len(names) > 100:
        raise HTTPException(400, "Zu viele Eigenschaften")
    if names is None and root is not None and root.find(D + "include") is not None:
        # allprop + include: include specifically requested optional properties.
        extra = [e.tag for e in root.find(D + "include")]
    else:
        extra = []
    targets = [(kind, event)]
    if depth == "1":
        children = {"root":["principals","calendars"], "principals":["principal"], "calendars":["home"], "home":["calendar"]}.get(kind, [])
        targets.extend((child, None) for child in children)
        if kind == "calendar":
            targets.extend(("event", row) for row in select_events(db, owner))
    response = ET.Element(D + "multistatus")
    for resource, row in targets:
        props = properties(db, owner, resource, row, (names or []) + extra)
        selected = list(dict.fromkeys(list(props) + extra)) if names is None and extra else names
        add_response(response, event_path(owner, row) if row else path_for(owner, resource), props, selected, propname)
    return xml_response(response)


def range_filter(root):
    filt = root.find(C + "filter")
    if filt is None:
        raise HTTPException(400, "Kalenderfilter fehlt")
    outer = list(filt)
    if len(outer) != 1 or outer[0].tag != C + "comp-filter" or outer[0].get("name") != "VCALENDAR":
        raise HTTPException(403, "Nur VCALENDAR/VEVENT-Filter werden unterstützt")
    inner = list(outer[0])
    if not inner:
        return None, None
    if len(inner) != 1 or inner[0].tag != C + "comp-filter" or inner[0].get("name") != "VEVENT":
        raise HTTPException(403, "Nur VEVENT-Filter werden unterstützt")
    children = list(inner[0])
    if not children:
        return None, None
    if len(children) != 1 or children[0].tag != C + "time-range":
        raise HTTPException(403, "Nur VEVENT-Zeitbereichsfilter werden unterstützt")
    try:
        span = children[0]
        start, end = (datetime.strptime(span.get(k), "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc) if span.get(k) else None for k in ("start","end"))
        if (start is None and end is None) or (start and end and start >= end):
            raise ValueError()
        return start, end
    except ValueError:
        raise HTTPException(400, "Ungültiger UTC-Zeitbereich") from None


def report(db, owner, root):
    prop = root.find(D + "prop")
    names = list(dict.fromkeys(e.tag for e in prop)) if prop is not None else [D + "getetag", C + "calendar-data"]
    if len(names) > 100:
        raise HTTPException(400, "Zu viele Eigenschaften")
    response = ET.Element(D + "multistatus")
    if root.tag == C + "calendar-query":
        start, end = range_filter(root)
        for event in select_events(db, owner, start, end):
            add_response(response, event_path(owner, event), properties(db, owner, "event", event, names), names)
    elif root.tag == C + "calendar-multiget":
        paths = [item.text or "" for item in root.findall(D + "href")]
        if len(paths) > MAX_RESOURCES:
            raise HTTPException(507, "Zu viele Kalenderressourcen")
        prefix = path_for(owner, "calendar")
        ids = set()
        for path in paths:
            try:
                parsed = urlsplit(path)
                if parsed.path.startswith(prefix) and parsed.path.endswith(".ics") and not parsed.query and not parsed.fragment:
                    ids.add(str(UUID(parsed.path[len(prefix):-4])))
            except ValueError:
                pass
        events = {e.id:e for e in select_events(db, owner, ids=ids)}
        for path in paths:
            try:
                parsed = urlsplit(path)
                event = events.get(parsed.path[len(prefix):-4]) if parsed.path.startswith(prefix) and parsed.path.endswith(".ics") and not parsed.query and not parsed.fragment else None
            except ValueError:
                event = None
            if event:
                add_response(response, event_path(owner, event), properties(db, owner, "event", event, names), names)
            else:
                item = ET.Element(D + "response")
                href(item, path)
                ET.SubElement(item, D + "status").text = "HTTP/1.1 404 Not Found"
                append_bounded(response, item)
    else:
        raise HTTPException(403, "Dieser DAV-Report wird nicht unterstützt")
    return xml_response(response)


@router.api_route("/.well-known/caldav", methods=["GET","HEAD","OPTIONS","PROPFIND"])
def discover():
    return RedirectResponse("/dav/", status_code=308, headers={"Cache-Control":"no-store"})


METHODS = ["OPTIONS","GET","HEAD","PROPFIND","REPORT","PUT","DELETE","POST","PATCH","PROPPATCH","MKCALENDAR","MKCOL","MOVE","COPY","LOCK","UNLOCK","ACL"]


def handle(db, owner, path, method, headers, root):
    kind, event = resolve(db, owner, path)
    if not kind:
        raise HTTPException(404, "Kalenderressource nicht gefunden")
    if method == "OPTIONS":
        return Response(status_code=200, headers=DAV_HEADERS)
    if method == "PROPFIND":
        return propfind(db, owner, kind, event, root, headers.get("depth", "infinity"))
    if method == "REPORT" and kind == "calendar":
        return report(db, owner, root)
    if method in ("GET","HEAD") and event:
        data = calendar_data(event).encode()
        tag = etag(event)
        response_headers = {**DAV_HEADERS, "ETag":tag, "Content-Length":str(len(data))}
        if headers.get("if-none-match") and (tag in [v.strip().removeprefix("W/") for v in headers["if-none-match"].split(",")] or headers["if-none-match"].strip() == "*"):
            return Response(status_code=304, headers={**DAV_HEADERS,"ETag":tag})
        return Response(data if method == "GET" else b"", media_type="text/calendar", headers=response_headers)
    raise HTTPException(405, "LifePilot-Kalender ist nur lesbar", headers=DAV_HEADERS)


@router.api_route("/dav", methods=METHODS, include_in_schema=False)
@router.api_route("/dav/{path:path}", methods=METHODS, include_in_schema=False)
async def dav(request: Request, db: Session = Depends(get_db), owner: User = Depends(dav_user)):
    method = request.method
    if method not in ("OPTIONS","GET","HEAD","PROPFIND","REPORT"):
        raise HTTPException(405, "LifePilot-Kalender ist nur lesbar", headers=DAV_HEADERS)
    root = await read_xml(request, method == "REPORT") if method in ("PROPFIND","REPORT") else None
    return await run_in_threadpool(handle, db, owner, request.url.path, method, request.headers, root)
