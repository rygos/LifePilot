import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError

from lifepilot.config import settings

logger = logging.getLogger(__name__)
COMMIT_PATTERN = re.compile(r"[0-9a-fA-F]{40}")


class UpdateState(BaseModel):
    model_config = ConfigDict(frozen=True)

    current_commit: str | None = None
    pending_commit: str | None = None
    pending_since: datetime | None = None


def state_path() -> Path:
    return Path(settings.data_dir) / "app-update-state.json"


def read_update_state() -> UpdateState:
    path = state_path()
    try:
        return UpdateState.model_validate_json(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return UpdateState()
    except (OSError, ValidationError, ValueError) as exc:
        logger.warning("Updatezustand konnte nicht gelesen werden (%s)", type(exc).__name__)
        return UpdateState()


def write_update_state(state: UpdateState) -> None:
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(".tmp")
    temporary_path.write_text(state.model_dump_json(), encoding="utf-8")
    temporary_path.replace(path)


def image_commit_sha() -> str:
    try:
        value = Path("/app/version-commit").read_text(encoding="ascii").strip()
    except OSError:
        return ""
    return value if COMMIT_PATTERN.fullmatch(value) else ""


def current_commit_sha() -> str:
    state = read_update_state()
    if state.current_commit:
        return state.current_commit
    configured_sha = settings.life_pilot_commit_sha.strip()
    if COMMIT_PATTERN.fullmatch(configured_sha):
        return configured_sha
    return image_commit_sha()


def mark_update_pending(target_commit: str) -> None:
    if not COMMIT_PATTERN.fullmatch(target_commit):
        raise ValueError("Ungültige Commit-ID für das Update")
    write_update_state(UpdateState(
        current_commit=current_commit_sha() or None,
        pending_commit=target_commit,
        pending_since=datetime.now(timezone.utc),
    ))


def clear_pending_update() -> None:
    state = read_update_state()
    write_update_state(state.model_copy(update={"pending_commit": None, "pending_since": None}))


def complete_pending_update() -> None:
    state = read_update_state()
    pending = state.pending_commit
    image_sha = image_commit_sha()
    if pending and image_sha == pending:
        write_update_state(UpdateState(current_commit=pending))
        return
    if state.current_commit is None and image_sha:
        write_update_state(UpdateState(current_commit=image_sha))
        return
    if pending:
        write_update_state(state.model_copy(update={"pending_commit": None, "pending_since": None}))
