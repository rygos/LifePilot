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

## Abgleich mit Monica HQ (Stand 21.11.2026)

### Screenshot-Abgleich Monica HQ 4.1.2 (23.11.2026)

Geprüfte Referenzen im Repository: `tmp/Dashboard.png`, `tmp/neue-beziehung-hinzufuegen.png`, `tmp/person-hinzufuegen.png` und `tmp/person-profil-notizen.png`. Die Monica-Farbgebung wird nicht übernommen; `DESIGN.md` bleibt für Hell-/Dunkelpalette, Typografie und LifePilot-Komponenten maßgeblich.

| Screenshot-Muster | LifePilot-Abgleich | Priorisierte Umsetzung |
| --- | --- | --- |
| Dashboard mit Drei-Monats-Ausblick, aktuellem Kontakt und Aufgabenbereichen | Tagesbriefing, Erinnerungen, Aufgaben und Schnellerfassung vorhanden; längerer Vorausblick fehlt | Geburtstage und Ereignisse der nächsten 90 Tage im Dashboard ergänzen; Profile und Eventdetails verlinken |
| Beziehung anlegen: vorhandene oder neue Person wählen, Geburtsdatum mit unterschiedlicher Genauigkeit | Manuelle Beziehung verlangt eine vorhandene Person; Geburtstag ist bislang exakt oder leer | Neue Person transaktional im Beziehungsablauf anlegen; Geburtstag als genau, Monat/Tag, ungefähres Alter oder unbekannt speichern |
| Person hinzufügen mit „weitere Person anlegen“ | Kurzformular enthält zentrale Felder; Folgeanlage und Kontaktimport fehlen | Nach dem Beziehungsablauf Folgeanlage ergänzen; Import bleibt spätere Priorität |
| Profil mit klaren Abschnitten für Beziehungen, Kontaktverlauf, Erinnerungen, Aufgaben, Geschenke, Schulden und Dokumente | Profile zeigen die meisten relevanten LifePilot-Daten, aktuell aber als lange Ansicht; Geldschulden und Telefonprotokoll fehlen | Profil nach Übersicht, Verlauf, Planung und Dateien gliedern; Telefonprotokoll und konfigurierbare Kontaktintervalle ergänzen |
| vCard-Export, Archivieren und Löschen | Export/Archiv fehlen; Löschen ist vorhanden | JSON/vCard-Export als Folgearbeit priorisieren; Archivierung später mit Wiederherstellungskonzept |

Der frühere Funktionsabgleich wurde bei diesem Screenshot-Audit korrigiert: Favoriten, Labels und „Wie kennengelernt“ sind bereits implementiert und keine offenen Punkte mehr.

### Umsetzung aus dem Screenshot-Abgleich

- [x] Dashboard: 90-Tage-Ausblick mit Ereignissen und bekannten Geburtstagen, responsiv und mit Links zu Profilen bzw. Ereignisarchiv.
- [x] Personenprofil: Tabs für Übersicht, Verlauf, Planung und Dateien; Identitätskopf bleibt sichtbar und die langen Inhalte sind sinnvoll getrennt.
- [x] Geburtstage: genaues Datum, Tag/Monat ohne Jahr, ungefähres Alter oder unbekannt; keine erfundenen Jahreszahlen. Bekannte Geburtstage erscheinen auch im Ereigniskalender.
- [x] Beziehungserfassung: bestehende Person suchen oder neue Person mitsamt Geburtstag und Beziehung transaktional in einem Ablauf anlegen.
- [x] Kontaktpflege: Telefonate mit Datum, Dauer und Notiz protokollieren; optionale Kontaktintervalle erzeugen persistente Wiedervorlagen nach einem protokollierten Kontakt.
- [x] Verifiziert: API-Suite 92 bestanden, 2 übersprungen; Next.js-Produktionsbuild; Browserablauf für neue Person/Beziehung, Teilgeburtstag und Telefonat bei 390 px sowie Prüfung der Light-/Dark-Farbtoken und des horizontalen Überlaufs; vollständige Alembic-Kette bis `0031` auf isoliertem PostgreSQL und SQLite.

Monica wird hier als persönliches CRM für Kontaktpflege verglichen; LifePilot bleibt ein persönliches Zweitgedächtnis mit KI, Graphbeziehungen und MCP. Grundlage sind die [aktuelle Produktseite](https://www.monicahq.com/en/), die [Monica-v3-Seite](https://www.monicahq.com/en/v3/) und das [Open-Source-Repository](https://github.com/monicahq/monica), nicht nur die frühere Funktionsliste der v4-Anwendung.

| Monica-Funktion | LifePilot-Stand | Maßnahme |
| --- | --- | --- |
| Kontakte mit Profilfoto, Geburtstag, Beziehungen und Kontaktverlauf | Vorhanden; Ereignisse, Gespräche, Erinnerungen und Aufgaben erscheinen im Profil | Beibehalten und weiter zusammenführen |
| Favoriten | Implementiert | Personen markieren und filtern |
| Labels/Tags und Suche danach | Implementiert | Normalisierte, filter- und durchsuchbare Labels |
| „Wie kennengelernt“ | Implementiert | Eigenes Profilfeld und Suche |
| Mehrere E-Mail-Adressen, Telefonnummern und Adressen mit Beschriftung | Beschriftete zusätzliche E-Mail-, Telefon-, Adress-, Webseiten-, Messenger-, Social- und sonstige Kontaktwege; Suche, REST und MCP | Vorhanden |
| Erinnerungen und Wiedervorlagen | Aufgaben-/Termin-Erinnerungen vorhanden; Geburtstage werden eine Woche vorher jährlich und in der Benutzerzeitzone vorgemerkt | Vorhanden; Vorlauf derzeit sieben Tage |
| Aktivitäten und Journal | Chronologisches Tagebuch mit freiem Text, optionaler Selbsteinschätzung der Stimmung und Verknüpfungen zu Personen, Projekten und Ereignissen | Grundfunktion vorhanden; Import älterer Journaleinträge ist Folgearbeit |
| Notizen, Geschenke und Beziehungen | Vorhanden | Bereits durch das Gedächtnismodell abgedeckt |
| Haustiere, Unternehmen, Orte, Projekte und weitere Entitäten | Vereine/Organisationen, Orte als Eventdaten, Projekte, Gegenstände und benutzergebundene Tierprofile vorhanden | Vorhanden; Import und Tierfotos bleiben Erweiterungen |
| Schulden und Geldbewegungen | Gegenstände-Leihgaben vorhanden; Geldschulden fehlen | Priorität 3: optionales Geldverzeichnis ergänzen |
| Anhänge und Dokumente | Sichere Anhänge für Personen, Erinnerungen/Notizen, Gespräche, Ereignisse und Projekte in UI und API; MCP kann Metadaten der eigenen Anhänge abfragen | Weitere Arbeit: Vorschaubilder und Import |
| Kontaktfreigabe und gemeinsam genutzte Bereiche | Benutzerbereiche sind isoliert; selektive Freigaben fehlen | Nicht ohne Freigabe- und Datenschutzmodell öffnen |
| Import/Export | Backup/Restore vorhanden; strukturierter Kontakt-/vCard-Export und Import sind nicht vollständig | Priorität 2: portabler JSON/vCard-Export |
| Anrufdauer, Kontaktfrequenz, Stimmungsverfolgung, frei definierte Profilabschnitte | Nicht vollständig vorhanden | Nur nach Produktentscheidung; nicht stillschweigend auswerten oder soziale Ranglisten bauen |

Frühere Monica-Ausbaupunkte wie Favoriten, Labels und „Wie kennengelernt“ sind bereits umgesetzt. Die folgenden Punkte dokumentieren tatsächliche Lücken oder bewusste Folgeentscheidungen.

### Monica-Kontaktfunktionen: erster Ausbau

- [x] Personen als Favoriten markieren und die Menschenliste nach Favoriten filtern.
- [x] Frei vergebbare Labels je Person speichern, im Profil anzeigen und im Menschenfilter durchsuchen.
- [x] Eigenes Feld „Wie kennengelernt“ im Profil bearbeiten, anzeigen und über die Personen-API-Suche finden.
- [x] MCP-Personenanlage, -bearbeitung und -suche unterstützen dieselben Felder und die Labelnormalisierung.
- [x] Der Scheduler plant jährliche Geburtstagserinnerungen sieben Tage vorher in der Zeitzone des Kontos; Dubletten werden pro Person und Jahr verhindert, der 29. Februar wird in Nichtschaltjahren auf den 28. Februar gelegt.
- [x] Alembic-Migration `0024_person_favorites_labels` ergänzt die drei Felder mit sicheren Werten für Bestandsprofile.
- [x] Alembic-Migration `0025_birthday_reminders` ergänzt die referenzierte, pro Jahr eindeutige Geburtstags-Wiedervorlage.
- [x] Beschriftete zusätzliche Kontaktwege pro Person mit validierten REST-CRUD-Operationen, Duplikatschutz, Audit und Besitzerprüfung.
- [x] REST-Personensuche, universelle Suche, Verzeichnis und MCP-Personensuche finden Kontaktwerte und Beschriftungen.
- [x] MCP-Kontaktwerkzeuge lesen, anlegen, bearbeiten und löschen dieselben validierten Kontaktweg-Datensätze.
- [x] Migration `0026_person_contact_methods` ergänzt eine relationale, besitzergebundene Kontakttabelle.
- [x] API-Test prüft Labelnormalisierung, Suche, Favoritenwechsel und Besitzergrenze: 1 bestanden; MCP-Integration prüft dieselben Profilfelder.
- [x] Scheduler-Regressionstest prüft Jahresplanung, Kontenzeitzone, Deduplizierung und Schaltjahrbehandlung.
- [x] Migration `0023` bis Head `0026` sowie Downgrade und erneutes Upgrade auf einer isolierten SQLite-Datenbank erfolgreich.
- [x] API-Suite nach den Ergänzungen: 81 bestanden, 2 übersprungen.
- [x] Next.js-Produktionsbuild erfolgreich; Playwright-E2E gegen eine isolierte App-/API-Instanz prüft Profilbearbeitung, Labels, Favoritenschalter, Filter, Kontaktweg-Erfassung und Suche: 1 bestanden.
- [ ] Folgearbeit laut Vergleich: Geldschulden; außerdem Vorschaubilder, Dokumentimport und Journalimport.

### Tierprofile

- [x] Eigene, benutzergebundene Tierentität mit Tierart, Rasse, Geschlecht, Geburtstag, Kastrationsstatus und Notizen; Schema- und Besitzerprüfungen verhindern ungültige oder fremde Verknüpfungen.
- [x] Tiere lassen sich mit Personen (Besitzer:in, Betreuung, gemeinsamer Haushalt) und Ereignissen verknüpfen; Verbindungen sind auf der Profilkarte sichtbar und führen zu den zugehörigen Personen/Ereignissen.
- [x] CRUD-REST-Endpunkte, auditierte Änderungen und typisierte MCP-Werkzeuge `pet_create`, `pet_search`, `pet_get`, `pet_update` und freigabepflichtiges `pet_delete` verwenden dieselbe Geschäftslogik.
- [x] Migration `0030_pet_profiles`; gezielte API-/MCP-Tests und SQLite-Migrationslauf bestanden.
- [x] Playwright-Szenario prüft Tieranlage, Autocomplete-Verknüpfung mit einer Person, Ereigniszuordnung und nachträgliche Profiländerung.
- [ ] Tierfotos, Import und eine dedizierte Detailansicht bleiben Folgearbeit.

### Tagebuch

- [x] Benutzergebundene Tagebucheinträge mit eigenem Datum, freiem Text und optionaler, manuell gewählter Stimmung speichern.
- [x] Einträge mit mehreren Personen, Projekten und Ereignissen verknüpfen; alle verknüpften IDs werden gegen den angemeldeten Benutzer geprüft.
- [x] Chronologische Ansicht mit Textsuche und Datumsbereich sowie Bearbeiten und Löschen ergänzen.
- [x] REST und MCP bieten typisierte Erstellen-, Suchen-, Lesen- und Bearbeiten-Werkzeuge; MCP-Löschungen verlangen die vorhandene Freigabe.
- [x] API- und MCP-Regressionen prüfen Zeitfilter, Verknüpfungen, Besitzertrennung, Löschung und Nur-Lese-Scope.
- [x] Verifikation: 86 API-Tests bestanden, 2 übersprungen; Produktionsbuild, Migration `0029` mit Downgrade/Upgrade und Browser-E2E für Eintrag, Verknüpfungen, Suche und Löschen erfolgreich.

### Monica-Anhänge: erster Ausbau

- [x] Ressourcenbezogene Dateimetadaten und Alembic-Migration `0027_resource_attachments` ergänzen.
- [x] Authentifizierte Upload-, Listen-, Download- und Lösch-API für Personen, Erinnerungen/Notizen, Gespräche, Ereignisse und Projekte; jeder Zugriff prüft Besitzer und Ressource.
- [x] Upload auf 20 MB begrenzen, Dateitypen erlauben-listen, Dateinamen vom Speicherpfad trennen und Downloads als private Anhänge mit `nosniff` ausliefern.
- [x] Audit-Ereignisse für Upload und Löschung sowie Dateibereinigung beim Löschen zugehöriger Personen, Erinnerungen, Gespräche, Ereignisse und dauerhaft gelöschter Konten.
- [x] Profiloberfläche für Personen und Ereignisdetails unterstützen Upload, Liste, Download und Löschen.
- [x] API-Regressionen für Upload, Downloadheader, Dateitypprüfung, Mandantentrennung und Löschbereinigung.
- [x] Browser-E2E prüft privaten Profilanhang-Upload, Download, Löschen und die Profil-/Mitgliedschaftsansicht.
- [x] Oberfläche für Dateianhänge an Erinnerungen und Gesprächen; MCP-Metadatenzugriff mit Besitzerprüfung und eingeschränktem Lesetoken.
- [x] Projektanhänge in Projektansicht und MCP-Metadatensuche ergänzen; Besitzerprüfung und Dateibereinigung bei direkter sowie bestätigter Projektlöschung.
- [x] Gesamte API-Suite nach dem Anhang-Ausbau: 85 bestanden, 2 übersprungen; Produktionsbuild und Migrationen `0027` bis `0028` inklusive Downgrade/Upgrade erfolgreich.

## Initiales Datenmodell

Alle fachlichen Datensätze gehören einem Benutzer (`owner_id`) und jeder Repository-Zugriff wird auf diesen Besitzer eingeschränkt. `Person` enthält Identitäts- und Kontaktdaten. `Relationship` verbindet gerichtete Quell- und Zielpersonen; `UserPersonRelationship` verbindet eine Person mit dem angemeldeten Nutzer, jeweils mit Gültigkeitszeitraum, Quelle und Bestätigungsstatus. `Memory` speichert Originaltext, optionale Zusammenfassung, Ereigniszeit und Erfassungszeit getrennt. `JournalEntry` speichert unabhängiges Eintragsdatum, freien Text und optional selbst gewählte Stimmung; separate besitzergebundene Verbindungstabellen verknüpfen mehrere Personen, Projekte und Ereignisse. `Task` enthält Status, Priorität, Fälligkeit und optional eine Person. `ResourceRevision` hält benutzergebundene, unveränderliche JSON-Snapshots für Aufgaben und Gespräche mit Revision, Aktion, Quelle und Erstellungszeit fest. Benutzerpasswörter werden ausschließlich als Argon2-Hash persistiert. Fremdschlüssel, eindeutige IDs und Datenbanktransaktionen schützen die Integrität.

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

## Geschlechtsbewusste Personenbeziehungen und Profilkarten

- [x] Personenprofile (einschließlich des eigenen Profils) speichern validierte Angaben `female`, `male`, `diverse` oder `unspecified`; bestehende Datensätze erhalten bei Migration den neutralen Wert.
- [x] Beziehungsauswahl nutzt neutrale Kategorien und leitet gerichtete Bezeichnungen wie „Mutter von“ / „Sohn von“ aus den Profilen beider Personen ab. Explizite Beziehungsbegriffe können eine noch unbekannte Geschlechtsangabe ergänzen; gespeicherte Angaben werden nicht überschrieben.
- [x] KI-Extraktion kennt explizite Geschlechtsbelege sowie vorsichtige Namensvermutungen. Vermutungen aus Vornamen müssen vor dem Speichern ausdrücklich bestätigt werden.
- [x] Änderung eines Profilgeschlechts benennt die vorhandenen gerichteten Beziehungen anhand beider Profile neu; MCP unterstützt Geschlecht beim Erstellen und Bearbeiten von Personen.
- [x] Beziehungsprofilkarten zeigen Entfernen als zugängliches X oben rechts statt als abgesetzten Textknopf.
- [x] Migration `0020_person_gender`, 66 Backend-Tests (2 übersprungen), Next.js-Produktionsbuild und Playwright-Profilablauf im laufenden Compose-Stack geprüft.

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

## Zweitgedächtnis: strukturierte Auswertung freier Notizen

- [x] Extraktionsschema unterscheidet Fakten, Gespräche, Beziehungen, frühere Namen, Lebensereignisse, Aufgaben, Termine und Projektverknüpfungen; der Prompt verbietet unbelegte Identitäten, Daten und Aufgaben.
- [x] Erfassungszeit wird in die Verarbeitung gegeben; eindeutige relative Tage wie „gestern“ werden relativ zum Erfassen aufgelöst, ungefähre Zeiträume behalten ihre Genauigkeit und bekommen keinen erfundenen Zeitpunkt.
- [x] Person-/Projektauflösung erfolgt nur innerhalb des Besitzers. Ein eindeutiger Name oder Projektcode wird verknüpft; mehrdeutige Treffer werden als Kandidaten angezeigt und müssen gewählt werden.
- [x] Review übernimmt vorgeschlagene Gespräche samt Originaltext, Teilnehmern und Projekten sowie bestätigte Namenshistorie, Biografie, gerichtete Beziehungen, Aufgaben mit Fälligkeitserinnerung, Termine und projektbezogene Fakten transaktional.
- [x] Webeingang kann Beziehungen mit zweiter Person auflösen; MCP bietet `memory_capture` und `memory_review` mit Zuordnungen und Bestätigungen.
- [x] MCP kann Capture-Status und Vorschläge benutzergebunden mit `memory_capture_status` abrufen und Erfassungen mit `memory_capture_list` auflisten.
- [x] Aufgaben und Gespräche haben eine unveränderliche Versionshistorie; Erstellung und Änderungen über REST, MCP und geprüfte KI-Erfassung werden revisionsgebunden gespeichert. REST-History-Endpunkte und MCP-History-Tools sind besitzergeprüft.
- [x] Beziehungen einer Person zum LifePilot-Nutzer sind ein eigenes, quellgebundenes Graphobjekt; Capture kann explizite Rollen wie „meine Arbeitskollegin“ vorschlagen und nach Review speichern. Personenbriefing, Suche und MCP-Personenkontext zeigen die Rolle.
- [x] Nutzerbeziehungen lassen sich im Personenprofil auch ohne KI manuell anlegen und entfernen; REST prüft den Datenbesitzer, verhindert aktive Duplikate und protokolliert Änderungen.
- [x] Eine ausdrücklich bestätigte, unbekannte Person kann direkt im Capture-Review angelegt und mit Gespräch oder Beziehung verknüpft werden; ohne Auswahl/Bestätigung entsteht kein Personendatensatz.
- [x] MCP `memory_review` akzeptiert strukturierte, vom Nutzer korrigierte Vorschläge; Änderungen erfolgen weiter gegen die unveränderte Originalerfassung.
- [x] Migration `0013_capture_knowledge` ergänzt Namenshistorie, Lebensereignisse, Projektverknüpfungen und Projektzuordnung von Aufgaben; SQLite-Migration bis Head erfolgreich.
- [x] Tests für Gespräch/Projekt/Person, keine erfundene Aufgabe, frühere Namen mit Quelle, ungenaues Hochzeitsdatum, projektbezogene Aufgabe/Erinnerung, inverse Beziehung/Quelle, relative Zeit und MCP-Erfassung.
- [x] Migration `0015_user_person_relationships`; Integrationstest prüft explizite Nutzerbeziehung, Quellverknüpfung, Profilkontext und Suche.
- [x] REST- und Frontendtest für manuelle Nutzerbeziehungen einschließlich Anzeige im Profil, Datumsvalidierung, Duplikatverhalten und fremden Benutzerzugriff.
- [x] Migration `0014_resource_revisions`, REST-Updatepfade für Aufgaben/Gespräche, MCP-History-Werkzeuge sowie owner-scoped Historienabruf; Integrationstest deckt Snapshotinhalt, fortlaufende Revision und Fremdbenutzerzugriff ab.
- [x] LM Studio auf diesem Host mit `qwen/qwen3.5-9b` im Compose-Worker verbunden (`host.containers.internal:1234/v1`); realen Chat-Completion-Aufruf sowie Extraktion der Kristin-Abeler-Notiz ausgeführt.
- [x] LM Studio verlangt `response_format.type=json_schema`; Extraktor sendet das Pydantic-Schema und begrenzt die Generierung auf 5000 Tokens. Das Schemaergebnis wurde vom echten Modell zurückgegeben und durch Pydantic validiert.
- [x] Prompt und Normalisierung präzisieren frühere Namen, ungefähre Lebensereignisse, heutige relative Gesprächstage und unterscheiden Nutzerbeziehungen von Beziehungen zwischen zwei Personen. Explizit genannte frühere Namen und Projektnummern werden als getrennte, quellnahe Vorschläge/Verknüpfungen geführt; unvollständige Vorschläge und unsichere biografische Daten bleiben bestätigungspflichtig.
- [x] Echte Qwen-Läufe lieferten belegte Gesprächs-/Personenhinweise, schwankten aber bei der Einordnung von Rolle, früherem Namen und Projektverknüpfung; der Eingang bleibt deshalb ausdrücklich ein Review-Schritt und speichert nichts vor Bestätigung.
- [x] Capture-Regressionstests prüfen LM-Studio-Schemaanfrage, Ausgabelimit, Reviewpflicht für frühere Namen und nicht zugeordnete Beziehungen sowie relative Tagespräzision; 16 Capture-Tests bestanden.
- [x] Gesamten produktiven Pfad über authentifizierte REST-Schnellerfassung, Redis/RQ-Worker, LM Studio und Statusabfrage ausgeführt. Ergebnis `ready` mit Gespräch, Projektverknüpfung, früherem Namen, Hochzeit und Nutzerbeziehung; keine Aufgabe und kein Kalendereintrag wurden erfunden. Der ausschließlich hierfür erstellte Capture-Datensatz wurde danach gelöscht.
- [x] Familien-, Treffen- und Leihgabenregeln ergänzen Qwen-Ausgaben deterministisch: Ehe-, Eltern- und Geschwisterkanten (inklusive inverser Typen), heutiges Lego-Treffen als Gespräch, sowie richtungsrichtige unbefristete Leihgabe mit Quellgedächtnis.
- [x] Unzuverlässige Modellkanten, die dieselben Familienmitglieder nennen, werden durch die expliziten Beziehungsvorschläge ersetzt; doppelte Fakten zum Treffen oder zur Leihgabe werden ausgefiltert.
- [x] Die Erfassungszeit wird für relative Angaben in die Zeitzone des Besitzers konvertiert; „heute“ bleibt auch rund um Mitternacht korrekt.
- [x] Echtes Qwen-3.5-9B-Capture zum Beispieltext über REST und den offiziellen MCP-Client: jeweils Status `ready`, 10 Familienkanten, kein Selbstbezug, keine doppelten Fakten, ein Gespräch am 18.11.2026 und eine Leihgabe ohne Rückgabefrist. UI-Review zeigt Zuordnungs- und Neuanlagekontrollen für beide Beziehungspartner sowie die Leihgabe.
- [x] Review-Integration prüft persistierte Beziehungskanten und Quellverknüpfungen, Gespräch statt Kalendereintrag sowie offenen Leihdatensatz; Backend-Suite: 40 bestanden, 2 übersprungen. Next.js-Produktionsbuild erfolgreich.

## GUI-Aufteilung nach MonicaHQs Kontaktansicht

- [x] Navigation in eigenständige Routen für Übersicht, Menschen, Einzelprofil, Gedächtnis, Planung, Gegenstände, Eingang und Einstellungen aufgeteilt; LifePilot-Palette beibehalten.
- [x] Menschenliste um lokale Suche ergänzt; Profile haben eine eigene Route und eine bestätigte Löschaktion.
- [x] UI-Löschaktionen mit Bestätigung für Erinnerungen, Gespräche, Aufgaben, Termine, Leihgaben und Geschenkideen ergänzt; API-Löschpfade prüfen den Datenbesitzer und protokollieren die Aktion.
- [x] Terminformulare unterstützen mehrere Teilnehmende beim Erstellen und Bearbeiten.
- [x] Next.js-Produktionsbuild und API-Tests (41 bestanden, 2 übersprungen) erfolgreich.
- [x] Playwright-E2E gegen die laufenden Container: Navigation, Capture-Eingang, Personenbeziehungen, Mehrfachteilnehmende am Termin, bestätigtes Löschen und Offline-Shell bestanden (1 Test).
- [x] Draft-Guard und `git diff --check` erfolgreich. Manueller CUA-Visual-QA war in der Sitzung nicht verfügbar.

## Chatoberfläche mit Capture und Gedächtnisfragen

- [x] Chat als eigene Route direkt unter Übersicht in der Hauptnavigation.
- [x] Modus „Festhalten“ speichert Originaltexte über die persistente Capture-Pipeline; erkannte Vorschläge werden direkt im Chat einzeln geprüft und übernommen.
- [x] Modus „Fragen“ nutzt benutzergebundene hybride Suche und OpenAI-kompatible Chat-Completions; Antworten erhalten anklickbare Quellen und erfinden bei leeren Treffern keine Antwort.
- [x] Bei fehlendem Modellzugriff bleiben gefundene Quellen sichtbar und die Oberfläche erklärt den Ausfall.
- [x] Migration `0018_capture_chat_source` trennt Chat-Eingaben vom allgemeinen Eingang; bestätigte Vorschläge werden entfernt, offene bleiben im Gespräch und werden in Folgeeingaben weiter berücksichtigt.
- [x] Ausgewählte Vorschläge werden beim nächsten Chatbeitrag automatisch übernommen; der Chatverlauf wird nach dem Neuladen aus gespeicherten Erfassungen wiederhergestellt.
- [x] Regressionstest für partielle Bestätigung, Datenbankspeicherung und Folgekontext; Backend-Suite: 52 bestanden, 2 übersprungen. Next.js-Produktionsbuild und PostgreSQL-Migration bis Head erfolgreich.
- [x] Playwright-E2E durchlief Chat, Ausschluss aus dem Eingang, Verlaufsladen und Folgeeingabe; es scheitert anschließend unverändert am Offline-Shell-Schritt mit „Failed to fetch“.
- [x] Auswahlfeld „Beziehung zu dir“ im dunklen Design an die übrigen Formularfelder angeglichen.
- [x] Chatverläufe nach „Festhalten“ und „Fragen“ getrennt; je Modus werden maximal 40 Nachrichten angezeigt, ältere gespeicherte Erfassungen bleiben erhalten.
- [x] Playwright-E2E prüft Feldgestaltung, Moduswechsel und dass Chatverläufe nicht in den jeweils anderen Modus durchsickern.

## Capture-Verläufe und Dublettenprüfung

- [x] Bereits gespeicherte Vorschläge anhand vorhandener, besitzergebundener Datensätze vor der Inbox-Anzeige herausfiltern; unveränderte Vorschläge aus einem Capture-Verlauf ebenfalls unterdrücken.
- [x] Familienmuster mit expliziten Söhnen/Töchtern sowie Elternlisten erkennen, inverse Kanten als prüfbare Vorschläge vorbereiten und redundante Fakten sowie unbelegte biografische Ereignisse ausblenden.
- [x] Nachträge an eine vorherige Erfassung hängen und deren Originaltext/strukturierte Vorschläge dem Modell als Verlaufskontext geben.
- [x] Strukturierte Vorschläge im Chat anzeigen und natürliche Korrekturen/Ergänzungen über den Eingang oder direkt im Chat als Nachtrag erfassen.
- [x] API-Test deckt Datenbesitzergrenze und Modell-Ausfall ab; Playwright-E2E prüft Chat-Erfassung und quellgebundene Frage.
- [x] Echter Chat-Aufruf über den konfigurierten lokalen Qwen beantwortete eine Frage aus einem gespeicherten Datensatz und lieferte die Datensatz-ID als Quelle; der Prüfdatensatz wurde danach gelöscht.
- [x] Compose-Produktionsbuild, Backend-Suite (50 bestanden, 2 übersprungen), Draft-Guard und `git diff --check` erfolgreich.
- [x] Live-Test mit `qwen/qwen3.5-9b`: erster Capture mit Ehebeziehung, Nachtrag mit zwei Söhnen; im Nachtrag erschienen nur vier neue Eltern-Kind-Kanten und eine Geschwisterkante, die Ehebeziehung und das Treffen wurden nicht wiederholt.
- [x] Explizite Formulierungen wie „Hanna ist die Tochter von Ramona und mir“ erzeugen bestätigungspflichtige Graphbeziehungen zu benannten Personen und zum eigenen Personenprofil; bestätigte Kanten erscheinen in der normalen Beziehungsansicht und behalten ihre Capture-Quelle.
- [x] Regressionstests decken regelbasierte und LLM-normalisierte Elternangaben ab; API-Suite: 54 bestanden, 2 übersprungen.
- [x] Beziehungstyp „Freunde“ ist symmetrisch, im Profil auswählbar und wird als „sind befreundet“ dargestellt; die KI-Anweisungen verwenden denselben Typ.
- [x] Ausdrückliche Sätze wie „Hanna Hering und Vincent Hering sind Freunde“ werden unabhängig von unvollständiger Modellausgabe als bestätigungspflichtige, beidseitig sichtbare Graphbeziehung vorbereitet.
- [x] API-Suite: 56 bestanden, 2 übersprungen; Next.js-Produktionsbuild und Playwright-Test für beide Personenprofile erfolgreich.
- [x] Live-Extraktion mit `qwen/qwen3.5-9b` erzeugt für „Hanna Hering und Vincent Hering sind Freunde“ genau einen vollständigen, beidseitigen und bestätigungspflichtigen Beziehungsvorschlag.
- [x] Die Formulierung mit einer separat genannten Ehefrau, drei Kindern und gemeinsamem Nachnamen erzeugt zehn vollständige Kanten: Ehepartner, sechs Eltern-Kind-Verbindungen und drei Geschwisterbeziehungen.
- [x] Integrationstest übernimmt alle fünf neuen Personen und zehn Beziehungen über die Bestätigungsstrecke; Live-Extraktion mit `qwen/qwen3.5-9b` liefert ebenfalls zehn vollständige Vorschläge.
- [x] API-Suite nach Familienverbesserung: 57 bestanden, 2 übersprungen.
- [ ] Playwright-E2E erreicht Chat-Erfassung, Folgeerfassung und Suche; der abschließende Offline-Shell-Schritt schlägt fehl und zeigt die Anmeldeseite mit „Failed to fetch“.
- [x] Playwright-Ansicht bei 390 und 1440 Pixeln in Hell- und Dunkelmodus geprüft; Moduswechsel und Bestätigungshinweis sichtbar, kein horizontales Overflow.

## Eigenes Personenprofil

- [x] Jedes Konto erhält genau ein geschütztes Personenprofil; die Migration übernimmt Name, Spitzname, Geburtstag und Kontaktdaten aus dem bisherigen Kontoprofil.
- [x] Kontoprofil und eigenes Personenprofil bleiben synchron; das Profil erscheint unter Menschen, kann Beziehungen im Graphen eingehen und ist nicht löschbar.
- [x] API-Regressionstest deckt Profilanlage, Bearbeitung in beide Richtungen, Graphverknüpfung und Löschschutz ab; Backend-Suite: 51 bestanden, 2 übersprungen. Next.js-Produktionsbuild erfolgreich.

## Leihgaben in beide Richtungen

- [x] Formular auf „Gegenstände“ erfasst jetzt sowohl „von jemandem geliehen“ als auch „an jemanden verliehen“.
- [x] Rückgabedatum ist optional, wird im Eintrag angezeigt und bleibt ohne Eingabe leer.
- [x] Capture-Schema, Qwen-Anweisungen und deterministische Erkennung unterscheiden beide Richtungen; bestätigte Vorschläge werden mit Verleiher und Entleiher korrekt gespeichert.
- [x] Live-Aufruf mit `qwen/qwen3.5-9b` ordnet „Ich habe Martin meine Bohrmaschine geliehen“ als `lent` mit Martin als Entleiher ein.
- [x] API- und Capture-Tests prüfen beide Richtungen, offene Leihgaben und optionale Fristen; 4 gezielte Backend-Tests bestanden.
- [x] Next.js-Produktionsbuild und Playwright-E2E durch beide Formularvarianten mit und ohne Rückgabedatum bestanden.

## Ereignisarchiv

- [x] Teilnehmende in manuellen Ereignis- und Terminformularen per Autocomplete hinzufügen, als Chips anzeigen und einzeln entfernen; Browserprüfung mit Auswahl, Entfernen und erneutem Hinzufügen bestanden.
- [x] Vergangene Ereignisse getrennt von zukünftigen Terminen speichern und beim Bestätigen einer datierten Gesprächserfassung anlegen; Teilnehmernamen und Ort gehen aus der strukturierten Erfassung in den Ereigniseintrag über.
- [x] Monatliche Kalenderansicht mit Monatswechsel, Datumsauswahl und auswählbaren Ereignissen.
- [x] Ereignisdetails mit bearbeitbarem Kontext, Ort/Adresse, Originaleingabe und anklickbaren Profilbildkarten der Teilnehmenden.
- [x] Monatsnavigation gleichmäßig ausrichten; Ereignisse standardmäßig als Details anzeigen und nur nach Wahl von „Bearbeiten“ als Formular öffnen, sodass dieselben Angaben nie doppelt erscheinen.
- [x] Ereignisbilder sicher hochladen, anzeigen und löschen; API beschränkt Bildformat, Größe, Auflösung und Zugriff auf den Dateneigentümer.
- [x] API-Tests für Ereignisfotos und Fremdnutzerzugriff; Capture-Test prüft getrennte Erlebnisdatensätze, alle genannten Teilnehmenden und fehlende Termin-Erinnerung; Playwright prüft Anlegen, Auswahl, Ort, Kontext, Foto und mobile Breite.
- [x] PostgreSQL-Migration 0021 auf der laufenden Compose-Instanz ausgeführt; Backend-Suite: 69 bestanden, 2 übersprungen; Frontend-Build und Ereignis-Playwright-Test erfolgreich.
- [x] Neue Adminverwaltung mit rollenbasierter API-Autorisierung, Schutz vor dem Entfernen des letzten Admins und Administratorbereich in der GUI.
- [x] Portainer-Git-Webhook als Adminaktion einrichten; Updates beziehen den aktuellen Commit und führen Alembic-Migrationen vor dem Start der API aus.
- [x] Migration 0022 auf lokaler und Server-PostgreSQL-Datenbank ausführen und `ryg` in beiden Datenbanken zum Administrator machen.

## Familien-Stammbaum

- [x] Geschützten API-Endpunkt für den vollständigen zusammenhängenden Familiengraphen ergänzen; Freunde, Kolleg:innen und fremde Benutzerdaten bleiben ausgeschlossen.
- [x] Im Personenprofil ein responsives, scrollbares Generationsdiagramm mit Profilbildern, anklickbaren Profilen und sichtbarem Bestätigungsstatus ergänzen.
- [x] Backendtests für Generationen, Beziehungen, Ausschlüsse und Benutzertrennung; Playwright-Test für Anzeige und Profilnavigation.
- [x] Diagramm als Familienverbände mit gemeinsamem Eltern-Kind-Bus darstellen; redundante Geschwister- und Partnerlinien ausblenden und Geschwister nach gemeinsamen Eltern gruppieren.
- [x] Astwerk als Referenz für Familienverbände mit gemeinsamen Kindern statt direkter Geschwisterkanten ausgewertet.

## Administration mobil und Versionsvergleich

- [x] Adminroute auf Benutzerverwaltung und Wartung begrenzen, damit Dashboard- und Planungsbereiche dort nicht zusätzlich erscheinen.
- [x] Mobile Navigation mit drei Schnellzielen und kompaktem „Mehr“-Menü statt mehrreihiger Seitenleiste.
- [x] API-Image enthält den Build-Commit; Admin-API vergleicht ihn mit `main` und liefert die letzten 20 Commit-Betreffzeilen sowie Anzahl verfügbarer Änderungen.
- [x] 75 Backendtests bestanden, 2 übersprungen; Next.js-Build, Docker-Compose-Konfiguration und API-Image-Build erfolgreich. Mobile Adminroute und „Mehr“-Menü bei 390 px im Browser geprüft; den Live-Stack auf dem vorherigen Commit gelassen, damit dieser Stand über die vorhandene Updateaktion getestet werden kann.
