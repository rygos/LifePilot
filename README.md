# LifePilot

LifePilot ist ein deutschsprachiges, selbst hostbares persönliches Gedächtnis. Der ausführbare Kern bietet Benutzerkonten, Personen, gerichtete Beziehungen zwischen Kontakten und zum Nutzerprofil, Erinnerungen/Notizen, Aufgaben, Gespräche, Termine, persistente In-App-Erinnerungen, offene Leihgaben, Geschenkideen, strukturierte Suche, REST und einen authentifizierten MCP-Endpunkt.

## Schnellstart mit Compose

```sh
cp .env.example .env
# SECRET_KEY, POSTGRES_PASSWORD und LIFE_PILOT_BOOTSTRAP_PASSWORD in .env ändern
docker compose up --build
```

Die Anwendung ist standardmäßig unter `http://localhost:3000` erreichbar. REST/OpenAPI liegt standardmäßig unter `http://localhost:8000/docs`, MCP unter `http://localhost:8002/mcp`. Ports lassen sich über `WEB_PORT`, `API_PORT` und `MCP_PORT` ändern. Beim API-Start wird der Bootstrap-Benutzer aus `LIFE_PILOT_BOOTSTRAP_USERNAME` und `LIFE_PILOT_BOOTSTRAP_PASSWORD` nur angelegt, wenn der Benutzername in der Datenbank noch nicht existiert. Diese Werte ändern ein bestehendes Konto nicht: Ein nachträglich geänderter Benutzername legt ein zusätzliches Konto mit getrennten Daten an; die Daten des bisherigen Kontos werden nicht übernommen. Eine nachträgliche Änderung von `LIFE_PILOT_BOOTSTRAP_PASSWORD` setzt auch das Passwort eines vorhandenen Kontos nicht zurück. Um auf die bisherigen Daten zuzugreifen, muss derselbe Benutzername verwendet werden. PostgreSQL persistiert seine Daten im Volume `lifepilot-postgres`; das Volume `lifepilot-data` bleibt für SQLite-Dateien verfügbar. Redis ist nicht öffentlich erreichbar; der lokale Port lässt sich über `REDIS_PORT` ändern und bindet standardmäßig nur an Loopback.

Die Weboberfläche kann als PWA installiert werden. Im Offline-Modus bleibt die App-Shell erreichbar; persönliche Daten und API-Änderungen werden aus Datenschutzgründen nicht lokal zwischengespeichert.

Für lokale API-Entwicklung: `cd apps/api && python -m venv .venv && . .venv/bin/activate && pip install -e '.[dev]' && alembic upgrade head && uvicorn lifepilot.main:app --reload`. Das Webprojekt benötigt Node 20+; `cd apps/web && npm install && npm run dev`.

## PWA und Browser-End-to-End-Test

Manifest, installierbare PNG-/SVG-Symbole und Service Worker werden unter `/manifest.webmanifest`, `/icon-192.png`, `/icon-512.png`, `/icon.svg` und `/sw.js` bereitgestellt. Der Service Worker speichert nur die App-Shell und statische Dateien; `/api/`-Antworten werden nie in den Cache geschrieben. Für Updates versioniert `sw.js` den Cache und entfernt ältere App-Shell-Caches.

Der Playwright-End-to-End-Test benötigt eine laufende, erreichbare API, eine zuvor erstellte Produktionsversion (`cd apps/web && npm run build`) und Chromium (`npx playwright install chromium`). Er meldet sich über die Oberfläche an, legt zwei Testpersonen an, prüft die automatische Gegenrichtung einer Beziehung und lädt die Offline-App-Shell. Die Testpersonen werden nach dem Lauf über die API entfernt.

```sh
cd apps/web
LIFEPILOT_E2E_USERNAME=admin LIFEPILOT_E2E_PASSWORD='<Passwort>' npm run test:e2e
```

Alternativ verwendet der Test `LIFE_PILOT_BOOTSTRAP_USERNAME` und `LIFE_PILOT_BOOTSTRAP_PASSWORD` aus der Umgebung. Bei abweichenden URLs lassen sich `LIFEPILOT_E2E_WEB_URL` und `LIFEPILOT_E2E_API_URL` setzen.

Für den Backend-Testlauf Redis mit `docker compose up -d redis` starten und in `apps/api` `REDIS_URL=redis://127.0.0.1:16379/15 pytest tests -q` ausführen. Der Redis-Sperrtest wird übersprungen, wenn `REDIS_URL` fehlt.

## MCP

MCP nutzt Streamable HTTP und Bearer-Token. Für getrennte Berechtigungen stellt `POST /api/auth/mcp-token` mit JSON `{ "username": "...", "password": "...", "access": "read_only" }` ein Nur-Lese-Token aus; `access: "read_write"` schaltet Schreibwerkzeuge frei. MCP-Tokens sind auf den MCP-Endpunkt beschränkt und können keine REST-Freigabe bestätigen. Benutzer-Token können umgekehrt nicht am MCP-Endpunkt verwendet werden. Die normale Anmeldung über `/api/auth/token` oder `/api/auth/login` erzeugt ein Benutzer-Token mit Lese- und Schreibrechten. Den MCP-Endpunkt `http://<host>:8002/mcp` und `Authorization: Bearer <token>` im Client konfigurieren. Codex kann beispielsweise mit `{"mcpServers":{"lifepilot":{"url":"http://localhost:8002/mcp","headers":{"Authorization":"Bearer <token>"}}}}` verbunden werden. Die Werkzeuge umfassen Profile, Personen, Beziehungen, Notizen und Erinnerungsreview, Gespräche, Aufgaben, Termine, Wiedervorlagen, Projekte, Tierprofile (`pet_create`, `pet_search`, `pet_get`, `pet_update`, `pet_delete`), Leihgaben, Geschenke, Briefings sowie `attachment_search` für Dateimetadaten an Personen, Erinnerungen, Gesprächen, Ereignissen und Projekten. MCP liefert Dateinamen und Metadaten, keine Datei-Inhalte. Löschungen laufen über eine benutzergenehmigte Freigabe; ein Personenmerge verlangt eine ausdrückliche `confirm: true`-Angabe und schreibt alle Verknüpfungen in einer Transaktion um. Schreiboperationen verwenden Besitzerprüfungen und auditierte Geschäftsoperationen. Der angemeldete Benutzer kann die eigenen Einträge über `audit_search` oder `GET /api/audit` abrufen. Tokens wie Passwörter behandeln.

Das Tagebuch ist über `journal_create`, `journal_search`, `journal_get` und `journal_update` erreichbar. `journal_delete` erstellt eine bestätigungspflichtige Freigabe. Datumswerte folgen dem Format `YYYY-MM-DD`; Einträge können mit mehreren eigenen Personen, Projekten und Ereignissen verknüpft werden.

Für den lokalen Testbetrieb waren die Standardports 8000 und 3000 bereits belegt; dort wurde daher `API_PORT=8001` und `WEB_PORT=3001` verwendet. Das beeinflusst die `.env.example` nicht.

## KI-Konfiguration und Eingang

Die Schnellerfassung speichert den Originaltext zuerst unverändert in `/api/captures`. Ist ein OpenAI-kompatibler Chat-Completions-Endpunkt konfiguriert, verarbeitet der RQ-Worker ihn im Hintergrund. Geprüfte Vorschläge können Gespräche, vergangene Ereignisse, Beziehungen mit beiden Richtungen, frühere Namen, biografische Ereignisse, Aufgaben, Termine und projektverknüpfte Fakten erzeugen. Ein datiertes Gespräch wird zusätzlich als Erlebnis im Ereignisarchiv gespeichert, einschließlich ausdrücklich genannter Teilnehmender und Orte. Eine Aufgabe wird nur aus einem ausdrücklichen Vorschlag erstellt und erhält bei Fälligkeit eine persistente Erinnerung. Ungefähre biografische Zeiträume werden nicht zu erfundenen Kalenderdaten. Jede Übernahme bleibt auf den unveränderten Originaltext zurückführbar. Mehrdeutige Personen und Projekte benötigen eine Zuordnung; eine unbekannte Person wird nur nach ausdrücklicher Auswahl angelegt. Biografische Angaben und unsichere Aussagen benötigen Bestätigung. Ohne Modell, bei einem Providerfehler oder einer nicht verfügbaren Queue bleibt die Eingabe erhalten.

Für LM Studio, Ollama im OpenAI-kompatiblen Modus oder einen anderen kompatiblen Endpunkt diese Werte in `.env` setzen:

```dotenv
LLM_BASE_URL=http://<modell-host>:1234/v1
LLM_API_KEY=
LLM_MODEL=<modellname>
LLM_TIMEOUT_SECONDS=15
```

Danach `docker compose up -d --build api worker` ausführen. Der Endpunkt muss aus dem Worker-Container erreichbar sein. Ein fehlender API-Schlüssel ist für lokale Server erlaubt. Das Modell schlägt strukturierte Änderungen vor; sie werden erst nach Bestätigung über den Eingang oder `memory_review` in die Datenbank übernommen. Mit `memory_review` kann ein MCP-Client einen Vorschlag vor dem Speichern auch korrigiert übergeben. Der vollständige MCP-Ablauf lautet `memory_capture` → `memory_capture_status` (bis `ready`, Vorschläge prüfen) → `memory_review`; `memory_capture_list` zeigt offene und frühere Erfassungen.

### Chat in der Weboberfläche

Der Punkt **Chat** steht direkt unter **Übersicht**. Im Modus **Festhalten** wird der unveränderte Text sofort dauerhaft gespeichert und von der bestehenden KI-Pipeline im Hintergrund verarbeitet. Erkannte Beziehungen, Ereignisse oder andere Änderungen erscheinen im Eingang und werden erst nach deiner Bestätigung übernommen. Im Modus **Fragen** durchsucht LifePilot die Daten des angemeldeten Benutzers und lässt das konfigurierte OpenAI-kompatible Modell ausschließlich aus diesen Treffern antworten. Die Treffer erscheinen als anklickbare Quellen. Ohne erreichbares Modell bleiben gefundene Treffer sichtbar; ohne passende Daten sagt LifePilot, dass keine Information gefunden wurde. Die API dafür ist `POST /api/chat/ask`.

Semantische Suche wird unabhängig konfiguriert. Das Modell muss 768 Dimensionen zurückgeben; OpenAI-kompatible Anbieter erhalten zusätzlich `dimensions: 768`. Ein lokaler Modellserver kann beispielsweise so aussehen:

Änderungen an Aufgaben und Gesprächen werden als benutzergebundene, unveränderliche Revision gespeichert. Die Historie ist über `GET /api/tasks/{id}/history`, `GET /api/conversations/{id}/history` sowie die MCP-Werkzeuge `task_history` und `conversation_history` abrufbar. Die Revisionen enthalten Felder, Beziehungs-IDs, Zeitstempel und den auslösenden Kanal. Capture kann außerdem eine ausdrücklich erwähnte Beziehung zum Nutzerprofil, etwa eine Kollegin, vorschlagen; nach Bestätigung erscheint sie im Personenprofil und im Personenbriefing. Sie lässt sich dort auch manuell ohne KI anlegen; der REST-Endpunkt ist `POST /api/people/{id}/owner-relationships`.

```dotenv
EMBEDDING_BASE_URL=http://<modell-host>:1234/v1
EMBEDDING_API_KEY=
EMBEDDING_MODEL=<embedding-modell-mit-768-dimensionen>
EMBEDDING_TIMEOUT_SECONDS=15
```

Ist `EMBEDDING_BASE_URL` leer, wird `LLM_BASE_URL` genutzt; das Embedding-Modell bleibt separat anzugeben. Neue und geänderte Erinnerungen, Gespräche, Aufgaben, Beziehungen und Projekte werden über Redis/RQ indexiert. Für bereits gespeicherte Einträge im Dashboard auf „Semantischen Index erneuern“ klicken. PostgreSQL kombiniert Volltext-Ranking mit pgvector-Cosinus-Ranking. Ohne Embedding-Modell bleibt die strukturierte Volltextsuche verfügbar; SQLite unterstützt dieselbe semantische Suche über eine lokale Cosinus-Berechnung.

## Betrieb und Daten

Migrationen laufen beim API-Start via Alembic. Compose verwendet PostgreSQL 16 mit pgvector und persistiert die Daten im Volume `lifepilot-postgres`. Redis speichert RQ-Jobs mit AOF im Volume `lifepilot-redis`; der Scheduler reiht Erinnerungsplanungen ein und der getrennte Worker verarbeitet sie mit begrenzten Wiederholungen. SQLite bleibt für Tests und lokale Entwicklung über eine angepasste `DATABASE_URL` nutzbar. Updates: `docker compose pull && docker compose up -d --build`. Vor Updates Backup mit `scripts/backup.sh` erstellen; Details und Restore-Ablauf stehen in [BACKUP_RESTORE.md](BACKUP_RESTORE.md). Ein automatischer Umzug bestehender SQLite-Daten nach PostgreSQL ist noch nicht implementiert; bestehende `.env`-Dateien mit SQLite-URL bleiben deshalb unverändert auf SQLite und können weiter betrieben werden.

## Status und Einschränkungen

Siehe [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md), [ARCHITECTURE.md](ARCHITECTURE.md) und [BACKUP_RESTORE.md](BACKUP_RESTORE.md). Noch fehlen allgemeine Datei- und Dokumentanhänge, kontrollierte Mehrbenutzerfreigaben, Kalenderintegrationen, externe Benachrichtigungskanäle und ein automatischer Umzug bestehender SQLite-Daten nach PostgreSQL. Profilbilder für Personen werden unterstützt und im persistenten Datenvolume gespeichert. Personen- und Tagesbriefings zeigen belegte gespeicherte Einträge samt Quellkennungen. Der Scheduler plant Aufgaben- und Terminerinnerungen sowie jährlich eine Geburtstags-Wiedervorlage sieben Tage vor dem Geburtstag; externe Zustellung ist nicht enthalten.

## Termine und Erinnerungen

Termine lassen sich über `POST /api/events` mit Startzeit, optionalem Ende, Ort, Teilnehmern und Quellerinnerung speichern. `GET /api/events` unterstützt `from_at`, `to_at` und `person_id`. Der unabhängige Scheduler reiht Erinnerungsplanungen in Redis ein; der `worker`-Dienst verarbeitet persistente Jobs mit Wiederholungen. `GET /api/notifications` liefert fällige Einträge; `PATCH /api/reminders/{id}` schließt sie ab, pausiert sie oder verschiebt sie mit `snoozed_until`. Beim Erledigen einer Aufgabe wird ihre geplante Erinnerung ebenfalls abgeschlossen. Die UI bietet Termin-Erfassung und Aktionen zum Verschieben um eine Stunde oder Abschließen.

## Ereignisarchiv

Vergangene Treffen und Erlebnisse werden getrennt von zukünftigen Terminen als `record_type="experience"` gespeichert. Bestätigst du im Chat ein datiertes Gespräch, entsteht zusätzlich zum Gespräch ein Eintrag im Ereignisarchiv. Unter `/events` kannst du Ereignisse in einem Monatskalender auswählen, Kontext und Zeitpunkt bearbeiten, mehrere Teilnehmende über ihre Profilkarten öffnen sowie Ort, Adresse und mehrere Bilder ergänzen. Das Original der Schnellerfassung bleibt im Ereignisdetail aufklappbar erhalten. Ereignisfotos sind auf JPEG-, PNG- und WebP-Uploads bis 8 MB und 40 Megapixel begrenzt, serverseitig normalisiert und nur nach Besitzerprüfung abrufbar. Bilder liegen im persistenten `data`-Volume.

Der Scheduler reiht minütlich eine Planung in RQ ein. Der Worker verarbeitet sie mit bis zu drei Wiederholungen nach 15, 60 und 180 Sekunden; eine zeitlich begrenzte Sperre und idempotente Datenbankoperation verhindern doppelte Planungsläufe. Redis-AOF und Volume erhalten Jobs bei Containerneustarts. Bei Redis-Ausfall bleiben API und gespeicherte Erinnerungen verfügbar; der Scheduler versucht den nächsten Zyklus erneut. Erinnerungen werden aktuell einmalig erzeugt; externe Zustellung ist nicht enthalten.

## Tagebuch

Unter `/journal` kannst du freie Einträge chronologisch erfassen, nach Text und Zeitraum filtern und nachträglich bearbeiten oder löschen. Jeder Eintrag hat ein eigenes Kalenderdatum, unabhängig vom Erfassungszeitpunkt, und kann optional mit mehreren Personen, Projekten und Ereignissen verbunden werden. Eine Stimmung ist eine freiwillige Selbstauswahl; LifePilot leitet sie nicht aus dem Text ab. Die REST-API verwendet `GET`, `POST`, `GET /{id}`, `PATCH /{id}` und `DELETE /{id}` unter `/api/journal`.

## Dokumente und Dateianhänge

Personenprofile, Ereignisdetails und Projekte unterstützen private Dateianhänge bis 20 MB. Erinnerungen/Notizen und Gespräche können ebenfalls Dateien tragen. Unterstützt werden PDF, Text/Markdown/CSV, JPEG/PNG/WebP und gängige OpenDocument-/Office-Dateien. Dateien werden unter `DATA_DIR/attachments/<Benutzer-ID>` mit zufälligen Speichernamen abgelegt; Downloads erfordern Anmeldung und eine passende Besitzer- und Ressourcenprüfung und werden als Dateianhang mit `nosniff` ausgeliefert. `DATA_DIR` muss wie Profil- und Ereignisbilder im persistenten Volume liegen und in Backups enthalten sein. Bei Löschung des zugehörigen Eintrags werden Anhangsdatensätze und Dateien entfernt.

## Personen und Beziehungen

Die Menschenansicht enthält responsive Profilkarten mit Foto, Alter und Geschlecht, Suche, Filtern nach Geburtstag, Foto oder Organisation sowie Sortierung nach Name, Alter, nächstem Geburtstag oder Erfassungszeit. Ein Profil lässt sich über die Karte öffnen. Profilbilder können auch für das eigene Profil hochgeladen werden; der Server prüft und normalisiert JPEG-, PNG- und WebP-Bilder und liefert sie nur nach Besitzerprüfung aus. Beziehungen erscheinen als anklickbare Profilkarten, gruppiert in Familie, Freunde, Arbeitskollegen und weitere Beziehungen. Ihre Entfernen-Schaltfläche steht separat oben rechts auf der Karte.

Vereine und andere Organisationen lassen sich als eigene Einträge verwalten. In jedem Personenprofil können Mitgliedschaften mit optionaler Funktion angelegt werden; so kann auch das eigene Benutzerprofil etwa mit einem Verein verknüpft werden. Die Mitgliedskarten zeigen die Profile weiterer Mitglieder. Geschlecht kann je Personenprofil angegeben werden; neutrale manuelle Beziehungstypen werden automatisch als Mutter/Vater, Tochter/Sohn, Ehefrau/Ehemann, Schwester/Bruder oder Kollegin/Kollege angezeigt. Explizite Bezeichnungen wie „Tochter von“ oder „Frau von“ können ein noch leeres Geschlechtsfeld ergänzen. Eine KI-Vermutung allein aus einem Vornamen wird im Chat sichtbar markiert und erst nach ausdrücklicher Bestätigung gespeichert. Diese Daten werden durch Migrationen `0019_people_photos_organizations` und `0020_person_gender` ergänzt; Fotos liegen im persistenten Datenvolume.

Profile enthalten außerdem Spitzname, Geburtstag, E-Mail, Telefon, Adresse, Webseite, Beruf, Organisation und Notizen. Monica-ähnliche Kontaktpflege umfasst zusätzlich Favoriten, frei vergebbare Labels, das Feld „Wie kennengelernt“ und beliebig viele beschriftete zusätzliche Kontaktwege wie Arbeits-E-Mail, Mobiltelefon, Messenger oder weitere Adressen. Diese Angaben sind im Profil bearbeitbar, durchsuchbar und über REST sowie MCP verfügbar. Beziehungen werden aus einer Auswahl angelegt, die Ausgangs- und Gegenrichtung festlegt, zum Beispiel „Tochter von / Vater von“. Beide Perspektiven werden angezeigt und doppelte Gegenkanten verhindert. Das persönliche Benutzerprofil ist über die Schaltfläche neben dem Datum erreichbar. Die Änderungen werden über `/api/profile`, `/api/people`, `/api/relationships` und `/api/organizations` persistiert.

## Tierprofile

Unter `/pets` speicherst du Tiere unabhängig von Personenprofilen mit Name, Tierart, Rasse, Geschlecht, Geburtstag, Kastrationsstatus und Notizen. Verknüpfe Menschen als Besitzer:innen, Betreuende oder Personen im gemeinsamen Haushalt und verbinde das Tier mit Ereignissen. Die Suche durchsucht Namen, Tierart, Rasse und Notizen. Änderungen und Löschungen sind über die Weboberfläche, REST (`/api/pets`) und MCP verfügbar. MCP-Werkzeuge sind `pet_create`, `pet_search`, `pet_get`, `pet_update` und `pet_delete`; Löschungen erfordern dieselbe separate Freigabe wie andere kritische MCP-Operationen. Alle Datensätze und Verknüpfungen sind auf den jeweiligen Benutzer begrenzt. Tierfotos und Import sind noch nicht enthalten.

## Administration

Administratorrollen und App-Updates über Portainer sind in [docs/ADMINISTRATION.md](docs/ADMINISTRATION.md) beschrieben.

## Verpflichtungen und Arbeitsstände

Unter `/commitments` werden eigene Versprechen und ausstehende Rückmeldungen getrennt angezeigt. Optional sind Person, Projekt, Gesprächsquelle und Fälligkeit verknüpfbar; abgeschlossene oder abgebrochene Einträge können erneut geöffnet werden. Arbeitsstände speichern Fortschritt, Blockade, nächsten Schritt, Ressourcen sowie optionale Aufgaben- und Projektzuordnung. Sie lassen sich archivieren und wiederherstellen.

REST: `GET/POST /api/commitments`, `PUT /api/commitments/{id}`, `PATCH /api/commitments/{id}/status`, `GET/POST /api/checkpoints`, `GET/PUT /api/checkpoints/{id}`, `PATCH /api/checkpoints/{id}/archive`. Listen unterstützen limit und offset. Fälligkeiten benötigen eine Zeitzone. MCP: commitment_create, commitment_list, commitment_set_status, waiting_for_list, work_checkpoint_save, work_checkpoint_list, work_checkpoint_resume. Schreibzugriffe erfordern memory:write. Die neue Migration 0033_commitments_checkpoints muss vor dem produktiven Start angewendet werden. Automatische Erkennung aus Capture, Push-Erinnerungen und Briefing-Integration sind noch nicht Bestandteil dieses Moduls.

## Intelligente Aufgabenplanung

Auf Übersicht und Planung können bestehende Aufgaben mit geschätzter Dauer, mentalem Aufwand, Einstiegshürde, Kontext und nächstem Schritt ergänzt werden. Die regelbasierte Empfehlung filtert offene Aufgaben nach verfügbarer Zeit, Energie und Kontext und sortiert passende Einträge nach Dringlichkeit und Einstiegshürde. Aufgaben ohne ausreichende Angaben werden separat ausgewiesen. REST: PATCH /api/tasks/{id}/planning und GET /api/planning/next-actions (minutes, energy, context). MCP: task_planning_update und next_best_action. Migration 0034_task_planning erweitert die Aufgaben um fünf optionale Felder. Wiederkehrende Aufgaben übernehmen die Planung bei der nächsten Wiederholung. Tagesbriefing und Personenbriefing enthalten offene Verpflichtungen; das Tagesbriefing zeigt zusätzlich aktive Arbeitsstände. Automatische Extraktion von Verpflichtungen aus Capture ist noch nicht enthalten.

## Fokusmodus

Auf Übersicht und Planung kann eine offene Aufgabe für einen Zeitblock von 1 bis 180 Minuten fokussiert werden. Pro Konto gibt es eine aktive Sitzung; Beginn und Ende werden serverseitig gespeichert. Der Countdown bleibt nach einem Seitenwechsel erhalten. Eine unterbrochene Sitzung kann atomar einen Arbeitsstand mit nächstem Schritt, Fortschritt, Blockade und Ressourcen erstellen. Beendete Sitzungen speichern die verstrichene Zeit (Wanduhrzeit zwischen Start und Ende, keine Aktivitätsüberwachung); ein Fokusende schließt die Aufgabe nicht automatisch ab. Die letzten Sitzungen sind in der Oberfläche sichtbar.

REST: GET /api/focus/active, POST /api/focus/start, POST /api/focus/{id}/end, GET /api/focus/history. MCP: focus_start, focus_active, focus_end, focus_history. Migration 0035_focus_sessions ergänzt die Tabelle und einen partiellen eindeutigen Index für eine aktive Sitzung pro Konto. Ein abgelaufener Countdown beendet die Sitzung nicht automatisch.

## Aufgabenzerlegung

Im Aufgabenplanungsbereich kann eine Aufgabe in geordnete, einzeln abhakbare Schritte mit optionaler Zeitschätzung zerlegt werden. Schritte können manuell angelegt oder durch das konfigurierte Sprachmodell vorgeschlagen werden. KI-Vorschläge werden zunächst nur angezeigt und können bearbeitet oder verworfen werden; gespeichert wird erst nach ausdrücklicher Übernahme. Die Liste bleibt unabhängig vom Abschluss der Hauptaufgabe erhalten. MCP: task_steps_list, task_steps_draft, task_steps_add (confirm=true nach Freigabe), task_step_set_state. REST: GET/POST /api/tasks/{id}/steps, POST /api/tasks/{id}/steps/draft, PATCH /api/tasks/{id}/steps/{step_id}. Migration 0036_task_steps legt die neue Tabelle an. Die KI-Vorschau verwendet den bestehenden LLM-Anbieter.

## Verpflichtungen aus Schnellerfassung und Chat

Das konfigurierte Sprachmodell kann ausdrückliche, noch offene Zusagen in neuen Erfassungen als Verpflichtung vorschlagen (eigenes Versprechen oder erwartete Rückmeldung). Ein wörtlicher Beleg aus der aktuellen Erfassung, eine Richtung und eine zugeordnete Person sind erforderlich. Die Vorschläge erscheinen zur Prüfung im Chat und Eingang; erst nach ausdrücklicher Bestätigung werden sie gespeichert. Originalzitat und Verweis auf die Erfassung werden in der Verpflichtung gespeichert und angezeigt. Fälligkeiten ohne konkreten Zeitpunkt bleiben als Text erhalten; ein genauer Zeitpunkt benötigt eine Zeitzone. Die Migration 0037_commitment_capture ergänzt die Herkunftsfelder. Die vorhandene MCP-Funktion memory_review unterstützt die neue Vorschlagsart. Identische offene Zusagen werden bei der KI-Verarbeitung nach Möglichkeit erkannt.

## Virtueller Arbeitsbegleiter (Body Doubling)

Beim Start einer Fokussitzung kann optional ein persönliches Ziel und ein Check-in-Intervall von 2 bis 60 Minuten gewählt werden. Die Oberfläche erinnert bei geöffneter Fokusansicht an freiwillige Check-ins. Du kannst melden, dass du dran bist, abgelenkt bist oder blockiert bist, den Check-in überspringen und bei Bedarf einen nächsten Schritt und eine Notiz festhalten. Check-ins bleiben auf dem Server gespeichert und die nächste Erinnerung wird nach einem Neuladen rekonstruiert. Bei einer Blockade kann das Unterbrechungsformular mit Notiz und nächstem Schritt vorbelegt werden. Der Begleiter verwendet regelbasierte Hinweise und vorhandene Aufgabenschritte, keine Überwachung, keine KI und keine Push-Nachrichten im Hintergrund.

REST: GET /api/focus/{id}/companion, POST /api/focus/{id}/checkins (request_id als UUID für wiederholbare Anfragen). MCP: focus_companion, focus_checkin; focus_start unterstützt companion_interval_minutes und companion_goal. Migration 0038_focus_companion ergänzt die Sitzungsfelder und die Check-in-Tabelle.

## Persönliche Routinen

Auf Dashboard und Planung können Routinen mit Wochentagen (0 = Montag bis 6 = Sonntag), optionalem lokalem Zeitfenster und geordneten Schritten erstellt werden. Die tägliche Checkliste orientiert sich an der Kontenzeitzone; erledigte Schritte werden pro lokalem Datum gespeichert und können am selben Tag wieder geöffnet werden. Zeitfenster sind Hinweise und blockieren keine verspätete Erledigung. Routinen und einzelne Schritte lassen sich archivieren und wiederherstellen, ohne ihre bisherigen Erledigungen zu löschen. Ein Verlauf zeigt Erledigungen der letzten 30 Tage (API bis 90 Tage). Das Tagesbriefing enthält die heutigen Routinen. Zeitfenster über Mitternacht, rückwirkende Erledigungen, automatische Benachrichtigungen und freie Neusortierung bestehender Schritte werden noch nicht unterstützt.

REST: GET/POST /api/routines, PUT /api/routines/{id}, PATCH /api/routines/{id}/archive, POST /api/routines/{id}/steps, PATCH /api/routines/{id}/steps/{step_id}/archive bzw. /completion, GET /api/routines/{id}/history. MCP: routine_list, routine_create, routine_update, routine_archive, routine_step_add, routine_step_archive, routine_step_complete, routine_history. Migration 0039_routines legt die drei Tabellen an.

## Spracheingabe (Whisper-kompatibel)

Chat, Schnellerfassung und Schnellerfassungsdialog unterstützen Mikrofonaufnahme (maximal 5 Minuten) oder Audiodatei-Upload (maximal 10 MiB). Die Aufnahme kann vor dem Senden angehört werden. Nach Klick auf „Transkribieren“ sendet die API das Audio an einen separat konfigurierten OpenAI-kompatiblen Sprachdienst mit POST /audio/transcriptions. Der Text bleibt zunächst eine editierbare Vorschau; erst „Text zur Eingabe hinzufügen“ übernimmt ihn in die Texteingabe und das normale Absenden erzeugt eine Erfassung bzw. Frage. Es wird keine Audiodatei in der LifePilot-Datenbank oder im Datenverzeichnis gespeichert. Der externe Sprachdienst kann eigene Speicher- und Protokollierungsregeln haben; für private Daten empfiehlt sich ein eigener vertrauenswürdiger Dienst.

Konfiguration in .env oder Portainer:
- TRANSCRIPTION_BASE_URL: Basis-URL inklusive API-Präfix, z. B. http://whisper:8000/v1 (der Dienst muss vom API-Container erreichbar sein).
- TRANSCRIPTION_MODEL: Modellname, den der Dienst erwartet (Standard whisper-1).
- TRANSCRIPTION_API_KEY: optionaler Schlüssel des Sprachdienstes.
- TRANSCRIPTION_TIMEOUT_SECONDS: Provider-Timeout (Standard 90 Sekunden).

Die Compose-Dateien reichen diese Variablen an den API-Container weiter. Es wird kein Whisper-Dienst automatisch installiert. Ohne konfigurierte Basis-URL bleibt die Spracheingabe deaktiviert. Mikrofonaufnahme benötigt HTTPS oder localhost sowie Browserberechtigung; ein Datei-Upload ist auch ohne Mikrofon möglich. WebM/Opus, Ogg, MP4/M4A, WAV, MP3 und FLAC werden auf erkennbare Dateisignaturen geprüft; tatsächliche Dekodierung erfolgt durch den Sprachdienst. REST: GET /api/voice/status, POST /api/voice/transcribe (rohe Audiodaten mit passendem Content-Type, Bearer-Authentifizierung). Es gibt bewusst keinen direkten Audio-Upload über MCP; geprüfter Text kann über die vorhandenen Capture-Werkzeuge erfasst werden. Keine Datenbankmigration erforderlich.

## Offline-Schnellerfassung

Dashboard und Schnellerfassungsdialog speichern Textentwürfe automatisch lokal und legen bewusst abgesendete Gedanken zunächst in einer konten- und serverbezogenen Warteschlange ab (maximal 100 Einträge à 20.000 Zeichen). Sobald die Anwendung geöffnet und der Server erreichbar ist, werden sie automatisch übertragen. Eine fehlgeschlagene oder nicht eindeutig bestätigte Übertragung bleibt erhalten und kann erneut versucht werden. Der Server verwendet pro Konto eine eindeutige Client-ID und erhält den ursprünglichen Erfassungszeitpunkt für die spätere KI-Auswertung. Die Migration 0040_capture_idempotency ergänzt diese ID. Doppelte Übertragungsversuche werden erkannt, solange die ursprüngliche serverseitige Erfassung noch existiert.

Der Service Worker speichert eine eigenständige Offline-Seite (/offline.html) und deren statische Ressourcen. Nach einer vorherigen erfolgreichen Online-Anmeldung und Installation des Service Workers kann diese Seite auch bei fehlender Verbindung geöffnet werden. Es werden keine persönlichen Serverdaten im Service-Worker-Cache gespeichert. Die Offline-Seite erlaubt nur lokale Texterfassung und Synchronisierung mit einem erneut serverseitig bestätigten Konto. Ein abgelaufenes Token erfordert erneute Anmeldung; lokale Eingaben bleiben im jeweiligen Kontospeicher erhalten. Bei Abmeldung wird die lokale Identitätsmarkierung entfernt, die noch nicht übertragenen Texte bleiben für eine spätere Anmeldung desselben Kontos erhalten.

Wichtig: Entwürfe und wartende Erfassungen liegen unverschlüsselt im Browserspeicher (localStorage). Keine Verwendung auf gemeinsam genutzten oder ungeschützten Geräten; das Löschen von Websitedaten oder private Browserfenster können lokale Eingaben verlieren. Die Synchronisierung erfolgt bei geöffneter Anwendung bzw. Offline-Seite, nicht bei geschlossenem Browser. Chat-Fragen, Sprache-Transkription und weitere Module benötigen weiterhin eine Serververbindung. Der Erfassungsentwurf wird zwischen Tabs desselben Kontos geteilt; parallele Bearbeitung desselben Entwurfs kann die letzte Änderung überschreiben. Test der lokalen Speicherlogik: npm run test:offline im Web-Verzeichnis.

## iOS-Kurzbefehle, Siri und externe Texterfassung

Unter Einstellungen → iOS-Kurzbefehle & externe Erfassung lässt sich nach Eingabe des aktuellen Kontopassworts ein eigener Erfassungsschlüssel erstellen. Er wird nur bei der Erstellung angezeigt, ist einzeln widerrufbar, läuft nach 1–365 Tagen ab (Standard 90 Tage) und wird serverseitig ausschließlich als SHA-256-Hash eines zufälligen 256-Bit-Geheimnisses gespeichert. Ein Passwortwechsel macht ältere Schlüssel ungültig. Pro Konto sind höchstens 20 aktive Schlüssel möglich; pro Schlüssel sind 60 Erfassungsanfragen je Stundenfenster zulässig (auch Wiederholungen zählen).

Kurzbefehl manuell in der Apple-App „Kurzbefehle“ einrichten:

1. Neuen Kurzbefehl „LifePilot festhalten“ anlegen.
2. Texteingabe oder Diktat als Eingabe verwenden. Für das Teilen-Menü die Anzeige im Teilen-Menü aktivieren und den empfangenen Text nutzen.
3. Aktion zum Abrufen von URL-Inhalten mit der eigenen LifePilot-API-Adresse und Pfad /api/shortcuts/capture hinzufügen.
4. Methode POST, Header Authorization: Bearer DEIN_ERFASSUNGSSCHLÜSSEL, Request-Body JSON mit Feld original_text (Eingabe/Diktat). Für wiederholbare Übertragungen optional client_request_id (UUID) und captured_at (ISO-8601-Zeitstempel mit Zeitzone) senden. Bei Wiederholung dieselbe UUID verwenden.
5. Nur bei erfolgreicher Antwort den Text als gespeichert betrachten. Den Kurzbefehl per Namen über Siri ausführen.

Beispiel (Platzhalter ersetzen, Geheimnis nicht in die Shell-History schreiben):

```http
POST /api/shortcuts/capture
Authorization: Bearer DEIN_ERFASSUNGSSCHLÜSSEL
Content-Type: application/json

{"original_text":"Ich habe versprochen, die Unterlagen zu senden."}
```

Die Antwort enthält ausschließlich id und status "saved". Der Originaltext landet in der bestehenden Schnellerfassung und KI-Prüfung, auch bei nicht verfügbarer KI. Der Schlüssel hat keine Lese-, Änderungs-, Lösch-, Verwaltungs- oder MCP-Berechtigungen. Er gehört nicht in URLs, öffentliche Kurzbefehle, Git oder Logs. Verwende eine HTTPS-Verbindung. Die Integration setzt eine erreichbare LifePilot-API voraus; eine native Offline-Warteschlange in der Kurzbefehle-App und ein importierbarer Apple-Kurzbefehl sind nicht Bestandteil dieser Implementierung. Eine bereits autorisierte, laufende Anfrage kann trotz unmittelbar folgendem Widerruf noch abgeschlossen werden.

REST: GET/POST /api/shortcuts/keys (normale Benutzersitzung), DELETE /api/shortcuts/keys/{id}, POST /api/shortcuts/capture (nur Erfassungsschlüssel). Migration 0041_capture_keys.

## Web-Push-Benachrichtigungen

LifePilot kann für registrierte Browser/PWAs bei fälligen bestehenden Erinnerungen (Aufgaben, Termine, Geburtstage und Kontakt-Wiedervorlagen), fälligen offenen Verpflichtungen sowie aktuell laufenden Routinen mit noch offenen Schritten einen diskreten Push-Hinweis senden. Routinen ohne Zeitfenster werden nicht per Push erinnert. Es werden keine persönlichen Inhalte in Push-Nachrichten übertragen; beim Antippen wird LifePilot geöffnet. Die vorhandenen Ruhezeiten und Zeitzonen werden bei der serverseitigen Versandentscheidung berücksichtigt. Bereits versandte Nachrichten können noch verspätet zugestellt werden (TTL 60 Sekunden).

Einrichtung:
1. Nach dem Build im eigenen Terminal einmal ein VAPID-Schlüsselpaar erzeugen: `docker compose run --rm --no-deps api python -m lifepilot.push_keys`. Die Ausgabe enthält den privaten Schlüssel; nicht teilen oder committen.
2. `PUSH_VAPID_PRIVATE_KEY` (base64url-kodierter DER-Privatschlüssel auf P-256) und `PUSH_VAPID_SUBJECT` (eigene Kontaktadresse als mailto: oder HTTPS-URL) in .env bzw. Portainer hinterlegen. Beide Compose-Dateien geben diese Werte an API und push-worker weiter. Der öffentliche Schlüssel wird automatisch abgeleitet. Den privaten Schlüssel dauerhaft aufbewahren; bei Rotation müssen Geräte erneut angemeldet werden.
3. Stack aktualisieren. Der separate push-worker prüft fällige Hinweise ungefähr einmal pro Minute und verarbeitet bis zu 20 Geräte je Durchlauf. Ohne gültige VAPID-Konfiguration erfolgt kein Versand. Die Migration 0042_push_subscriptions ergänzt die Gerätetabelle.
4. In LifePilot unter Einstellungen → Push-Benachrichtigungen das jeweilige Gerät aktivieren. HTTPS, Service Worker und Benachrichtigungsberechtigung sind notwendig; unter iOS/iPadOS ab 16.4 muss die Web-App auf dem Home-Bildschirm installiert und von dort geöffnet werden. Unterstützte Push-Endpunkte sind auf bekannte HTTPS-Browseranbieter beschränkt; Weiterleitungen werden nicht verfolgt. Der Server muss diese Dienste erreichen können.

Pro Konto sind maximal zehn Geräte vorgesehen. Jeder Browser-Endpunkt ist genau einem Konto zugeordnet. Push-Anmeldungen können einzeln entfernt werden; ein Passwortwechsel macht alte Anmeldungen inaktiv. Abmelden alleine deaktiviert Push nicht. Der Versanddienst speichert pro Gerät die bereits gesendeten noch fälligen Vorkommen, bündelt neue Hinweise, berücksichtigt Snooze und wiederholt fehlgeschlagene Sendungen mit Backoff. Anbieterantworten 404/410 entfernen abgelaufene Abonnements. Die Übermittlung ist best-effort: nach einem Prozessabsturz zwischen Versand und Datenbank-Commit kann ein Hinweis wiederholt werden, und Provider/OS können Zustellung verzögern oder verwerfen. Es wird keine Änderung der Erinnerungszustände vorgenommen. Die Service-Worker-Nachricht enthält keine personenbezogenen Details.

REST: GET /api/push/status, GET/POST /api/push/devices, DELETE /api/push/devices/{id}. Anbieterkommunikation nutzt pywebpush; die automatisierten Backend-Tests simulieren deren Versand, kein realer Push wird während der Tests gesendet.

## CalDAV (lesender Kalenderzugriff)

Unter Einstellungen → CalDAV – Kalender können separat widerrufbare App-Passwörter mit 1–365 Tagen Gültigkeit erstellt werden. Die Konto-ID dient als DAV-Benutzername, das generierte App-Passwort als HTTP-Basic-Passwort. Geheimnisse werden nur bei der Erstellung angezeigt und serverseitig als SHA-256-Hash eines zufälligen 256-Bit-Geheimnisses gespeichert. Ein Passwortwechsel macht ältere DAV-Zugänge ungültig. Verwende HTTPS; teile keine Zugangsdaten oder exportierten Kalenderdateien.

Der Kalender enthält ausschließlich Termine (record_type=appointment) des authentifizierten Kontos mit Titel, Beschreibung, Ort und Beginn/Ende in UTC. Erlebnisse, Personenverknüpfungen, Aufgaben, Erinnerungen und sonstige Gedächtnisinhalte werden nicht exportiert. Kalender-Apps können exportierte Daten lokal zwischenspeichern; ein Widerruf löscht diese Kopien nicht.

Serverpfad: /dav/; Discovery: /.well-known/caldav; Kalenderpfad: /dav/calendars/{Konto-ID}/lifepilot/. Portainer-Traefik-Routing für diese Pfade wurde ergänzt. Bei anderen Reverse-Proxies müssen diese Pfade ebenfalls zum API-Container geleitet werden.

Unterstützt werden OPTIONS, PROPFIND (Depth 0/1), calendar-query (VEVENT und optionaler UTC-Zeitbereich), calendar-multiget, GET/HEAD einzelner iCalendar-Ressourcen, stabile UID und inhaltsbasierte ETags, If-None-Match sowie getctag. Schreibzugriffe werden abgewiesen. Es handelt sich um eine lesende Teilimplementierung von CalDAV, nicht um einen vollständigen DAV-Server: kein sync-collection, Scheduling, VTODO, Serienmodell, All-day-Modell oder bidirektionaler Abgleich. Maximal 2000 Ressourcen pro Abfrage; größere Abfragen müssen zeitlich eingeschränkt werden. Client-Kompatibilität (Apple Kalender, Thunderbird, DAVx5) muss separat praktisch getestet werden. LifePilot bleibt das führende System.

REST-Schlüsselverwaltung: GET/POST /api/dav/keys, DELETE /api/dav/keys/{id}. Migration 0043_dav_keys. Die automatisierten Tests prüfen Discovery, Zeitbereich, Multiget, ETags, iCalendar-Escaping, Mandantentrennung, Ablauf/Widerruf und die Ablehnung von Schreibzugriffen.

## CardDAV (lesendes Adressbuch)

Unter Einstellungen → CalDAV & CardDAV kann für das Adressbuch ein separater App-Zugang (scope contacts:read) erstellt werden. Bestehende Kalenderzugänge behalten ihren bisherigen scope calendar:read. Ein Schlüssel darf nur den jeweils ausgewählten Dienst nutzen. Keine neue Datenbankmigration notwendig: Die vorhandene Tabelle dav_keys unterstützt beide Scopes. Ablauf, Widerruf, Kontopasswortwechsel und einmalige Geheimnisanzeige funktionieren analog zu CalDAV.

Serverpfad: /carddav/; Discovery: /.well-known/carddav; Adressbuchpfad: /carddav/addressbooks/{Konto-ID}/lifepilot/. Portainer-Traefik-Routing ergänzt. Konto-ID als Benutzername, generiertes App-Passwort als Passwort. Ausschließlich über HTTPS nutzen.

Exportiert werden Namen, Spitznamen, E-Mail, Telefonnummern, Adressen, Websites, exakte Geburtstage und direkt gepflegte Berufs-/Organisationsfelder als vCard 3.0. Zusätzliche Kontaktmethoden der Typen email, phone, address und website werden einbezogen und identische Werte dedupliziert. Adressen bleiben unstrukturiert im Straßenfeld. Das eigene Profil, private Notizen, Tags, Beziehungen, Fotos, Social-/Messaging-Konten, Organisationsmitgliedschaften, Kontaktverläufe, ungefähre Geburtstage und Altersangaben werden nicht exportiert. Externe Adressbücher können die freigegebenen Kontaktdaten lokal speichern; ein Widerruf löscht diese Kopien nicht.

Unterstützt: OPTIONS, PROPFIND Depth 0/1, addressbook-query (einfache Eigenschafts-/Textfilter), addressbook-multiget, GET/HEAD einzelner vCards, stabile UID, inhaltsbasierte ETags, If-None-Match und getctag. Schreibzugriffe werden abgewiesen. Es handelt sich um eine lesende Teilimplementierung, ohne inkrementellen Sync-Report, Teilprojektion, Query-Limits, Parameterfilter, vCard 4.0 oder bidirektionale Synchronisierung. Maximal 2000 Kontakte pro Abfrage. Reale CardDAV-Clients müssen separat getestet werden. Die vorhandene REST-Schlüsselverwaltung /api/dav/keys akzeptiert nun optional scope (calendar:read oder contacts:read), ohne Angabe bleibt calendar:read der Standard.

## E-Mail-Integration (manueller IMAPS-Import)

In .env oder Portainer `IMAP_HOST` auf den eigenen vertrauenswürdigen IMAP-Server setzen und `IMAP_PORT` (Standard 993) konfigurieren. Der API-Container muss den Server erreichen und dessen TLS-Zertifikat validieren können. Leere Host-Konfiguration deaktiviert das Modul. Benutzer können keinen beliebigen Zielhost vorgeben. Kein SMTP-Versand, keine Mailcow-Administrationsberechtigung erforderlich.

Unter Einstellungen → E-Mail – IMAP-Import mit dem Postfach-Benutzernamen und Passwort (möglichst App-Passwort) anmelden. Die Zugangsdaten verbleiben während der Nutzung im Formularzustand und werden bei jeder Anfrage über HTTPS übertragen, aber nicht dauerhaft in LifePilot gespeichert. Die Vorschau zeigt die letzten 20 Nachrichten im INBOX-Ordner und mögliche Personen anhand exakter, nicht verifizierter Absender-E-Mail-Adressen. Es werden ausschließlich lesende IMAP-Operationen (SELECT readonly und BODY.PEEK) verwendet. Nach Auswahl und Kontrolle der Textvorschau kann eine einzelne E-Mail ausdrücklich zur bestehenden KI-Prüfung übernommen werden. Die Vorschläge erfordern Bestätigung; Absender-Aussagen werden nicht als Aussagen des Kontoinhabers behandelt, ausgehende Versprechen und automatisierte Familien-/Beziehungsheuristiken werden für importierte E-Mails ausgeschlossen.

Eine UIDVALIDITY-/UID-basierte Erfassungs-ID verhindert identische Mehrfachimporte pro LifePilot-Konto, solange der ursprüngliche Capture existiert. Der Inhalt wird vor dem Import erneut abgerufen und mit dem Vorschau-Hash verglichen. Der Originaltext enthält Absender, Empfänger, Betreff und das Nachrichtendatum (unverifizierte Headerangaben). Personen-/Projektzuordnung erfolgt bei der nachfolgenden Vorschlagsprüfung. Der ausgewählte Text kann an den konfigurierten KI-Anbieter gesendet werden. Keine automatische Postfachüberwachung, kein Massenimport, keine weiteren Ordner, keine HTML-only-Nachrichten, keine Anhänge oder externen Ressourcen. Maximal 256 KiB pro E-Mail und 16.000 Zeichen Nachrichtentext. Keine Datenbankmigration erforderlich.

REST: GET /api/mail/status, POST /api/mail/messages, POST /api/mail/preview, POST /api/mail/import. Die Tests verwenden einen simulierten IMAP-Server; reale Mailserver-Kompatibilität und TLS-Verbindung müssen nach der Konfiguration geprüft werden.

## Home Assistant (REST-Sensor und gezielte Erfassung)

Unter Einstellungen → Kurzbefehle & Home Assistant einen eigenen Integrationsschlüssel mit der Berechtigung „Home Assistant – Status lesen“ erstellen. Für die Ereigniserfassung separat einen Schlüssel „Externe Erfassung“ anlegen. Beide Schlüssel werden nur einmal angezeigt und bleiben einzeln widerrufbar. Bestehende Kurzbefehle funktionieren nach der Migration 0044_integration_key_scope unverändert weiter; sie behalten den Scope capture:write. Der neue Scope ha:status ist ausschließlich für GET /api/home-assistant/status gültig. Maximal 20 aktive Integrationsschlüssel insgesamt, 120 Statusanfragen bzw. 60 Erfassungsanfragen pro Schlüssel und Stundenfenster. Beim Passwortwechsel werden alle Schlüssel ungültig. Ein Downgrade der Migration entfernt Statusschlüssel.

Der Status enthält ausschließlich:
- notification_pending: mindestens ein fälliger Hinweis außerhalb der Ruhezeit.
- quiet_hours: persönliche Ruhezeit aktiv.
- due_reminders, due_commitments, due_routines: Anzahl aktuell fälliger Erinnerungen, Verpflichtungen und zeitgebundener Routinen (auch während Ruhezeiten).
- routine_steps_open: offene Schritte aller heute vorgesehenen Routinen.
- focus_active: eine Fokussitzung läuft (auch nach Ablauf der geplanten Zeit bis zum manuellen Ende).

Keine Namen, Titel, Texte, Orte, Ressourcen-IDs oder Kontaktdaten. Statuswerte können dennoch Rückschlüsse auf die persönliche Aktivität erlauben und sollten nicht an unbefugte Personen weitergegeben werden. Kein direkter Zugriff auf Home Assistant, keine Gerätebefehle, keine automatische Anwesenheitsüberwachung. LifePilot verwaltet den Status; Home Assistant fragt ihn ab. Die Integration funktioniert unabhängig von der VAPID-Konfiguration.

Beispiel für Home Assistant: eigene API-Adresse und die beiden tatsächlichen Schlüssel lokal in secrets.yaml hinterlegen (Bearer-Präfix gehört zum Secret):

```yaml
lifepilot_status_url: "https://lifepilot.example.org/api/home-assistant/status"
lifepilot_capture_url: "https://lifepilot.example.org/api/shortcuts/capture"
lifepilot_status_authorization: "Bearer DEIN_STATUSSCHLUESSEL"
lifepilot_capture_authorization: "Bearer DEIN_ERFASSUNGSSCHLUESSEL"
```

In configuration.yaml vorhandene rest: und rest_command: Abschnitte ergänzen, nicht doppelt definieren:

```yaml
rest:
  - resource: !secret lifepilot_status_url
    headers:
      Authorization: !secret lifepilot_status_authorization
    scan_interval: 60
    timeout: 10
    binary_sensor:
      - name: LifePilot Erinnerung
        unique_id: lifepilot_notification_pending
        value_template: "{{ value_json.notification_pending }}"
        json_attributes:
          - quiet_hours
          - due_reminders
          - due_commitments
          - due_routines
          - routine_steps_open
          - focus_active

rest_command:
  lifepilot_capture:
    url: !secret lifepilot_capture_url
    method: POST
    headers:
      Authorization: !secret lifepilot_capture_authorization
    content_type: "application/json"
    payload: "{{ {'original_text': message} | to_json }}"
    timeout: 15
```

Beispiel für eine eigene Automation (in automations.yaml; Entitäts-ID und notify-Dienst an die eigene Installation anpassen):

```yaml
- alias: LifePilot Erinnerung anzeigen
  triggers:
    - trigger: state
      entity_id: binary_sensor.lifepilot_erinnerung
      from: "off"
      to: "on"
  actions:
    - action: notify.mobile_app_mein_telefon
      data:
        title: LifePilot
        message: Du hast offene Erinnerungen.
  mode: single
```

Diese Automation meldet nur den Übergang von off zu on, nicht jeden weiteren Hinweis bei bereits aktivem Sensor. Ein bewusst ausgewähltes Ereignis kann über die Aktion rest_command.lifepilot_capture mit data.message als Text erfasst werden; die bestehende KI-Prüfung entscheidet erst nach Benutzerfreigabe über die Übernahme in das Gedächtnis. Optional kann ein eigener REST-Aufruf eine UUID als client_request_id für idempotente Wiederholungen übergeben. Keine automatische Weitergabe aller Sensorzustände. Verwende HTTPS und beschränke die Schlüssel auf vertrauenswürdige Installationen.

Die REST-Schnittstelle ist implementiert und automatisiert getestet. Die YAML-Beispiele sind eine manuell zu konfigurierende Integration, keine native Home-Assistant-/HACS-Komponente; sie wurden noch nicht an einer laufenden Home-Assistant-Instanz validiert.

## Zeitliche Fakten

Im Gedächtnis und im Verlauf eines Personenprofils können zeitabhängige Aussagen als eigene Fakten erfasst werden. Jeder Fakt enthält eine Person als Subjekt (auch das eigene Profil ist möglich), eine frei benannte, normalisierte Eigenschaft, einen Textwert, optionale Datumsgrenzen, eine Vertrauenseinschätzung (low/medium/high), Prüfstatus (proposed/confirmed/rejected) und Quellenbeschreibung. Optional sind eine eigene Originalerfassung und ein wörtlich darin belegtes Zitat verknüpfbar. Das Zitat wird beim Speichern auf exaktes Vorkommen geprüft; seine semantische Aussage und der angegebene Zeitraum müssen weiterhin vom Benutzer geprüft werden.

Neue Fakten beginnen immer als proposed. Bestätigen und Verwerfen sind separate Aktionen. Änderungen einer bestätigten Aussage können durch ausdrückliches Beenden ihres Zeitraums und Anlegen eines neuen Fakts dokumentiert werden. Ein bereits gesetztes Enddatum wird nicht überschrieben; bei einer fehlerhaften Aussage den Fakt verwerfen und einen korrigierten anlegen. Frühere Fakten bleiben abrufbar. Die Zeitgrenzen sind Kalendertage, Beginn inklusive und Ende exklusiv; fehlt eine Grenze, ist sie unbekannt bzw. offen. Stichtagsfilter liefern mögliche Treffer, keine Garantie der tatsächlichen Gültigkeit. Gleichzeitig gültige Werte sind erlaubt (z. B. mehrere Hobbys). Widerspruchserkennung folgt separat. Bestehende Profilfelder und historische Spezialmodelle werden nicht automatisch übernommen oder verändert. Das Personenbriefing liefert bis zu 50 bestätigte mögliche aktuelle Fakten unter current_fact_candidates.

REST: GET /api/facts (Filter person_id, predicate, status, as_of; limit/offset), POST /api/facts, PATCH /api/facts/{id}/status, PATCH /api/facts/{id}/end. MCP: temporal_fact_list, temporal_fact_propose, temporal_fact_review, temporal_fact_end. MCP-Statusänderungen und Beenden benötigen explizites confirm=true; alle Schreiboperationen erfordern memory:write. Migration 0045_temporal_facts. Der erste Funktionsumfang ist auf Personen und Textwerte begrenzt; keine automatische KI-Extraktion, typisierten Objektverknüpfungen, ungefähren Datumsmodelle, vollständige Änderungsversionen oder allgemeine Chat-/Suchindexintegration. Löschen einer Person entfernt zugehörige Fakten; Löschen der Quellerfassung trennt die Referenz, das gespeicherte Zitat bleibt erhalten.

## Mögliche Faktenwidersprüche

Im Faktenbereich und in der Personenhistorie werden unterschiedliche Werte derselben normalisierten Eigenschaft bei derselben Person geprüft, wenn ihre Gültigkeitsintervalle möglicherweise überlappen. Das Verfahren ist regelbasiert und bewusst auf ausgewählte veränderliche Zustandsfelder beschränkt (Wohnort, Hauptwohnsitz, Arbeitgeber, Arbeitsstelle, Beruf, Beziehungsstatus, Familienstand und ausgewählte englische Entsprechungen). Andere Eigenschaften, insbesondere Hobbys und Interessen, sind nicht automatisch widersprüchlich. Groß-/Kleinschreibung, Unicode-NFC und zusätzliche Leerzeichen werden beim Wertevergleich normalisiert; Synonyme oder inhaltliche Widersprüche in Freitext werden nicht erkannt. Fehlende Datumsgrenzen führen zu einem möglichen, nicht bewiesenen Konflikt. Abgelehnte Fakten und nicht überlappende Intervalle werden ausgeschlossen. Bereits vorhandene Fakten werden durch Migration 0046_fact_conflicts berücksichtigt.

Die Prüfung zeigt beide Angaben, Quellen, Status, Vertrauen und Zeiträume nebeneinander. Der Benutzer kann beide bestätigen (die konkrete Paarung wird für die geprüften Revisionen ausgeblendet), eine Angabe verwerfen und die andere bestätigen, eine zeitliche Veränderung dokumentieren oder die Prüfung vertagen. Bei einer zeitlichen Veränderung muss der frühere Fakt ein offenes Ende haben und der nachfolgende ein bekanntes Beginndatum; das frühere Ende wird auf diesen Tag gesetzt (exklusiv), beide Fakten werden bestätigt. Bereits gesetzte Enddaten werden nicht überschrieben. Keine automatische Änderung oder Zusammenführung. Normales Bestätigen bleibt möglich; ungelöste Konflikte bleiben sichtbar. Jede Entscheidung einschließlich Vertagung wird mit Begründung und Vorher-/Nachher-Zustand gespeichert. Bei späteren Status- oder Zeitänderungen wird die Paarung neu geprüft. Die atomare Auflösung sperrt beide Fakten in fester Reihenfolge unter PostgreSQL und verlangt die aktuell angezeigten Versionswerte; veraltete Anfragen werden mit 409 abgewiesen.

REST: GET /api/facts/conflicts, POST /api/facts/conflicts/resolve, GET /api/facts/conflicts/history; Listen sind paginiert und optional nach Person gefiltert. MCP: temporal_fact_conflicts, temporal_fact_resolve (memory:write und confirm=true), temporal_fact_conflict_history. Das Personenbriefing enthält bis zu 20 offene Konflikte unter fact_conflicts. Die Erkennung ist auf das zeitliche Personenfaktenmodell beschränkt, nicht auf alte Profilfelder, Beziehungen, beliebige Notizen oder KI-Ausgaben. Entscheidungen werden bei Löschung der zugehörigen Person/Fakten ebenfalls gelöscht. Migration 0046_fact_conflicts ergänzt normalisierte Wertschlüssel, Revisionsnummern und die Entscheidungstabelle.

## Interaktiver Wissensgraph

Im Gedächtnis und in der Personenhistorie steht eine interaktive Graphansicht bereit. Als Ausgangspunkt eine Person auswählen; jeder sichtbare Knoten kann anschließend zum Mittelpunkt werden. Typfilter, direkte oder zweistufige Umgebung, Knotengrenze (30/60/100), Zoom und eine textuelle Knotenauswahl helfen beim Erkunden. Der ausgewählte Knoten zeigt seine im Ausschnitt sichtbaren gerichteten Verbindungen, gegebenenfalls Bestätigungsstatus und Gültigkeitsgrenzen. Personenprofile lassen sich direkt öffnen.

Der Graph ist eine lesende Projektion bestehender Daten, keine separate Wissensdatenbank. Er nutzt ausdrücklich gespeicherte Personenbeziehungen (auch zum eigenen Profil), Organisationsmitgliedschaften, Gesprächs- und Ereignisteilnahmen, Erinnerungs-, Aufgaben-, Verpflichtungs- und Projektverknüpfungen sowie zeitliche Personenfakten. Unbestätigte Beziehungen und vorgeschlagene Fakten sind standardmäßig ausgeblendet und optional sichtbar; verworfene Fakten bleiben ausgeschlossen. Historische Verbindungen werden nicht automatisch als aktuell bezeichnet. Der Graph erkennt keine neuen Beziehungen durch Namensähnlichkeit, Textanalyse oder KI. Faktwerte erscheinen als eigenständige Faktenknoten, nicht als automatisch zusammengeführte Orts- oder Organisationsobjekte.

REST: GET /api/graph?root_kind=person&root_id=ID&depth=1&limit=60 (wiederholbarer kinds-Filter, include_unconfirmed). MCP: knowledge_graph mit den gleichen Parametern. Zulässige Knotentypen: person, organization, conversation, project, event, memory, commitment, fact, task. Abfragen sind auf zwei Verbindungsschritte, 100 Knoten und höchstens drei Kanten pro erlaubtem Knoten begrenzt; bei Begrenzung wird truncated gesetzt. Der Ausschnitt enthält gefundene Verbindungen der durchlaufenen Knoten, nicht zwingend sämtliche Querverbindungen am äußeren Rand. Reihenfolge bei Begrenzung ist deterministisch, nicht nach semantischer Relevanz. Sowohl Verknüpfungsdatensätze als auch beide Endpunkte werden auf Kontozugehörigkeit geprüft. Vollständige Gesprächs-/Erinnerungstexte werden nicht geladen in die API-Antwort. Keine Datenbankmigration nötig. Weitere Modelle (z. B. Tagebuch, Haustiere, Leihgaben) und globale Vollansicht sind noch nicht Bestandteil dieser Projektion.

## Globale Lebenschronik

Im Gedächtnisbereich und im Verlauf des Personenprofils führt die Lebenschronik vorhandene Gespräche, Kalendertermine und Erlebnisse, Erinnerungen, Tagebuch, biografische Ereignisse, Telefonate, zeitliche Fakten und Leihgaben zusammen. Zeitliche Fakten erscheinen mit ihren bekannten Beginn- und exklusiven Enddaten als separate Einträge; Leihgaben erscheinen am gespeicherten Ausleih- und Rückgabedatum. Kalendertermine werden als solche gekennzeichnet, nicht als bestätigte Erlebnisse. Die Chronik umfasst das gesamte Konto einschließlich ausdrücklich verknüpfter Ereignisse anderer Personen, nicht ausschließlich die eigene Biografie.

Die Darstellung nutzt die Kontenzeitzone. Datierte Einträge sind absteigend sortiert, Datumsfilter beziehen sich auf lokale Kalendertage (beide Grenzen inklusive). Reine Datumsangaben werden ohne Uhrzeit dargestellt. Einträge ohne konkretes Datum und nur grob datierte Lebensereignisse stehen in einer gesonderten Ansicht; Erstellungsdaten werden nicht als Ereignisdaten verwendet. Die vorhandenen Datumspräzisionen werden angezeigt. Unbestätigte Lebensereignisse und vorgeschlagene Fakten sind standardmäßig ausgeblendet; verworfene Fakten werden nicht angezeigt. Personenzuordnungen folgen ausschließlich gespeicherten direkten Verweisen oder Teilnahmebeziehungen und prüfen die Kontozugehörigkeit beider Seiten. Es werden Titel, Art, Datum, Status, Quell-ID und eine begrenzte Auswahl verknüpfter Personennamen ausgegeben, keine vollständigen privaten Notiztexte.

REST: GET /api/timeline mit person_id, wiederholbarem kinds-Filter (conversation, event, memory, journal, life_event, call, fact, loan), start/end (ISO-Kalendertage), mode (dated oder undated), include_unconfirmed, limit (1–100), offset (0–2000). Antwort: items, next_offset, window_limited, timezone. MCP: life_timeline mit denselben Parametern. Bei größeren Ausschnitten Zeitraum/Typ eingrenzen. Offset-Paginierung kann bei gleichzeitigen Änderungen Verschiebungen verursachen; es gibt keine eingefrorene Momentaufnahme. Keine automatische Deduplizierung inhaltlich ähnlicher Datensätze aus unterschiedlichen Modulen. Keine neue Datenbankmigration. Noch nicht enthalten: Beziehungs-/Namenshistorie, Projektmeilensteine, Haustierchronik als eigener Typ und vollständige Detailnavigation aller Quellressourcen. Die Chronik ist lesend; Änderungen erfolgen in den jeweiligen Ursprungsmodulen.
