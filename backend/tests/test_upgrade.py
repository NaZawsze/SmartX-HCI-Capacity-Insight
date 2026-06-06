from app.core.config import read_app_version, read_runner_version
from app.services import upgrade
from fastapi import HTTPException


def test_verification_summary_uses_latest_successful_platform_task(monkeypatch):
    monkeypatch.setattr(upgrade, "_platform_runtime_services", lambda: [])
    monkeypatch.setattr(upgrade, "_task_package_sha256", lambda task: "c" * 64)
    monkeypatch.setattr(upgrade, "_latest_successful_platform_task", lambda: {
        "task_id": "abc123",
        "package_filename": "smartx-capacity-insight-upgrade-v0.5.0.tar.gz",
        "uploaded_at": "2026-06-02T01:00:00+00:00",
        "finished_at": "2026-06-02T01:05:00+00:00",
        "manifest": {
            "version": "v0.5.0",
            "images": [
                {"service": "web-api", "file": "images/web-api.tar", "sha256": "a" * 64},
                {"service": "frontend", "file": "images/frontend.tar", "sha256": "b" * 64},
            ],
        },
    })

    summary = upgrade.verification_summary()

    assert summary["package"]["version"] == "v0.5.0"
    assert summary["package"]["sha256"] == "c" * 64
    assert summary["package"]["image_sha256"] == {"web-api": "a" * 64, "frontend": "b" * 64}


def test_read_app_version_prefers_image_version_file(tmp_path, monkeypatch) -> None:
    version_file = tmp_path / "VERSION"
    version_file.write_text("v9.9.9\n", encoding="utf-8")
    monkeypatch.setenv("SMARTX_APP_VERSION", "v1.0.0")

    assert read_app_version(version_file) == "v9.9.9"


def test_read_app_version_falls_back_to_environment(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SMARTX_APP_VERSION", "v1.0.0")

    assert read_app_version(tmp_path / "missing") == "v1.0.0"


def test_read_runner_version_prefers_image_runner_version_file(tmp_path, monkeypatch) -> None:
    version_file = tmp_path / "RUNNER_VERSION"
    version_file.write_text("v0.9.9\n", encoding="utf-8")
    monkeypatch.setenv("SMARTX_RUNNER_VERSION", "v0.1.0")

    assert read_runner_version(version_file) == "v0.9.9"


def test_read_runner_version_falls_back_to_environment(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SMARTX_RUNNER_VERSION", "v0.1.0")

    assert read_runner_version(tmp_path / "missing") == "v0.1.0"

class _UpgradeTestSettings:
    def __init__(self, root):
        self.data_path = root / "data"
        self.project_path = root / "readonly-project"
        self.compose_file = "docker-compose.offline.yml"
        self.compose_project_name = "smartx-capacity-insight"
        self.upgrade_path = self.data_path / "upgrades"
        self.backup_path = self.data_path / "backups"
        self.prometheus_data_path = root / "prometheus"
        self.runtime_path = root / "compose-runtime"
        self.app_version = "v-test"
        self.runner_version = "v0.1.0"


def test_runner_override_is_written_to_data_compose_runtime(tmp_path, monkeypatch):
    settings = _UpgradeTestSettings(tmp_path)
    settings.data_path.mkdir(parents=True)
    settings.project_path.mkdir(parents=True)
    monkeypatch.setattr(upgrade, "get_settings", lambda: settings)

    task = {"manifest": {"images": [{"service": "upgrade-runner", "image": "runner:v0.2.1"}]}}

    message = upgrade._write_runner_override(task)

    runtime_path = settings.runtime_path / "docker-compose.runner-upgrade.yml"
    project_path = settings.project_path / "docker-compose.runner-upgrade.yml"
    assert message == f"已写入 {runtime_path}"
    assert runtime_path.read_text(encoding="utf-8") == "services:\n  upgrade-runner:\n    image: runner:v0.2.1\n"
    assert not project_path.exists()


def test_compose_command_uses_data_runner_override(tmp_path, monkeypatch):
    settings = _UpgradeTestSettings(tmp_path)
    settings.data_path.mkdir(parents=True)
    settings.project_path.mkdir(parents=True)
    compose_path = settings.project_path / settings.compose_file
    compose_path.write_text("services: {}\n", encoding="utf-8")
    runtime_path = settings.runtime_path / "docker-compose.runner-upgrade.yml"
    runtime_path.parent.mkdir(parents=True)
    runtime_path.write_text("services:\n  upgrade-runner:\n    image: runner:v0.2.1\n", encoding="utf-8")
    monkeypatch.setattr(upgrade, "get_settings", lambda: settings)
    monkeypatch.setattr(upgrade, "_has_docker_compose_plugin", lambda: True)
    monkeypatch.setattr(upgrade, "_docker_safe_compose_file", lambda path: path)

    command = upgrade._compose_command(runner_override=True)

    assert str(runtime_path) in command
    assert str(settings.project_path / "docker-compose.runner-upgrade.yml") not in command


def test_compose_cwd_uses_container_project_path(tmp_path, monkeypatch):
    settings = _UpgradeTestSettings(tmp_path)
    settings.data_path.mkdir(parents=True)
    settings.project_path.mkdir(parents=True)
    host_path = tmp_path / "host-project-not-mounted-in-container"
    host_path.mkdir()
    monkeypatch.setattr(upgrade, "get_settings", lambda: settings)
    monkeypatch.setenv("SMARTX_HOST_PROJECT_PATH", str(host_path))

    assert upgrade._docker_safe_project_path() == host_path
    assert upgrade._compose_cwd() == settings.project_path


def test_compose_cwd_falls_back_to_data_path(tmp_path, monkeypatch):
    settings = _UpgradeTestSettings(tmp_path)
    settings.data_path.mkdir(parents=True)
    monkeypatch.setattr(upgrade, "get_settings", lambda: settings)

    assert upgrade._compose_cwd() == settings.data_path



def test_runner_override_uses_runtime_path_not_data_subdirectory(tmp_path, monkeypatch):
    settings = _UpgradeTestSettings(tmp_path)
    settings.data_path.mkdir(parents=True)
    settings.runtime_path.mkdir(parents=True)
    monkeypatch.setattr(upgrade, "get_settings", lambda: settings)

    task = {"manifest": {"images": [{"service": "upgrade-runner", "image": "runner:v0.3.0"}]}}
    upgrade._write_runner_override(task)

    assert (settings.runtime_path / "docker-compose.runner-upgrade.yml").exists()
    assert not (settings.data_path / "compose-runtime" / "docker-compose.runner-upgrade.yml").exists()


def test_start_upgrade_assumes_runner_v022_runtime_is_ready(tmp_path, monkeypatch):
    settings = _UpgradeTestSettings(tmp_path)
    task = {
        "task_id": "abc123",
        "status": "prechecked",
        "precheck_ok": True,
        "logs": [],
        "manifest": {"version": "v0.5.0"},
    }
    saved = {}
    monkeypatch.setattr(upgrade, "get_settings", lambda: settings)
    monkeypatch.setattr(upgrade, "_load_task_or_404", lambda task_id: task)
    monkeypatch.setattr(upgrade, "_save_task", lambda value: saved.update(value))

    result = upgrade.start_upgrade("abc123")

    assert result["status"] == "pending"
    assert saved["status"] == "pending"
    assert "upgrade-runner 运行时挂载" not in "\n".join(saved["logs"])


def test_platform_manifest_rejects_upgrade_runner_service():
    manifest = {
        "product": "smartx-storage-forecast",
        "version": "v0.5.0",
        "images": [
            {"service": "web-api", "file": "images/web-api.tar", "image": "nazawsze/smartx-hci-capacity-insight-web-api:v0.5.0"},
            {"service": "collector-worker", "file": "images/collector-worker.tar", "image": "nazawsze/smartx-hci-capacity-insight-collector-worker:v0.5.0"},
            {"service": "frontend", "file": "images/frontend.tar", "image": "nazawsze/smartx-hci-capacity-insight-frontend:v0.5.0"},
            {"service": "upgrade-runner", "file": "images/upgrade-runner.tar", "image": "nazawsze/smartx-hci-capacity-insight-upgrade-runner:v0.3.0"},
        ],
        "restart_services": ["web-api", "collector-worker", "frontend"],
        "project_files": ["docker-compose.offline.yml", "docker-compose.release.yml"],
    }

    try:
        upgrade._validate_manifest_shape(manifest)
    except HTTPException as exc:
        assert "不支持升级服务：upgrade-runner" in str(exc.detail)
    else:
        raise AssertionError("platform manifest accepted upgrade-runner")
