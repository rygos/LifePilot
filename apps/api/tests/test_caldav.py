import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from uuid import uuid4

from sqlalchemy.orm import Session
from lifepilot.db import engine
from lifepilot.models import User, DavKey
from lifepilot.security import hash_password
from lifepilot.caldav_routes import D, C
from lifepilot.shortcut_routes import digest


def account(client):
    username = "dav-" + uuid4().hex
    with Session(engine) as db:
        user = User(username=username, password_hash=hash_password("test-password"))
        db.add(user)
        db.commit()
    token = client.post("/api/auth/login", json={"username": username, "password": "test-password"}).json()["access_token"]
    return {"Authorization": "Bearer " + token}


def issue(client, auth):
    result = client.post("/api/dav/keys", headers=auth, json={"label":"Kalender", "current_password":"test-password", "expires_in_days":30})
    assert result.status_code == 201, result.text
    assert result.headers["cache-control"] == "no-store"
    return result.json()


def event(client, auth, **values):
    response = client.post("/api/events", headers=auth, json={"title":"Termin", "starts_at":"2027-01-10T09:00:00Z", **values})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def propfind(client, path, creds, props, depth="0"):
    body = '<D:propfind xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav"><D:prop>' + props + '</D:prop></D:propfind>'
    result = client.request("PROPFIND", path, auth=creds, headers={"Depth":depth}, content=body)
    assert result.status_code == 207, result.text
    return ET.fromstring(result.content)


def test_caldav_discovery_and_calendar_query(client):
    auth = account(client)
    other = account(client)
    key = issue(client, auth)
    creds = (key["username"], key["password"])
    path = key["calendar_path"]
    assert client.get("/.well-known/caldav", follow_redirects=False).headers["location"] == "/dav/"
    assert client.request("PROPFIND", "/dav/", headers={"Depth":"0"}).status_code == 401
    assert client.options("/dav/", auth=creds).status_code == 200
    root = propfind(client, "/dav/", creds, "<D:current-user-principal/>")
    principal = root.find(".//"+D+"current-user-principal/"+D+"href").text
    home = propfind(client, principal, creds, "<C:calendar-home-set/>").find(".//"+C+"calendar-home-set/"+D+"href").text
    collections = propfind(client, home, creds, "<D:resourcetype/><D:displayname/>", "1")
    assert path in [el.text for el in collections.findall(".//"+D+"response/"+D+"href")]
    assert collections.find(".//"+C+"calendar") is not None
    first = event(client, auth, title="Besprechung, München; " + "ä"*80, description="Zeile 1\nBEGIN:VEVENT", starts_at="2027-01-10T09:00:00+01:00", ends_at="2027-01-10T11:00:00+01:00", location="Büro")
    second = event(client, auth, starts_at="2027-01-10T10:00:00Z")
    event(client, auth, starts_at="2027-02-10T10:00:00Z")
    event(client, auth, record_type="experience")
    foreign = event(client, other)
    query = '<C:calendar-query xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav"><D:prop><D:getetag/><C:calendar-data/></D:prop><C:filter><C:comp-filter name="VCALENDAR"><C:comp-filter name="VEVENT"><C:time-range start="20270110T090000Z" end="20270110T100000Z"/></C:comp-filter></C:comp-filter></C:filter></C:calendar-query>'
    result = client.request("REPORT", path, auth=creds, content=query)
    assert result.status_code == 207, result.text
    xml = ET.fromstring(result.content)
    assert [r.text for r in xml.findall(".//"+D+"response/"+D+"href")] == [path+first+".ics"]
    get = client.get(path+first+".ics", auth=creds)
    assert get.status_code == 200
    assert "DTSTART:20270110T080000Z" in get.text
    assert "DTEND:20270110T100000Z" in get.text
    assert "DESCRIPTION:Zeile 1\\nBEGIN:VEVENT" in get.text
    assert "Besprechung\\, München\\;" in get.text
    assert all(len(line) <= 75 for line in get.content.split(b"\r\n"))
    tag = get.headers["etag"]
    assert tag == xml.find(".//"+D+"getetag").text
    assert client.get(path+first+".ics", auth=creds, headers={"If-None-Match":tag}).status_code == 304
    assert client.head(path+first+".ics", auth=creds).headers["content-length"] == str(len(get.content))
    assert client.patch("/api/events/"+first, headers=auth, json={"title":"Geändert"}).status_code == 200
    assert client.get(path+first+".ics", auth=creds).headers["etag"] != tag
    multi = '<C:calendar-multiget xmlns:C="urn:ietf:params:xml:ns:caldav" xmlns:D="DAV:"><D:prop><D:getetag/><C:calendar-data/></D:prop><D:href>'+path+second+'.ics</D:href><D:href>'+path+foreign+'.ics</D:href></C:calendar-multiget>'
    reply = client.request("REPORT", path, auth=creds, content=multi)
    assert reply.status_code == 207
    results = ET.fromstring(reply.content).findall(D+"response")
    assert results[0].find(".//"+C+"calendar-data") is not None
    assert results[1].find(D+"status").text == "HTTP/1.1 404 Not Found"
    assert client.get(path+foreign+".ics", auth=creds).status_code == 404
    for method in ["PUT","DELETE","PROPPATCH","MKCALENDAR","MOVE"]:
        assert client.request(method,path+first+".ics",auth=creds).status_code == 405
    assert client.get(path+first+".ics",auth=creds).status_code == 200
    assert client.request("PROPFIND", path, auth=creds, headers={"Depth":"infinity"}).status_code == 403
    assert client.request("REPORT", path, auth=creds, content=b'<!DOCTYPE x [<!ENTITY e "x">]><x>&e;</x>').status_code == 400
    assert client.request("REPORT", path, auth=creds, content=b"x"*65537).status_code == 413


def test_dav_key_scope_and_revocation(client):
    auth = account(client)
    other = account(client)
    assert client.post("/api/dav/keys",headers=auth,json={"label":"Test","current_password":"wrong"}).status_code == 403
    key = issue(client, auth)
    creds = (key["username"], key["password"])
    with Session(engine) as db:
        row = db.get(DavKey, key["id"])
        assert row.secret_hash == digest(key["password"])
    assert key["password"] not in client.get("/api/dav/keys",headers=auth).text
    assert client.get("/api/dav/keys",headers=other).json() == []
    assert client.delete("/api/dav/keys/"+key["id"],headers=other).status_code == 404
    assert client.get("/api/people",auth=creds).status_code == 401
    assert client.request("PROPFIND", "/dav/",headers={**auth,"Depth":"0"}).status_code == 401
    assert client.delete("/api/dav/keys/"+key["id"],headers=auth).status_code == 204
    assert client.options("/dav/",auth=creds).status_code == 401
    key = issue(client, auth)
    with Session(engine) as db:
        db.get(DavKey,key["id"]).expires_at = datetime.now(timezone.utc)-timedelta(seconds=1)
        db.commit()
    assert client.options("/dav/",auth=(key["username"],key["password"])).status_code == 401
    key = issue(client, auth)
    assert client.post("/api/auth/password",headers=auth,json={"current_password":"test-password","new_password":"new-secure-password-123"}).status_code == 200
    assert client.options("/dav/",auth=(key["username"],key["password"])).status_code == 401
