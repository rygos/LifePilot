# LifePilot: Implementierungsplan

## Ausgangslage

Das GitHub-Repository war leer. Es gab keine vorhandene Anwendung oder Datenbank zu erhalten. Das lokale Umfeld stellt Podman Compose bereit; Docker wird über dessen Kompatibilitätsschicht angeboten.

## Priorisierte Arbeit

- [x] Grundsystem: FastAPI, SQLite/PostgreSQL-kompatible SQLAlchemy-Modelle, initiale Alembic-Migration, Benutzerkonten und mandantenbezogene Daten.
- [x] Kernfunktionen ohne KI: Personen, Beziehungen, Notizen/Erinnerungen, Aufgaben, Suche und deutsche Weboberfläche.
- [x] MCP-Server mit Streamable HTTP und authentifizierten, typisierten Werkzeugen; initiale Kernwerkzeuge per offiziellem Client geprüft.
- [x] Compose-Datei, Konfigurationsbeispiel, Betriebs- und Architekturhinweise.
- [x] Backend-Tests (3 bestanden), Next.js-Produktionsbuild, SQLite-Migration und Compose-Health/API-/MCP-Szenarien ausgeführt.
- [x] Erweiterung: 4 Backend-Tests bestanden, Migration `0002_phase1_domains` auf Test- und Compose-Datenbank aktiv, Web-Build und Compose-API-Aufrufe für Gespräche/Leihgaben/Geschenke geprüft.
- [x] Gespräche mit Teilnehmern und Ereigniszeit, Leihgaben mit Rückgabe und Geschenke mit Anlass/Quelle (REST, UI und Migration).
- [x] Termine mit Teilnehmern/Quellen, persistente Erinnerungen und unabhängiger Scheduler-Worker.
- [x] PostgreSQL 16 mit pgvector-Extension-Image, persistentem Compose-Volume, Healthcheck und SQLAlchemy-Treiber ergänzen; Alembic-Migration aktiviert pgvector nur unter PostgreSQL. PostgreSQL- und SQLite-Migrationen wurden erfolgreich ausgeführt.
- [x] Verbindung aus dem API-Container zum PostgreSQL-Dienst mit Passwortvariable und SQLAlchemy geprüft (`SELECT 1`); vorhandene Installationen mit SQLite-URL laufen weiter auf SQLite.
- [x] Redis 7 per Compose mit Healthcheck und persistentem AOF-Volume; Scheduler-Zyklen koordinieren und Hintergrundjobs über RQ mit begrenzten Wiederholungen verarbeiten.
- [x] Optionale LLM-Extraktion mit expliziter Prüfung, Quellenbezug und OpenAI-kompatibler API.
- [x] OpenAI-kompatible Embeddings für Erinnerungen, asynchrone RQ-Indizierung, HNSW/pgvector und hybride PostgreSQL-Suche; klassische Suche bleibt ohne Provider funktionsfähig.
- [x] Semantische Suche für Gespräche, Aufgaben, Beziehungen und Projekte einschließlich Volltext-Fallback.
- [x] Personen- und Tagesbriefings aus belegten Quellen.
- [x] Personen-/Tagesbriefings, installierbare PWA mit Offline-App-Shell und UI-Kernflüsse für Schnellerfassung, Personen und gerichtete Beziehungen.
- [x] MCP-Abdeckung für Profile, Personenmerge, Notizen, Faktenreview, Beziehungen, Gespräche, Aufgaben, Termine, Erinnerungen, Leihgaben, Geschenke, Projekte, Briefings und bestätigungspflichtige Löschungen.

## Initiales Datenmodell

Alle fachlichen Datensätze gehören einem Benutzer (`owner_id`) und jeder Repository-Zugriff wird auf diesen Besitzer eingeschränkt. `Person` enthält Identitäts- und Kontaktdaten. `Relationship` verbindet gerichtete Quell- und Zielpersonen, speichert Typ, Gültigkeitszeitraum, Quelle und Bestätigungsstatus. `Memory` speichert Originaltext, optionale Zusammenfassung, Ereigniszeit und Erfassungszeit getrennt. `Task` enthält Status, Priorität, Fälligkeit und optional eine Person. Benutzerpasswörter werden ausschließlich als Argon2-Hash persistiert. Fremdschlüssel, eindeutige IDs und Datenbanktransaktionen schützen die Integrität. Spätere Fakten- und Graphobjekte können dieselben Quellen- und Zeitfelder verwenden.

## Architekturentscheidungen

- FastAPI, Pydantic, SQLAlchemy 2 und Alembic bilden API, Validierung, Persistenz und Migrationen.
- SQLite ermöglicht sofortige lokale Nutzung und Tests; `DATABASE_URL` schaltet auf PostgreSQL um. Für semantische Suche wird PostgreSQL mit pgvector ergänzt.
- Ein Next.js-Frontend und FastAPI-Backend laufen getrennt in Compose. Der API-Service enthält zunächst den MCP-Transport, damit Autorisierung dieselbe Anwendungskonfiguration nutzt.
- Die optionale KI verarbeitet neue Schnellerfassungen zu prüfbaren Vorschlägen. Fakten werden erst nach ausdrücklicher Review-Aktion übernommen.

## Nächste Schritte

1. [x] Projekte (REST, UI, MCP) und explizite Benutzerfreigaben für kritische MCP-Löschungen ergänzt; danach verbleibende UI-, E2E- und Backup/Restore-Lücken schließen.
2. [x] Semantische Suche auf Gespräche, Aufgaben, Beziehungen und Projekte erweitern.
3. [x] Personen- und Tagesbriefings mit Quelldatensätzen, Zeitzonenbezug und MCP-Ausgabe ergänzen.
4. [x] E2E-, Datenschutz-, Backup/Restore- und Compose-Neustart-Szenarien automatisieren.

## Letzter Ausbauschritt

## Embeddings und hybride Gedächtnissuche

- [x] OpenAI-kompatibler Embedding-Adapter mit Modell-/URL-/Timeout-Konfiguration und Validierung von Vektoren mit 768 Dimensionen.
- [x] Erinnerungen werden nach REST-, MCP- und geprüfter Schnellerfassung asynchron über die bestehende Redis/RQ-Queue indiziert; Modell- und Inhaltshash vermeiden unnötige Neuindizierung.
- [x] Migration 0011_memory_embeddings speichert Vektoren und erzeugt auf PostgreSQL einen HNSW-Cosinusindex; SQLite bleibt für lokale Nutzung und Tests verfügbar.
- [x] PostgreSQL kombiniert Volltext-Ranking und Vektor-Ranking. Der Suchendpunkt ordnet lexikalische, Volltext- und semantische Treffer per Reciprocal Rank Fusion und bleibt bei Provider-Ausfall klassisch durchsuchbar.
- [x] Eine authentifizierte Reindex-Aktion im Dashboard plant vorhandene Erinnerungen ein. Tests prüfen semantische Treffer, Besitzertrennung, idempotente Indizierung und den Fallback bei Provider-Ausfall.
- [x] Migration `0012_entity_embeddings` speichert referentielle, benutzergebundene Embeddings für Gespräche, Aufgaben, Beziehungen und Projekte; Fremdschlüssel entfernen den Indexeintrag bei Ressourcendeletion.
- [x] Create- und Update-Pfade in REST, MCP und Projekt-/Beziehungsservices reihen semantische Neuindizierung ein. Die Reindex-Aktion nimmt jetzt alle fünf indizierten Ressourcentypen auf.
- [x] Hybride Suche rankt alle fünf indizierten Typen per Reciprocal Rank Fusion; PostgreSQL-Volltextsuche deckt zusätzliche Felder der vier neuen Typen ab, Beziehungen liefern beide Personennamen.
- [x] Backend-Tests prüfen semantische Treffer über alle vier zusätzlichen Typen, Besitzertrennung und das Entfernen eines Beziehungsindexes beim Löschen.

## Personen- und Tagesbriefings

- [x] Tagesbriefing liefert Datum und Zeitzone des Benutzers, offene Aufgaben, heutige Termine sowie anstehende und überfällige Wiedervorlagen mit verknüpften Quell-IDs.
- [x] Personenbriefing bündelt Gespräche, Erinnerungen, offene Aufgaben, Leihgaben, Geschenkideen, anstehende Termine und Beziehungen aus benutzergebundenen Daten.
- [x] Dashboard zeigt das Tagesbriefing; Personenprofile zeigen Kontext mit Datum und Kurzkennung der Originalquelle.
- [x] MCP-Werkzeuge `daily_briefing` und `person_context` geben die erweiterten Briefings zurück.
- [x] Backend-Tests decken Zeitzonen-/Tageszuordnung, Quellen und MCP-Antworten ab; Next.js-Produktionsbuild erfolgreich.

## Backup und Wiederherstellung

- [x] `scripts/backup.sh` erkennt PostgreSQL oder SQLite und erstellt ein Datenbankbackup, App-Datenarchiv, Manifest und Prüfsummen mit restriktiven Dateirechten.
- [x] `scripts/restore.sh` validiert Prüfsummen und Archivpfade und restauriert ausschließlich in neue Datenbank- und Dateisystemziele.
- [x] `BACKUP_RESTORE.md` dokumentiert den Linux-/Compose-Ablauf, Stagingprüfung, Umschaltung und Grenzen (SQLite, `.env`, Redis).
- [x] SQLite-Backup mit der laufenden Compose-Datenbank erstellt, in ein neues Staging-Verzeichnis restauriert und Tabelleninhalte abgeglichen.
- [x] PostgreSQL-Backup/Restore mit einem isolierten Compose-Projekt in eine neue Staging-Datenbank validiert; Migration `0012_entity_embeddings` und Bootstrap-Benutzer nach Restore geprüft.

## Datenschutz und Compose-Neustarts

- [x] REST-Integrationstests prüfen Besitzertrennung für Sammlungen, hybride Suche, Profil-/Projektbriefings sowie fremde IDs bei Lese- und Schreibzugriffen.
- [x] Compose-Dienste (PostgreSQL, Redis, Worker, Scheduler, API und Web) neu gestartet; API-/Web-Erreichbarkeit und stabiler Fingerprint der SQLite-Benutzer-, Personen- und Beziehungsdaten danach geprüft.
- [x] `scripts/test-postgres-restore.sh`, `scripts/verify-compose-restart.sh` und Playwright-E2E ergänzen reproduzierbare PostgreSQL-Restore-, Compose-Neustart- und Browserprüfungen.

- [x] Migration `0003_events_reminders`, 5 Backend-Tests einschließlich Scheduler-Deduplizierung und Aufgabenabschluss, In-App-Erinnerungen, Verschieben, Python-Kompilierung, Compose-Konfiguration und Next.js-Produktionsbuild geprüft.
- [x] Laufender Compose-Stack nach Migration mit API-Aufrufen für fällige Erinnerungen und deren Abschluss geprüft.
- [x] Browser-Smoke-Test für Menschen, Profile und Beziehungsansicht durchgeführt; vollständige Light/Dark- und Mobil/Desktop-Matrix bleibt ausstehend.
- [x] Redis-Sperre verhindert parallele Scheduler-Zyklen; Redis-Integrationstest mit zwei Clients und ein Worker-Container-Roundtrip gegen eine temporäre SQLite-Datenbank geprüft.

## Personenprofile und Beziehungen

- [x] Personenprofile um Adresse, Webseite, Beruf und Organisation erweitert; bestehende Felder für Spitzname, Geburtstag, E-Mail und Telefon in der Oberfläche sichtbar und bearbeitbar.
- [x] Beziehungsansicht mit Namen, Richtung und Beziehungstyp im jeweiligen Personenprofil sowie Hinzufügen und Entfernen.
- [x] Eigenes Benutzerprofil für Name, Spitzname, Geburtstag und Kontaktdaten.
- [x] Migration `0004_person_profiles` und Backend-Tests für Profil- und Beziehungsoperationen.
- [x] Browser-Interaktion für Profilwechsel, Beziehungserfassung und Formularreset geprüft; vollständige visuelle Matrix bleibt ausstehend.

## Beziehungstypen

- [x] Beziehungsformular speichert das Formular nach dem asynchronen Request zuverlässig zurück.
- [x] Beziehungskatalog speichert gerichteten Typ und Gegenrichtung; Profile zeigen beide Perspektiven mit Personennamen.
- [x] Doppelte Beziehungspaare werden erkannt und abgewiesen; Migration `0005_relationship_inverses` deckt vorhandene Beziehungen mit neutraler Gegenrichtung ab.
- [x] Browser-Test: „Tochter von“ speichert und zeigt „Vater von“, Formularwerte werden zurückgesetzt, Wechsel des Personenprofils lädt die passenden Felder.
- [x] Weitere Create-Formulare greifen nach asynchronem Speichern nicht mehr auf das geleerte Event-Target zu.

## Ruhezeiten, Wiederholungen und Terminänderungen

- [x] Benutzerprofil speichert IANA-Zeitzone und optionales Ruhezeitfenster; Ruhezeiten blenden fällige In-App-Benachrichtigungen aus.
- [x] Aufgaben können mit Tagesintervall und Enddatum wiederholt werden; Abschluss plant genau eine nächste Aufgabe samt Erinnerung.
- [x] Terminänderungen sind im Dashboard bearbeitbar, erhalten bei Bedarf die bisherige Dauer und aktualisieren die verknüpfte Erinnerung.
- [x] Browser-Formulare senden Fälligkeiten als UTC-Zeitpunkte; Task-, Event- und Reminder-Antworten kennzeichnen UTC auch nach Speicherung über SQLite.
- [x] Migration `0007_recurring_tasks_and_quiet_hours`, SQLite-Migrationslauf, 9 Backend-Tests mit aktivem Redis und Next.js-Produktionsbuild geprüft.
- [x] SQLite- und PostgreSQL-Migration bis `0007_quiet_hours_repeat`; Compose-API gesund und Web-Container mit aktualisiertem Frontend gestartet.
- [x] Browser-Smoke-Test für wiederkehrende Aufgabe samt Folgeaufgabe, Terminbearbeitung, UTC-Zeitdarstellung und Ruhezeitprofil; responsive Oberfläche bei 1440 px und 390 px in Hell- und Dunkelmodus geprüft, kein mobiler Horizontalüberlauf.

## Redis-Jobqueue

- [x] Redis 7 speichert Queue-Daten mit AOF in einem persistenten Compose-Volume.
- [x] Scheduler stellt Erinnerungsplanungen in eine RQ-Queue; ein separater Worker verarbeitet sie mit begrenztem Retry-Backoff.
- [x] Ausführungssperre verhindert überlappende Planungsläufe; Datenbankoperation bleibt idempotent.
- [x] RQ-Integrationstest prüft Jobstatus, Retry-Konfiguration und erstellte Erinnerung mit echtem Redis.
- [x] KI-Extraktion läuft als Redis/RQ-Hintergrundjob; der Eingang aktualisiert den Status selbstständig.
- [x] KI-Erfassung, Erinnerungsplanung sowie Memory-/Entitäten-Embeddings verwenden dieselbe Redis/RQ-Job-Infrastruktur; weitere asynchrone Fachprozesse sind derzeit nicht vorgesehen.

## MCP-Toolkatalog und Zugriff

- [x] Typisierte Tools für Personen, Beziehungen, Erinnerungen, Gespräche, Aufgaben, Termine, Leihgaben, Geschenke und Briefings ergänzt; die vorhandenen Service- und REST-Geschäftsoperationen werden wiederverwendet.
- [x] Lese- und Schreibrechte sind über kurzlebige MCP-Tokens getrennt konfigurierbar; schreibende Tools prüfen den Scope, Löschung verlangt eine explizite Bestätigung.
- [x] Offizieller Streamable-HTTP-MCP-Client prüft Verbindung, Tool-Aufruf, Suche, Beziehungskontext und verweigerten Schreibzugriff mit Nur-Lese-Token.
- [x] Änderungswerkzeuge für Aufgaben, Termine, Gespräche, Erinnerungen, Geschenke und Leihgaben sowie bestätigungspflichtige Personen- und Beziehungs-Löschungen ergänzt.
- [x] Audit-Ereignisse für MCP-Schreibvorgänge werden innerhalb derselben Datenbanktransaktion gespeichert und benutzerspezifisch über `audit_search` und `GET /api/audit` abgerufen.
- [x] Migration `0008_audit_events`; offizieller MCP-Client prüft Updates, Audit-Protokoll, Benutzertrennung und Scope-Verweigerung.
- [x] Projekte mit benutzergebundener Liste, Detailansicht, Suche, Anlage und Bearbeitung in REST, UI und MCP; Projektlöschung über den MCP-Freigabefluss.
- [x] Kritische MCP-Löschungen für Personen, Beziehungen, Erinnerungen und Projekte legen einen Freigabeantrag an. Ein MCP-Token kann nur anfragen und den Status lesen; ein separates Benutzer-Token bestätigt oder verwirft die Aktion in der Weboberfläche.
- [x] Freigabeanträge speichern Operation, Ziel-ID, lesbare Zielbezeichnung und Entscheidungsstatus. Doppelte offene Anträge werden zusammengeführt; Entscheidung und Löschung erfolgen gemeinsam in einer Transaktion und werden auditiert. Fremde Anträge und Ressourcen sind per Benutzer-ID abgeschirmt.
- [x] Migration 0010_projects_and_approvals; 18 Backend-Tests einschließlich offiziellem Streamable-HTTP-MCP-Client bestanden; Next.js-Produktionsbuild bestanden.
- [x] Typisierte MCP-Operationen umfassen Erstellen, Suchen/Lesen, Aktualisieren und kontrolliertes Löschen der unterstützten Ressourcen; Browser-, Berechtigungs-, PostgreSQL-Restore- und Compose-Neustartprüfungen laufen automatisiert.

## Optionale KI-Schnellerfassung

- [x] Originaleingaben werden vor jeder KI-Verarbeitung mandantenbezogen gespeichert und bleiben bei fehlender oder nicht erreichbarer KI erhalten.
- [x] Konfigurierbarer OpenAI-kompatibler Extraktor mit strukturierter, validierter Ausgabe und Begrenzung für Provider-Timeouts.
- [x] Modellaufrufe laufen in Redis/RQ außerhalb des HTTP-Requests; bei nicht verfügbarer Queue bleibt der Originaltext erhalten und der Fehler sichtbar.
- [x] Vorschläge bleiben bis zur Auswahl unbestätigt; ausgewählte Erinnerungen speichern ihre Quell-Eingabe und Ereigniszeit.
- [x] Eingang in der Weboberfläche zeigt Originaltext, Vorschläge und Fehlerstatus; Vorschläge können einzeln ausgewählt und übernommen werden.
- [x] Migration `0009_reviewable_captures` und Backend-Tests für Persistenz ohne Provider, Review-Auswahl, Quellverknüpfung, Fehlerbehandlung und Benutzertrennung.
- [x] Embeddings und hybride Suche für Erinnerungen, Gespräche, Aufgaben, Beziehungen und Projekte; Briefings bleiben offen.
