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
