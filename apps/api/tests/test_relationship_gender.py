import json
from io import BytesIO

from lifepilot.capture_ai import extract_facts
from lifepilot.capture_jobs import process_capture_job
from lifepilot.capture_schemas import CaptureSuggestion
from lifepilot.config import settings


PERSON_FIELDS = (
    "first_name", "last_name", "nickname", "birthday", "gender", "email", "phone",
    "address", "website", "job_title", "organization", "notes",
)


def create_person(client, auth, first_name: str, gender: str = "unspecified") -> dict:
    response = client.post(
        "/api/people",
        headers=auth,
        json={"first_name": first_name, "gender": gender},
    )
    assert response.status_code == 201
    return response.json()


def test_neutral_parent_selection_uses_profile_gender_for_both_directions(client, auth) -> None:
    mother = create_person(client, auth, "Mara", "female")
    son = create_person(client, auth, "Jonas", "male")

    response = client.post(
        "/api/relationships",
        headers=auth,
        json={
            "source_person_id": mother["id"],
            "target_person_id": son["id"],
            "relationship_type": "parent",
        },
    )

    assert response.status_code == 201
    assert (response.json()["relationship_type"], response.json()["inverse_relationship_type"]) == (
        "Mutter von",
        "Sohn von",
    )


def test_explicit_wife_and_husband_word_sets_only_unknown_genders(client, auth) -> None:
    christina = create_person(client, auth, "Christina")
    sven = create_person(client, auth, "Sven")

    response = client.post(
        "/api/relationships",
        headers=auth,
        json={
            "source_person_id": christina["id"],
            "target_person_id": sven["id"],
            "relationship_type": "Frau von",
            "inverse_relationship_type": "Mann von",
        },
    )

    assert response.status_code == 201
    assert (response.json()["relationship_type"], response.json()["inverse_relationship_type"]) == (
        "Ehefrau von",
        "Ehemann von",
    )
    assert client.get(f"/api/people/{christina['id']}", headers=auth).json()["gender"] == "female"
    assert client.get(f"/api/people/{sven['id']}", headers=auth).json()["gender"] == "male"


def test_colleague_gender_does_not_guess_the_other_person(client, auth) -> None:
    colleague = create_person(client, auth, "Kristin")
    other_person = create_person(client, auth, "Kollege")

    response = client.post(
        "/api/relationships",
        headers=auth,
        json={
            "source_person_id": colleague["id"],
            "target_person_id": other_person["id"],
            "relationship_type": "Arbeitskollegin",
            "inverse_relationship_type": "Arbeitskollegin von",
        },
    )

    assert response.status_code == 201
    assert client.get(f"/api/people/{colleague['id']}", headers=auth).json()["gender"] == "female"
    assert client.get(f"/api/people/{other_person['id']}", headers=auth).json()["gender"] == "unspecified"


def test_profile_gender_change_relabels_saved_relationship(client, auth) -> None:
    parent = create_person(client, auth, "Elternteil")
    child = create_person(client, auth, "Kind", "male")
    relation = client.post(
        "/api/relationships",
        headers=auth,
        json={
            "source_person_id": parent["id"],
            "target_person_id": child["id"],
            "relationship_type": "parent",
        },
    ).json()
    payload = {field: parent[field] for field in PERSON_FIELDS}
    payload["gender"] = "female"

    updated = client.patch(f"/api/people/{parent['id']}", headers=auth, json=payload)

    assert updated.status_code == 200
    refreshed = client.get(f"/api/relationships?person_id={parent['id']}", headers=auth).json()
    assert refreshed[0]["id"] == relation["id"]
    assert (refreshed[0]["relationship_type"], refreshed[0]["inverse_relationship_type"]) == (
        "Mutter von",
        "Sohn von",
    )


def test_name_based_gender_suggestion_requires_confirmation_before_saving(client, auth, monkeypatch) -> None:
    monkeypatch.setattr(settings, "llm_base_url", "http://local-model/v1")
    monkeypatch.setattr(settings, "llm_model", "small-local-model")
    monkeypatch.setattr(settings, "redis_url", "redis://unused/0")
    monkeypatch.setattr("lifepilot.capture_routes.enqueue_capture_job", lambda capture_id, owner_id: None)
    person = create_person(client, auth, "Kim")
    suggestion = CaptureSuggestion(
        kind="fact",
        title="Erzählte vom Ausflug",
        content="Kim erzählte vom Ausflug.",
        person_name="Kim",
        person_gender="female",
        person_gender_basis="name_inference",
        confirmation_required=True,
    )
    monkeypatch.setattr("lifepilot.capture_jobs.extract_facts", lambda text, captured_at=None: [suggestion])
    capture = client.post(
        "/api/captures",
        headers=auth,
        json={"original_text": "Kim erzählte vom Ausflug."},
    ).json()
    owner_id = client.get("/api/auth/me", headers=auth).json()["id"]
    assert process_capture_job(capture["id"], owner_id) == "ready"
    assignment = {"person_assignments": {"0": person["id"]}}

    rejected = client.post(
        f"/api/captures/{capture['id']}/review",
        headers=auth,
        json={"accepted_indices": [0], **assignment},
    )
    assert rejected.status_code == 422
    assert client.get(f"/api/people/{person['id']}", headers=auth).json()["gender"] == "unspecified"

    accepted = client.post(
        f"/api/captures/{capture['id']}/review",
        headers=auth,
        json={"accepted_indices": [0], "confirmations": [0], **assignment},
    )
    assert accepted.status_code == 201
    assert client.get(f"/api/people/{person['id']}", headers=auth).json()["gender"] == "female"


def test_name_guess_from_local_model_is_marked_for_confirmation(monkeypatch) -> None:
    monkeypatch.setattr(settings, "llm_base_url", "http://local-model/v1")
    monkeypatch.setattr(settings, "llm_model", "small-local-model")
    payload = {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "suggestions": [
                                {
                                    "kind": "conversation",
                                    "title": "Gespräch mit Kim",
                                    "content": "Kim erzählte vom Ausflug.",
                                    "person_name": "Kim",
                                    "person_gender": "female",
                                    "person_gender_basis": "name_inference",
                                }
                            ]
                        }
                    )
                }
            }
        ]
    }
    monkeypatch.setattr(
        "lifepilot.capture_ai.urlopen",
        lambda request, timeout: BytesIO(json.dumps(payload).encode()),
    )

    suggestions = extract_facts("Kim erzählte vom Ausflug.")

    assert suggestions is not None
    assert suggestions[0].person_gender == "female"
    assert suggestions[0].person_gender_basis == "name_inference"
    assert suggestions[0].confirmation_required is True
