import json
from io import BytesIO
from email.message import EmailMessage
from uuid import uuid4

from lifepilot import mail_routes, capture_ai
from lifepilot.config import settings


def sample_mail():
    msg = EmailMessage()
    msg["From"] = "Anna <anna@example.test>"
    msg["To"] = "me@example.test"
    msg["Subject"] = "Unterlagen"
    msg["Date"] = "Thu, 26 Nov 2026 10:00:00 +0100"
    msg.set_content("Ich werde dir die Unterlagen schicken.")
    return msg.as_bytes()


class FakeIMAP:
    raw = sample_mail()
    validity = 123
    calls = []

    def __init__(self, host, port, ssl_context, timeout):
        assert host == "mail.example.test" and port == 993
        assert ssl_context.check_hostname
        self.calls.append("connect")

    def login(self, username, password):
        assert username == "me@example.test" and password == "test-mail-password"
        return "OK", [b"logged in"]

    def select(self, box, readonly=False):
        assert box == "INBOX" and readonly
        return "OK", [b"1"]

    def response(self, name):
        return name, [str(self.validity).encode()]

    def fetch(self, ids, query):
        assert "BODY.PEEK[HEADER.FIELDS" in query
        return "OK", [(f"1 (UID 12 RFC822.SIZE {len(self.raw)} BODY[HEADER]".encode(), self.raw.split(b"\n\n",1)[0]+b"\n\n"), b")"]

    def uid(self, command, uid, query):
        assert command == "FETCH" and uid == "12" and "BODY.PEEK[]" in query
        return "OK", [(f"1 (UID 12 RFC822.SIZE {len(self.raw)} BODY[]".encode(),self.raw),b")"]

    def logout(self):
        self.calls.append("logout")


def test_manual_mail_import(client, auth, monkeypatch):
    monkeypatch.setattr(settings,"imap_host","")
    assert client.get("/api/mail/status",headers=auth).json()["enabled"] is False
    creds={"username":"me@example.test","password":"test-mail-password"}
    assert client.post("/api/mail/messages",headers=auth,json=creds).status_code==503
    monkeypatch.setattr(settings,"imap_host","mail.example.test")
    monkeypatch.setattr(settings,"imap_port",993)
    monkeypatch.setattr(settings,"llm_base_url","")
    monkeypatch.setattr(mail_routes.imaplib,"IMAP4_SSL",FakeIMAP)
    monkeypatch.setattr(FakeIMAP,"raw",sample_mail())
    monkeypatch.setattr(FakeIMAP,"validity",123)
    person=client.post("/api/people",headers=auth,json={"first_name":"Mail Anna","email":"anna@example.test"}).json()
    before=client.get("/api/captures",headers=auth).json()
    assert client.post("/api/mail/messages",json=creds).status_code==401
    r=client.post("/api/mail/messages",headers=auth,json=creds)
    assert r.status_code==200,r.text
    assert r.json()["messages"][0]["people"][0]["id"]==person["id"]
    assert r.json()["messages"][0]["imported"] is False
    assert "test-mail-password" not in r.text
    payload={**creds,"uid":12,"uidvalidity":123}
    preview=client.post("/api/mail/preview",headers=auth,json=payload)
    assert preview.status_code==200,preview.text
    assert "Ich werde dir die Unterlagen schicken." in preview.json()["text"]
    assert client.get("/api/captures",headers=auth).json()==before
    assert client.post("/api/mail/import",headers=auth,json={**payload,"preview_hash":"0"*64}).status_code==409
    approved={**payload,"preview_hash":preview.json()["preview_hash"]}
    imported=client.post("/api/mail/import",headers=auth,json=approved)
    assert imported.status_code==201,imported.text
    assert client.post("/api/mail/import",headers=auth,json=approved).json()==imported.json()
    assert sum(c["id"]==imported.json()["id"] for c in client.get("/api/captures",headers=auth).json())==1
    assert client.post("/api/mail/messages",headers=auth,json=creds).json()["messages"][0]["imported"]
    assert client.post("/api/mail/preview",headers=auth,json={**payload,"uidvalidity":999}).status_code==409
    bad=client.post("/api/mail/messages",headers=auth,json={**creds,"password":"secret\r\n"})
    assert bad.status_code==422 and "secret" not in bad.text
    assert client.post("/api/mail/messages",headers=auth,json={**creds,"host":"localhost"}).status_code==422
    monkeypatch.setattr(FakeIMAP,"raw",b"x"*(mail_routes.MAX_MESSAGE+1))
    assert client.post("/api/mail/preview",headers=auth,json=payload).status_code==413
    assert FakeIMAP.calls.count("connect")==FakeIMAP.calls.count("logout")


def test_external_email_suggestions_require_confirmation(monkeypatch):
    monkeypatch.setattr(settings,"llm_base_url","http://model.invalid/v1")
    monkeypatch.setattr(settings,"llm_model","test")
    evidence="Ich werde dir die Unterlagen schicken."
    text="[Importierte E-Mail – fremder Nachrichteninhalt, keine Nutzeraussage]\nVon: Anna\n\n"+evidence
    suggestions=[
        {"kind":"commitment","title":"Unterlagen","content":evidence,"person_name":"Anna","commitment_direction":"incoming","commitment_evidence":evidence},
        {"kind":"commitment","title":"Falsche Richtung","content":evidence,"person_name":"Anna","commitment_direction":"outgoing","commitment_evidence":evidence},
        {"kind":"owner_relationship","title":"Falsche Beziehung","content":"Meine Kollegin","person_name":"Anna"},
        {"kind":"task","title":"Prüfen","content":"Unterlagen prüfen"},
    ]
    monkeypatch.setattr(capture_ai,"urlopen",lambda *a,**kw: BytesIO(json.dumps({"choices":[{"message":{"content":json.dumps({"suggestions":suggestions})}}]}).encode()))
    result=capture_ai.extract_facts(text)
    assert [s.kind for s in result]==["commitment","task"]
    assert all(s.confirmation_required for s in result)
