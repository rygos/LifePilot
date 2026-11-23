import json
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from pydantic import BaseModel, ConfigDict

from lifepilot.config import settings

logger = logging.getLogger(__name__)
EXPECTED_SERVICES = ("api", "web", "worker", "scheduler", "db", "redis")
APPLICATION_SERVICES = frozenset(("api", "web", "worker", "scheduler"))


class ContainerStatus(BaseModel):
    model_config = ConfigDict(frozen=True)

    service: str
    name: str | None
    state: str
    health: str | None
    image: str | None
    image_id: str
    started_at: datetime | None
    version_commit: str | None
    updated: bool | None


class ContainerMonitorResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    configured: bool
    available: bool
    error: str | None
    containers: list[ContainerStatus]


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req: Request, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
        return None


def is_configured() -> bool:
    return bool(settings.portainer_api_url.strip() and settings.portainer_api_key.strip() and settings.portainer_endpoint_id)


def _request_json(path: str) -> Any:
    base_url = settings.portainer_api_url.strip().rstrip("/")
    request = Request(f"{base_url}{path}", headers={"X-API-Key": settings.portainer_api_key.strip(), "Accept": "application/json"})
    opener = build_opener(ProxyHandler({}), _NoRedirect())
    with opener.open(request, timeout=5) as response:
        return json.loads(response.read())


def _inspect(container_id: str) -> dict[str, Any]:
    return _request_json(f"/api/endpoints/{settings.portainer_endpoint_id}/docker/containers/{container_id}/json")


def _inspect_image(image_id: str) -> dict[str, Any]:
    return _request_json(f"/api/endpoints/{settings.portainer_endpoint_id}/docker/images/{quote(image_id, safe='')}/json")


def _inspect_container_and_image(item: tuple[str, dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    row = item[1]
    return _inspect(row["Id"]), _inspect_image(row["ImageID"])


def _container_status(row: dict[str, Any], state: dict[str, Any], image: dict[str, Any], baseline: dict[str, str], target_commit: str | None) -> ContainerStatus:
    labels = row.get("Labels") or {}
    service = labels.get("com.docker.compose.service", "")
    inspect_config = state.get("Config") or {}
    version_commit = ((image.get("Config") or {}).get("Labels") or {}).get("org.opencontainers.image.revision")
    container_state = state.get("State") or {}
    health = (container_state.get("Health") or {}).get("Status")
    image_id = row.get("ImageID", "")
    if target_commit is None:
        updated = None
    elif service in APPLICATION_SERVICES:
        updated = container_state.get("Running") is True and version_commit == target_commit
    else:
        previous_image = baseline.get(service)
        updated = image_id != previous_image if previous_image else None
    names = row.get("Names") or []
    started_at = container_state.get("StartedAt")
    try:
        parsed_started_at = datetime.fromisoformat(started_at.replace("Z", "+00:00")) if started_at and not started_at.startswith("0001-") else None
    except (TypeError, ValueError):
        parsed_started_at = None
    return ContainerStatus(
        service=service,
        name=names[0].lstrip("/") if names else None,
        state=container_state.get("Status") or row.get("State", "unknown"),
        health=health,
        image=inspect_config.get("Image") or row.get("Image"),
        image_id=image_id,
        started_at=parsed_started_at,
        version_commit=version_commit[:12] if version_commit else None,
        updated=updated,
    )


def container_statuses(baseline: dict[str, str] | None = None, target_commit: str | None = None) -> ContainerMonitorResult:
    if not is_configured():
        return ContainerMonitorResult(configured=False, available=False, error=None, containers=[])
    baseline = baseline or {}
    filters = json.dumps({"label": [f"com.docker.compose.project={settings.portainer_stack_name.strip()}"]}, separators=(",", ":"))
    try:
        rows = _request_json(f"/api/endpoints/{settings.portainer_endpoint_id}/docker/containers/json?{urlencode({'all': 'true', 'filters': filters})}")
        if not isinstance(rows, list):
            raise ValueError("Portainer lieferte eine ungültige Containerliste")
        rows_by_service: dict[str, list[dict[str, Any]]] = {service: [] for service in EXPECTED_SERVICES}
        for row in rows:
            service = (row.get("Labels") or {}).get("com.docker.compose.service")
            if service in rows_by_service:
                rows_by_service[service].append(row)
        pending: list[tuple[str, dict[str, Any]]] = [(service, row) for service, service_rows in rows_by_service.items() for row in service_rows]
        with ThreadPoolExecutor(max_workers=6) as executor:
            details = list(executor.map(_inspect_container_and_image, pending))
        found: dict[str, list[ContainerStatus]] = {service: [] for service in EXPECTED_SERVICES}
        for (service, row), (inspection, image) in zip(pending, details, strict=True):
            found[service].append(_container_status(row, inspection, image, baseline, target_commit))
        result = [container for service in EXPECTED_SERVICES for container in (found[service] or [ContainerStatus(service=service, name=None, state="waiting", health=None, image=None, image_id="", started_at=None, version_commit=None, updated=None)])]
        return ContainerMonitorResult(configured=True, available=True, error=None, containers=result)
    except (HTTPError, URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError, KeyError) as exc:
        logger.info("Portainer-Containerstatus nicht verfügbar (%s)", type(exc).__name__)
        return ContainerMonitorResult(configured=True, available=False, error="Der Portainer-Containerstatus ist momentan nicht erreichbar.", containers=[])
