import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from lifepilot.db import engine
from lifepilot.embeddings import EmbeddingProviderError, EMBEDDING_DIMENSIONS
from lifepilot.embedding_jobs import process_memory_embedding
from lifepilot.models import Conversation, EntityEmbedding, Memory, MemoryEmbedding, Person, Project, Relationship, Task, User
from lifepilot.security import create_token, resolve_bearer_user


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


def test_hybrid_search_returns_semantic_hits_for_conversations_tasks_relationships_and_projects(client, auth, monkeypatch):
    import lifepilot.config
    import lifepilot.entity_embedding_jobs
    import lifepilot.main
    import lifepilot.planner
    import lifepilot.services

    monkeypatch.setattr(lifepilot.config.settings, "embedding_model", "test-embedding")
    monkeypatch.setattr(lifepilot.services, "embedding_provider_configured", lambda: True)
    monkeypatch.setattr(lifepilot.main, "enqueue_entity_embedding", lambda entity_type, entity_id, owner_id: False)
    monkeypatch.setattr(lifepilot.planner, "enqueue_entity_embedding", lambda entity_type, entity_id, owner_id: False)
    monkeypatch.setattr(lifepilot.services, "enqueue_entity_embedding", lambda entity_type, entity_id, owner_id: False)

    def embed(text: str) -> list[float]:
        vector = [0.0] * EMBEDDING_DIMENSIONS
        vector[0 if "Lea" in text or "Wohnungswechsel" in text else 1] = 1.0
        return vector

    monkeypatch.setattr(lifepilot.entity_embedding_jobs, "embed_text", embed)
    monkeypatch.setattr(lifepilot.services, "embed_text", embed)
    with Session(engine) as db:
        owner_id = resolve_bearer_user(auth["Authorization"].removeprefix("Bearer "), db).id

    lea = client.post("/api/people", headers=auth, json={"first_name": "Lea", "last_name": "Muster"}).json()
    martin = client.post("/api/people", headers=auth, json={"first_name": "Martin", "last_name": "Beispiel"}).json()
    conversation = client.post("/api/conversations", headers=auth, json={"title": "Treffen", "original_note": "Wir sprachen über Urlaub.", "participant_ids": [lea["id"]]}).json()
    task = client.post("/api/tasks", headers=auth, json={"title": "Rückmeldung", "description": "Nach dem Treffen nachfragen.", "person_id": lea["id"]}).json()
    relationship = client.post("/api/relationships", headers=auth, json={"source_person_id": lea["id"], "target_person_id": martin["id"], "relationship_type": "kennt", "confirmed": True}).json()
    project = client.post("/api/projects", headers=auth, json={"name": "Ausflug", "description": "Lea plant mit."}).json()

    for entity_type, entity_id in (("conversation", conversation["id"]), ("task", task["id"]), ("relationship", relationship["id"]), ("project", project["id"])):
        assert lifepilot.entity_embedding_jobs.process_entity_embedding(entity_type, entity_id, owner_id) == "indexed"

    with Session(engine) as db:
        private_owner = User(username="semantic-private-project", password_hash="unused")
        db.add(private_owner)
        db.flush()
        private_project = Project(owner_id=private_owner.id, name="Lea private", description="Wohnungswechsel")
        db.add(private_project)
        db.flush()
        db.add(EntityEmbedding(owner_id=private_owner.id, entity_type="project", entity_id=private_project.id, project_id=private_project.id, model="test-embedding", content_hash="private", embedding=embed("Lea")))
        db.commit()

    response = client.get("/api/search?q=Wohnungswechsel", headers=auth)

    assert response.status_code == 200
    result = response.json()
    assert [row["id"] for row in result["conversations"]] == [conversation["id"]]
    assert [row["id"] for row in result["tasks"]] == [task["id"]]
    assert [row["id"] for row in result["relationships"]] == [relationship["id"]]
    assert result["relationships"][0]["source_person_name"] == "Lea Muster"
    assert [row["id"] for row in result["projects"]] == [project["id"]]


def test_deleting_relationship_cascades_its_semantic_embedding(client, auth, monkeypatch):
    import lifepilot.config
    import lifepilot.entity_embedding_jobs
    import lifepilot.main

    monkeypatch.setattr(lifepilot.config.settings, "embedding_model", "test-embedding")
    monkeypatch.setattr(lifepilot.main, "enqueue_entity_embedding", lambda entity_type, entity_id, owner_id: False)
    monkeypatch.setattr(lifepilot.entity_embedding_jobs, "embed_text", lambda _: [1.0] + [0.0] * (EMBEDDING_DIMENSIONS - 1))
    with Session(engine) as db:
        owner_id = resolve_bearer_user(auth["Authorization"].removeprefix("Bearer "), db).id
    first = client.post("/api/people", headers=auth, json={"first_name": "Anna"}).json()
    second = client.post("/api/people", headers=auth, json={"first_name": "Ben"}).json()
    relationship = client.post("/api/relationships", headers=auth, json={"source_person_id": first["id"], "target_person_id": second["id"], "relationship_type": "kennt", "confirmed": True}).json()
    assert lifepilot.entity_embedding_jobs.process_entity_embedding("relationship", relationship["id"], owner_id) == "indexed"

    response = client.delete(f"/api/relationships/{relationship['id']}", headers=auth)

    assert response.status_code == 204
    with Session(engine) as db:
        assert db.scalar(select(EntityEmbedding).where(EntityEmbedding.relationship_id == relationship["id"])) is None


def test_reindex_queues_each_owned_searchable_resource(client, auth, monkeypatch):
    import lifepilot.config
    import lifepilot.search_routes

    monkeypatch.setattr(lifepilot.config.settings, "embedding_model", "test-embedding")
    monkeypatch.setattr(lifepilot.config.settings, "redis_url", "redis://localhost/15")
    monkeypatch.setattr(lifepilot.search_routes, "embedding_provider_configured", lambda: True)
    queued: list[tuple[str, str, str]] = []

    def enqueue_memory(memory_id: str, owner_id: str) -> bool:
        queued.append(("memory", memory_id, owner_id))
        return True

    def enqueue_entity(entity_type: str, entity_id: str, owner_id: str) -> bool:
        queued.append((entity_type, entity_id, owner_id))
        return True

    monkeypatch.setattr(lifepilot.search_routes, "enqueue_memory_embedding", enqueue_memory)
    monkeypatch.setattr(lifepilot.search_routes, "enqueue_entity_embedding", enqueue_entity)
    with Session(engine) as db:
        private_owner = User(username="semantic-reindex-owner", password_hash="unused")
        db.add(private_owner)
        db.flush()
        owner_id = private_owner.id
        source = Person(owner_id=owner_id, first_name="Lea")
        target = Person(owner_id=owner_id, first_name="Martin")
        db.add_all([source, target])
        db.flush()
        db.add_all([
            Memory(owner_id=owner_id, title="Gedanke", content="Originalnotiz"),
            Conversation(owner_id=owner_id, title="Gespräch", original_note="Notiz"),
            Task(owner_id=owner_id, title="Aufgabe"),
            Relationship(owner_id=owner_id, source_person_id=source.id, target_person_id=target.id, relationship_type="kennt"),
            Project(owner_id=owner_id, name="Vorhaben"),
        ])
        db.commit()

    response = client.post("/api/search/reindex", headers={"Authorization": f"Bearer {create_token(owner_id)}"})

    assert response.status_code == 202
    assert response.json()["queued"] == 5
    assert {item[0] for item in queued} == {"memory", "conversation", "task", "relationship", "project"}
