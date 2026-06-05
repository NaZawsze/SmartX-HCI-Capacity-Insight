#!/usr/bin/env sh
set -eu

DATA_ROOT="${SMARTX_DATA_ROOT:-/data/smartx-capacity-insight-data}"
APP_DIR="$DATA_ROOT/app"
PROMETHEUS_DIR="$DATA_ROOT/prometheus"
UPGRADES_DIR="${SMARTX_UPGRADES_DIR:-/data/upgrades}"
BACKUPS_DIR="${SMARTX_BACKUPS_DIR:-/data/backups}"
EXPORTS_DIR="${SMARTX_EXPORTS_DIR:-/data/exports}"
COMPOSE_RUNTIME_DIR="${SMARTX_COMPOSE_RUNTIME_DIR:-/data/compose-runtime}"
PROMETHEUS_UID="${SMARTX_PROMETHEUS_UID:-65534}"
PROMETHEUS_GID="${SMARTX_PROMETHEUS_GID:-65534}"

if [ "$(id -u)" != "0" ]; then
  echo "pre_install.sh must be run as root." >&2
  exit 1
fi

mkdir -p "$APP_DIR" "$PROMETHEUS_DIR" "$UPGRADES_DIR" "$BACKUPS_DIR" "$EXPORTS_DIR" "$COMPOSE_RUNTIME_DIR"

chown root:root "$DATA_ROOT" "$APP_DIR" "$UPGRADES_DIR" "$BACKUPS_DIR" "$EXPORTS_DIR" "$COMPOSE_RUNTIME_DIR"
chown -R "$PROMETHEUS_UID:$PROMETHEUS_GID" "$PROMETHEUS_DIR"
chmod 755 "$DATA_ROOT" "$APP_DIR" "$PROMETHEUS_DIR" "$UPGRADES_DIR" "$BACKUPS_DIR" "$EXPORTS_DIR" "$COMPOSE_RUNTIME_DIR"

echo "SmartX HCI Capacity Insight data directories are ready."
echo "  app:        $APP_DIR -> root:root"
echo "  prometheus: $PROMETHEUS_DIR -> $PROMETHEUS_UID:$PROMETHEUS_GID"
echo "  upgrades:   $UPGRADES_DIR -> root:root"
echo "  backups:    $BACKUPS_DIR -> root:root"
echo "  exports:    $EXPORTS_DIR -> root:root"
echo "  runtime:    $COMPOSE_RUNTIME_DIR -> root:root"
