# Architektur

## Schichten

`apps/api` stellt FastAPI REST und MCP bereit. Pydantic-Schemas validieren Eingaben und Antworten, SQLAlchemy-Modelle persistieren Daten, Services bündeln Transaktionen und Besitzerprüfungen. `apps/web` ist ein Next.js-Client und spricht ausschließlich über die API. Alembic versioniert das relationale Schema.

## Daten- und Sicherheitsgrenzen

Jede fachliche Zeile trägt einen Besitzer. Services filtern jede Abfrage anhand des authentifizierten Benutzers. Passwörter werden mit Argon2 gehasht; signierte kurzlebige Bearer-Tokens authentifizieren API und MCP. Fremdschlüssel verhindern Beziehungen zu nicht vorhandenen Personen. KI-Ausgaben werden in der späteren Architektur zunächst als Vorschläge behandelt und benötigen Bestätigung.

## Temporale und Quellenfelder

Erinnerungen unterscheiden Erfassungszeit (`created_at`) von Ereigniszeit (`occurred_at`). Beziehungen bewahren `valid_from`, `valid_until`, `source_memory_id` und `confirmed`. Diese Felder bilden die Grundlage für nachvollziehbare Aussagen und spätere Korrekturhistorie.

## Betrieb

Compose betreibt Web, API, PostgreSQL mit pgvector, Redis, Scheduler und Job-Worker. PostgreSQL liegt in einem persistenten Volume; SQLite bleibt über `DATABASE_URL` für lokale Entwicklung und Tests verfügbar. Der Scheduler stellt Erinnerungsplanungen in eine RQ-Queue. Der Worker verarbeitet sie mit bis zu drei Wiederholungen bei 15, 60 und 180 Sekunden Abstand. Eine Redis-Ausführungssperre verhindert überlappende Planungsläufe; die Datenbankoperation selbst ist idempotent. Redis AOF und das Volume `lifepilot-redis` erhalten eingereihte Jobs über Containerneustarts hinweg. Erinnerungen und deren Zustand bleiben in PostgreSQL. Das Vektor-Extension-Image ist vorbereitet; semantische Vektorspalten und Embedding-Suche folgen mit der KI-Pipeline.
