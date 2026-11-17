import json
from io import BytesIO
from urllib.request import Request

import pytest
from redis.exceptions import RedisError

from lifepilot.capture_ai import ProviderError, extract_facts
from lifepilot.capture_jobs import process_capture_job
from lifepilot.capture_schemas import CaptureSuggestion
from lifepilot.config import settings
from lifepilot.db import engine
from lifepilot.models import Capture, Memory, User
from lifepilot.security import create_token
from sqlalchemy import select
from sqlalchemy.orm import Session


def test_capture_persists_original_when_ai_is_not_configured(client, auth, monkeypatch) -> None:
    monkeypatch.setattr(settings, "llm_base_url", "")
    monkeypatch.setattr(settings, "llm_model", "")
    response = client.post("/api/captures", headers=auth, json={"original_text": "Martin hat gestern angerufen."})
    assert response.status_code == 201
    assert response.json()["status"] == "unavailable"
    assert response.json()["original_text"] == "Martin hat gestern angerufen."
    assert response.json()["suggestions"] == []
    assert client.get("/api/captures", headers=auth).json()[0]["id"] == response.json()["id"]


def test_capture_review_only_persists_explicitly_accepted_suggestions(client, auth, monkeypatch) -> None:
    monkeypatch.setattr(settings, "llm_base_url", "http://local-model/v1")
    monkeypatch.setattr(settings, "llm_model", "small-local-model")
    monkeypatch.setattr(settings, "redis_url", "redis://unused/0")
    queued: list[tuple[str, str]] = []
    monkeypatch.setattr("lifepilot.capture_routes.enqueue_capture_job", lambda capture_id, owner_id: queued.append((capture_id, owner_id)))
    monkeypatch.setattr(
        "lifepilot.capture_jobs.extract_facts",
        lambda text: [
            CaptureSuggestion(title="Wunsch", content="Martin wünscht sich einen Roman.", person_name="Martin"),
            CaptureSuggestion(title="Gespräch", content="Martin hat angerufen.", occurred_at=None),
        ],
    )
    capture = client.post("/api/captures", headers=auth, json={"original_text": "Martin wünscht sich einen Roman und hat angerufen."}).json()
    assert capture["status"] == "pending"
    assert queued and queued[0][0] == capture["id"]
    assert process_capture_job(capture["id"], queued[0][1]) == "ready"
    capture = client.get("/api/captures", headers=auth).json()[0]
    assert capture["status"] == "ready"
    assert len(capture["suggestions"]) == 2
    invalid = client.post(f"/api/captures/{capture['id']}/review", headers=auth, json={"accepted_indices": [4]})
    assert invalid.status_code == 422
    accepted = client.post(f"/api/captures/{capture['id']}/review", headers=auth, json={"accepted_indices": [0]})
    assert accepted.status_code == 201
    assert accepted.json()[0]["title"] == "Wunsch"
    assert client.get("/api/memories", headers=auth).json()[0]["source_capture_id"] == capture["id"]


def test_capture_failure_keeps_original_and_other_users_cannot_read_it(client, auth, monkeypatch) -> None:
    monkeypatch.setattr(settings, "llm_base_url", "http://local-model/v1")
    monkeypatch.setattr(settings, "llm_model", "small-local-model")
    monkeypatch.setattr(settings, "redis_url", "redis://unused/0")
    monkeypatch.setattr("lifepilot.capture_routes.enqueue_capture_job", lambda capture_id, owner_id: None)
    def fail_provider(text: str) -> list[CaptureSuggestion] | None:
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
    requests: list[tuple[str, int, str]] = []

    def respond(request: Request, timeout: int) -> BytesIO:
        requests.append((request.full_url, timeout, request.get_header("Authorization")))
        return BytesIO(json.dumps(payload).encode())

    monkeypatch.setattr("lifepilot.capture_ai.urlopen", respond)
    suggestions = extract_facts("Anna mag Romane.")
    assert suggestions == [CaptureSuggestion(title="Wunsch", content="Anna mag Romane.", person_name="Anna", occurred_at=None)]
    assert requests == [("http://local-model/v1/chat/completions", settings.llm_timeout_seconds, "Bearer local-key")]


def test_openai_compatible_extractor_rejects_malformed_model_output(monkeypatch) -> None:
    monkeypatch.setattr(settings, "llm_base_url", "http://local-model/v1")
    monkeypatch.setattr(settings, "llm_model", "small-local-model")
    monkeypatch.setattr("lifepilot.capture_ai.urlopen", lambda request, timeout: BytesIO(b'{"choices":[{"message":{"content":"{}"}}]}'))
    with pytest.raises(ProviderError):
        extract_facts("Unstrukturierter Text")
