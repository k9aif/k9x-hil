#!/usr/bin/env bash
# K9X HIL — a dedicated instance for one project (HIL_INSTANCE, backend/instance.py)
#
# Same image as hil.k9x.ai; its own env file, schema, consumer group, JWT secret and port.
# Example (DAS):  ./build-run.sh all das      → .env.das, container k9x-hil-das, port 8116
#
# Commands:
#   build            — build the container image (shared with the public HIL)
#   start <name>     — start instance <name> from .env.<name>
#   stop  <name>     — stop it
#   logs  <name>     — tail its logs
#   all   <name>     — build + start

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
IMAGE="k9x-hil:latest"

cmd="${1:-help}"
NAME="${2:-}"
need_name() { [ -n "$NAME" ] || { echo "Usage: $0 $cmd <instance name, e.g. das>"; exit 1; }; }
CONTAINER="k9x-hil-${NAME}"
ENV_FILE="$PROJECT_DIR/.env.${NAME}"

case "$cmd" in

  build)
    "$PROJECT_DIR/ubuntu/build-run.sh" build
    ;;

  start)
    need_name
    [ -f "$ENV_FILE" ] || { echo "Missing $ENV_FILE (copy .env.${NAME}.example, or .env.das.example, and fill it in)"; exit 1; }
    [ -f "$PROJECT_DIR/instances/${NAME}.yaml" ] || { echo "Missing instances/${NAME}.yaml"; exit 1; }
    for key in HIL_INSTANCE POSTGRES_SCHEMA HIL_CONSUMER_GROUP JWT_SECRET_KEY HIL_ADMIN_PASSWORD HIL_INSTANCE_PORT; do
      n=$(grep -c "^${key}=" "$ENV_FILE" || true)
      [ "$n" = 1 ] || { echo "$ENV_FILE has ${key} ${n} times; keep exactly one line."; exit 1; }
      grep -qE "^${key}=.+" "$ENV_FILE" || { echo "$ENV_FILE: ${key} is empty."; exit 1; }
    done
    grep -qE "^HIL_INSTANCE=${NAME}$" "$ENV_FILE" || { echo "$ENV_FILE must set HIL_INSTANCE=${NAME}"; exit 1; }
    for other in .env .env.internal; do
      [ -f "$PROJECT_DIR/$other" ] || continue
      for key in JWT_SECRET_KEY POSTGRES_SCHEMA HIL_CONSUMER_GROUP; do
        a=$(grep -E "^${key}=" "$PROJECT_DIR/$other" | tail -1 || true)
        b=$(grep -E "^${key}=" "$ENV_FILE" | tail -1)
        if [ -n "$a" ] && [ "$a" = "$b" ]; then echo "$ENV_FILE reuses ${key} from $other; give this instance its own."; exit 1; fi
      done
    done
    if grep -qE '^POSTGRES_SCHEMA=k9hil$' "$ENV_FILE" || grep -qE '^HIL_CONSUMER_GROUP=k9x-hil-ingest$' "$ENV_FILE"; then
      echo "$ENV_FILE shares the public instance's schema or consumer group; use its own."; exit 1
    fi
    PORT=$(grep -E '^HIL_INSTANCE_PORT=' "$ENV_FILE" | tail -1 | cut -d= -f2)
    echo "Starting $CONTAINER on port $PORT ..."
    sudo podman rm -f "$CONTAINER" 2>/dev/null || true
    sudo podman run -d \
      --name "$CONTAINER" \
      --restart=always \
      -p "$PORT:8086" \
      --env-file "$ENV_FILE" \
      "$IMAGE"
    HOST_IP=$(hostname -I | awk '{print $1}')
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  K9X HIL — dedicated instance '${NAME}'"
    echo "  Web UI:  http://${HOST_IP}:${PORT}/"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    ;;

  stop)
    need_name
    sudo podman stop "$CONTAINER" 2>/dev/null || true
    echo "Stopped $CONTAINER."
    ;;

  logs)
    need_name
    sudo podman logs -f "$CONTAINER"
    ;;

  all)
    need_name
    "$0" build
    "$0" start "$NAME"
    ;;

  *)
    echo "Usage: $0 {build|start|stop|logs|all} <instance name>"
    exit 1
    ;;
esac
