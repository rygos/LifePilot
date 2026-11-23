import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

from lifepilot.config import settings
from lifepilot.portainer_monitor import container_statuses


def test_portainer_container_status_compares_service_images_and_app_versions(monkeypatch) -> None:
    target_commit = "c" * 40
    services = ("api", "web", "worker", "scheduler", "db", "redis")
    image_ids = {service: f"sha256:{service}" for service in services}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path.startswith("/api/endpoints/3/docker/containers/json?"):
                payload = [{"Id": service, "Image": f"example/{service}", "ImageID": image_ids[service], "Names": [f"/lifepilot-{service}-1"], "State": "running", "Labels": {"com.docker.compose.project": "lifepilot", "com.docker.compose.service": service}} for service in services]
            elif "/docker/images/" in self.path:
                payload = {"Config": {"Labels": {"org.opencontainers.image.revision": target_commit}}}
            else:
                service = self.path.split("/")[-2]
                payload = {"Config": {"Image": f"example/{service}"}, "State": {"Status": "running", "Running": True, "StartedAt": "2026-11-23T10:00:00Z", "Health": {"Status": "healthy"}}}
            body = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(settings, "portainer_api_url", f"http://127.0.0.1:{server.server_port}")
    monkeypatch.setattr(settings, "portainer_api_key", "test-token")
    monkeypatch.setattr(settings, "portainer_endpoint_id", 3)
    monkeypatch.setattr(settings, "portainer_stack_name", "lifepilot")
    try:
        result = container_statuses({"db": image_ids["db"], "redis": "sha256:old-redis"}, target_commit)
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()

    assert result.configured is True
    assert result.available is True
    by_service = {container.service: container for container in result.containers}
    assert by_service["api"].updated is True
    assert by_service["web"].version_commit == "c" * 12
    assert by_service["db"].updated is False
    assert by_service["redis"].updated is True
    assert by_service["worker"].health == "healthy"
