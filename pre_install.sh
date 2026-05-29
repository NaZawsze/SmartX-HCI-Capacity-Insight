#!/usr/bin/env sh
set -eu

DATA_ROOT="${SMARTX_DATA_ROOT:-/data/smartx-capacity-insight-data}"
APP_DIR="$DATA_ROOT/app"
PROMETHEUS_DIR="$DATA_ROOT/prometheus"
PROMETHEUS_UID="${SMARTX_PROMETHEUS_UID:-65534}"
PROMETHEUS_GID="${SMARTX_PROMETHEUS_GID:-65534}"

if [ "$(id -u)" != "0" ]; then
  echo "pre_install.sh must be run as root." >&2
  exit 1
fi

mkdir -p "$APP_DIR" "$PROMETHEUS_DIR"

chown root:root "$DATA_ROOT" "$APP_DIR"
chown -R "$PROMETHEUS_UID:$PROMETHEUS_GID" "$PROMETHEUS_DIR"
chmod 755 "$DATA_ROOT" "$APP_DIR" "$PROMETHEUS_DIR"

echo "SmartX HCI Capacity Insight data directories are ready."
echo "  app:        $APP_DIR -> root:root"
echo "  prometheus: $PROMETHEUS_DIR -> $PROMETHEUS_UID:$PROMETHEUS_GID"
