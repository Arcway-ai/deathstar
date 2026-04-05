#!/bin/bash
set -euo pipefail

# DeathStar control-api entrypoint
#
# 1. Run Alembic migrations (idempotent — safe on every restart).
# 2. Exec the main process (uvicorn or whatever CMD is passed).
#
# Requires DEATHSTAR_DATABASE_URL to be set when using PostgreSQL.
# For SQLite (dev/test), migrations are skipped — tables are created
# by SQLModel.metadata.create_all() in app_state.py.

if [ -n "${DEATHSTAR_DATABASE_URL:-}" ]; then
  case "$DEATHSTAR_DATABASE_URL" in
    postgresql://*|postgresql+*|postgres://*|postgres+*)
      echo "[entrypoint] Running Alembic migrations..."
      alembic upgrade head
      echo "[entrypoint] Migrations complete."
      ;;
    *)
      echo "[entrypoint] Non-PostgreSQL database — skipping Alembic migrations."
      ;;
  esac
else
  echo "[entrypoint] DEATHSTAR_DATABASE_URL not set — skipping migrations."
fi

# Hand off to the CMD (uvicorn by default)
exec "$@"
