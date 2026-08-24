#!/usr/bin/env bash
# K9X HIL — Build and run helper
#
# Commands:
#   build   — build the container image
#   start   — start the container
#   stop    — stop the container
#   logs    — tail logs
#   all     — build + start

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
IMAGE="k9x-hil:latest"
CONTAINER="k9x-hil"

cmd="${1:-help}"

case "$cmd" in

  build)
    echo "Building $IMAGE ..."
    cd "$PROJECT_DIR"
    sudo podman build -t "$IMAGE" -f RHEL/Containerfile .
    echo "Build complete: $IMAGE"
    ;;

  start)
    ENV_FILE="$PROJECT_DIR/.env"
    RHEL_HOST_IP="${RHEL_HOST_IP:?Set RHEL_HOST_IP to the host LAN IP before running start (e.g. RHEL_HOST_IP=10.0.0.5 ./build-run.sh start)}"
    echo "Starting $CONTAINER on port 8086 ..."
    sudo podman rm -f "$CONTAINER" 2>/dev/null || true
    sudo podman run -d \
      --name "$CONTAINER" \
      -p 8086:8086 \
      --add-host "rhel-host:${RHEL_HOST_IP}" \
      --env-file "$ENV_FILE" \
      "$IMAGE"
    echo ""
    HOST_IP=$(hostname -I | awk '{print $1}')
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  K9X HIL — Human-in-the-Loop"
    echo "  Web UI:  http://${HOST_IP}:8086/"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    ;;

  stop)
    echo "Stopping $CONTAINER ..."
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
    echo "Usage: $0 <command>"
    echo ""
    echo "Commands:"
    echo "  build   — build the container image"
    echo "  start   — start the container (port 8086)"
    echo "  stop    — stop the container"
    echo "  logs    — tail logs"
    echo "  all     — build + start"
    ;;

esac
