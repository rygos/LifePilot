# LifePilot

LifePilot ist ein deutschsprachiges, selbst hostbares persönliches Gedächtnis. Dieser erste ausführbare Stand bietet Benutzerkonten, Personen, gerichtete Beziehungen, Erinnerungen/Notizen, Aufgaben, Suche, REST und einen authentifizierten MCP-Endpunkt.

## Schnellstart mit Compose

```sh
cp .env.example .env
# SECRET_KEY und LIFE_PILOT_BOOTSTRAP_PASSWORD in .env ändern
docker compose up --build
```

Die Anwendung ist unter `http://localhost:${WEB_PORT}` erreichbar. REST/OpenAPI: `http://localhost:${API_PORT}/docs`; MCP Streamable HTTP: `http://localhost:${MCP_PORT}/mcp`. Beim ersten Start wird genau ein Bootstrap-Benutzer aus den Umgebungsvariablen angelegt. Die Datenbank liegt im persistenten Volume `lifepilot-data`.

Für lokale API-Entwicklung: `cd apps/api && python -m venv .venv && . .venv/bin/activate && pip install -e '.[dev]' && alembic upgrade head && uvicorn lifepilot.main:app --reload`. Das Webprojekt benötigt Node 20+; `cd apps/web && npm install && npm run dev`.

## MCP

MCP nutzt Streamable HTTP und Bearer-Token. Ein Benutzer erzeugt ein Zugangstoken durch `POST /api/auth/token` mit seinem Benutzernamen und Passwort (OAuth2-Password-Form). Für kompatible Clients den MCP-Endpunkt `http://<host>:8002/mcp` und `Authorization: Bearer <token>` konfigurieren. Codex kann beispielsweise mit `{"mcpServers":{"lifepilot":{"url":"http://localhost:8002/mcp","headers":{"Authorization":"Bearer <token>"}}}}` verbunden werden. Die derzeit vier Werkzeuge decken Person anlegen/suchen und Erinnerung erfassen/suchen ab. Das Token wie ein Passwort behandeln.

## KI-Konfiguration

In diesem Stand gibt es keinen aktiven LLM-Provider. `LLM_BASE_URL` und `LLM_MODEL` sind für die kommende OpenAI-kompatible Adapterstufe reserviert. Daten bleiben bei nicht konfigurierter oder nicht erreichbarer KI vollständig klassisch verwaltbar.

## Betrieb und Daten

Migrationen laufen beim API-Start via Alembic. Updates: `docker compose pull && docker compose up -d --build`. Das Volume enthält SQLite-Daten. Vor Updates sichern: `docker compose exec api python -m lifepilot.backup /app/data /tmp/lifepilot-backup.tar.gz` (Backup-Werkzeug folgt in einem späteren Schritt; bis dahin Volume-Snapshot bzw. konsistentes Kopieren der SQLite-Datei im gestoppten Zustand verwenden).

## Status und Einschränkungen

Siehe [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) und [ARCHITECTURE.md](ARCHITECTURE.md). Noch fehlen u.a. PostgreSQL/pgvector-Betrieb, Redis-Worker, Gespräche, Ereignisse, Leihgaben, Geschenke, echte Terminplanung, Hintergrundbenachrichtigungen, Datei-Uploads, KI, vollständige MCP-Operationen und automatisierte End-to-End-Tests. Dies ist ein benutzbarer Kern, noch keine Umsetzung des Gesamtumfangs.
