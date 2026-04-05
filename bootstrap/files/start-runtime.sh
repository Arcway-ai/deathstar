#!/bin/bash
set -euo pipefail

# Blue/green deploy: health-check new image, then swap.
# The old container keeps serving traffic until the new one is verified healthy.
#
# Image source:
#   - Initial deploy (cloud-init): built from source via sync-runtime.sh + docker build
#   - Subsequent deploys (redeploy/upgrade): pre-loaded via `docker load`

# ── Load runtime.env into the shell ────────────────────────────────
# render-runtime-env.sh (ExecStartPre) writes secrets from SSM into
# this file.  We must source it *before* any docker-compose call so
# that shell variables like DEATHSTAR_DB_PASSWORD are available for
# docker-compose.yml variable substitution.
if [ -f /opt/deathstar/runtime.env ]; then
  set -a
  # shellcheck source=/dev/null
  source /opt/deathstar/runtime.env
  set +a
fi

COMPOSE_FILE="/opt/deathstar/repo/docker/docker-compose.yml"
SERVICE="control-api"
IMAGE="deathstar-app:latest"
HEALTH_URL="http://127.0.0.1:8081/v1/health"
HEALTH_TIMEOUT=60
HEALTH_INTERVAL=3

compose() {
  if docker compose version >/dev/null 2>&1; then
    docker compose -f "$COMPOSE_FILE" "$@"
  elif command -v docker-compose >/dev/null 2>&1; then
    docker-compose -f "$COMPOSE_FILE" "$@"
  else
    echo "docker compose is not installed" >&2
    exit 1
  fi
}

# ── Step 1: Ensure image exists ──────────────────────────────────
# If the image isn't loaded yet (first deploy), build it from source.
if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  echo "[blue/green] Image not found — building from source..."
  docker build \
    -t "$IMAGE" \
    -f /opt/deathstar/repo/docker/control-api.Dockerfile \
    /opt/deathstar/repo
fi

echo "[blue/green] Using image: $IMAGE"

# ── Step 2: Ensure Postgres is running ──────────────────────────
# Start Postgres first (if not already running) so the canary can connect.
compose up -d postgres
echo "[blue/green] Postgres is ready."

# ── Step 3: Check if there's an existing control-api running ────
OLD_CONTAINER=$(docker ps -q -f "name=deathstar-control-api" 2>/dev/null || true)

if [ -z "$OLD_CONTAINER" ]; then
  # No existing container — first deploy, just start normally
  echo "[blue/green] No existing container — starting fresh..."
  compose up -d
  echo "[blue/green] Started."
  exit 0
fi

echo "[blue/green] Old container running: $OLD_CONTAINER"

# ── Step 4: Start canary container on port 8081 for health check ─
echo "[blue/green] Starting canary on port 8081..."

# Determine the Docker compose network name so canary can reach Postgres
NETWORK=$(docker inspect deathstar-postgres --format '{{range $k, $v := .NetworkSettings.Networks}}{{$k}}{{end}}' 2>/dev/null || echo "docker_default")

# Resolve DB password: host env takes priority, then runtime.env, then default.
# The --env-file flag only injects vars into the container, not the host shell,
# so we must parse it ourselves to build the DATABASE_URL.
if [ -z "${DEATHSTAR_DB_PASSWORD:-}" ] && [ -f /opt/deathstar/runtime.env ]; then
    _pw=$(grep -m1 '^DEATHSTAR_DB_PASSWORD=' /opt/deathstar/runtime.env | cut -d= -f2- || true)
    [ -n "${_pw:-}" ] && DEATHSTAR_DB_PASSWORD="$_pw"
fi
DB_PASSWORD="${DEATHSTAR_DB_PASSWORD:-deathstar}"

CANARY_NAME="deathstar-canary-$$"
docker run -d \
  --name "$CANARY_NAME" \
  --network "$NETWORK" \
  --env-file /opt/deathstar/runtime.env \
  -e CLAUDE_PLUGIN_DIR=/opt/claude-plugins \
  -e DEATHSTAR_DATABASE_URL=postgresql://deathstar:${DB_PASSWORD}@postgres:5432/deathstar \
  -p 8081:8080 \
  -v /workspace:/workspace \
  -v /workspace/deathstar/logs:/var/log/deathstar \
  -v /workspace/deathstar/.claude:/root/.claude \
  "$IMAGE" \
  uvicorn deathstar_server.main:app --host 0.0.0.0 --port 8080 \
  >/dev/null

# ── Step 5: Health check the canary ─────────────────────────────
echo "[blue/green] Waiting for canary health check..."
elapsed=0
healthy=false

while [ "$elapsed" -lt "$HEALTH_TIMEOUT" ]; do
  if curl -sf --max-time 3 "$HEALTH_URL" >/dev/null 2>&1; then
    healthy=true
    break
  fi
  sleep "$HEALTH_INTERVAL"
  elapsed=$((elapsed + HEALTH_INTERVAL))
  echo "[blue/green]   ...waiting ($elapsed/${HEALTH_TIMEOUT}s)"
done

# ── Step 6: Swap or rollback ────────────────────────────────────
if [ "$healthy" = true ]; then
  echo "[blue/green] Canary healthy! Swapping..."

  # Stop canary (it was just for health checking)
  docker rm -f "$CANARY_NAME" >/dev/null 2>&1 || true

  # Now do the actual swap: stop old, start new on port 8080
  compose up -d --force-recreate --no-build

  echo "[blue/green] Deploy complete. New version is live."
else
  echo "[blue/green] Canary FAILED health check — rolling back!" >&2

  # Kill the canary, old container is still running
  docker rm -f "$CANARY_NAME" >/dev/null 2>&1 || true

  echo "[blue/green] Rollback complete. Old version still serving." >&2
  exit 1
fi
