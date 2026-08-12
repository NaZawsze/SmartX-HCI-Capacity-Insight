#!/usr/bin/env sh
set -eu

INSTALL_ROOT="${SMARTX_INSTALL_ROOT:-/data/smartx-storage-forecast}"
PROJECT_DIR="${SMARTX_PROJECT_PATH:-$INSTALL_ROOT/project}"
APP_DIR="${SMARTX_DATA_ROOT:-$INSTALL_ROOT/app}"
PROMETHEUS_DIR="${SMARTX_PROMETHEUS_DATA_PATH:-$INSTALL_ROOT/prometheus}"
UPGRADES_DIR="${SMARTX_UPGRADES_DIR:-$INSTALL_ROOT/upgrades}"
BACKUPS_DIR="${SMARTX_BACKUPS_DIR:-$INSTALL_ROOT/backups}"
EXPORTS_DIR="${SMARTX_EXPORTS_DIR:-$INSTALL_ROOT/exports}"
COMPOSE_RUNTIME_DIR="${SMARTX_COMPOSE_RUNTIME_DIR:-$INSTALL_ROOT/compose-runtime}"
REPORT_EXPORT_DIR="$EXPORTS_DIR/reports"
MIGRATION_EXPORT_DIR="$EXPORTS_DIR/migrations"
MIGRATION_IMPORT_DIR="$EXPORTS_DIR/imports"
MIGRATION_TASK_DIR="$EXPORTS_DIR/migration-tasks"
PROMETHEUS_UID="${SMARTX_PROMETHEUS_UID:-65534}"
PROMETHEUS_GID="${SMARTX_PROMETHEUS_GID:-65534}"

if [ "$(id -u)" != "0" ]; then
  echo "pre_install.sh must be run as root." >&2
  exit 1
fi

mkdir -p "$INSTALL_ROOT" "$PROJECT_DIR" "$APP_DIR" "$PROMETHEUS_DIR" "$UPGRADES_DIR" "$BACKUPS_DIR" "$EXPORTS_DIR" "$COMPOSE_RUNTIME_DIR"
mkdir -p "$REPORT_EXPORT_DIR" "$MIGRATION_EXPORT_DIR" "$MIGRATION_IMPORT_DIR" "$MIGRATION_TASK_DIR"

chown root:root "$INSTALL_ROOT" "$PROJECT_DIR" "$APP_DIR" "$UPGRADES_DIR" "$BACKUPS_DIR" "$EXPORTS_DIR" "$COMPOSE_RUNTIME_DIR"
chown root:root "$REPORT_EXPORT_DIR" "$MIGRATION_EXPORT_DIR" "$MIGRATION_IMPORT_DIR" "$MIGRATION_TASK_DIR"
chown -R "$PROMETHEUS_UID:$PROMETHEUS_GID" "$PROMETHEUS_DIR"
chmod 755 "$INSTALL_ROOT" "$PROJECT_DIR" "$APP_DIR" "$PROMETHEUS_DIR" "$UPGRADES_DIR" "$BACKUPS_DIR" "$EXPORTS_DIR" "$COMPOSE_RUNTIME_DIR"
chmod 755 "$REPORT_EXPORT_DIR" "$MIGRATION_EXPORT_DIR" "$MIGRATION_IMPORT_DIR" "$MIGRATION_TASK_DIR"

echo "SmartX HCI Capacity Insight data directories are ready."
echo "  root:       $INSTALL_ROOT -> root:root, mode 755"
echo "  project:    $PROJECT_DIR -> root:root, mode 755"
echo "  app:        $APP_DIR -> root:root, mode 755"
echo "  prometheus: $PROMETHEUS_DIR -> $PROMETHEUS_UID:$PROMETHEUS_GID, mode 755"
echo "  upgrades:   $UPGRADES_DIR -> root:root, mode 755"
echo "  backups:    $BACKUPS_DIR -> root:root, mode 755"
echo "  exports:    $EXPORTS_DIR -> root:root, mode 755"
echo "    reports:          $REPORT_EXPORT_DIR"
echo "    migrations:       $MIGRATION_EXPORT_DIR"
echo "    imports:          $MIGRATION_IMPORT_DIR"
echo "    migration-tasks:  $MIGRATION_TASK_DIR"
echo "  runtime:    $COMPOSE_RUNTIME_DIR -> root:root, mode 755"
