#!/bin/bash
set -euo pipefail

COMPOSE_FILE="/opt/deathstar/repo/docker/docker-compose.yml"

if docker compose version >/dev/null 2>&1; then
  docker compose -f "$COMPOSE_FILE" down
  exit 0
fi

if command -v docker-compose >/dev/null 2>&1; then
  docker-compose -f "$COMPOSE_FILE" down
  exit 0
fi
