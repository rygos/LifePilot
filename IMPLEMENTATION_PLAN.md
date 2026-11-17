# LifePilot: Implementierungsplan

## Ausgangslage

Das GitHub-Repository war leer. Es gab keine vorhandene Anwendung oder Datenbank zu erhalten. Das lokale Umfeld stellt Podman Compose bereit; Docker wird über dessen Kompatibilitätsschicht angeboten.

## Priorisierte Arbeit

- [x] Grundsystem: FastAPI, SQLite/PostgreSQL-kompatible SQLAlchemy-Modelle, initiale Alembic-Migration, Benutzerkonten und mandantenbezogene Daten.
- [x] Kernfunktionen ohne KI: Personen, Beziehungen, Notizen/Erinnerungen, Aufgaben, Suche und deutsche Weboberfläche.
- [x] MCP-Server mit Streamable HTTP und authentifizierten, typisierten Werkzeugen (4 Kernwerkzeuge erfolgreich mit offiziellem Client geprüft).
- [x] Compose-Datei, Konfigurationsbeispiel, Betriebs- und Architekturhinweise.
- [x] Backend-Tests (3 bestanden), Next.js-Produktionsbuild, SQLite-Migration und Compose-Health/API-/MCP-Szenarien ausgeführt.
- [x] Erweiterung: 4 Backend-Tests bestanden, Migration `0002_phase1_domains` auf Test- und Compose-Datenbank aktiv, Web-Build und Compose-API-Aufrufe für Gespräche/Leihgaben/Geschenke geprüft.
- [x] Gespräche mit Teilnehmern und Ereigniszeit, Leihgaben mit Rückgabe und Geschenke mit Anlass/Quelle (REST, UI und Migration).
- [x] Termine mit Teilnehmern/Quellen, persistente Erinnerungen und unabhängiger Scheduler-Worker.
- [ ] PostgreSQL/pgvector und Redis; Scheduler nutzt derzeit dieselbe persistente Datenbank.
- [ ] KI-Pipeline mit expliziter Prüfung vorgeschlagener Fakten, Embeddings und hybride Suche.
- [ ] Ruhezeiten, Wiederholungsregeln, Briefings, PWA und vollständige UI- und MCP-Abdeckung.
- [ ] Vollständige MCP-Toolabdeckung, Berechtigungs-, E2E- und Wiederherstellungsprüfungen.

## Initiales Datenmodell

Alle fachlichen Datensätze gehören einem Benutzer (`owner_id`) und jeder Repository-Zugriff wird auf diesen Besitzer eingeschränkt. `Person` enthält Identitäts- und Kontaktdaten. `Relationship` verbindet gerichtete Quell- und Zielpersonen, speichert Typ, Gültigkeitszeitraum, Quelle und Bestätigungsstatus. `Memory` speichert Originaltext, optionale Zusammenfassung, Ereigniszeit und Erfassungszeit getrennt. `Task` enthält Status, Priorität, Fälligkeit und optional eine Person. Benutzerpasswörter werden ausschließlich als Argon2-Hash persistiert. Fremdschlüssel, eindeutige IDs und Datenbanktransaktionen schützen die Integrität. Spätere Fakten- und Graphobjekte können dieselben Quellen- und Zeitfelder verwenden.

## Architekturentscheidungen

- FastAPI, Pydantic, SQLAlchemy 2 und Alembic bilden API, Validierung, Persistenz und Migrationen.
- SQLite ermöglicht sofortige lokale Nutzung und Tests; `DATABASE_URL` schaltet auf PostgreSQL um. Für semantische Suche wird PostgreSQL mit pgvector ergänzt.
- Ein Next.js-Frontend und FastAPI-Backend laufen getrennt in Compose. Der API-Service enthält zunächst den MCP-Transport, damit Autorisierung dieselbe Anwendungskonfiguration nutzt.
- KI ist in dieser Ausbaustufe nicht aktiv: ungeprüfte Fakten können daher nicht als bestätigte Erinnerungen gespeichert werden.

## Nächste Schritte

1. PostgreSQL mit pgvector, Redis und getrenntem Scheduler/Worker ergänzen.
2. Regeln für Ruhezeiten, Wiederholungen und Ereignisänderungen erweitern.
3. MCP-Toolkatalog entlang der Geschäftsoperationen vervollständigen und per MCP-Client integrieren testen.
4. KI-Extraktion nur als prüfbare Vorschläge implementieren, danach hybride Suche und Briefings.
5. E2E-, Datenschutz-, Backup/Restore- und Compose-Neustart-Szenarien automatisieren.

## Letzter Ausbauschritt

- [x] Migration `0003_events_reminders`, 5 Backend-Tests einschließlich Scheduler-Deduplizierung und Aufgabenabschluss, In-App-Erinnerungen, Verschieben, Python-Kompilierung, Compose-Konfiguration und Next.js-Produktionsbuild geprüft.
- [x] Laufender Compose-Stack nach Migration mit API-Aufrufen für fällige Erinnerungen und deren Abschluss geprüft.
- [x] Browser-Smoke-Test für Menschen, Profile und Beziehungsansicht durchgeführt; vollständige Light/Dark- und Mobil/Desktop-Matrix bleibt ausstehend.

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
