import json
from datetime import datetime, timezone
from io import BytesIO

from sqlalchemy import select
from sqlalchemy.orm import Session

from lifepilot.capture_ai import _life_event_has_explicit_evidence, extract_facts
from lifepilot.capture_jobs import capture_time_in_timezone, process_capture_job
from lifepilot.capture_schemas import CaptureSuggestion
from lifepilot.config import settings
from lifepilot.db import engine
from lifepilot.models import Capture, Conversation, Event, Loan, Memory, Person, Relationship


EXAMPLE = "Ich war heute bei Christan Decker und habe dort seine Frau Tanja und seine Kinder Julian, Lukas und seine Tochter Mia getroffen. Dann habe ich mit ihm ein wenig gequatscht, Lego auseinander gebaut und er hat mir einen Supersternenzerstörer geliehen um ihn mal bauen zu können."
CAPTURED_AT = datetime(2026, 11, 17, 8, tzinfo=timezone.utc)


def test_life_event_suggestions_need_evidence_in_user_text() -> None:
    wedding = CaptureSuggestion(kind="life_event", title="Hochzeit von Tanja und Christian", content="Sie haben Anfang des Jahres geheiratet.")
    birth = CaptureSuggestion(kind="life_event", title="Geburt von Julian", content="Julian wurde geboren.")

    assert not _life_event_has_explicit_evidence(wedding, "Tanja ist Christians Frau. Tanja und Christian haben zwei Söhne.")
    assert not _life_event_has_explicit_evidence(birth, "Tanja und Christian haben zwei Söhne. Julian und Lukas.")
    assert _life_event_has_explicit_evidence(wedding, "Kristin hat Anfang des Jahres geheiratet.")


def test_capture_reference_time_uses_owner_timezone_for_relative_days() -> None:
    captured_at = capture_time_in_timezone(datetime(2026, 11, 17, 23, tzinfo=timezone.utc), "Europe/Berlin")

    assert captured_at.date().isoformat() == "2026-11-18"
    assert captured_at.utcoffset().total_seconds() == 3600


def test_explicit_sons_and_daughter_are_extracted_from_full_names(monkeypatch) -> None:
    monkeypatch.setattr(settings, "llm_base_url", "http://local-model/v1")
    monkeypatch.setattr(settings, "llm_model", "qwen/qwen3.5-9b")
    payload = {"choices": [{"message": {"content": json.dumps({"suggestions": []})}}]}
    monkeypatch.setattr("lifepilot.capture_ai.urlopen", lambda request, timeout: BytesIO(json.dumps(payload).encode()))
    note = "Ich war gestern bei Christian Decker. Seine Söhne Julian Decker und Lukas Decker sowie seine Tochter Mia Decker und seine Frau Tanja Decker habe ich getroffen."

    suggestions = extract_facts(note, CAPTURED_AT)

    assert suggestions is not None
    edges = {(item.person_name, item.relationship_type, item.related_person_name) for item in suggestions if item.kind == "relationship"}
    assert len(edges) == 10
    assert ("Christian Decker", "Elternteil von", "Julian Decker") in edges
    assert ("Tanja Decker", "Elternteil von", "Mia Decker") in edges
    assert ("Julian Decker", "Geschwister von", "Lukas Decker") in edges
    meeting = next(item for item in suggestions if item.kind == "conversation")
    assert meeting.occurred_at == datetime(2026, 11, 16, 12, tzinfo=timezone.utc)


def test_two_named_parents_and_sons_create_parent_and_sibling_edges(monkeypatch) -> None:
    monkeypatch.setattr(settings, "llm_base_url", "http://local-model/v1")
    monkeypatch.setattr(settings, "llm_model", "qwen/qwen3.5-9b")
    payload = {"choices": [{"message": {"content": json.dumps({"suggestions": []})}}]}
    monkeypatch.setattr("lifepilot.capture_ai.urlopen", lambda request, timeout: BytesIO(json.dumps(payload).encode()))

    suggestions = extract_facts("Tanja und Christian haben zwei Söhne. Julian und Lukas Decker.", CAPTURED_AT)

    assert suggestions is not None
    edges = {(item.person_name, item.relationship_type, item.related_person_name) for item in suggestions if item.kind == "relationship"}
    assert edges == {
        ("Tanja Decker", "Elternteil von", "Julian Decker"),
        ("Tanja Decker", "Elternteil von", "Lukas Decker"),
        ("Christian Decker", "Elternteil von", "Julian Decker"),
        ("Christian Decker", "Elternteil von", "Lukas Decker"),
        ("Julian Decker", "Geschwister von", "Lukas Decker"),
    }


def test_extractor_turns_family_meeting_and_indefinite_loan_into_reviewable_suggestions(monkeypatch) -> None:
    monkeypatch.setattr(settings, "llm_base_url", "http://local-model/v1")
    monkeypatch.setattr(settings, "llm_model", "qwen/qwen3.5-9b")
    model_output = {
        "suggestions": [
            {"kind": "event", "title": "Treffen mit Christan Decker", "content": "Heute traf der Nutzer Christan Decker und seine Familie.", "person_name": None, "occurred_at": "2026-11-17T08:00:00Z", "date_precision": "exact"},
            {"kind": "relationship", "title": "Familie", "content": "Tanja ist die Frau von Christan Decker.", "person_name": "Christan Decker", "related_person_name": "Christan Decker", "relationship_type": "Ehepartnerin", "inverse_relationship_type": "Ehemann", "confirmation_required": False},
            {"kind": "fact", "title": "Besuch bei Christian Decker", "content": "Heute war ich bei Christan Decker.", "person_name": "Christan Decker"},
            {"kind": "fact", "title": "Familienstruktur", "content": "Christian Decker ist der Vater von Julian Decker.", "person_name": "Christian Decker"},
            {"kind": "fact", "title": "Familienstruktur", "content": "Christian Decker ist mit Tanja Decker verheiratet.", "person_name": "Christian Decker"},
            {"kind": "fact", "title": "Leihgabe", "content": "Christian Decker hat mir einen Supersternenzerstörer geliehen.", "person_name": "Christian Decker"},
        ]
    }
    payload = {"choices": [{"message": {"content": json.dumps(model_output, ensure_ascii=False)}}]}
    monkeypatch.setattr("lifepilot.capture_ai.urlopen", lambda request, timeout: BytesIO(json.dumps(payload).encode()))

    suggestions = extract_facts(EXAMPLE, CAPTURED_AT)

    assert suggestions is not None
    conversations = [item for item in suggestions if item.kind == "conversation"]
    assert len(conversations) == 1, "Ein bereits stattgefundenes Treffen muss als Gespräch statt als Kalendertermin vorgeschlagen werden."
    assert conversations[0].person_name == "Christian Decker"
    assert conversations[0].occurred_at == datetime(2026, 11, 17, 12, tzinfo=timezone.utc)
    assert all(item.kind != "event" for item in suggestions)
    assert all(item.kind != "fact" for item in suggestions)

    relationships = [item for item in suggestions if item.kind == "relationship"]
    edges = {(item.person_name, item.relationship_type, item.related_person_name, item.inverse_relationship_type) for item in relationships}
    assert len(edges) == 10, "Die Familie muss als Ehe-, Eltern- und Geschwisterkanten vollständig vorgeschlagen werden."
    assert ("Christian Decker", "Ehepartner von", "Tanja Decker", "Ehepartner von") in edges
    assert ("Christian Decker", "Elternteil von", "Julian Decker", "Kind von") in edges
    assert ("Tanja Decker", "Elternteil von", "Mia Decker", "Kind von") in edges
    assert ("Julian Decker", "Geschwister von", "Lukas Decker", "Geschwister von") in edges
    assert all(item.confirmation_required for item in relationships)
    assert {name for edge in edges for name in (edge[0], edge[2])} == {"Christian Decker", "Tanja Decker", "Julian Decker", "Lukas Decker", "Mia Decker"}

    loans = [item for item in suggestions if item.kind == "loan"]
    assert len(loans) == 1, "Der ausdrücklich genannte Supersternenzerstörer muss als Leihgabe erfasst werden."
    assert loans[0].title == "Supersternenzerstörer"
    assert loans[0].person_name == "Christian Decker"
    assert loans[0].occurred_at == datetime(2026, 11, 17, 12, tzinfo=timezone.utc)
    assert loans[0].due_at is None, "Ohne Rückgabetermin bleibt die Leihgabe unbefristet offen."


def test_review_saves_family_graph_meeting_and_open_loan_with_original_source(client, auth, monkeypatch) -> None:
    monkeypatch.setattr(settings, "llm_base_url", "http://local-model/v1")
    monkeypatch.setattr(settings, "llm_model", "qwen/qwen3.5-9b")
    monkeypatch.setattr(settings, "redis_url", "redis://unused/0")
    monkeypatch.setattr("lifepilot.capture_routes.enqueue_capture_job", lambda capture_id, owner_id: None)
    people = {
        name: client.post("/api/people", headers=auth, json={"first_name": name.split()[0], "last_name": "FamilyCapture"}).json()
        for name in ("Christian Decker", "Tanja", "Julian", "Lukas", "Mia")
    }
    suggestions = [
        CaptureSuggestion(kind="conversation", title="Treffen mit Christian Decker · Lego auseinandergebaut", content="Heute getroffen, gequatscht und Lego auseinandergenommen.", person_name="Christian Decker", occurred_at=datetime(2026, 11, 17, 12, tzinfo=timezone.utc), date_precision="day"),
        CaptureSuggestion(kind="relationship", title="Ehepartner", content="Christian Decker ist mit Tanja verheiratet.", person_name="Christian Decker", related_person_name="Tanja", relationship_type="Ehepartner von", inverse_relationship_type="Ehepartner von", confirmation_required=True),
        CaptureSuggestion(kind="relationship", title="Elternteil", content="Christian Decker ist Elternteil von Julian.", person_name="Christian Decker", related_person_name="Julian", relationship_type="Elternteil von", inverse_relationship_type="Kind von", confirmation_required=True),
        CaptureSuggestion(kind="relationship", title="Elternteil", content="Christian Decker ist Elternteil von Lukas.", person_name="Christian Decker", related_person_name="Lukas", relationship_type="Elternteil von", inverse_relationship_type="Kind von", confirmation_required=True),
        CaptureSuggestion(kind="relationship", title="Elternteil", content="Christian Decker ist Elternteil von Mia.", person_name="Christian Decker", related_person_name="Mia", relationship_type="Elternteil von", inverse_relationship_type="Kind von", confirmation_required=True),
        CaptureSuggestion(kind="relationship", title="Elternteil", content="Tanja ist Elternteil von Julian.", person_name="Tanja", related_person_name="Julian", relationship_type="Elternteil von", inverse_relationship_type="Kind von", confirmation_required=True),
        CaptureSuggestion(kind="relationship", title="Elternteil", content="Tanja ist Elternteil von Lukas.", person_name="Tanja", related_person_name="Lukas", relationship_type="Elternteil von", inverse_relationship_type="Kind von", confirmation_required=True),
        CaptureSuggestion(kind="relationship", title="Elternteil", content="Tanja ist Elternteil von Mia.", person_name="Tanja", related_person_name="Mia", relationship_type="Elternteil von", inverse_relationship_type="Kind von", confirmation_required=True),
        CaptureSuggestion(kind="relationship", title="Geschwister", content="Julian und Lukas sind Geschwister.", person_name="Julian", related_person_name="Lukas", relationship_type="Geschwister von", inverse_relationship_type="Geschwister von", confirmation_required=True),
        CaptureSuggestion(kind="relationship", title="Geschwister", content="Julian und Mia sind Geschwister.", person_name="Julian", related_person_name="Mia", relationship_type="Geschwister von", inverse_relationship_type="Geschwister von", confirmation_required=True),
        CaptureSuggestion(kind="relationship", title="Geschwister", content="Lukas und Mia sind Geschwister.", person_name="Lukas", related_person_name="Mia", relationship_type="Geschwister von", inverse_relationship_type="Geschwister von", confirmation_required=True),
        CaptureSuggestion(kind="loan", title="Supersternenzerstörer", content="Christian hat mir den Supersternenzerstörer geliehen, damit ich ihn bauen kann.", person_name="Christian Decker", occurred_at=datetime(2026, 11, 17, 12, tzinfo=timezone.utc), date_precision="day"),
    ]
    monkeypatch.setattr("lifepilot.capture_jobs.extract_facts", lambda text, captured_at=None: suggestions)
    capture = client.post("/api/captures", headers=auth, json={"original_text": EXAMPLE}).json()
    owner_id = client.get("/api/auth/me", headers=auth).json()["id"]
    process_capture_job(capture["id"], owner_id)
    stored = next(item for item in client.get("/api/captures", headers=auth).json() if item["id"] == capture["id"])
    assignments = {index: people[item.person_name]["id"] for index, item in enumerate(suggestions) if item.person_name}
    related_assignments = {index: people[item.related_person_name]["id"] for index, item in enumerate(suggestions) if item.related_person_name}
    accepted = client.post(
        f"/api/captures/{capture['id']}/review",
        headers=auth,
        json={"accepted_indices": list(range(len(suggestions))), "person_assignments": assignments, "related_person_assignments": related_assignments, "confirmations": list(range(1, 11))},
    )

    assert accepted.status_code == 201, accepted.text
    assert len([item for item in accepted.json() if item["resource_type"] == "relationship"]) == 10
    assert len([item for item in accepted.json() if item["resource_type"] == "conversation"]) == 1
    assert len([item for item in accepted.json() if item["resource_type"] == "loan"]) == 1
    assert stored["original_text"] == EXAMPLE
    with Session(engine) as db:
        conversation = db.get(Conversation, next(item["resource_id"] for item in accepted.json() if item["resource_type"] == "conversation"))
        loan = db.scalar(select(Loan).where(Loan.owner_id == owner_id, Loan.item_name == "Supersternenzerstörer"))
        assert conversation is not None and conversation.original_note == EXAMPLE
        assert conversation.occurred_at.replace(tzinfo=timezone.utc) == datetime(2026, 11, 17, 12, tzinfo=timezone.utc)
        assert loan is not None and loan.lender_person_id == people["Christian Decker"]["id"]
        assert loan.borrower_person_id is None and loan.due_at is None and loan.returned_at is None
        source = db.get(Memory, loan.source_memory_id)
        assert source is not None and source.source_capture_id == capture["id"]
        relations = db.scalars(select(Relationship).where(Relationship.owner_id == owner_id)).all()
        assert sum(1 for row in relations if row.confirmed and row.source_memory_id) >= 10
        assert db.scalar(select(Event.id).where(Event.owner_id == owner_id, Event.title.like("Treffen mit Christian Decker%"))) is None


def test_capture_hides_a_saved_spouse_edge_but_keeps_new_children(client, auth, monkeypatch) -> None:
    monkeypatch.setattr(settings, "llm_base_url", "http://local-model/v1")
    monkeypatch.setattr(settings, "llm_model", "qwen/qwen3.5-9b")
    monkeypatch.setattr(settings, "redis_url", "redis://unused/0")
    monkeypatch.setattr("lifepilot.capture_routes.enqueue_capture_job", lambda capture_id, owner_id: None)
    christian = client.post("/api/people", headers=auth, json={"first_name": "Christian", "last_name": "DuplicateFamily"}).json()
    tanja = client.post("/api/people", headers=auth, json={"first_name": "Tanja", "last_name": "DuplicateFamily"}).json()
    relationship = client.post("/api/relationships", headers=auth, json={"source_person_id": christian["id"], "target_person_id": tanja["id"], "relationship_type": "Ehepartner von", "inverse_relationship_type": "Ehepartner von"})
    assert relationship.status_code == 201
    monkeypatch.setattr("lifepilot.capture_jobs.extract_facts", lambda text, captured_at=None: [
        CaptureSuggestion(kind="relationship", title="Ehepartner", content="Christian und Tanja sind verheiratet.", person_name="Christian DuplicateFamily", related_person_name="Tanja DuplicateFamily", relationship_type="Ehepartner von", inverse_relationship_type="Ehepartner von"),
        CaptureSuggestion(kind="relationship", title="Elternteil", content="Christian ist Vater von Julian.", person_name="Christian DuplicateFamily", related_person_name="Julian", relationship_type="Elternteil von", inverse_relationship_type="Kind von"),
    ])
    capture = client.post("/api/captures", headers=auth, json={"original_text": "Bei Christian DuplicateFamily war ich. Seine Frau Tanja DuplicateFamily und seine Kinder Julian und Lukas habe ich getroffen."}).json()
    owner_id = client.get("/api/auth/me", headers=auth).json()["id"]

    process_capture_job(capture["id"], owner_id)

    saved = next(item for item in client.get("/api/captures", headers=auth).json() if item["id"] == capture["id"])
    assert saved["status"] == "ready", saved["processing_error"]
    edges = {(item["person_name"], item["relationship_type"], item["related_person_name"]) for item in saved["suggestions"]}
    assert edges
    assert not any(item[0] == "Christian DuplicateFamily" and item[2] == "Tanja DuplicateFamily" for item in edges)
    assert any(item[2] == "Julian" for item in edges)
    assert "1 bereits gespeicherte" in saved["processing_error"]
