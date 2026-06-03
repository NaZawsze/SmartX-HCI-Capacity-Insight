from app.core.config import read_app_version
from app.services import upgrade


def test_verification_summary_uses_latest_successful_platform_task(monkeypatch):
    monkeypatch.setattr(upgrade, "_platform_runtime_services", lambda: [])
    monkeypatch.setattr(upgrade, "_task_package_sha256", lambda task: "c" * 64)
    monkeypatch.setattr(upgrade, "_latest_successful_platform_task", lambda: {
        "task_id": "abc123",
        "package_filename": "smartx-capacity-insight-upgrade-v0.4.0.tar.gz",
        "uploaded_at": "2026-06-02T01:00:00+00:00",
        "finished_at": "2026-06-02T01:05:00+00:00",
        "manifest": {
            "version": "v0.4.0",
            "images": [
                {"service": "web-api", "file": "images/web-api.tar", "sha256": "a" * 64},
                {"service": "frontend", "file": "images/frontend.tar", "sha256": "b" * 64},
            ],
        },
    })

    summary = upgrade.verification_summary()

    assert summary["package"]["version"] == "v0.4.0"
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
