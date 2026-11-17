#!/usr/bin/env bash
set -euo pipefail

backup_root=${1:-./backups}
timestamp=$(date -u +%Y%m%dT%H%M%SZ)
backup_dir="$backup_root/lifepilot-$timestamp"

umask 077
mkdir -p "$backup_root"
mkdir "$backup_dir"

database_type=$(docker compose exec -T api python -c 'from lifepilot.config import settings; from sqlalchemy.engine import make_url; url = make_url(settings.database_url); print("sqlite" if url.get_backend_name() == "sqlite" else "postgresql" if url.get_backend_name() == "postgresql" else "unsupported")')
if [[ "$database_type" == "sqlite" ]]; then
  sqlite_path=$(docker compose exec -T api python -c 'from lifepilot.config import settings; from sqlalchemy.engine import make_url; print(make_url(settings.database_url).database or "")')
  sqlite_filename=${sqlite_path##*/}
  if [[ "$sqlite_path" != /app/data/* || ! "$sqlite_filename" =~ ^[A-Za-z0-9_.-]+$ || "$sqlite_filename" == . || "$sqlite_filename" == .. ]]; then
    printf 'SQLite database must be a file inside /app/data to be included safely.\n' >&2
    exit 2
  fi
  docker compose exec -T api python -c 'import os, shutil, sqlite3, sys, tempfile; source = sys.argv[1]; handle = tempfile.NamedTemporaryFile(delete=False); target = handle.name; handle.close(); src = sqlite3.connect(source, timeout=30); dst = sqlite3.connect(target); src.backup(dst); dst.close(); src.close(); stream = open(target, "rb"); shutil.copyfileobj(stream, sys.stdout.buffer); stream.close(); os.unlink(target)' "$sqlite_path" > "$backup_dir/database.sqlite"
  docker compose exec -T api sh -c 'tar -czf - --exclude="$1" --exclude="$1-wal" --exclude="$1-shm" --exclude="$1-journal" -C /app/data .' sh "$sqlite_filename" > "$backup_dir/app-data.tar.gz"
elif [[ "$database_type" == "postgresql" ]]; then
  database_host=$(docker compose exec -T api python -c 'from lifepilot.config import settings; from sqlalchemy.engine import make_url; print(make_url(settings.database_url).host or "")')
  if [[ "$database_host" != "db" ]]; then
    printf 'PostgreSQL backup currently supports the Compose db service; configured host is not the Compose db service.\n' >&2
    exit 2
  fi
  docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom --no-owner --no-acl' > "$backup_dir/postgres.dump"
  docker compose exec -T api sh -c 'tar -czf - -C /app/data .' > "$backup_dir/app-data.tar.gz"
else
  printf 'Unsupported DATABASE_URL backend: %s\n' "$database_type" >&2
  exit 2
fi
printf 'created_at_utc=%s\n' "$timestamp" > "$backup_dir/manifest.txt"
printf 'database_type=%s\n' "$database_type" >> "$backup_dir/manifest.txt"
if [[ "$database_type" == "sqlite" ]]; then
  printf 'sqlite_filename=%s\n' "$sqlite_filename" >> "$backup_dir/manifest.txt"
fi
printf 'git_commit=%s\n' "$(git rev-parse HEAD 2>/dev/null || printf unknown)" >> "$backup_dir/manifest.txt"
if [[ "$database_type" == "sqlite" ]]; then
  (cd "$backup_dir" && sha256sum database.sqlite app-data.tar.gz manifest.txt > SHA256SUMS)
else
  (cd "$backup_dir" && sha256sum postgres.dump app-data.tar.gz manifest.txt > SHA256SUMS)
fi

printf 'Backup created: %s\n' "$backup_dir"
