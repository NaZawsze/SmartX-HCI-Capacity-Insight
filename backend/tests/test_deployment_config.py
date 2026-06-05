from pathlib import Path
import importlib.util


def test_compose_mounts_runtime_artifacts_outside_app_data() -> None:
    root = Path(__file__).resolve().parents[2]
    for name in ("docker-compose.yml", "docker-compose.offline.yml", "docker-compose.release.yml"):
        text = (root / name).read_text(encoding="utf-8")
        assert "/data/smartx-capacity-insight-data/app:/data" in text
        assert "/data/upgrades:/data/upgrades" in text
        assert "/data/backups:/data/backups" in text
        assert "/data/exports:/data/exports" in text
        assert "/data/compose-runtime:/data/compose-runtime" in text


def test_pre_install_creates_runtime_artifact_directories() -> None:
    root = Path(__file__).resolve().parents[2]
    text = (root / "pre_install.sh").read_text(encoding="utf-8")
    for value in ("/data/upgrades", "/data/backups", "/data/exports", "/data/compose-runtime"):
        assert value in text


def test_upgrade_package_migrate_script_refreshes_runtime_compose(tmp_path) -> None:
    root = Path(__file__).resolve().parents[2]
    module_path = root / "scripts/build_upgrade_package.py"
    spec = importlib.util.spec_from_file_location("build_upgrade_package", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    script_path = tmp_path / "migrate.sh"
    module.write_migrate_script(script_path, "v0.4.0")
    text = script_path.read_text(encoding="utf-8")

    assert "/data:/host-data" in text
    assert "/package-project:ro" in text
    assert "sync_runtime_compose" in text
    assert "docker-compose.offline.yml" in text
    assert "docker-compose.runner-upgrade.yml.before-" in text
    assert "runner_override.unlink()" in text
    assert "copy_task_file_if_newer" in text
    assert "task_updated_at(dst) >= task_updated_at(src)" in text
    assert "child.name.startswith('docker-compose.runner-upgrade.yml')" in text

def test_migration_and_report_artifacts_live_under_exports() -> None:
    root = Path(__file__).resolve().parents[2]
    data_migration = (root / "backend/app/services/data_migration.py").read_text(encoding="utf-8")
    report_export = (root / "backend/app/services/report_export.py").read_text(encoding="utf-8")
    system_control = (root / "backend/app/services/system_control.py").read_text(encoding="utf-8")

    assert 'settings.export_path / "migrations"' in data_migration
    assert 'settings.export_path / "migration-tasks"' in data_migration or "EXPORT_TASK_DIR" in data_migration
    assert 'IMPORT_TASK_DIR = "imports"' in data_migration
    assert "settings.export_path / IMPORT_TASK_DIR" in data_migration
    assert 'settings.export_path / "reports"' in report_export
    assert "migration_imports" in system_control

def test_upgrade_backup_skips_legacy_runtime_artifacts() -> None:
    root = Path(__file__).resolve().parents[2]
    text = (root / "backend/app/services/upgrade.py").read_text(encoding="utf-8")

    assert '"compose-runtime"' in text
    assert '"upgrades"' in text
    assert '"backups"' in text
    assert '"exports"' in text
