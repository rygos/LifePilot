import json
from io import BytesIO
from uuid import uuid4

from lifepilot.capture_ai import extract_facts
from lifepilot.capture_jobs import process_capture_job
from lifepilot.config import settings


def test_capture_commitments_review_and_provenance(client, auth, monkeypatch):
    name = "Zusage" + uuid4().hex[:10]
    outgoing = f"Ich habe {name} versprochen, die Unterlagen zu senden."
    incoming = f"{name} hat mir zugesagt, die Antwort am 4. Januar 2027 um 15 Uhr MEZ zu schicken."
    original = outgoing + " " + incoming
    suggestions = [
        {"kind": "commitment", "title": "Unterlagen senden", "content": outgoing, "person_name": name, "commitment_direction": "outgoing", "commitment_evidence": outgoing, "confirmation_required": False},
        {"kind": "commitment", "title": "Antwort erhalten", "content": incoming, "person_name": name, "commitment_direction": "incoming", "commitment_evidence": incoming, "due_at": "2027-01-04T15:00:00+01:00"},
        {"kind": "commitment", "title": "Erfundene Zusage", "content": "Nicht vorhanden", "person_name": name, "commitment_direction": "incoming", "commitment_evidence": "Erfundene Quelle"},
    ]
    monkeypatch.setattr(settings, "llm_base_url", "http://local-model/v1")
    monkeypatch.setattr(settings, "llm_model", "test")
    monkeypatch.setattr(settings, "redis_url", "redis://unused/0")
    monkeypatch.setattr("lifepilot.capture_routes.enqueue_capture_job", lambda *args: None)
    monkeypatch.setattr("lifepilot.capture_ai.urlopen", lambda *args, **kwargs: BytesIO(json.dumps({"choices": [{"message": {"content": json.dumps({"suggestions": suggestions})}}]}).encode()))
    person = client.post("/api/people", headers=auth, json={"first_name": name}).json()
    capture = client.post("/api/captures", headers=auth, json={"original_text": original}).json()
    owner = client.get("/api/auth/me", headers=auth).json()["id"]
    assert process_capture_job(capture["id"], owner) == "ready"
    row = next(c for c in client.get("/api/captures", headers=auth).json() if c["id"] == capture["id"])
    assert len(row["suggestions"]) == 2
    assert all(s["confirmation_required"] and s["person_id"] == person["id"] for s in row["suggestions"])
    path = f"/api/captures/{capture['id']}/review"
    before = client.get(f"/api/briefing/person/{person['id']}", headers=auth).json()
    assert before["open_commitments"] == []
    assert client.post(path, headers=auth, json={"accepted_indices": [0]}).status_code == 422
    forged = [dict(s) for s in row["suggestions"]]
    forged[0]["commitment_evidence"] = "Nicht im Original"
    assert client.post(path, headers=auth, json={"accepted_indices": [0], "confirmations": [0], "suggestions": forged}).status_code == 422
    result = client.post(path, headers=auth, json={"accepted_indices": [0, 1], "confirmations": [0, 1]})
    assert result.status_code == 201, result.text
    assert {r["resource_type"] for r in result.json()} == {"commitment"}
    saved = client.get(f"/api/briefing/person/{person['id']}", headers=auth).json()["open_commitments"]
    by_direction = {c["direction"]: c for c in saved}
    assert set(by_direction) == {"incoming", "outgoing"}
    assert by_direction["outgoing"]["source_quote"] == outgoing
    assert by_direction["incoming"]["source_quote"] == incoming
    assert all(c["source_capture_id"] == capture["id"] for c in saved)
    assert by_direction["incoming"]["due_at"].startswith("2027-01-04T14:00:00")
    assert client.post(path, headers=auth, json={"accepted_indices": [0], "confirmations": [0]}).status_code == 409
    repeat = client.post("/api/captures", headers=auth, json={"original_text": original}).json()
    assert process_capture_job(repeat["id"], owner) == "ready"
    repeated = next(c for c in client.get("/api/captures", headers=auth).json() if c["id"] == repeat["id"])
    assert repeated["suggestions"] == []


def test_commitment_evidence_only_from_current_capture(monkeypatch):
    text = "Heute habe ich mit Anna gesprochen. Anna hat mir zugesagt, die Datei zu schicken."
    evidence = "Anna hat mir zugesagt, die Datei zu schicken."
    suggestions = [
        {"kind": "commitment", "title": "Datei erhalten", "content": evidence, "person_name": "Anna", "commitment_direction": "incoming", "commitment_evidence": evidence, "due_at": "2027-01-01T12:00:00"},
        {"kind": "commitment", "title": "Alt", "content": "Alte Zusage", "person_name": "Anna", "commitment_direction": "outgoing", "commitment_evidence": "Alte Zusage"},
    ]
    monkeypatch.setattr(settings, "llm_base_url", "http://local-model/v1")
    monkeypatch.setattr(settings, "llm_model", "test")
    monkeypatch.setattr("lifepilot.capture_ai.urlopen", lambda *args, **kwargs: BytesIO(json.dumps({"choices": [{"message": {"content": json.dumps({"suggestions": suggestions})}}]}).encode()))
    extracted = extract_facts(text, prior_context="Bisherige Nutzereingabe: Alte Zusage")
    commitments = [s for s in extracted if s.kind == "commitment"]
    assert len(commitments) == 1
    assert commitments[0].commitment_evidence == evidence
    assert commitments[0].confirmation_required
    assert commitments[0].due_at is None
