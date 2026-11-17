#!/usr/bin/env bash
set -euo pipefail

backup_dir=${1:?Usage: DATA_RESTORE_DIR=empty-path [RESTORE_DB=name] scripts/restore.sh BACKUP_DIR}
restore_db=${RESTORE_DB:-}
data_restore_dir=${DATA_RESTORE_DIR:?Set DATA_RESTORE_DIR to a new, empty directory}

if [[ -e "$data_restore_dir" ]]; then
  printf 'Refusing to overwrite existing data directory: %s\n' "$data_restore_dir" >&2
  exit 2
fi
if [[ ! -f "$backup_dir/app-data.tar.gz" || ! -f "$backup_dir/manifest.txt" || ! -f "$backup_dir/SHA256SUMS" ]]; then
  printf 'Backup directory is incomplete: %s\n' "$backup_dir" >&2
  exit 2
fi
(cd "$backup_dir" && sha256sum --check SHA256SUMS)
if ! tar -tzf "$backup_dir/app-data.tar.gz" | awk '$0 ~ /^\// || $0 ~ /(^|\/)\.\.(\/|$)/ {bad=1} END {exit bad}'; then
  printf 'App data archive contains an unsafe path.\n' >&2
  exit 2
fi

database_type=$(sed -n 's/^database_type=//p' "$backup_dir/manifest.txt")
sqlite_filename=
case "$database_type" in
  sqlite)
    sqlite_filename=$(sed -n 's/^sqlite_filename=//p' "$backup_dir/manifest.txt")
    if [[ ! "$sqlite_filename" =~ ^[A-Za-z0-9_.-]+$ || "$sqlite_filename" == . || "$sqlite_filename" == .. || ! -f "$backup_dir/database.sqlite" ]]; then
      printf 'SQLite backup is incomplete or has an invalid filename.\n' >&2
      exit 2
    fi
    ;;
  postgresql)
    if [[ ! "$restore_db" =~ ^[A-Za-z_][A-Za-z0-9_]{0,62}$ ]]; then
      printf 'Invalid or missing RESTORE_DB identifier.\n' >&2
      exit 2
    fi
    if [[ ! -f "$backup_dir/postgres.dump" ]]; then
      printf 'PostgreSQL backup archive is missing.\n' >&2
      exit 2
    fi
    exists=$(docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d postgres -Atqc "$1"' sh "SELECT 1 FROM pg_database WHERE datname = '$restore_db'")
    if [[ "$exists" == "1" ]]; then
      printf 'Refusing to overwrite existing database: %s\n' "$restore_db" >&2
      exit 2
    fi
    docker compose exec -T db sh -c 'createdb -U "$POSTGRES_USER" "$1"' sh "$restore_db"
    if ! docker compose exec -T db sh -c 'pg_restore -U "$POSTGRES_USER" -d "$1" --no-owner --no-acl --exit-on-error' sh "$restore_db" < "$backup_dir/postgres.dump"; then
      printf 'Database restore failed; the newly created database %s may be partial.\n' "$restore_db" >&2
      exit 1
    fi
    ;;
  *)
    printf 'Unsupported or missing database_type in backup manifest.\n' >&2
    exit 2
    ;;
esac

mkdir -m 700 -p "$data_restore_dir"
tar --no-same-owner --no-same-permissions -xzf "$backup_dir/app-data.tar.gz" -C "$data_restore_dir"
if [[ "$database_type" == "sqlite" ]]; then
  cp "$backup_dir/database.sqlite" "$data_restore_dir/$sqlite_filename"
  printf 'Restored SQLite database: %s\n' "$data_restore_dir/$sqlite_filename"
else
  printf 'Restored PostgreSQL database: %s\n' "$restore_db"
fi
printf 'Restored app data to staging directory: %s\n' "$data_restore_dir"
printf 'The running application still uses its configured database and Docker volume. Switch them only after validating this restore.\n'
