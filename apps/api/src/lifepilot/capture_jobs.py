import json

from redis import Redis
from rq import Queue
from sqlalchemy import select
from sqlalchemy.orm import Session

from lifepilot.capture_ai import ProviderError, extract_facts
from lifepilot.capture_schemas import CaptureSuggestion
from lifepilot.config import settings
from lifepilot.db import engine
from lifepilot.models import Capture

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
            suggestions = extract_facts(capture.original_text)
        except ProviderError as error:
            capture.status = "failed"
            capture.processing_error = str(error)
        else:
            if suggestions is None:
                capture.status = "unavailable"
                capture.processing_error = "KI ist nicht konfiguriert. Der Originaltext wurde gespeichert."
            else:
                _save_suggestions(capture, suggestions)
        db.commit()
        return capture.status


def _save_suggestions(capture: Capture, suggestions: list[CaptureSuggestion]) -> None:
    capture.status = "ready"
    capture.processing_error = ""
    capture.suggestions_json = json.dumps(
        [item.model_dump(mode="json") for item in suggestions], ensure_ascii=False
    )
