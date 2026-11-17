# Backup und Wiederherstellung

LifePilot kann PostgreSQL oder SQLite als primäre Datenbank verwenden. `scripts/backup.sh` erkennt den konfigurierten Datenbanktyp und erstellt ein zeitgestempeltes Verzeichnis mit einem konsistenten Datenbankbackup, einem Archiv der übrigen Dateien in `/app/data`, Manifest und SHA-256-Prüfsummen. SQLite wird über die Online Backup API gesichert; WAL-/SHM-Dateien und die separate SQLite-Datei werden aus dem zweiten Archiv ausgeschlossen. Das Zielverzeichnis wird mit Modus `0700` angelegt. Das Backup enthält absichtlich keine `.env`-Datei und keine Zugangsdaten.

## Backup erstellen

Im Projektverzeichnis bei laufendem Compose-Stack:

```sh
scripts/backup.sh /srv/backups/lifepilot
```

Die erzeugte Sicherung enthält bei PostgreSQL `postgres.dump` und bei SQLite `database.sqlite`; beide Varianten enthalten außerdem `app-data.tar.gz`, `manifest.txt` und `SHA256SUMS`. Kopiere sie anschließend auf ein getrenntes, verschlüsseltes Ziel. Sichere `.env` separat und verschlüsselt. Das App-Datenarchiv ist vorsorglich enthalten, auch wenn die Anwendung derzeit noch keine Datei-Anhänge speichert. PostgreSQL-URLs werden derzeit nur unterstützt, wenn der Host dem Compose-Service `db` entspricht.

## In eine neue Datenbank wiederherstellen

Der Restore verweigert vorhandene PostgreSQL-Datenbanken und Datenverzeichnisse. Er verändert nicht die in `.env` konfigurierte Datenbank oder das laufende Docker-Volume.

Für PostgreSQL:

```sh
RESTORE_DB=lifepilot_restore_20261117 \
DATA_RESTORE_DIR=/srv/restore/lifepilot-data \
scripts/restore.sh /srv/backups/lifepilot/lifepilot-20261117T120000Z
```

Vor dem Start prüft das Skript die SHA-256-Prüfsummen und verweigert Archivpfade mit absoluten Pfaden oder `..`. PostgreSQL wird in einer neu angelegten Datenbank restauriert; App-Dateien werden in ein neues Staging-Verzeichnis entpackt. Danach Datenbank und Dateien kontrollieren und erst nach geplanter Wartung `DATABASE_URL` beziehungsweise das persistente App-Volume auf die geprüften Daten umstellen. Falls `pg_restore` fehlschlägt, kann die neu angelegte Staging-Datenbank unvollständig sein; die Meldung benennt sie zur manuellen Bereinigung.

Für SQLite:

```sh
DATA_RESTORE_DIR=/srv/restore/lifepilot-data \
scripts/restore.sh /srv/backups/lifepilot/lifepilot-20261117T120000Z
```

Die Datenbankdatei wird unter dem in `manifest.txt` dokumentierten Dateinamen neben den übrigen App-Dateien bereitgestellt (standardmäßig `lifepilot.db`). SQLite-Backups funktionieren nur, wenn die konfigurierte Datenbankdatei innerhalb von `/app/data` liegt.

Beispielprüfung des Dumps:

```sh
docker compose exec -T db pg_restore --list < /srv/backups/lifepilot/lifepilot-20261117T120000Z/postgres.dump
```

## Wiederanlauf und Grenzen

- `lifepilot-postgres`, `lifepilot-redis` und `lifepilot-data` sind persistente Compose-Volumes.
- Redis enthält Queue- und Schedulerzustand, aber keine maßgeblichen Gedächtnisdaten. Der Scheduler kann Erinnerungsjobs nach dem Neustart erneut planen.
- PostgreSQL-Backups enthalten Schema, Daten und pgvector-Inhalte; Container-Images und `.env` sind nicht Bestandteil der Sicherung.
- Ein SQLite-Restore wird zunächst in ein Staging-Verzeichnis geschrieben und muss unter Wartung manuell in das App-Datenvolume kopiert werden.
- Vor einem Update ein Backup erstellen. Nach einem Restore Migrationen nur auf der Staging-Datenbank ausführen und die Anwendung erst nach erfolgreicher Prüfung umschalten.

## Automatisierte Betriebsprüfungen

Nach dem Einrichten von `.env` lässt sich der PostgreSQL-Backup-/Restorepfad in einer eigenen Compose-Umgebung prüfen. Das Skript migriert eine isolierte PostgreSQL-Datenbank, sichert sie, restauriert in eine neue Staging-Datenbank, prüft die aktuelle Alembic-Version und den Bootstrap-Benutzer und entfernt anschließend die Testcontainer:

```sh
scripts/test-postgres-restore.sh
```

Für einen laufenden Hauptstack prüft dieses Skript den Neustart von Redis, PostgreSQL, API, Web, Scheduler und Worker einzeln. Es vergleicht vor und nach dem Neustart einen Hash der Benutzer-, Personen- und Beziehungsdatensätze und wartet auf API-/Web-Erreichbarkeit:

```sh
scripts/verify-compose-restart.sh
```

Bei abweichenden Ports `API_PORT` und `WEB_PORT` setzen oder `LIFEPILOT_RESTART_API_URL` und `LIFEPILOT_RESTART_WEB_URL` angeben. Der Restoretest verwendet `PG_RESTORE_API_PORT` und `PG_RESTORE_MCP_PORT` für seine isolierte Umgebung.
