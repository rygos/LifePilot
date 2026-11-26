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
