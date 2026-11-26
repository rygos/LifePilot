import xml.etree.ElementTree as ET
from uuid import uuid4

from sqlalchemy.orm import Session
from lifepilot.db import engine
from lifepilot.models import User
from lifepilot.security import hash_password
from lifepilot.carddav_routes import A, D


def account(client):
    name = "carddav-" + uuid4().hex
    with Session(engine) as db:
        db.add(User(username=name, password_hash=hash_password("test-password")))
        db.commit()
    token = client.post("/api/auth/login", json={"username": name, "password": "test-password"}).json()["access_token"]
    return {"Authorization": "Bearer " + token}


def issue(client, auth, scope="contacts:read"):
    r = client.post("/api/dav/keys", headers=auth, json={"label":"Adressbuch", "current_password":"test-password", "scope":scope})
    assert r.status_code == 201, r.text
    return r.json()


def person(client, auth, **fields):
    r = client.post("/api/people", headers=auth, json={"first_name":"Anna", **fields})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def propfind(client, path, creds, props, depth="0"):
    xml = '<D:propfind xmlns:D="DAV:" xmlns:A="urn:ietf:params:xml:ns:carddav"><D:prop>'+props+'</D:prop></D:propfind>'
    response = client.request("PROPFIND", path, auth=creds, headers={"Depth":depth}, content=xml)
    assert response.status_code == 207, response.text
    return ET.fromstring(response.content)


def test_carddav_discovery_privacy_and_etags(client):
    auth, other = account(client), account(client)
    key = issue(client,auth)
    assert key["calendar_path"] is None
    path = key["addressbook_path"]
    creds = key["username"],key["password"]
    calendar = issue(client,auth,"calendar:read")
    assert client.options("/carddav/",auth=(calendar["username"],calendar["password"])).status_code == 401
    assert client.options("/dav/",auth=creds).status_code == 401
    assert client.get("/api/people",auth=creds).status_code == 401
    assert client.get("/.well-known/carddav",follow_redirects=False).headers["location"] == "/carddav/"
    assert client.options("/carddav/",auth=creds).headers["dav"] == "1, addressbook"
    principal=propfind(client,"/carddav/",creds,"<D:current-user-principal/>").find(".//"+D+"current-user-principal/"+D+"href").text
    home=propfind(client,principal,creds,"<A:addressbook-home-set/>").find(".//"+A+"addressbook-home-set/"+D+"href").text
    book=propfind(client,home,creds,"<D:resourcetype/>","1")
    assert book.find(".//"+A+"addressbook") is not None
    assert path in [h.text for h in book.findall(".//"+D+"response/"+D+"href")]
    pid=person(client,auth,last_name="Müller, Test",email="anna@example.test",phone="+49123",address="Straße 1\nKöln",birthday="1990-03-04",notes="GEHEIME NOTIZ",how_met="GEHEIMER KONTEXT",tags=["PRIVAT"],organization="Firma",job_title="Technik")
    foreign=person(client,other,first_name="Fremd")
    partial=person(client,auth,first_name="Teilgeburtstag",birthday_precision="month_day",birthday_month=3,birthday_day=4)
    for typ,value in [("email","zweite@example.test"),("phone","+49124"),("social","NICHT_EXPORTIEREN"),("email","anna@example.test")]:
        r=client.post(f"/api/people/{pid}/contact-methods",headers=auth,json={"method_type":typ,"value":value})
        assert r.status_code==201,r.text
    url=path+pid+".vcf"
    r=client.get(url,auth=creds)
    assert r.status_code==200
    assert r.text.startswith("BEGIN:VCARD\r\nVERSION:3.0")
    assert "FN:Anna Müller\\, Test" in r.text
    assert "BDAY:1990-03-04" in r.text
    assert "ADR:;;Straße 1\\nKöln;;;;" in r.text
    assert "EMAIL:zweite@example.test" in r.text and r.text.count("EMAIL:anna@example.test")==1
    assert "TEL:+49124" in r.text and "ORG:Firma" in r.text
    assert all(x not in r.text for x in ["GEHEIM","PRIVAT","NICHT_EXPORTIEREN","NOTE:"])
    assert all(len(line)<=75 for line in r.content.split(b"\r\n"))
    assert "BDAY:" not in client.get(path+partial+".vcf",auth=creds).text
    assert client.get(path+foreign+".vcf",auth=creds).status_code==404
    tag=r.headers["etag"]
    assert client.get(url,auth=creds,headers={"If-None-Match":tag}).status_code==304
    assert client.head(url,auth=creds).headers["content-length"]==str(len(r.content))
    assert client.patch("/api/people/"+pid,headers=auth,json={"nickname":"Neu"}).status_code==200
    assert client.get(url,auth=creds).headers["etag"]!=tag
    for method in ["PUT","DELETE","PROPPATCH","MKCOL"]:
        assert client.request(method,url,auth=creds).status_code==405
    assert client.get(url,auth=creds).status_code==200
    listed=propfind(client,path,creds,"<D:getetag/>","1")
    assert set(h.text for h in listed.findall(".//"+D+"response/"+D+"href"))=={path,url,path+partial+".vcf"}
    # The session-wide test database also feeds the global birthday scheduler.
    # Remove these test contacts and verify they disappear from DAV.
    for contact in (pid, partial):
        assert client.delete("/api/people/"+contact,headers=auth).status_code==204
        assert client.get(path+contact+".vcf",auth=creds).status_code==404


def test_carddav_reports_and_key_revocation(client):
    auth=account(client)
    other=account(client)
    key=issue(client,auth)
    creds=key["username"],key["password"]
    path=key["addressbook_path"]
    a=person(client,auth,last_name="Müller")
    b=person(client,auth,first_name="Thomas")
    foreign=person(client,other)
    query='<A:addressbook-query xmlns:A="urn:ietf:params:xml:ns:carddav" xmlns:D="DAV:"><D:prop><D:getetag/><A:address-data/></D:prop><A:filter><A:prop-filter name="FN"><A:text-match match-type="contains">MÜLLER</A:text-match></A:prop-filter></A:filter></A:addressbook-query>'
    r=client.request("REPORT",path,auth=creds,content=query)
    assert r.status_code==207,r.text
    assert [h.text for h in ET.fromstring(r.content).findall(".//"+D+"response/"+D+"href")]==[path+a+".vcf"]
    multi='<A:addressbook-multiget xmlns:A="urn:ietf:params:xml:ns:carddav" xmlns:D="DAV:"><D:prop><A:address-data/></D:prop><D:href>'+path+b+'.vcf</D:href><D:href>'+path+foreign+'.vcf</D:href></A:addressbook-multiget>'
    r=client.request("REPORT",path,auth=creds,content=multi)
    assert r.status_code==207,r.text
    results=ET.fromstring(r.content).findall(D+"response")
    assert "FN:Thomas" in results[0].find(".//"+A+"address-data").text
    assert results[1].find(D+"status").text=="HTTP/1.1 404 Not Found"
    assert client.request("REPORT",path,auth=creds,content=query.replace('name="FN"','name="NOTE"')).status_code==403
    assert client.request("REPORT",path,auth=creds,content='<!DOCTYPE x [<!ENTITY e "x">]><x>&e;</x>').status_code==400
    assert client.delete("/api/dav/keys/"+key["id"],headers=other).status_code==404
    assert client.delete("/api/dav/keys/"+key["id"],headers=auth).status_code==204
    assert client.options("/carddav/",auth=creds).status_code==401
    assert key["password"] not in client.get("/api/dav/keys",headers=auth).text
