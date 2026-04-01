#!/bin/bash
set -euo pipefail

# Blue/green deploy: build new image, health-check it, then swap.
# The old container keeps serving traffic until the new one is verified healthy.

COMPOSE_FILE="/opt/deathstar/repo/docker/docker-compose.yml"
SERVICE="control-api"
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

# ── Step 1: Build the new image (old container keeps running) ──
echo "[blue/green] Building new image..."
compose build --build-arg "CACHEBUST=$(date +%s)" "$SERVICE"

NEW_IMAGE=$(compose config --images | head -1)
echo "[blue/green] New image: $NEW_IMAGE"

# ── Step 2: Check if there's an existing container running ──
OLD_CONTAINER=$(docker ps -q -f "name=deathstar-control-api" 2>/dev/null || true)

if [ -z "$OLD_CONTAINER" ]; then
  # No existing container — first deploy, just start normally
  echo "[blue/green] No existing container — starting fresh..."
  compose up -d
  echo "[blue/green] Started."
  exit 0
fi

echo "[blue/green] Old container running: $OLD_CONTAINER"

# ── Step 3: Start canary container on port 8081 for health check ──
echo "[blue/green] Starting canary on port 8081..."

# Extract env file and volumes from compose config for the canary
CANARY_NAME="deathstar-canary-$$"
docker run -d \
  --name "$CANARY_NAME" \
  --env-file /opt/deathstar/runtime.env \
  -e CLAUDE_PLUGIN_DIR=/opt/claude-plugins \
  -p 8081:8080 \
  -v /workspace:/workspace \
  -v /workspace/deathstar/logs:/var/log/deathstar \
  -v /workspace/deathstar/.claude:/root/.claude \
  "$NEW_IMAGE" \
  uvicorn deathstar_server.main:app --host 0.0.0.0 --port 8080 \
  >/dev/null

# ── Step 4: Health check the canary ──
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

# ── Step 5: Swap or rollback ──
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
