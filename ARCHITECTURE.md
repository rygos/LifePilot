# Architektur

## Schichten

`apps/api` stellt FastAPI REST und MCP bereit. Pydantic-Schemas validieren Eingaben und Antworten, SQLAlchemy-Modelle persistieren Daten, Services bündeln Transaktionen und Besitzerprüfungen. `apps/web` ist ein Next.js-Client und spricht ausschließlich über die API. Alembic versioniert das relationale Schema.

## Daten- und Sicherheitsgrenzen

Jede fachliche Zeile trägt einen Besitzer. Services filtern jede Abfrage anhand des authentifizierten Benutzers. Passwörter werden mit Argon2 gehasht; signierte kurzlebige Bearer-Tokens authentifizieren API und MCP. Fremdschlüssel verhindern Beziehungen zu nicht vorhandenen Personen. KI-Ausgaben werden in der späteren Architektur zunächst als Vorschläge behandelt und benötigen Bestätigung.

## Temporale und Quellenfelder

Erinnerungen unterscheiden Erfassungszeit (`created_at`) von Ereigniszeit (`occurred_at`). Beziehungen bewahren `valid_from`, `valid_until`, `source_memory_id` und `confirmed`. Diese Felder bilden die Grundlage für nachvollziehbare Aussagen und spätere Korrekturhistorie.

## Betrieb

Compose betreibt Web und API; die Datenbankdatei liegt im persistenten Volume. SQLite erleichtert Einzelbenutzerbetrieb; `DATABASE_URL` erlaubt PostgreSQL für den nächsten Ausbau. Redis und separater Worker sind noch nicht enthalten. Siehe Implementierungsplan für offene Schritte.
