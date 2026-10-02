#!/usr/bin/env bash
# K9X HIL (internal) — the LAN-only instance that decides tasks.
#
# Same image as ubuntu/build-run.sh (the public, read-only hil.k9x.ai);
# different container, port, schema, consumer group and JWT secret, all from
# .env.internal (see .env.internal.example). Never add this port to cloudflared.
#
# Commands:
#   build   — build the container image (shared with the public instance)
#   start   — start the internal container
#   stop    — stop it
#   logs    — tail logs
#   all     — build + start

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
IMAGE="k9x-hil:latest"
CONTAINER="k9x-hil-internal"
PORT="${HIL_INTERNAL_PORT:-8096}"
ENV_FILE="$PROJECT_DIR/.env.internal"

cmd="${1:-help}"

case "$cmd" in

  build)
    "$PROJECT_DIR/ubuntu/build-run.sh" build
    ;;

  start)
    [ -f "$ENV_FILE" ] || { echo "Missing $ENV_FILE (copy .env.internal.example and fill it in)"; exit 1; }
    for key in HIL_PROFILE=internal POSTGRES_SCHEMA= HIL_CONSUMER_GROUP= JWT_SECRET_KEY= HIL_ADMIN_PASSWORD=; do
      grep -q "^${key}" "$ENV_FILE" || { echo "$ENV_FILE must set ${key}..."; exit 1; }
    done
    if grep -qE '^POSTGRES_SCHEMA=k9hil$' "$ENV_FILE" || grep -qE '^HIL_CONSUMER_GROUP=k9x-hil-ingest$' "$ENV_FILE"; then
      echo "$ENV_FILE shares the public instance's schema or consumer group; use its own."; exit 1
    fi
    echo "Starting $CONTAINER on port $PORT (LAN only) ..."
    sudo podman rm -f "$CONTAINER" 2>/dev/null || true
    sudo podman run -d \
      --name "$CONTAINER" \
      --restart=always \
      -p "$PORT:8086" \
      --env-file "$ENV_FILE" \
      "$IMAGE"
    HOST_IP=$(hostname -I | awk '{print $1}')
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  K9X HIL — internal (decides tasks)"
    echo "  Web UI:  http://${HOST_IP}:${PORT}/"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    ;;

  stop)
    sudo podman stop "$CONTAINER" 2>/dev/null || true
    echo "Stopped."
    ;;

  logs)
    sudo podman logs -f "$CONTAINER"
    ;;

  all)
    "$0" build
    "$0" start
    ;;

  help|*)
    sed -n '2,14p' "$0"
    ;;

esac
