import json

from redis import Redis
from rq import Queue
from sqlalchemy import select
from sqlalchemy.orm import Session

from lifepilot.capture_ai import ProviderError, extract_facts
from lifepilot.capture_schemas import CaptureSuggestion
from lifepilot.config import settings
from lifepilot.db import engine
from lifepilot.models import Capture, Person, PersonNameHistory, Project

CAPTURE_QUEUE_NAME = "lifepilot"


def enqueue_capture_job(capture_id: str, owner_id: str) -> None:
    redis_client = Redis.from_url(settings.redis_url)
    try:
        queue = Queue(CAPTURE_QUEUE_NAME, connection=redis_client)
        queue.enqueue(
            "lifepilot.capture_jobs.process_capture_job",
            capture_id,
            owner_id,
            job_timeout=settings.llm_timeout_seconds + 15,
            result_ttl=3600,
            failure_ttl=86400,
            description="Schnellerfassung analysieren",
        )
    finally:
        redis_client.close()


def process_capture_job(capture_id: str, owner_id: str) -> str:
    with Session(engine) as db:
        capture = db.scalar(select(Capture).where(Capture.id == capture_id, Capture.owner_id == owner_id))
        if capture is None:
            return "missing"
        try:
            suggestions = extract_facts(capture.original_text, capture.created_at)
        except ProviderError as error:
            capture.status = "failed"
            capture.processing_error = str(error)
        else:
            if suggestions is None:
                capture.status = "unavailable"
                capture.processing_error = "KI ist nicht konfiguriert. Der Originaltext wurde gespeichert."
            else:
                _save_suggestions(capture, suggestions, db)
        db.commit()
        return capture.status


def _save_suggestions(capture: Capture, suggestions: list[CaptureSuggestion], db: Session) -> None:
    people = db.scalars(select(Person).where(Person.owner_id == capture.owner_id)).all()
    projects = db.scalars(select(Project).where(Project.owner_id == capture.owner_id)).all()
    aliases = db.scalars(select(PersonNameHistory).where(PersonNameHistory.owner_id == capture.owner_id, PersonNameHistory.confirmed.is_(True))).all()
    aliases_by_person: dict[str, set[str]] = {}
    for alias in aliases:
        aliases_by_person.setdefault(alias.person_id, set()).add(alias.name.casefold())
    resolved: list[CaptureSuggestion] = []
    for suggestion in suggestions:
        person_matches = []
        if suggestion.person_name:
            needle = suggestion.person_name.strip().casefold()
            person_matches = [person for person in people if needle in {person.first_name.casefold(), f"{person.first_name} {person.last_name}".strip().casefold(), (person.nickname or "").casefold()} | aliases_by_person.get(person.id, set())]
        project_needle = (suggestion.project_name or "").strip().casefold()
        project_matches = [
            project
            for project in projects
            if project_needle
            and (
                project_needle == project.name.strip().casefold()
                or project_needle in project.name.strip().casefold()
                or project_needle in project.description.strip().casefold()
            )
        ]
        related_matches = [person for person in people if suggestion.related_person_name and suggestion.related_person_name.strip().casefold() in {person.first_name.casefold(), f"{person.first_name} {person.last_name}".strip().casefold(), (person.nickname or "").casefold()} | aliases_by_person.get(person.id, set())]
        resolved.append(suggestion.model_copy(update={
            "person_id": person_matches[0].id if len(person_matches) == 1 else None,
            "person_candidates": [person.id for person in person_matches[:5]],
            "project_id": project_matches[0].id if len(project_matches) == 1 else None,
            "project_candidates": [project.id for project in project_matches[:5]],
            "related_person_id": related_matches[0].id if len(related_matches) == 1 else None,
            "related_person_candidates": [person.id for person in related_matches[:5]],
            "confirmation_required": suggestion.confirmation_required or len(person_matches) > 1 or len(project_matches) > 1 or len(related_matches) > 1,
        }))
    capture.status = "ready"
    capture.processing_error = ""
    capture.suggestions_json = json.dumps(
        [item.model_dump(mode="json") for item in resolved], ensure_ascii=False
    )
