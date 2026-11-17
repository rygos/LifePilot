#!/usr/bin/env bash
set -euo pipefail

project="lifepilot-pg-restore-$$"
work_dir=$(mktemp -d "${TMPDIR:-/tmp}/lifepilot-pg-restore.XXXXXX")
export COMPOSE_PROJECT_NAME=$project
export COMPOSE_FILE="$PWD/docker-compose.yml:$PWD/infrastructure/docker-compose.postgres-test.yml"
export API_PORT=${PG_RESTORE_API_PORT:-18081}
export MCP_PORT=${PG_RESTORE_MCP_PORT:-18083}

cleanup() {
  timeout 30s docker compose down -v --remove-orphans >/dev/null 2>&1 || true
  find "$work_dir" -depth -delete >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker compose up -d db api
for attempt in $(seq 1 60); do
  if docker compose exec -T api python -c 'import urllib.request; urllib.request.urlopen("http://localhost:8000/health", timeout=2)' >/dev/null 2>&1; then
    break
  fi
  if [[ "$attempt" == 60 ]]; then
    docker compose logs api db >&2
    exit 1
  fi
  sleep 2
done

backup_root="$work_dir/backups"
scripts/backup.sh "$backup_root"
backup_dir=$(find "$backup_root" -mindepth 1 -maxdepth 1 -type d -name 'lifepilot-*' -print -quit)
if [[ -z "$backup_dir" ]]; then
  printf 'Backup directory was not created.\n' >&2
  exit 1
fi

restore_db="lifepilot_restore_$$"
restore_dir="$work_dir/restored-files"
RESTORE_DB=$restore_db DATA_RESTORE_DIR=$restore_dir scripts/restore.sh "$backup_dir"

restored_version=$(docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$1" -Atqc "SELECT version_num FROM alembic_version"' sh "$restore_db")
restored_users=$(docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$1" -Atqc "SELECT count(*) FROM users"' sh "$restore_db")
if [[ "$restored_version" != "0012_entity_embeddings" || "$restored_users" -lt 1 ]]; then
  printf 'Staging restore validation failed (migration=%s users=%s).\n' "$restored_version" "$restored_users" >&2
  exit 1
fi

printf 'PostgreSQL backup and staging restore passed: migration=%s users=%s\n' "$restored_version" "$restored_users"
