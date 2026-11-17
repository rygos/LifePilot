# LifePilot

LifePilot ist ein deutschsprachiges, selbst hostbares persönliches Gedächtnis. Der ausführbare Kern bietet Benutzerkonten, Personen, gerichtete Beziehungen, Erinnerungen/Notizen, Aufgaben, Gespräche, Termine, persistente In-App-Erinnerungen, offene Leihgaben, Geschenkideen, strukturierte Suche, REST und einen authentifizierten MCP-Endpunkt.

## Schnellstart mit Compose

```sh
cp .env.example .env
# SECRET_KEY und LIFE_PILOT_BOOTSTRAP_PASSWORD in .env ändern
docker compose up --build
```

Die Anwendung ist standardmäßig unter `http://localhost:3000` erreichbar. REST/OpenAPI liegt standardmäßig unter `http://localhost:8000/docs`, MCP unter `http://localhost:8002/mcp`. Ports lassen sich über `WEB_PORT`, `API_PORT` und `MCP_PORT` ändern. Beim ersten Start wird genau ein Bootstrap-Benutzer aus den Umgebungsvariablen angelegt. Die Datenbank liegt im persistenten Volume `lifepilot-data`.

Für lokale API-Entwicklung: `cd apps/api && python -m venv .venv && . .venv/bin/activate && pip install -e '.[dev]' && alembic upgrade head && uvicorn lifepilot.main:app --reload`. Das Webprojekt benötigt Node 20+; `cd apps/web && npm install && npm run dev`.

## MCP

MCP nutzt Streamable HTTP und Bearer-Token. Ein Benutzer erzeugt ein Zugangstoken durch `POST /api/auth/token` mit seinem Benutzernamen und Passwort (OAuth2-Password-Form). Für kompatible Clients den MCP-Endpunkt `http://<host>:8002/mcp` und `Authorization: Bearer <token>` konfigurieren. Codex kann beispielsweise mit `{"mcpServers":{"lifepilot":{"url":"http://localhost:8002/mcp","headers":{"Authorization":"Bearer <token>"}}}}` verbunden werden. Die derzeit vier Werkzeuge decken Person anlegen/suchen und Erinnerung erfassen/suchen ab. Das Token wie ein Passwort behandeln.

Für den lokalen Testbetrieb waren die Standardports 8000 und 3000 bereits belegt; dort wurde daher `API_PORT=8001` und `WEB_PORT=3001` verwendet. Das beeinflusst die `.env.example` nicht.

## KI-Konfiguration

In diesem Stand gibt es keinen aktiven LLM-Provider. `LLM_BASE_URL` und `LLM_MODEL` sind für die kommende OpenAI-kompatible Adapterstufe reserviert. Daten bleiben bei nicht konfigurierter oder nicht erreichbarer KI vollständig klassisch verwaltbar.

## Betrieb und Daten

Migrationen laufen beim API-Start via Alembic. Updates: `docker compose pull && docker compose up -d --build`. Das Volume enthält SQLite-Daten. Vor Updates sichern: `docker compose exec api python -m lifepilot.backup /app/data /tmp/lifepilot-backup.tar.gz` (Backup-Werkzeug folgt in einem späteren Schritt; bis dahin Volume-Snapshot bzw. konsistentes Kopieren der SQLite-Datei im gestoppten Zustand verwenden).

## Status und Einschränkungen

Siehe [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) und [ARCHITECTURE.md](ARCHITECTURE.md). Noch fehlen u.a. PostgreSQL/pgvector-Betrieb, Redis, Ruhezeiten und Wiederholungsregeln für Benachrichtigungen, Datei-Uploads, KI, vollständige MCP-Operationen und automatisierte End-to-End-Tests. Der Scheduler erzeugt einmalige Erinnerungen für Aufgaben und Termine; externe Zustellkanäle sind nicht enthalten.

## Termine und Erinnerungen

Termine lassen sich über `POST /api/events` mit Startzeit, optionalem Ende, Ort, Teilnehmern und Quellerinnerung speichern. `GET /api/events` unterstützt `from_at`, `to_at` und `person_id`. Der unabhängige `worker`-Dienst plant persistente Erinnerungen für Termine und fällige Aufgaben. `GET /api/notifications` liefert fällige Einträge; `PATCH /api/reminders/{id}` schließt sie ab, pausiert sie oder verschiebt sie mit `snoozed_until`. Beim Erledigen einer Aufgabe wird ihre geplante Erinnerung ebenfalls abgeschlossen. Die UI bietet Termin-Erfassung und Aktionen zum Verschieben um eine Stunde oder Abschließen.

Der Scheduler prüft die gemeinsame persistente Datenbank minütlich und benötigt kein Sprachmodell oder Redis. Erinnerungen werden aktuell einmalig erzeugt; wiederkehrende Regeln, Ruhezeiten und externe Zustellung sind noch nicht umgesetzt.

## Personen und Beziehungen

Die Personenansicht enthält bearbeitbare Profile mit Spitzname, Geburtstag, E-Mail, Telefon, Adresse, Webseite, Beruf, Organisation und Notizen. Ein Profil lässt sich aus der Menschenliste öffnen. Im Profil werden alle gerichteten Beziehungen mit den Namen beider Personen angezeigt; neue Beziehungen können mit Richtungstext angelegt und bestehende entfernt werden. Das persönliche Benutzerprofil ist über die Schaltfläche neben dem Datum erreichbar und enthält Name, Spitzname, Geburtstag und Kontaktdaten. Die Änderungen werden über `/api/profile`, `/api/people` und `/api/relationships` persistiert; Migration `0004_person_profiles` ergänzt die Felder ohne vorhandene Einträge zu löschen.
