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


def test_backend_images_carry_platform_and_runner_version_files() -> None:
    root = Path(__file__).resolve().parents[2]
    for name in ("backend/Dockerfile", "backend/Dockerfile.worker", "backend/Dockerfile.upgrade"):
        text = (root / name).read_text(encoding="utf-8")
        assert "COPY VERSION ./VERSION" in text
        assert "COPY RUNNER_VERSION ./RUNNER_VERSION" in text


def test_deployment_docs_use_explicit_platform_and_runner_tags() -> None:
    root = Path(__file__).resolve().parents[2]
    text = (root / "docs/deployment.md").read_text(encoding="utf-8")

    assert "uses local `latest` image tags by default" not in text
    assert "SMARTX_IMAGE_TAG=v0.3.1" not in text
    assert "nazawsze/smartx-hci-capacity-insight-web-api:latest" not in text
    assert "nazawsze/smartx-hci-capacity-insight-upgrade-runner:latest" not in text
    assert "SMARTX_IMAGE_TAG=v0.4.1" in text
    assert "SMARTX_RUNNER_IMAGE_TAG=v0.2.2" in text
    assert "nazawsze/smartx-hci-capacity-insight-web-api:v0.4.1" in text
    assert "nazawsze/smartx-hci-capacity-insight-upgrade-runner:v0.2.2" in text


def test_platform_upgrade_package_excludes_runner() -> None:
    root = Path(__file__).resolve().parents[2]
    text = (root / "scripts/build_upgrade_package.py").read_text(encoding="utf-8")
    assert '"images/upgrade-runner.tar"' not in text
    assert "and the offline upgrade-runner image" not in text
    assert '("upgrade-runner",' not in text


def test_upgrade_runner_uses_v2_runner_entrypoint() -> None:
    root = Path(__file__).resolve().parents[2]
    for name in ("docker-compose.yml", "docker-compose.offline.yml", "docker-compose.release.yml", "backend/Dockerfile.upgrade"):
        text = (root / name).read_text(encoding="utf-8")
        assert "app.v2.upgrade.runner" in text
        assert "app.upgrade.runner" not in text


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


def test_upgrade_backup_reports_progress() -> None:
    root = Path(__file__).resolve().parents[2]
    backend = (root / "backend/app/services/upgrade.py").read_text(encoding="utf-8")
    frontend = (root / "frontend/src/pages/ServicePage.tsx").read_text(encoding="utf-8")

    assert "class _BackupProgress" in backend
    assert 'task["backup_total_bytes"]' in backend
    assert '"backup_processed_bytes"' in backend
    assert "备份中 {percent}%" in backend
    assert "activeUpgradeDetail(next)" in frontend


def test_upgrade_precheck_checks_network_and_project_closure() -> None:
    root = Path(__file__).resolve().parents[2]
    backend = (root / "backend/app/services/upgrade.py").read_text(encoding="utf-8")
    frontend = (root / "frontend/src/pages/ServicePage.tsx").read_text(encoding="utf-8")

    assert 'EXPECTED_NETWORK_SUBNET = "10.249.249.0/24"' in backend
    assert 'check("network", network_ok, network_message, network_detail)' in backend
    assert '"volumes", "network", "compose-tag"' in frontend
    assert '"project-files"' in frontend
    assert "formatCheckMessages(relatedFailed)" in frontend


def test_image_cleanup_deletes_scanned_candidates() -> None:
    root = Path(__file__).resolve().parents[2]
    text = (root / "backend/app/services/system_control.py").read_text(encoding="utf-8")

    assert 'before = scan_unused_images()' in text
    assert '"/images/prune' not in text
    assert 'DELETE", f"/images/{quote(image_id' in text
    assert '"space_reclaimable_before_label"' in text
    assert '"errors": errors' in text


def test_space_cleanup_keeps_cleanup_result_visible() -> None:
    root = Path(__file__).resolve().parents[2]
    text = (root / "frontend/src/pages/ServicePage.tsx").read_text(encoding="utf-8")

    assert 'setSpaceCleanupTotal(result.space_reclaimed_label)' in text
    assert 'setSpaceCleanupItems([])' in text
    assert 'await scanSpaceCleanup();' not in text
