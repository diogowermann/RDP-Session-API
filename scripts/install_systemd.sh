#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="rdp-session-api"
SERVICE_USER="rdp-session-api"
APP_DIR="/opt/rdp-session-api"
ENV_SOURCE=""
START_SERVICE=0

usage() {
    cat <<'EOF'
Usage: sudo bash ./scripts/install_systemd.sh [options]

Options:
  --app-dir PATH       Application checkout path (default: /opt/rdp-session-api)
  --env-source PATH    Existing environment file to copy into /etc/rdp-session-api/
  --start              Enable and restart the service after installation
  --help               Show this help

The installer never overwrites an existing production environment file unless
--env-source is explicitly supplied. Alembic migrations run as ExecStartPre
using the same protected environment as the API service.
EOF
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --app-dir)
            if [ "$#" -lt 2 ]; then
                echo "--app-dir requires a path." >&2
                exit 2
            fi
            APP_DIR="$2"
            shift 2
            ;;
        --env-source)
            if [ "$#" -lt 2 ]; then
                echo "--env-source requires a path." >&2
                exit 2
            fi
            ENV_SOURCE="$2"
            shift 2
            ;;
        --start)
            START_SERVICE=1
            shift
            ;;
        --help|-h)
            usage
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

if [ "$(id -u)" -ne 0 ]; then
    echo "This installer must run as root." >&2
    exit 1
fi

APP_DIR="$(cd "$APP_DIR" 2>/dev/null && pwd)" || {
    echo "Application directory not found: $APP_DIR" >&2
    exit 1
}

UNIT_TEMPLATE="$APP_DIR/deploy/rdp-session-api.service.in"
UVICORN_BIN="$APP_DIR/.venv/bin/uvicorn"
ALEMBIC_BIN="$APP_DIR/.venv/bin/alembic"
ENV_DIR="/etc/rdp-session-api"
ENV_TARGET="$ENV_DIR/rdp-session-api.env"
UNIT_TARGET="/etc/systemd/system/$SERVICE_NAME.service"

if [ ! -f "$UNIT_TEMPLATE" ]; then
    echo "Systemd unit template not found: $UNIT_TEMPLATE" >&2
    exit 1
fi
if [ ! -x "$UVICORN_BIN" ]; then
    echo "Uvicorn executable not found: $UVICORN_BIN" >&2
    echo "Create the virtual environment and install the project first." >&2
    exit 1
fi
if [ ! -x "$ALEMBIC_BIN" ]; then
    echo "Alembic executable not found: $ALEMBIC_BIN" >&2
    exit 1
fi

if ! id "$SERVICE_USER" >/dev/null 2>&1; then
    useradd --system --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin "$SERVICE_USER"
    echo "Created system user: $SERVICE_USER"
fi

install -d -m 0750 "$ENV_DIR"

if [ -n "$ENV_SOURCE" ]; then
    if [ ! -f "$ENV_SOURCE" ]; then
        echo "Environment source not found: $ENV_SOURCE" >&2
        exit 1
    fi
    install -m 0600 -o root -g root "$ENV_SOURCE" "$ENV_TARGET"
    echo "Installed environment file: $ENV_TARGET"
elif [ ! -f "$ENV_TARGET" ]; then
    echo "Production environment file is missing: $ENV_TARGET" >&2
    echo "Re-run with --env-source PATH, or create the file manually with mode 0600." >&2
    exit 1
else
    echo "Preserving existing environment file: $ENV_TARGET"
fi

escaped_app_dir="$(printf '%s' "$APP_DIR" | sed 's/[&|]/\\&/g')"
escaped_service_user="$(printf '%s' "$SERVICE_USER" | sed 's/[&|]/\\&/g')"
sed \
    -e "s|@APP_DIR@|$escaped_app_dir|g" \
    -e "s|@SERVICE_USER@|$escaped_service_user|g" \
    "$UNIT_TEMPLATE" > "$UNIT_TARGET"
chmod 0644 "$UNIT_TARGET"

systemctl daemon-reload
systemctl enable "$SERVICE_NAME.service" >/dev/null

echo "Installed systemd unit: $UNIT_TARGET"
echo "Service user: $SERVICE_USER"
echo "Application directory: $APP_DIR"
echo "Environment file: $ENV_TARGET"

if [ "$START_SERVICE" -eq 1 ]; then
    systemctl restart "$SERVICE_NAME.service"
    systemctl --no-pager --full status "$SERVICE_NAME.service"
else
    echo "Service enabled but not started."
    echo "Validate the protected environment file, then use:"
    echo "  systemctl start $SERVICE_NAME.service"
fi
