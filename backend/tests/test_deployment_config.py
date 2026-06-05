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


def test_upgrade_package_migrate_script_only_syncs_project_files(tmp_path) -> None:
    root = Path(__file__).resolve().parents[2]
    module_path = root / "scripts/build_upgrade_package.py"
    spec = importlib.util.spec_from_file_location("build_upgrade_package", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    script_path = tmp_path / "migrate.sh"
    module.write_migrate_script(script_path, "v0.4.1")
    text = script_path.read_text(encoding="utf-8")

    assert "project_files = manifest.get(\"project_files\") or []" in text
    assert "override_path.write_text" in text
    assert "migrate_legacy_artifacts" not in text
    assert "/host-data" not in text
    assert "/package-project" not in text
    assert "docker-compose.runner-upgrade.yml.before-" not in text
    assert "runner_override.unlink()" not in text
    assert "copy_task_file_if_newer" not in text


def test_compose_splits_platform_and_runner_versions() -> None:
    root = Path(__file__).resolve().parents[2]
    for name in ("docker-compose.offline.yml", "docker-compose.release.yml"):
        text = (root / name).read_text(encoding="utf-8")
        assert "SMARTX_IMAGE_TAG:-v0.4.1" in text
        assert "SMARTX_RUNNER_IMAGE_TAG:-v0.2.2" in text
        assert "upgrade-runner:${SMARTX_IMAGE_TAG" not in text
        assert "SMARTX_IMAGE_TAG:-v0.4.0" not in text


def test_platform_upgrade_package_excludes_runner() -> None:
    root = Path(__file__).resolve().parents[2]
    text = (root / "scripts/build_upgrade_package.py").read_text(encoding="utf-8")
    assert '"images/upgrade-runner.tar"' not in text
    assert "and the offline upgrade-runner image" not in text
    assert '("upgrade-runner",' not in text


def test_upgrade_override_uses_platform_release_images() -> None:
    root = Path(__file__).resolve().parents[2]
    text = (root / "docker-compose.upgrade.yml").read_text(encoding="utf-8")
    assert "nazawsze/smartx-hci-capacity-insight-web-api:v0.4.1" in text
    assert "nazawsze/smartx-hci-capacity-insight-collector-worker:v0.4.1" in text
    assert "nazawsze/smartx-hci-capacity-insight-frontend:v0.4.1" in text
    assert "smartx-storage-forecast-web-api:v0.4.0" not in text


def test_runner_workflow_is_separate_from_platform_workflow() -> None:
    root = Path(__file__).resolve().parents[2]
    platform = (root / ".github/workflows/docker-images.yml").read_text(encoding="utf-8")
    runner = (root / ".github/workflows/upgrade-runner-image.yml").read_text(encoding="utf-8")
    assert "smartx-hci-capacity-insight-upgrade-runner" not in platform
    assert 'tags:\n      - "runner-v*"' in runner
    assert "type=raw,value=${{ steps.version.outputs.tag }}" in runner


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
