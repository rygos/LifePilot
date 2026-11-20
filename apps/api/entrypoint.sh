#!/bin/sh
set -eu

alembic upgrade head

uvicorn lifepilot.main:app --host 0.0.0.0 --port 8000 &
api_pid=$!
python -c 'from lifepilot.main import run_mcp; run_mcp()' &
mcp_pid=$!

shutdown() {
  trap - INT TERM
  kill "$api_pid" "$mcp_pid" 2>/dev/null || true
  wait "$api_pid" 2>/dev/null || true
  wait "$mcp_pid" 2>/dev/null || true
  exit 0
}
trap shutdown INT TERM

while kill -0 "$api_pid" 2>/dev/null && kill -0 "$mcp_pid" 2>/dev/null; do
  sleep 1
done

kill "$api_pid" "$mcp_pid" 2>/dev/null || true
wait "$api_pid" 2>/dev/null || true
wait "$mcp_pid" 2>/dev/null || true
exit 1
