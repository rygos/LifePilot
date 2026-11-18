# Architektur

## Schichten

`apps/api` stellt FastAPI REST und MCP bereit. Pydantic-Schemas validieren Eingaben und Antworten, SQLAlchemy-Modelle persistieren Daten, Services bündeln Transaktionen und Besitzerprüfungen. `apps/web` ist ein Next.js-Client und spricht ausschließlich über die API. Alembic versioniert das relationale Schema.

## Daten- und Sicherheitsgrenzen

Jede fachliche Zeile trägt einen Besitzer. Services filtern jede Abfrage anhand des authentifizierten Benutzers. Passwörter werden mit Argon2 gehasht; signierte kurzlebige Bearer-Tokens authentifizieren API und MCP. Fremdschlüssel verhindern Beziehungen zu nicht vorhandenen Personen. Eine Schnellerfassung speichert den Originaltext als `Capture`; strukturierte Vorschläge werden separat validiert und erst nach Review in typisierte Datensätze übernommen. Gespräche, Fakten und Beziehungen verweisen auf ihre Quellerfassung. Frühere Namen (`PersonNameHistory`) und biografische Ereignisse (`PersonLifeEvent`) behalten zeitliche Genauigkeit und Quelle. Projekte können mit Gesprächen, Fakten und Aufgaben verknüpft werden. Kritische MCP-Löschungen werden als typisierte Freigabeanträge gespeichert. Die API prüft bei der Entscheidung erneut Antrag, Besitzer und Zielressource; Freigabezustand und Löschung werden gemeinsam committet.

Jedes Benutzerkonto besitzt außerdem genau ein geschütztes `Person`-Profil (`is_self`). Eine Migration legt dieses Profil für bestehende Konten aus den Kontaktdaten des Benutzerkontos an. Es kann wie jede andere Person in Beziehungen und Ereignissen verwendet werden; Änderungen an Name und Kontaktdaten werden zwischen Konto und Profil synchronisiert. Das eigene Profil kann nicht gelöscht werden.

Die Weboberfläche bietet zwei Chat-Modi. „Festhalten“ delegiert an den vorhandenen Capture-Endpunkt, der den Originaltext vor dem optionalen LLM-Auftrag persistiert. „Fragen“ führt eine besitzergebundene hybride Suche aus und übergibt nur eine begrenzte Menge passender Treffer an den konfigurierten OpenAI-kompatiblen Chat-Completions-Provider. Antworten verlinken die verwendeten Quellen; bei leerer Suche wird kein LLM um eine Vermutung gebeten.

## Temporale und Quellenfelder

Erinnerungen unterscheiden Erfassungszeit (`created_at`) von Ereigniszeit (`occurred_at`). Beziehungen bewahren `valid_from`, `valid_until`, `source_memory_id` und `confirmed`. Diese Felder bilden die Grundlage für nachvollziehbare Aussagen und spätere Korrekturhistorie.

## Betrieb

Compose betreibt Web, API, PostgreSQL mit pgvector, Redis, Scheduler und Job-Worker. PostgreSQL liegt in einem persistenten Volume; SQLite bleibt über `DATABASE_URL` für lokale Entwicklung und Tests verfügbar. Der Scheduler stellt Erinnerungsplanungen in eine RQ-Queue. Der Worker verarbeitet sie mit bis zu drei Wiederholungen bei 15, 60 und 180 Sekunden Abstand. Eine Redis-Ausführungssperre verhindert überlappende Planungsläufe; die Datenbankoperation selbst ist idempotent. Redis AOF und das Volume `lifepilot-redis` erhalten eingereihte Jobs über Containerneustarts hinweg. Erinnerungen und deren Zustand bleiben in PostgreSQL. Vektoren für Erinnerungen sowie Gespräche, Aufgaben, Beziehungen und Projekte werden nach dem Speichern asynchron berechnet und jeweils mit Besitzer und Fremdschlüssel der Quelle gespeichert. PostgreSQL kombiniert Volltextsuche mit HNSW-Cosinus-Ranking; SQLite bleibt ohne Vektor-Erweiterung nutzbar und berechnet Cosinus-Abstände lokal.
