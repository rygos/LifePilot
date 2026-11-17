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

MCP nutzt Streamable HTTP und Bearer-Token. Für getrennte Berechtigungen stellt `POST /api/auth/mcp-token` mit JSON `{ "username": "...", "password": "...", "access": "read_only" }` ein Nur-Lese-Token aus; `access: "read_write"` schaltet Schreibwerkzeuge frei. MCP-Tokens sind auf den MCP-Endpunkt beschränkt und können keine REST-Freigabe bestätigen. Benutzer-Token können umgekehrt nicht am MCP-Endpunkt verwendet werden. Die normale Anmeldung über `/api/auth/token` oder `/api/auth/login` erzeugt ein Benutzer-Token mit Lese- und Schreibrechten. Den MCP-Endpunkt `http://<host>:8002/mcp` und `Authorization: Bearer <token>` im Client konfigurieren. Codex kann beispielsweise mit `{"mcpServers":{"lifepilot":{"url":"http://localhost:8002/mcp","headers":{"Authorization":"Bearer <token>"}}}}` verbunden werden. Die Werkzeuge umfassen Personen und Beziehungen, Erinnerungen, Gespräche, Aufgaben, Termine, Projekte, Leihgaben, Geschenke sowie Briefings. Schreiboperationen verwenden dieselben Besitzerprüfungen und Geschäftsoperationen wie die REST-API. Kritische Löschungen erstellen einen Antrag; sie werden erst ausgeführt, wenn der angemeldete Benutzer sie im Dashboard unter „Freigaben“ bestätigt. Anträge können auch abgelehnt werden. MCP-Schreibvorgänge werden mit Benutzer, Ressource, Aktion und Zeitpunkt protokolliert. Der angemeldete Benutzer kann die eigenen Einträge über `audit_search` oder `GET /api/audit` abrufen. Tokens wie Passwörter behandeln.

Für den lokalen Testbetrieb waren die Standardports 8000 und 3000 bereits belegt; dort wurde daher `API_PORT=8001` und `WEB_PORT=3001` verwendet. Das beeinflusst die `.env.example` nicht.

## KI-Konfiguration und Eingang

Die Schnellerfassung speichert den Originaltext zuerst unverändert in `/api/captures`. Ist ein OpenAI-kompatibler Chat-Completions-Endpunkt konfiguriert, verarbeitet der RQ-Worker ihn im Hintergrund. Vorschläge erscheinen im Eingang und werden erst nach manueller Auswahl als Erinnerungen übernommen; die übernommenen Fakten behalten eine Verknüpfung zur Quelle. Ohne Modell, bei einem Providerfehler oder einer nicht verfügbaren Queue bleibt die Eingabe erhalten und kann klassisch weiterverwendet werden.

Für LM Studio, Ollama im OpenAI-kompatiblen Modus oder einen anderen kompatiblen Endpunkt diese Werte in `.env` setzen:

```dotenv
LLM_BASE_URL=http://<modell-host>:1234/v1
LLM_API_KEY=
LLM_MODEL=<modellname>
LLM_TIMEOUT_SECONDS=15
```

Danach `docker compose up -d --build api` ausführen. Der Endpunkt muss aus dem API-Container erreichbar sein. Ein fehlender API-Schlüssel ist für lokale Server erlaubt. Die KI verarbeitet nur die jeweilige Eingabe; Personen, Beziehungen und Aufgaben werden durch sie nicht direkt angelegt.

## Betrieb und Daten

Migrationen laufen beim API-Start via Alembic. Compose verwendet PostgreSQL 16 mit pgvector und persistiert die Daten im Volume `lifepilot-postgres`. Redis speichert RQ-Jobs mit AOF im Volume `lifepilot-redis`; der Scheduler reiht Erinnerungsplanungen ein und der getrennte Worker verarbeitet sie mit begrenzten Wiederholungen. SQLite bleibt für Tests und lokale Entwicklung über eine angepasste `DATABASE_URL` nutzbar. Updates: `docker compose pull && docker compose up -d --build`. Vor Updates PostgreSQL mit `pg_dump` sichern. Ein automatischer Umzug bestehender SQLite-Daten nach PostgreSQL ist noch nicht implementiert; bestehende `.env`-Dateien mit SQLite-URL bleiben deshalb unverändert auf SQLite und können weiter betrieben werden.

## Status und Einschränkungen

Siehe [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) und [ARCHITECTURE.md](ARCHITECTURE.md). Noch fehlen u.a. Datei-Uploads, Embeddings und semantische Suche, vollständige CRUD-Abdeckung, automatisierte End-to-End- und Backup/Restore-Tests. Der Scheduler erzeugt einmalige Erinnerungen für Aufgaben und Termine; externe Zustellkanäle sind nicht enthalten.

## Termine und Erinnerungen

Termine lassen sich über `POST /api/events` mit Startzeit, optionalem Ende, Ort, Teilnehmern und Quellerinnerung speichern. `GET /api/events` unterstützt `from_at`, `to_at` und `person_id`. Der unabhängige Scheduler reiht Erinnerungsplanungen in Redis ein; der `worker`-Dienst verarbeitet persistente Jobs mit Wiederholungen. `GET /api/notifications` liefert fällige Einträge; `PATCH /api/reminders/{id}` schließt sie ab, pausiert sie oder verschiebt sie mit `snoozed_until`. Beim Erledigen einer Aufgabe wird ihre geplante Erinnerung ebenfalls abgeschlossen. Die UI bietet Termin-Erfassung und Aktionen zum Verschieben um eine Stunde oder Abschließen.

Der Scheduler reiht minütlich eine Planung in RQ ein. Der Worker verarbeitet sie mit bis zu drei Wiederholungen nach 15, 60 und 180 Sekunden; eine zeitlich begrenzte Sperre und idempotente Datenbankoperation verhindern doppelte Planungsläufe. Redis-AOF und Volume erhalten Jobs bei Containerneustarts. Bei Redis-Ausfall bleiben API und gespeicherte Erinnerungen verfügbar; der Scheduler versucht den nächsten Zyklus erneut. Erinnerungen werden aktuell einmalig erzeugt; externe Zustellung ist nicht enthalten.

## Personen und Beziehungen

Die Personenansicht enthält bearbeitbare Profile mit Spitzname, Geburtstag, E-Mail, Telefon, Adresse, Webseite, Beruf, Organisation und Notizen. Ein Profil lässt sich aus der Menschenliste öffnen. Beziehungen werden aus einer Auswahl angelegt, die Ausgangs- und Gegenrichtung festlegt, zum Beispiel „Tochter von / Vater von“. Beide Perspektiven erscheinen mit den Namen der Personen; doppelte Gegenkanten werden verhindert. Das persönliche Benutzerprofil ist über die Schaltfläche neben dem Datum erreichbar und enthält Name, Spitzname, Geburtstag und Kontaktdaten. Die Änderungen werden über `/api/profile`, `/api/people` und `/api/relationships` persistiert; Migration `0004_person_profiles` und `0005_relationship_inverses` ergänzen die Felder ohne vorhandene Einträge zu löschen. Die Auswahl umfasst gängige Familien-, Partner-, Geschwister- und soziale Beziehungen.
