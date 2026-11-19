import json
from datetime import datetime, timezone
from io import BytesIO
from urllib.request import Request

import pytest
from redis.exceptions import RedisError

from lifepilot.capture_ai import ProviderError, extract_facts
from lifepilot.capture_rules import apply_family_meeting_and_loan_rules
from lifepilot.capture_jobs import process_capture_job
from lifepilot.capture_schemas import CaptureSuggestion
from lifepilot.config import settings
from lifepilot.db import engine
from lifepilot.models import Capture, Conversation, ConversationParticipant, ConversationProject, Memory, MemoryProject, Person, PersonNameHistory, Project, Relationship, Reminder, Task, User, UserPersonRelationship
from lifepilot.security import create_token
from sqlalchemy import select
from sqlalchemy.orm import Session


@pytest.mark.parametrize(
    ("text", "person_name", "item_name", "direction"),
    [
        ("Ich habe Martin meine Bohrmaschine geliehen.", "Martin", "Bohrmaschine", "lent"),
        ("Ich war bei Christian Decker, er hat mir einen Supersternenzerstörer geliehen.", "Christian Decker", "Supersternenzerstörer", "borrowed"),
    ],
    ids=("user-lent-item", "user-borrowed-item"),
)
def test_capture_rules_keep_both_loan_directions(text, person_name, item_name, direction) -> None:
    suggestions = apply_family_meeting_and_loan_rules(text, datetime(2026, 11, 18, 12, tzinfo=timezone.utc), [])

    loan = next(item for item in suggestions if item.kind == "loan")
    assert loan.person_name == person_name
    assert loan.title == item_name
    assert loan.loan_direction == direction
    assert loan.due_at is None


def test_capture_persists_original_when_ai_is_not_configured(client, auth, monkeypatch) -> None:
    monkeypatch.setattr(settings, "llm_base_url", "")
    monkeypatch.setattr(settings, "llm_model", "")
    response = client.post("/api/captures", headers=auth, json={"original_text": "Martin hat gestern angerufen."})
    assert response.status_code == 201
    assert response.json()["status"] == "unavailable"
    assert response.json()["original_text"] == "Martin hat gestern angerufen."
    assert response.json()["suggestions"] == []
    assert client.get("/api/captures", headers=auth).json()[0]["id"] == response.json()["id"]


def test_follow_up_capture_is_linked_and_receives_the_previous_context(client, auth, monkeypatch) -> None:
    monkeypatch.setattr(settings, "llm_base_url", "http://local-model/v1")
    monkeypatch.setattr(settings, "llm_model", "small-local-model")
    monkeypatch.setattr(settings, "redis_url", "redis://unused/0")
    monkeypatch.setattr("lifepilot.capture_routes.enqueue_capture_job", lambda capture_id, owner_id: None)
    contexts: list[str] = []

    def extract(text: str, captured_at=None, prior_context: str = "") -> list[CaptureSuggestion]:
        contexts.append(prior_context)
        return []

    monkeypatch.setattr("lifepilot.capture_jobs.extract_facts", extract)
    parent = client.post("/api/captures", headers=auth, json={"original_text": "Ich traf Christian mit seiner Familie."}).json()
    owner_id = client.get("/api/auth/me", headers=auth).json()["id"]
    assert process_capture_job(parent["id"], owner_id) == "ready"

    child_response = client.post("/api/captures", headers=auth, json={"original_text": "Die Kinder Julian und Lukas fehlten.", "parent_capture_id": parent["id"]})

    assert child_response.status_code == 201
    child = child_response.json()
    assert child["parent_capture_id"] == parent["id"]
    assert process_capture_job(child["id"], owner_id) == "ready"
    assert "Ich traf Christian mit seiner Familie." in contexts[-1]
    assert "Die Kinder Julian und Lukas fehlten." == child["original_text"]


def test_follow_up_hides_unchanged_parent_suggestions_but_keeps_new_facts(client, auth, monkeypatch) -> None:
    monkeypatch.setattr(settings, "llm_base_url", "http://local-model/v1")
    monkeypatch.setattr(settings, "llm_model", "small-local-model")
    monkeypatch.setattr(settings, "redis_url", "redis://unused/0")
    monkeypatch.setattr("lifepilot.capture_routes.enqueue_capture_job", lambda capture_id, owner_id: None)
    spouse = CaptureSuggestion(kind="relationship", title="Ehepartner", content="Christian ist Tanjas Ehepartner.", person_name="Christian", related_person_name="Tanja", relationship_type="Ehepartner von", inverse_relationship_type="Ehepartner von")
    conversation = CaptureSuggestion(kind="conversation", title="Treffen mit Christian", content="Gestern habe ich Christian getroffen.", person_name="Christian", occurred_at=datetime(2026, 11, 17, 12, tzinfo=timezone.utc), date_precision="day")
    child_relation = CaptureSuggestion(kind="relationship", title="Elternteil", content="Christian ist Julians Vater.", person_name="Christian", related_person_name="Julian", relationship_type="Elternteil von", inverse_relationship_type="Kind von")
    responses = [[spouse, conversation], [spouse, conversation, child_relation]]

    def extract(text: str, captured_at=None, prior_context: str = "") -> list[CaptureSuggestion]:
        return responses.pop(0)

    monkeypatch.setattr("lifepilot.capture_jobs.extract_facts", extract)
    parent = client.post("/api/captures", headers=auth, json={"original_text": "Gestern traf ich Christian und Tanja."}).json()
    owner_id = client.get("/api/auth/me", headers=auth).json()["id"]
    process_capture_job(parent["id"], owner_id)
    child = client.post("/api/captures", headers=auth, json={"original_text": "Julian ist Christians Sohn.", "parent_capture_id": parent["id"]}).json()

    process_capture_job(child["id"], owner_id)

    child = next(item for item in client.get("/api/captures", headers=auth).json() if item["id"] == child["id"])
    assert [(item["kind"], item["relationship_type"]) for item in child["suggestions"]] == [("relationship", "Elternteil von")]
    assert "2 bereits gespeicherte oder doppelte Vorschläge ausgeblendet." == child["processing_error"]


def test_follow_up_capture_cannot_reference_another_users_capture(client, auth, monkeypatch) -> None:
    monkeypatch.setattr(settings, "llm_base_url", "http://local-model/v1")
    monkeypatch.setattr(settings, "llm_model", "small-local-model")
    monkeypatch.setattr(settings, "redis_url", "redis://unused/0")
    monkeypatch.setattr("lifepilot.capture_routes.enqueue_capture_job", lambda capture_id, owner_id: None)
    parent = client.post("/api/captures", headers=auth, json={"original_text": "Privater Verlauf"}).json()
    with Session(engine) as db:
        user = User(username="capture-thread-owner-check", password_hash="unused")
        db.add(user)
        db.commit()
        other_headers = {"Authorization": f"Bearer {create_token(user.id)}"}

    response = client.post("/api/captures", headers=other_headers, json={"original_text": "Fremder Nachtrag", "parent_capture_id": parent["id"]})

    assert response.status_code == 404


def test_capture_review_only_persists_explicitly_accepted_suggestions(client, auth, monkeypatch) -> None:
    monkeypatch.setattr(settings, "llm_base_url", "http://local-model/v1")
    monkeypatch.setattr(settings, "llm_model", "small-local-model")
    monkeypatch.setattr(settings, "redis_url", "redis://unused/0")
    queued: list[tuple[str, str]] = []
    martin = client.post("/api/people", headers=auth, json={"first_name": "Martin", "last_name": "CaptureTest"}).json()
    monkeypatch.setattr("lifepilot.capture_routes.enqueue_capture_job", lambda capture_id, owner_id: queued.append((capture_id, owner_id)))
    monkeypatch.setattr(
        "lifepilot.capture_jobs.extract_facts",
        lambda text, captured_at=None: [
            CaptureSuggestion(title="Wunsch", content="Martin wünscht sich einen Roman.", person_name="Martin CaptureTest"),
            CaptureSuggestion(kind="conversation", title="Gespräch", content="Martin hat angerufen.", person_name="Martin CaptureTest", occurred_at=None),
        ],
    )
    capture = client.post("/api/captures", headers=auth, json={"original_text": "Martin wünscht sich einen Roman und hat angerufen."}).json()
    assert capture["status"] == "pending"
    assert queued and queued[0][0] == capture["id"]
    assert process_capture_job(capture["id"], queued[0][1]) == "ready"
    capture = next(item for item in client.get("/api/captures", headers=auth).json() if item["id"] == capture["id"])
    assert capture["status"] == "ready"
    assert len(capture["suggestions"]) == 2
    invalid = client.post(f"/api/captures/{capture['id']}/review", headers=auth, json={"accepted_indices": [4]})
    assert invalid.status_code == 422
    accepted = client.post(f"/api/captures/{capture['id']}/review", headers=auth, json={"accepted_indices": [0], "person_assignments": {"0": martin["id"]}})
    assert accepted.status_code == 201
    assert accepted.json()[0]["title"] == "Wunsch"
    assert client.get("/api/memories", headers=auth).json()[0]["source_capture_id"] == capture["id"]


def test_chat_capture_partial_review_applies_checked_items_and_carries_only_open_items_forward(client, auth, monkeypatch) -> None:
    monkeypatch.setattr(settings, "llm_base_url", "http://local-model/v1")
    monkeypatch.setattr(settings, "llm_model", "small-local-model")
    monkeypatch.setattr(settings, "redis_url", "redis://unused/0")
    monkeypatch.setattr("lifepilot.capture_routes.enqueue_capture_job", lambda capture_id, owner_id: None)
    suggestion_done = CaptureSuggestion(title="Erledigter Fakt", content="Martin mag Kaffee.")
    suggestion_open = CaptureSuggestion(title="Offener Fakt", content="Martin plant einen Umzug.")
    contexts: list[str] = []

    def extract(text: str, captured_at=None, prior_context: str = "") -> list[CaptureSuggestion]:
        contexts.append(prior_context)
        return [suggestion_done, suggestion_open] if not prior_context else []

    monkeypatch.setattr("lifepilot.capture_jobs.extract_facts", extract)
    created = client.post("/api/captures", headers=auth, json={"original_text": "Martin erzählte mir etwas.", "source": "chat"}).json()
    assert created["source"] == "chat"
    owner_id = client.get("/api/auth/me", headers=auth).json()["id"]
    assert process_capture_job(created["id"], owner_id) == "ready"

    accepted = client.post(f"/api/captures/{created['id']}/review", headers=auth, json={"accepted_indices": [0]})

    assert accepted.status_code == 201
    remaining = next(item for item in client.get("/api/captures", headers=auth).json() if item["id"] == created["id"])
    assert remaining["status"] == "ready"
    assert [item["title"] for item in remaining["suggestions"]] == ["Offener Fakt"]
    assert any(item["content"] == "Martin mag Kaffee." for item in client.get("/api/memories", headers=auth).json())

    follow_up = client.post("/api/captures", headers=auth, json={"original_text": "Das mit dem Umzug möchte ich noch prüfen.", "parent_capture_id": created["id"], "source": "chat"}).json()
    assert process_capture_job(follow_up["id"], owner_id) == "ready"
    assert "Erledigter Fakt" not in contexts[-1]
    assert "Offener Fakt" in contexts[-1]


def test_capture_failure_keeps_original_and_other_users_cannot_read_it(client, auth, monkeypatch) -> None:
    monkeypatch.setattr(settings, "llm_base_url", "http://local-model/v1")
    monkeypatch.setattr(settings, "llm_model", "small-local-model")
    monkeypatch.setattr(settings, "redis_url", "redis://unused/0")
    monkeypatch.setattr("lifepilot.capture_routes.enqueue_capture_job", lambda capture_id, owner_id: None)
    def fail_provider(text: str, captured_at=None) -> list[CaptureSuggestion] | None:
        raise ProviderError("Der Anbieter ist nicht erreichbar")

    monkeypatch.setattr("lifepilot.capture_jobs.extract_facts", fail_provider)
    created = client.post("/api/captures", headers=auth, json={"original_text": "Nicht verlieren."})
    assert created.status_code == 201
    capture_id = created.json()["id"]
    owner_id = client.get("/api/auth/me", headers=auth).json()["id"]
    assert created.json()["status"] == "pending"
    assert process_capture_job(capture_id, owner_id) == "failed"
    capture_view = client.get("/api/captures", headers=auth).json()[0]
    assert capture_view["status"] == "failed"
    assert capture_view["original_text"] == "Nicht verlieren."
    with Session(engine) as db:
        user = User(username="capture-owner-check", password_hash="unused")
        db.add(user)
        db.commit()
        other_user_id = user.id
        capture = db.get(Capture, capture_id)
        assert capture is not None
        assert capture.owner_id != user.id
        assert db.scalar(select(Memory.id).where(Memory.source_capture_id == capture.id)) is None
    other_headers = {"Authorization": f"Bearer {create_token(other_user_id)}"}
    assert client.get("/api/captures", headers=other_headers).json() == []


def test_capture_queue_failure_still_saves_original(client, auth, monkeypatch) -> None:
    monkeypatch.setattr(settings, "llm_base_url", "http://local-model/v1")
    monkeypatch.setattr(settings, "llm_model", "small-local-model")
    monkeypatch.setattr(settings, "redis_url", "redis://unused/0")

    def reject_job(capture_id: str, owner_id: str) -> None:
        raise RedisError("queue unavailable")

    monkeypatch.setattr("lifepilot.capture_routes.enqueue_capture_job", reject_job)
    response = client.post("/api/captures", headers=auth, json={"original_text": "Eingabe trotz Queue-Fehler sichern."})
    assert response.status_code == 201
    assert response.json()["status"] == "failed"
    assert response.json()["original_text"] == "Eingabe trotz Queue-Fehler sichern."
    assert "Originaltext bleibt gespeichert" in response.json()["processing_error"]


def test_openai_compatible_extractor_parses_validated_json(monkeypatch) -> None:
    monkeypatch.setattr(settings, "llm_base_url", "http://local-model/v1")
    monkeypatch.setattr(settings, "llm_api_key", "local-key")
    monkeypatch.setattr(settings, "llm_model", "small-local-model")
    payload = {"choices": [{"message": {"content": json.dumps({"suggestions": [{"title": "Wunsch", "content": "Anna mag Romane.", "person_name": "Anna", "occurred_at": None}]})}}]}
    requests: list[tuple[str, int, str, dict]] = []

    def respond(request: Request, timeout: int) -> BytesIO:
        requests.append((request.full_url, timeout, request.get_header("Authorization"), json.loads(request.data)))
        return BytesIO(json.dumps(payload).encode())

    monkeypatch.setattr("lifepilot.capture_ai.urlopen", respond)
    suggestions = extract_facts("Anna mag Romane.")
    assert suggestions == [CaptureSuggestion(title="Wunsch", content="Anna mag Romane.", person_name="Anna", occurred_at=None)]
    assert len(requests) == 1
    endpoint, timeout, authorization, body = requests[0]
    assert (endpoint, timeout, authorization) == ("http://local-model/v1/chat/completions", settings.llm_timeout_seconds, "Bearer local-key")
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["name"] == "capture_suggestions"
    assert body["max_tokens"] == 5000
    assert body["temperature"] == 0.7


def test_openai_compatible_extractor_rejects_malformed_model_output(monkeypatch) -> None:
    monkeypatch.setattr(settings, "llm_base_url", "http://local-model/v1")
    monkeypatch.setattr(settings, "llm_model", "small-local-model")
    monkeypatch.setattr("lifepilot.capture_ai.urlopen", lambda request, timeout: BytesIO(b'{"choices":[{"message":{"content":"{}"}}]}'))
    with pytest.raises(ProviderError):
        extract_facts("Unstrukturierter Text")


def test_review_links_verified_conversation_to_person_and_project_without_inventing_task(client, auth, monkeypatch) -> None:
    monkeypatch.setattr(settings, "llm_base_url", "http://local-model/v1")
    monkeypatch.setattr(settings, "llm_model", "small-local-model")
    monkeypatch.setattr(settings, "redis_url", "redis://unused/0")
    monkeypatch.setattr("lifepilot.capture_routes.enqueue_capture_job", lambda capture_id, owner_id: None)
    person = client.post("/api/people", headers=auth, json={"first_name": "Kristin", "last_name": "Abeler"}).json()
    project = client.post("/api/projects", headers=auth, json={"name": "6012 - OAS Umzüge"}).json()
    monkeypatch.setattr("lifepilot.capture_jobs.extract_facts", lambda text, captured_at=None: [
        CaptureSuggestion(kind="conversation", title="Gespräch über Projekt 6012", content="Kristin sprach mit mir über das Projekt.", person_name="Kristin Abeler", project_name="6012 - OAS Umzüge", date_precision="day", occurred_at=datetime(2026, 11, 16, 12, tzinfo=timezone.utc)),
    ])
    capture = client.post("/api/captures", headers=auth, json={"original_text": "Kristin Abeler hat heute mit mir über das Projekt 6012 - OAS Umzüge gesprochen."}).json()
    owner_id = client.get("/api/auth/me", headers=auth).json()["id"]
    assert process_capture_job(capture["id"], owner_id) == "ready"
    suggestion = next(item for item in client.get("/api/captures", headers=auth).json() if item["id"] == capture["id"])["suggestions"][0]
    assert suggestion["person_id"] == person["id"]
    assert suggestion["project_id"] == project["id"]
    accepted = client.post(f"/api/captures/{capture['id']}/review", headers=auth, json={"accepted_indices": [0], "person_assignments": {"0": person["id"]}}).json()
    assert accepted[0]["resource_type"] == "conversation"
    with Session(engine) as db:
        conversation = db.get(Conversation, accepted[0]["resource_id"])
        assert conversation is not None and conversation.original_note == capture["original_text"]
        assert db.scalar(select(ConversationParticipant.person_id).where(ConversationParticipant.conversation_id == conversation.id)) == person["id"]
        assert db.scalar(select(ConversationProject.project_id).where(ConversationProject.conversation_id == conversation.id)) == project["id"]
        assert db.scalar(select(Task.id).where(Task.owner_id == owner_id, Task.title == "Gespräch über Projekt 6012")) is None


def test_capture_saves_explicit_relationship_to_owner_and_surfaces_it_in_context(client, auth) -> None:
    person = client.post("/api/people", headers=auth, json={"first_name": "Maya", "last_name": "Kollegin"}).json()
    owner_id = client.get("/api/auth/me", headers=auth).json()["id"]
    suggestion = CaptureSuggestion(kind="owner_relationship", title="Maya ist meine Arbeitskollegin", content="Maya arbeitet mit mir.", person_name="Maya Kollegin", relationship_type="Arbeitskollegin", confirmation_required=True)
    capture = client.post("/api/captures", headers=auth, json={"original_text": "Meine Arbeitskollegin Maya Kollegin hat mit mir gesprochen."}).json()
    with Session(engine) as db:
        stored_capture = db.get(Capture, capture["id"])
        assert stored_capture is not None
        stored_capture.status = "ready"
        stored_capture.suggestions_json = json.dumps([suggestion.model_dump(mode="json")], ensure_ascii=False)
        db.commit()

    accepted = client.post(f"/api/captures/{capture['id']}/review", headers=auth, json={"accepted_indices": [0], "person_assignments": {"0": person["id"]}, "confirmations": [0]})
    assert accepted.status_code == 201 and accepted.json()[0]["resource_type"] == "relationship"
    context = client.get(f"/api/briefing/person/{person['id']}", headers=auth).json()
    self_id = client.get("/api/profile", headers=auth).json()["self_person_id"]
    links = client.get(f"/api/relationships?person_id={person['id']}", headers=auth).json()
    assert any(link["source_person_id"] == person["id"] and link["target_person_id"] == self_id and link["relationship_type"] == "Arbeitskollegin von" for link in links)
    assert context["owner_relationships"] == []
    assert person["id"] in {item["id"] for item in client.get("/api/search?q=Arbeitskollegin", headers=auth).json()["people"]}
    with Session(engine) as db:
        edge = db.scalar(select(Relationship).where(Relationship.owner_id == owner_id, Relationship.source_person_id == person["id"], Relationship.target_person_id == self_id))
        assert edge is not None and edge.source_memory_id
        memory = db.get(Memory, edge.source_memory_id)
        assert memory is not None and memory.source_capture_id == capture["id"]


def test_family_statements_link_named_parent_and_user_profile_to_each_child(client, auth) -> None:
    from datetime import datetime, timezone
    from lifepilot.capture_rules import apply_family_meeting_and_loan_rules

    ramona = client.post("/api/people", headers=auth, json={"first_name": "Ramona", "last_name": "ElternTest"}).json()
    hanna = client.post("/api/people", headers=auth, json={"first_name": "Hanna", "last_name": "Hering"}).json()
    vincent = client.post("/api/people", headers=auth, json={"first_name": "Vincent", "last_name": "Hering"}).json()
    self_id = client.get("/api/profile", headers=auth).json()["self_person_id"]
    original = "Füge Hanna Hering und Vincent Hering hinzu. Hanna ist die Tochter von Ramona und mir. Vincent ist der Sohn von Ramona und mir."
    suggestions = apply_family_meeting_and_loan_rules(original, datetime(2026, 11, 18, 12, tzinfo=timezone.utc), [])
    capture = client.post("/api/captures", headers=auth, json={"original_text": original}).json()
    with Session(engine) as db:
        stored = db.get(Capture, capture["id"])
        assert stored is not None
        stored.status = "ready"
        stored.suggestions_json = json.dumps([item.model_dump(mode="json") for item in suggestions], ensure_ascii=False)
        db.commit()

    relation_indices = [index for index, item in enumerate(suggestions) if item.kind == "relationship"]
    owner_indices = [index for index, item in enumerate(suggestions) if item.kind == "owner_relationship"]
    person_assignments = {
        index: ramona["id"] if suggestions[index].kind == "relationship" else hanna["id"] if suggestions[index].person_name.startswith("Hanna") else vincent["id"]
        for index in relation_indices + owner_indices
    }
    related_assignments = {index: hanna["id"] if suggestions[index].related_person_name.startswith("Hanna") else vincent["id"] for index in relation_indices}
    accepted = client.post(f"/api/captures/{capture['id']}/review", headers=auth, json={"accepted_indices": relation_indices + owner_indices, "person_assignments": person_assignments, "related_person_assignments": related_assignments, "confirmations": relation_indices + owner_indices})

    assert accepted.status_code == 201, accepted.text
    self_gender = client.get(f"/api/people/{self_id}", headers=auth).json()["gender"]
    owner_parent_label = {
        "female": "Mutter von",
        "male": "Vater von",
    }.get(self_gender, "Elternteil von")
    for child in (hanna, vincent):
        links = client.get(f"/api/relationships?person_id={child['id']}", headers=auth).json()
        assert any(link["source_person_id"] == ramona["id"] and link["target_person_id"] == child["id"] and link["relationship_type"] == "Elternteil von" for link in links)
        assert any(link["source_person_id"] == child["id"] and link["target_person_id"] == self_id and link["inverse_relationship_type"] == owner_parent_label for link in links)


def test_review_stores_former_name_with_original_source_after_explicit_confirmation(client, auth, monkeypatch) -> None:
    monkeypatch.setattr(settings, "llm_base_url", "http://local-model/v1")
    monkeypatch.setattr(settings, "llm_model", "small-local-model")
    monkeypatch.setattr(settings, "redis_url", "redis://unused/0")
    monkeypatch.setattr("lifepilot.capture_routes.enqueue_capture_job", lambda capture_id, owner_id: None)
    person = client.post("/api/people", headers=auth, json={"first_name": "Kristin", "last_name": "Abeler"}).json()
    monkeypatch.setattr("lifepilot.capture_jobs.extract_facts", lambda text, captured_at=None: [
        CaptureSuggestion(kind="former_name", title="Früherer Name", content="Kristin Dölz", person_name="Kristin Abeler", occurred_at=datetime(2026, 2, 1, tzinfo=timezone.utc), date_precision="approximate", confirmation_required=True),
    ])
    capture = client.post("/api/captures", headers=auth, json={"original_text": "Kristin hieß vor der Hochzeit Anfang des Jahres noch Dölz."}).json()
    owner_id = client.get("/api/auth/me", headers=auth).json()["id"]
    process_capture_job(capture["id"], owner_id)
    assert next(item for item in client.get("/api/captures", headers=auth).json() if item["id"] == capture["id"])["suggestions"][0]["person_candidates"]
    response = client.post(f"/api/captures/{capture['id']}/review", headers=auth, json={"accepted_indices": [0]})
    assert response.status_code == 422
    accepted_response = client.post(f"/api/captures/{capture['id']}/review", headers=auth, json={"accepted_indices": [0], "confirmations": [0], "person_assignments": {"0": person["id"]}})
    assert accepted_response.status_code == 201, accepted_response.text
    accepted = accepted_response.json()
    assert accepted[0]["resource_type"] == "person_name"
    assert client.get(f"/api/people?q=Dölz", headers=auth).json()[0]["id"] == person["id"]
    assert client.get(f"/api/people/{person['id']}/names", headers=auth).json()[0]["name"] == "Kristin Dölz"
    assert client.get(f"/api/people/{person['id']}/names", headers=auth).json()[0]["source_capture_id"] == capture["id"]


def test_review_stores_approximate_marriage_as_biography_not_calendar_event(client, auth, monkeypatch) -> None:
    monkeypatch.setattr(settings, "llm_base_url", "http://local-model/v1")
    monkeypatch.setattr(settings, "llm_model", "small-local-model")
    monkeypatch.setattr(settings, "redis_url", "redis://unused/0")
    monkeypatch.setattr("lifepilot.capture_routes.enqueue_capture_job", lambda capture_id, owner_id: None)
    person = client.post("/api/people", headers=auth, json={"first_name": "Kristin", "last_name": "Abeler"}).json()
    monkeypatch.setattr("lifepilot.capture_jobs.extract_facts", lambda text, captured_at=None: [CaptureSuggestion(kind="life_event", title="Hochzeit", content="Kristin hat geheiratet.", person_name="Kristin Abeler", date_precision="approximate", confirmation_required=True)])
    capture = client.post("/api/captures", headers=auth, json={"original_text": "Kristin hat Anfang des Jahres geheiratet."}).json()
    owner_id = client.get("/api/auth/me", headers=auth).json()["id"]
    process_capture_job(capture["id"], owner_id)
    event_ids_before = {item["id"] for item in client.get("/api/events", headers=auth).json()}
    blocked = client.post(f"/api/captures/{capture['id']}/review", headers=auth, json={"accepted_indices": [0]})
    assert blocked.status_code == 422
    accepted = client.post(f"/api/captures/{capture['id']}/review", headers=auth, json={"accepted_indices": [0], "confirmations": [0], "person_assignments": {"0": person["id"]}}).json()
    assert accepted[0]["resource_type"] == "life_event"
    life_event = client.get(f"/api/briefing/person/{person['id']}", headers=auth).json()["life_events"][0]
    assert life_event["title"] == "Hochzeit"
    assert life_event["occurred_at"] is None
    assert life_event["date_precision"] == "approximate"
    assert life_event["source_capture_id"] == capture["id"]
    assert {item["id"] for item in client.get("/api/events", headers=auth).json()} == event_ids_before


def test_capture_review_keeps_source_when_project_is_explicitly_assigned(client, auth, monkeypatch) -> None:
    monkeypatch.setattr(settings, "llm_base_url", "http://local-model/v1")
    monkeypatch.setattr(settings, "llm_model", "small-local-model")
    monkeypatch.setattr(settings, "redis_url", "redis://unused/0")
    monkeypatch.setattr("lifepilot.capture_routes.enqueue_capture_job", lambda capture_id, owner_id: None)
    person = client.post("/api/people", headers=auth, json={"first_name": "Kristin", "last_name": "Abeler"}).json()
    project = client.post("/api/projects", headers=auth, json={"name": "8823 - OAS Umzüge"}).json()
    monkeypatch.setattr("lifepilot.capture_jobs.extract_facts", lambda text, captured_at=None: [CaptureSuggestion(kind="fact", title="Projektverknüpfung", content="Kristin hat mir das Projekt ausdrücklich übergeben.", person_name="Kristin Abeler", project_name="6012 - OAS Umzüge", confirmation_required=True)])
    capture = client.post("/api/captures", headers=auth, json={"original_text": "Kristin hat mir das Projekt 6012 ausdrücklich übergeben."}).json()
    owner_id = client.get("/api/auth/me", headers=auth).json()["id"]
    process_capture_job(capture["id"], owner_id)
    assert next(item for item in client.get("/api/captures", headers=auth).json() if item["id"] == capture["id"])["suggestions"][0]["person_candidates"]
    accepted = client.post(f"/api/captures/{capture['id']}/review", headers=auth, json={"accepted_indices": [0], "confirmations": [0], "person_assignments": {"0": person["id"]}, "project_assignments": {"0": project["id"]}})
    assert accepted.status_code == 201, accepted.text
    with Session(engine) as db:
        memory = db.get(Memory, accepted.json()[0]["id"])
        assert memory is not None and memory.source_capture_id == capture["id"] and memory.person_id == person["id"]
        assert db.scalar(select(MemoryProject.project_id).where(MemoryProject.memory_id == memory.id)) == project["id"]


def test_review_resolves_project_code_and_creates_explicitly_dated_follow_up(client, auth, monkeypatch) -> None:
    monkeypatch.setattr(settings, "llm_base_url", "http://local-model/v1")
    monkeypatch.setattr(settings, "llm_model", "small-local-model")
    monkeypatch.setattr(settings, "redis_url", "redis://unused/0")
    monkeypatch.setattr("lifepilot.capture_routes.enqueue_capture_job", lambda capture_id, owner_id: None)
    person = client.post("/api/people", headers=auth, json={"first_name": "Rita", "last_name": "Projektfall"}).json()
    project = client.post("/api/projects", headers=auth, json={"name": "7659 - OAS Umzüge"}).json()
    due_at = datetime(2026, 11, 24, 12, tzinfo=timezone.utc)
    monkeypatch.setattr("lifepilot.capture_jobs.extract_facts", lambda text, captured_at=None: [
        CaptureSuggestion(kind="task", title="Rückmeldung zu 7659 erfragen", content="Rita soll Rückmeldung geben.", person_name="Rita Projektfall", project_name="7659", due_at=due_at, date_precision="day"),
    ])
    capture = client.post("/api/captures", headers=auth, json={"original_text": "Rita meldet sich zum Projekt 7659 am 24. November."}).json()
    owner_id = client.get("/api/auth/me", headers=auth).json()["id"]
    process_capture_job(capture["id"], owner_id)
    suggestion = next(item for item in client.get("/api/captures", headers=auth).json() if item["id"] == capture["id"])["suggestions"][0]
    assert suggestion["project_id"] == project["id"]
    accepted = client.post(f"/api/captures/{capture['id']}/review", headers=auth, json={"accepted_indices": [0]}).json()
    with Session(engine) as db:
        task = db.get(Task, accepted[0]["resource_id"])
        assert task is not None and task.person_id == person["id"] and task.project_id == project["id"]
        assert task.due_at.replace(tzinfo=timezone.utc) == due_at
        assert db.scalar(select(Reminder.id).where(Reminder.task_id == task.id, Reminder.owner_id == owner_id)) is not None


def test_review_links_relationship_both_directions_and_source(client, auth, monkeypatch) -> None:
    monkeypatch.setattr(settings, "llm_base_url", "http://local-model/v1")
    monkeypatch.setattr(settings, "llm_model", "small-local-model")
    monkeypatch.setattr(settings, "redis_url", "redis://unused/0")
    monkeypatch.setattr("lifepilot.capture_routes.enqueue_capture_job", lambda capture_id, owner_id: None)
    mother = client.post("/api/people", headers=auth, json={"first_name": "Mutter", "last_name": "CaptureRelation"}).json()
    daughter = client.post("/api/people", headers=auth, json={"first_name": "Tochter", "last_name": "CaptureRelation"}).json()
    monkeypatch.setattr("lifepilot.capture_jobs.extract_facts", lambda text, captured_at=None: [
        CaptureSuggestion(kind="relationship", title="Mutter und Tochter", content="Die Personen sind Mutter und Tochter.", person_name="Mutter CaptureRelation", person_candidates=[mother["id"]], related_person_name="Tochter CaptureRelation", related_person_candidates=[daughter["id"]], relationship_type="Mutter von", inverse_relationship_type="Tochter von", confirmation_required=True),
    ])
    capture = client.post("/api/captures", headers=auth, json={"original_text": "Die Mutter ist die Mutter der Tochter."}).json()
    owner_id = client.get("/api/auth/me", headers=auth).json()["id"]
    process_capture_job(capture["id"], owner_id)
    refused = client.post(f"/api/captures/{capture['id']}/review", headers=auth, json={"accepted_indices": [0], "person_assignments": {"0": mother["id"]}})
    assert refused.status_code == 422
    accepted = client.post(f"/api/captures/{capture['id']}/review", headers=auth, json={"accepted_indices": [0], "person_assignments": {"0": mother["id"]}, "related_person_assignments": {"0": daughter["id"]}, "confirmations": [0]})
    assert accepted.status_code == 201, accepted.text
    links = client.get(f"/api/relationships?person_id={daughter['id']}", headers=auth).json()
    assert any(link["source_person_id"] == mother["id"] and link["relationship_type"] == "Mutter von" and link["inverse_relationship_type"] == "Tochter von" for link in links)
    with Session(engine) as db:
        relation_id = accepted.json()[0]["resource_id"]
        relationship = db.get(Relationship, relation_id)
        assert relationship is not None and relationship.source_memory_id
        source = db.get(Memory, relationship.source_memory_id)
        assert source is not None and source.source_capture_id == capture["id"]


def test_review_can_create_explicitly_named_person_only_after_confirmation(client, auth, monkeypatch) -> None:
    monkeypatch.setattr(settings, "llm_base_url", "http://local-model/v1")
    monkeypatch.setattr(settings, "llm_model", "small-local-model")
    monkeypatch.setattr(settings, "redis_url", "redis://unused/0")
    monkeypatch.setattr("lifepilot.capture_routes.enqueue_capture_job", lambda capture_id, owner_id: None)
    monkeypatch.setattr("lifepilot.capture_jobs.extract_facts", lambda text, captured_at=None: [
        CaptureSuggestion(kind="conversation", title="Gespräch mit Lia Neumann", content="Lia berichtete vom neuen Verein.", person_name="Lia Neumann"),
    ])
    capture = client.post("/api/captures", headers=auth, json={"original_text": "Ich habe heute Lia Neumann kennengelernt."}).json()
    owner_id = client.get("/api/auth/me", headers=auth).json()["id"]
    process_capture_job(capture["id"], owner_id)
    rejected = client.post(f"/api/captures/{capture['id']}/review", headers=auth, json={"accepted_indices": [0], "create_people": [0]})
    assert rejected.status_code == 422
    assert not any(person["first_name"] == "Lia" and person["last_name"] == "Neumann" for person in client.get("/api/people", headers=auth).json())
    accepted = client.post(f"/api/captures/{capture['id']}/review", headers=auth, json={"accepted_indices": [0], "create_people": [0], "confirmations": [0]})
    assert accepted.status_code == 201, accepted.text
    conversation = next(item for item in client.get("/api/conversations", headers=auth).json() if item["id"] == accepted.json()[0]["resource_id"])
    created_people = [person for person in client.get("/api/people", headers=auth).json() if person["first_name"] == "Lia" and person["last_name"] == "Neumann"]
    assert len(created_people) == 1
    assert conversation["participant_ids"] == [created_people[0]["id"]]


def test_relative_day_uses_capture_timestamp_not_processing_timestamp(monkeypatch) -> None:
    from lifepilot.capture_ai import extract_facts

    monkeypatch.setattr(settings, "llm_base_url", "http://local-model/v1")
    monkeypatch.setattr(settings, "llm_model", "small-local-model")
    captured_at = datetime(2026, 11, 17, 8, tzinfo=timezone.utc)
    result = {"suggestions": [{"kind": "conversation", "title": "Treffen", "content": "Ich traf Kristin Gestern.", "person_name": "Kristin", "occurred_at": None, "date_precision": "unknown"}]}
    monkeypatch.setattr("lifepilot.capture_ai.urlopen", lambda request, timeout: BytesIO(json.dumps({"choices": [{"message": {"content": json.dumps(result)}}]}).encode()))
    suggestions = extract_facts("Ich traf Kristin Gestern.", captured_at)
    assert suggestions is not None
    assert suggestions[0].occurred_at == datetime(2026, 11, 16, 12, tzinfo=timezone.utc)
    assert suggestions[0].date_precision == "day"
    assert "2026-11-16" in suggestions[0].content


def test_extractor_requires_confirmation_for_former_names_and_unlinked_relations(monkeypatch) -> None:
    monkeypatch.setattr(settings, "llm_base_url", "http://local-model/v1")
    monkeypatch.setattr(settings, "llm_model", "small-local-model")
    result = {"suggestions": [
        {"kind": "former_name", "title": "Früherer Name", "content": "Vor der Hochzeit Anfang des Jahres hieß Kristin Dölz.", "person_name": "Kristin Abeler", "former_name": "Dölz", "date_precision": "year", "confirmation_required": False},
        {"kind": "owner_relationship", "title": "Kristin Kollegin", "content": "Kristin ist Arbeitskollegin des Nutzers.", "person_name": "Kristin Abeler", "former_name": "Dölz", "relationship_type": "Arbeitskollegin", "date_precision": "unknown", "confirmation_required": False},
        {"kind": "conversation", "title": "Gespräch", "content": "Heute mit Kristin gesprochen.", "person_name": "Kristin Abeler", "occurred_at": "2026-11-17T12:00:00Z", "date_precision": "exact", "confirmation_required": False},
        {"kind": "relationship", "title": "Kollegin", "content": "Kristin ist Arbeitskollegin des Nutzers.", "related_person_name": "Kristin Abeler", "relationship_type": "Arbeitskollegin", "date_precision": "unknown", "confirmation_required": False},
    ]}
    monkeypatch.setattr("lifepilot.capture_ai.urlopen", lambda request, timeout: BytesIO(json.dumps({"choices": [{"message": {"content": json.dumps(result, ensure_ascii=False)}}]}).encode()))
    suggestions = extract_facts("Meine Arbeitskollegin, Kristin Abeler, die vor der Hochzeit Anfang dieses Jahres noch Dölz hieß, hat heute mit mir über das Projekt 6012 - OAS Umzüge gesprochen.", datetime(2026, 11, 17, 12, tzinfo=timezone.utc))
    assert suggestions is not None
    former_name = next(item for item in suggestions if item.kind == "former_name")
    conversation = next(item for item in suggestions if item.kind == "conversation")
    owner_relationship = next(item for item in suggestions if item.kind == "owner_relationship")
    assert former_name.person_name == "Kristin Abeler"
    assert former_name.former_name == "Dölz"
    assert former_name.confirmation_required is True
    assert conversation.date_precision == "day"
    assert conversation.project_name == "6012 - OAS Umzüge"
    assert owner_relationship.person_name == "Kristin Abeler"
    assert all(item.kind != "relationship" for item in suggestions)


def test_extractor_turns_parent_facts_about_user_into_graph_relationship_suggestions(monkeypatch) -> None:
    from lifepilot.capture_ai import extract_facts

    monkeypatch.setattr(settings, "llm_base_url", "http://local-model/v1")
    monkeypatch.setattr(settings, "llm_model", "small-local-model")
    result = {"suggestions": [
        {"kind": "fact", "title": "Beziehung: Hanna Hering als Tochter", "content": "Hanna Hering wird als Tochter des Nutzers und von Ramona identifiziert.", "person_name": "Hanna Hering"},
        {"kind": "fact", "title": "Beziehung: Vincent Hering als Sohn", "content": "Vincent Hering wird als Sohn des Nutzers und von Ramona identifiziert.", "person_name": "Vincent Hering"},
    ]}
    monkeypatch.setattr("lifepilot.capture_ai.urlopen", lambda request, timeout: BytesIO(json.dumps({"choices": [{"message": {"content": json.dumps(result, ensure_ascii=False)}}]}).encode()))

    suggestions = extract_facts("Füge Hanna Hering und Vincent Hering hinzu. Hanna ist die Tochter von Ramona und mir. Vincent ist der Sohn von Ramona und mir.", datetime(2026, 11, 18, 12, tzinfo=timezone.utc))

    assert suggestions is not None
    assert [(item.kind, item.person_name, item.related_person_name, item.relationship_type) for item in suggestions] == [
        ("relationship", "Ramona", "Hanna Hering", "Elternteil von"),
        ("relationship", "Ramona", "Vincent Hering", "Elternteil von"),
        ("owner_relationship", "Hanna Hering", None, "Tochter von"),
        ("owner_relationship", "Vincent Hering", None, "Sohn von"),
    ]
