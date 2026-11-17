import pytest
from sqlalchemy.orm import Session

from lifepilot.db import engine
from lifepilot.embeddings import EmbeddingProviderError, EMBEDDING_DIMENSIONS
from lifepilot.embedding_jobs import process_memory_embedding
from lifepilot.models import Memory, MemoryEmbedding, User
from lifepilot.security import resolve_bearer_user


def test_semantic_search_indexes_memories_and_falls_back_to_text(client, auth, monkeypatch):
    import lifepilot.config
    import lifepilot.embedding_jobs
    import lifepilot.services
    import lifepilot.main

    monkeypatch.setattr(lifepilot.config.settings, "embedding_model", "test-embedding")
    monkeypatch.setattr(lifepilot.services, "embedding_provider_configured", lambda: True)
    monkeypatch.setattr(lifepilot.main, "enqueue_memory_embedding", lambda memory_id, owner_id: False)

    def embed(text: str) -> list[float]:
        vector = [0.0] * EMBEDDING_DIMENSIONS
        vector[0 if "Hausarzt" in text or "medizinischer Schutz" in text else 1] = 1.0
        return vector

    monkeypatch.setattr(lifepilot.embedding_jobs, "embed_text", embed)
    monkeypatch.setattr(lifepilot.services, "embed_text", embed)
    with Session(engine) as db:
        owner_id = resolve_bearer_user(auth["Authorization"].removeprefix("Bearer "), db).id
    wanted = client.post("/api/memories", headers=auth, json={"title": "Arztbesuch am Dienstag", "content": "Der Hausarzt impfte mich am Nachmittag."}).json()
    other = client.post("/api/memories", headers=auth, json={"title": "Autohaus Vertrag", "content": "Kaufvertrag beim Autohaus unterschrieben."}).json()
    assert process_memory_embedding(wanted["id"], owner_id) == "indexed"
    assert process_memory_embedding(other["id"], owner_id) == "indexed"
    assert process_memory_embedding(wanted["id"], owner_id) == "unchanged"

    with Session(engine) as db:
        private_owner = User(username="semantic-private-user", password_hash="unused")
        db.add(private_owner)
        db.flush()
        private_memory = Memory(owner_id=private_owner.id, title="Impfung", content="Hausarzt Impfung")
        db.add(private_memory)
        db.flush()
        db.add(MemoryEmbedding(memory_id=private_memory.id, owner_id=private_owner.id, model="test-embedding", content_hash="private", embedding=embed("Hausarzt")))
        db.commit()

    semantic = client.get("/api/search?q=medizinischer+Schutz", headers=auth)
    assert semantic.status_code == 200
    assert [row["id"] for row in semantic.json()["memories"]] == [wanted["id"]]
    assert semantic.json()["search_info"]["semantic_matches"] == 1

    def unavailable(_: str) -> list[float]:
        raise EmbeddingProviderError("offline")

    monkeypatch.setattr(lifepilot.services, "embed_text", unavailable)
    lexical = client.get("/api/search?q=Autohaus", headers=auth)
    assert lexical.status_code == 200
    assert [row["id"] for row in lexical.json()["memories"]] == [other["id"]]
    assert lexical.json()["search_info"]["semantic_available"] is False


def test_reindex_requires_an_embedding_provider(client, auth, monkeypatch):
    import lifepilot.search_routes

    monkeypatch.setattr(lifepilot.search_routes, "embedding_provider_configured", lambda: False)
    response = client.post("/api/search/reindex", headers=auth)
    assert response.status_code == 409
