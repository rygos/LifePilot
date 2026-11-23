import logging
from datetime import datetime
from typing import Literal
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import ProxyHandler, Request, build_opener

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from lifepilot.config import settings
from lifepilot.db import get_db
from lifepilot.attachment_routes import attachment_files_for_owner, remove_attachment_files
from lifepilot.models import AuditEvent, User
from lifepilot.security import current_user
from lifepilot.update_state import COMMIT_PATTERN, clear_pending_update, current_commit_sha, read_update_state
from lifepilot.portainer_monitor import ContainerStatus, container_statuses, is_configured
from lifepilot.update_state import mark_update_pending_with_images

router = APIRouter(prefix="/api/admin", tags=["Administration"])
logger = logging.getLogger(__name__)
GITHUB_COMPARE_URL = "https://api.github.com/repos/rygos/LifePilot/compare/{base}...main"
GITHUB_BRANCH_URL = "https://api.github.com/repos/rygos/LifePilot/commits/main"


class GitHubCommitAuthor(BaseModel):
    date: str | None = None


class GitHubCommitDetails(BaseModel):
    message: str
    author: GitHubCommitAuthor | None = None


class GitHubCommit(BaseModel):
    sha: str
    commit: GitHubCommitDetails


class GitHubComparePayload(BaseModel):
    ahead_by: int
    commits: list[GitHubCommit]


class UpdateCommit(BaseModel):
    model_config = ConfigDict(frozen=True)

    sha: str
    message: str
    date: str | None


class GitUpdateComparison(BaseModel):
    model_config = ConfigDict(frozen=True)

    available: bool
    update_available: bool
    ahead_by: int
    latest_commit: str | None
    commits: list[UpdateCommit]


class AppUpdateStatus(GitUpdateComparison):
    model_config = ConfigDict(frozen=True)

    configured: bool
    source: str
    current_commit: str | None
    pending_update: bool
    pending_commit: str | None
    last_update_commit: str | None
    last_update_requested_at: datetime | None
    monitor_configured: bool
    monitor_available: bool
    monitor_error: str | None
    containers: list[ContainerStatus]


def call_portainer_webhook(webhook_url: str, commit_sha: str) -> int:
    parsed_url = urlsplit(webhook_url)
    query = [(key, value) for key, value in parse_qsl(parsed_url.query, keep_blank_values=True) if key != "LIFE_PILOT_COMMIT_SHA"]
    query.append(("LIFE_PILOT_COMMIT_SHA", commit_sha))
    webhook_url = urlunsplit(parsed_url._replace(query=urlencode(query)))
    request = Request(webhook_url, data=b"", method="POST")
    try:
        with build_opener(ProxyHandler({})).open(request, timeout=15) as response:
            if response.geturl() != webhook_url:
                return 502
            return response.status
    except HTTPError as exc:
        return exc.code
    except (URLError, TimeoutError, OSError, ValueError):
        raise


def compare_github_commits(current_sha: str) -> GitUpdateComparison:
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "LifePilot"}
    opener = build_opener(ProxyHandler({}))
    try:
        latest_request = Request(GITHUB_BRANCH_URL, headers=headers)
        with opener.open(latest_request, timeout=8) as response:
            latest = GitHubCommit.model_validate_json(response.read())
        compare_request = Request(GITHUB_COMPARE_URL.format(base=current_sha), headers=headers)
        with opener.open(compare_request, timeout=8) as response:
            payload = GitHubComparePayload.model_validate_json(response.read())
    except (HTTPError, URLError, TimeoutError, OSError, ValidationError) as exc:
        logger.info("GitHub-Versionsvergleich nicht verfügbar (%s)", type(exc).__name__)
        return GitUpdateComparison(available=False, update_available=False, ahead_by=0, latest_commit=None, commits=[])

    commits = [
        UpdateCommit(
            sha=item.sha[:12],
            message=item.commit.message.partition("\n")[0][:240],
            date=item.commit.author.date if item.commit.author else None,
        )
        for item in payload.commits[-20:]
    ]
    return GitUpdateComparison(
        available=True,
        update_available=payload.ahead_by > 0,
        ahead_by=payload.ahead_by,
        latest_commit=latest.sha[:12],
        commits=commits,
    )


class AdminUserView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    username: str
    full_name: str
    role: Literal["user", "admin"]
    created_at: datetime
    deleted_at: datetime | None


class UserRoleUpdate(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    role: Literal["user", "admin"]


def require_admin(user: User = Depends(current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Administratorrechte erforderlich")
    return user


@router.get("/users", response_model=list[AdminUserView])
def list_users(db: Session = Depends(get_db), _: User = Depends(require_admin)) -> list[AdminUserView]:
    users = db.scalars(select(User).order_by(User.deleted_at.is_not(None), User.username)).all()
    return [AdminUserView.model_validate(user) for user in users]


@router.patch("/users/{user_id}/role", response_model=AdminUserView)
def update_user_role(
    user_id: str,
    data: UserRoleUpdate,
    db: Session = Depends(get_db),
    actor: User = Depends(require_admin),
) -> AdminUserView:
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Benutzer nicht gefunden")
    if target.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Gelöschte Benutzer können keine Rollen ändern")
    if target.role == data.role:
        return AdminUserView.model_validate(target)
    if target.role == "admin" and data.role == "user":
        admin_count = db.scalar(select(func.count()).select_from(User).where(User.role == "admin")) or 0
        if admin_count <= 1:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Mindestens ein Administrator muss bestehen bleiben")
    target.role = data.role
    db.add(AuditEvent(owner_id=actor.id, action="update", resource_type="user_role", resource_id=target.id, source="web"))
    db.commit()
    db.refresh(target)
    return AdminUserView.model_validate(target)


@router.delete("/users/{user_id}", response_model=AdminUserView)
def soft_delete_user(user_id: str, db: Session = Depends(get_db), actor: User = Depends(require_admin)) -> AdminUserView:
    target = db.get(User, user_id)
    if target is None or target.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Aktiver Benutzer nicht gefunden")
    if target.id == actor.id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Das eigene Administratorkonto kann hier nicht gelöscht werden")
    if target.role == "admin":
        active_admins = db.scalar(select(func.count()).select_from(User).where(User.role == "admin", User.deleted_at.is_(None))) or 0
        if active_admins <= 1:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Mindestens ein aktiver Administrator muss bestehen bleiben")
    target.deleted_at = datetime.now().astimezone()
    db.add(AuditEvent(owner_id=actor.id, action="soft_delete", resource_type="user", resource_id=target.id, source="admin"))
    db.commit()
    db.refresh(target)
    return AdminUserView.model_validate(target)


@router.post("/users/{user_id}/restore", response_model=AdminUserView)
def restore_user(user_id: str, db: Session = Depends(get_db), actor: User = Depends(require_admin)) -> AdminUserView:
    target = db.get(User, user_id)
    if target is None or target.deleted_at is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Gelöschter Benutzer nicht gefunden")
    target.deleted_at = None
    db.add(AuditEvent(owner_id=actor.id, action="restore", resource_type="user", resource_id=target.id, source="admin"))
    db.commit()
    db.refresh(target)
    return AdminUserView.model_validate(target)


@router.delete("/users/{user_id}/permanent", status_code=status.HTTP_204_NO_CONTENT)
def permanently_delete_user(user_id: str, db: Session = Depends(get_db), actor: User = Depends(require_admin)) -> None:
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Benutzer nicht gefunden")
    if target.id == actor.id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Das eigene Administratorkonto kann hier nicht gelöscht werden")
    if target.role == "admin" and target.deleted_at is None:
        active_admins = db.scalar(select(func.count()).select_from(User).where(User.role == "admin", User.deleted_at.is_(None))) or 0
        if active_admins <= 1:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Mindestens ein aktiver Administrator muss bestehen bleiben")
    target_id = target.id
    attachment_paths = attachment_files_for_owner(db, target_id)
    audit = AuditEvent(owner_id=actor.id, action="permanent_delete", resource_type="user", resource_id=target_id, source="admin")
    db.add(audit)
    db.flush()
    db.delete(target)
    db.commit()
    remove_attachment_files(attachment_paths)


@router.get("/app-update")
def app_update_status(progress_only: bool = Query(default=False), _: User = Depends(require_admin)) -> AppUpdateStatus:
    current_sha = current_commit_sha()
    comparison = (
        compare_github_commits(current_sha)
        if not progress_only and COMMIT_PATTERN.fullmatch(current_sha)
        else GitUpdateComparison(available=False, update_available=False, ahead_by=0, latest_commit=None, commits=[])
    )
    update_state = read_update_state()
    monitored = container_statuses(update_state.previous_images, update_state.last_update_commit)
    return AppUpdateStatus(
        configured=bool(settings.portainer_webhook_url.strip()),
        source="main",
        current_commit=current_sha[:12] or None,
        pending_update=bool(update_state.pending_commit),
        pending_commit=update_state.pending_commit[:12] if update_state.pending_commit else None,
        last_update_commit=update_state.last_update_commit[:12] if update_state.last_update_commit else None,
        last_update_requested_at=update_state.last_update_requested_at,
        monitor_configured=monitored.configured,
        monitor_available=monitored.available,
        monitor_error=monitored.error,
        containers=monitored.containers,
        **comparison.model_dump(),
    )


@router.post("/app-update", status_code=status.HTTP_202_ACCEPTED)
def request_app_update(db: Session = Depends(get_db), actor: User = Depends(require_admin)) -> dict[str, str]:
    webhook_url = settings.portainer_webhook_url.strip()
    if not webhook_url:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Der Portainer-Git-Webhook ist nicht konfiguriert")
    if not webhook_url.startswith(("https://", "http://")):
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Die Portainer-Webhook-Adresse ist ungültig")
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "LifePilot"}
    try:
        latest_request = Request(GITHUB_BRANCH_URL, headers=headers)
        with build_opener(ProxyHandler({})).open(latest_request, timeout=8) as response:
            latest = GitHubCommit.model_validate_json(response.read())
    except (HTTPError, URLError, TimeoutError, OSError, ValidationError) as exc:
        logger.warning("GitHub-Zielversion konnte nicht gelesen werden (%s)", type(exc).__name__)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Die Zielversion konnte bei GitHub nicht ermittelt werden") from None
    if not COMMIT_PATTERN.fullmatch(latest.sha):
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="GitHub hat eine ungültige Zielversion geliefert")
    previous_images: dict[str, str] = {}
    if is_configured():
        baseline = container_statuses()
        if not baseline.available:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=baseline.error or "Portainer-Containerstatus ist nicht verfügbar")
        if any(item.name is None for item in baseline.containers):
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Portainer hat nicht alle sechs LifePilot-Stackdienste gefunden. Prüfe PORTAINER_STACK_NAME und die Environment-ID.")
        previous_images = {item.service: item.image_id for item in baseline.containers if item.image_id}
    mark_update_pending_with_images(latest.sha, previous_images)
    try:
        response_status = call_portainer_webhook(webhook_url, latest.sha)
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        clear_pending_update()
        logger.warning("Portainer-Webhook konnte nicht erreicht werden (%s)", type(exc).__name__)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Portainer konnte nicht erreicht werden") from None
    if not 200 <= response_status < 300:
        clear_pending_update()
        logger.warning("Portainer-Webhook antwortete mit HTTP %s", response_status)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Portainer hat die Aktualisierung nicht angenommen")
    db.add(AuditEvent(owner_id=actor.id, action="update", resource_type="application_update", resource_id="main", source="web"))
    db.commit()
    return {"status": "triggered", "target_commit": latest.sha[:12], "message": "Portainer hat das Update angenommen. Der neue Stand wird beim Neustart geprüft."}
