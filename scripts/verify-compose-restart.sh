#!/usr/bin/env bash
set -euo pipefail

api_url=${LIFEPILOT_RESTART_API_URL:-http://localhost:${API_PORT:-8000}}
web_url=${LIFEPILOT_RESTART_WEB_URL:-http://localhost:${WEB_PORT:-3000}}

fingerprint() {
  docker compose exec -T api python -c 'import hashlib,json; from sqlalchemy import select; from sqlalchemy.orm import Session; from lifepilot.db import engine; from lifepilot.models import Person,Relationship,User; db=Session(engine); rows=[(model.__tablename__,tuple(tuple(getattr(row,column.name) for column in model.__table__.columns) for row in db.scalars(select(model).order_by(model.id)))) for model in (User,Person,Relationship)]; db.close(); print(hashlib.sha256(json.dumps(rows,default=str,sort_keys=True).encode()).hexdigest())'
}

wait_http() {
  local url=$1
  for attempt in $(seq 1 30); do
    if curl --fail --silent --show-error "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done
  printf 'Service did not become reachable: %s\n' "$url" >&2
  return 1
}

before=$(fingerprint)
for service in redis db api web scheduler worker; do
  docker compose restart "$service"
  case "$service" in
    redis) docker compose exec -T redis redis-cli ping | grep -qx PONG ;;
    db) docker compose exec -T db sh -c 'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"' >/dev/null ;;
    api) wait_http "$api_url/health" ;;
    web) wait_http "$web_url" ;;
    scheduler|worker) docker compose exec -T "$service" python -c 'print("ready")' | grep -qx ready ;;
  esac
done
after=$(fingerprint)
if [[ "$before" != "$after" ]]; then
  printf 'Database fingerprint changed across service restarts.\n' >&2
  exit 1
fi
printf 'Compose restart passed; user, person and relationship fingerprint %s\n' "$after"
