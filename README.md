# LifePilot

LifePilot ist ein deutschsprachiges, selbst hostbares persönliches Gedächtnis. Der ausführbare Kern bietet Benutzerkonten, Personen, gerichtete Beziehungen, Erinnerungen/Notizen, Aufgaben, Gespräche, Termine, persistente In-App-Erinnerungen, offene Leihgaben, Geschenkideen, strukturierte Suche, REST und einen authentifizierten MCP-Endpunkt.

## Schnellstart mit Compose

```sh
cp .env.example .env
# SECRET_KEY, POSTGRES_PASSWORD und LIFE_PILOT_BOOTSTRAP_PASSWORD in .env ändern
docker compose up --build
```

Die Anwendung ist standardmäßig unter `http://localhost:3000` erreichbar. REST/OpenAPI liegt standardmäßig unter `http://localhost:8000/docs`, MCP unter `http://localhost:8002/mcp`. Ports lassen sich über `WEB_PORT`, `API_PORT` und `MCP_PORT` ändern. Beim ersten Start wird genau ein Bootstrap-Benutzer aus den Umgebungsvariablen angelegt. PostgreSQL persistiert seine Daten im Volume `lifepilot-postgres`; das Volume `lifepilot-data` bleibt für SQLite-Dateien verfügbar. Redis ist nicht öffentlich erreichbar; der lokale Port lässt sich über `REDIS_PORT` ändern und bindet standardmäßig nur an Loopback.

Für lokale API-Entwicklung: `cd apps/api && python -m venv .venv && . .venv/bin/activate && pip install -e '.[dev]' && alembic upgrade head && uvicorn lifepilot.main:app --reload`. Das Webprojekt benötigt Node 20+; `cd apps/web && npm install && npm run dev`.

Für den Backend-Testlauf Redis mit `docker compose up -d redis` starten und in `apps/api` `REDIS_URL=redis://127.0.0.1:16379/15 pytest tests -q` ausführen. Der Redis-Sperrtest wird übersprungen, wenn `REDIS_URL` fehlt.

## MCP

MCP nutzt Streamable HTTP und Bearer-Token. Ein Benutzer erzeugt ein Zugangstoken durch `POST /api/auth/token` mit seinem Benutzernamen und Passwort (OAuth2-Password-Form). Für kompatible Clients den MCP-Endpunkt `http://<host>:8002/mcp` und `Authorization: Bearer <token>` konfigurieren. Codex kann beispielsweise mit `{"mcpServers":{"lifepilot":{"url":"http://localhost:8002/mcp","headers":{"Authorization":"Bearer <token>"}}}}` verbunden werden. Die derzeit vier Werkzeuge decken Person anlegen/suchen und Erinnerung erfassen/suchen ab. Das Token wie ein Passwort behandeln.

Für den lokalen Testbetrieb waren die Standardports 8000 und 3000 bereits belegt; dort wurde daher `API_PORT=8001` und `WEB_PORT=3001` verwendet. Das beeinflusst die `.env.example` nicht.

## KI-Konfiguration

In diesem Stand gibt es keinen aktiven LLM-Provider. `LLM_BASE_URL` und `LLM_MODEL` sind für die kommende OpenAI-kompatible Adapterstufe reserviert. Daten bleiben bei nicht konfigurierter oder nicht erreichbarer KI vollständig klassisch verwaltbar.

## Betrieb und Daten

Migrationen laufen beim API-Start via Alembic. Compose verwendet PostgreSQL 16 mit pgvector und persistiert die Daten im Volume `lifepilot-postgres`. Redis speichert RQ-Jobs mit AOF im Volume `lifepilot-redis`; der Scheduler reiht Erinnerungsplanungen ein und der getrennte Worker verarbeitet sie mit begrenzten Wiederholungen. SQLite bleibt für Tests und lokale Entwicklung über eine angepasste `DATABASE_URL` nutzbar. Updates: `docker compose pull && docker compose up -d --build`. Vor Updates PostgreSQL mit `pg_dump` sichern. Ein automatischer Umzug bestehender SQLite-Daten nach PostgreSQL ist noch nicht implementiert; bestehende `.env`-Dateien mit SQLite-URL bleiben deshalb unverändert auf SQLite und können weiter betrieben werden.

## Status und Einschränkungen

Siehe [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) und [ARCHITECTURE.md](ARCHITECTURE.md). Noch fehlen u.a. Datei-Uploads, KI und semantische Suche, vollständige MCP-Operationen sowie automatisierte End-to-End- und Backup/Restore-Tests. Der Scheduler erzeugt einmalige Erinnerungen für Aufgaben und Termine; externe Zustellkanäle sind nicht enthalten.

## Termine und Erinnerungen

Termine lassen sich über `POST /api/events` mit Startzeit, optionalem Ende, Ort, Teilnehmern und Quellerinnerung speichern. `GET /api/events` unterstützt `from_at`, `to_at` und `person_id`. Der unabhängige Scheduler reiht Erinnerungsplanungen in Redis ein; der `worker`-Dienst verarbeitet persistente Jobs mit Wiederholungen. `GET /api/notifications` liefert fällige Einträge; `PATCH /api/reminders/{id}` schließt sie ab, pausiert sie oder verschiebt sie mit `snoozed_until`. Beim Erledigen einer Aufgabe wird ihre geplante Erinnerung ebenfalls abgeschlossen. Die UI bietet Termin-Erfassung und Aktionen zum Verschieben um eine Stunde oder Abschließen.

Der Scheduler reiht minütlich eine Planung in RQ ein. Der Worker verarbeitet sie mit bis zu drei Wiederholungen nach 15, 60 und 180 Sekunden; eine zeitlich begrenzte Sperre und idempotente Datenbankoperation verhindern doppelte Planungsläufe. Redis-AOF und Volume erhalten Jobs bei Containerneustarts. Bei Redis-Ausfall bleiben API und gespeicherte Erinnerungen verfügbar; der Scheduler versucht den nächsten Zyklus erneut. Erinnerungen werden aktuell einmalig erzeugt; externe Zustellung ist nicht enthalten.

## Personen und Beziehungen

Die Personenansicht enthält bearbeitbare Profile mit Spitzname, Geburtstag, E-Mail, Telefon, Adresse, Webseite, Beruf, Organisation und Notizen. Ein Profil lässt sich aus der Menschenliste öffnen. Beziehungen werden aus einer Auswahl angelegt, die Ausgangs- und Gegenrichtung festlegt, zum Beispiel „Tochter von / Vater von“. Beide Perspektiven erscheinen mit den Namen der Personen; doppelte Gegenkanten werden verhindert. Das persönliche Benutzerprofil ist über die Schaltfläche neben dem Datum erreichbar und enthält Name, Spitzname, Geburtstag und Kontaktdaten. Die Änderungen werden über `/api/profile`, `/api/people` und `/api/relationships` persistiert; Migration `0004_person_profiles` und `0005_relationship_inverses` ergänzen die Felder ohne vorhandene Einträge zu löschen. Die Auswahl umfasst gängige Familien-, Partner-, Geschwister- und soziale Beziehungen.
