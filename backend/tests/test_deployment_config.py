"""Deployment/compose configuration assertions (unittest, no pytest dependency).

Converted from pytest style so the suite runs inside the web-api image
(which does not ship pytest). The v1 report_export assertions were dropped
after the v1 dead-code removal; the v2 export font check now reads the
export/ package.
"""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _load_build_module():
    module_path = ROOT / "scripts/build_upgrade_package.py"
    spec = importlib.util.spec_from_file_location("build_upgrade_package", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestDeploymentConfig(unittest.TestCase):
    def test_compose_mounts_runtime_artifacts_outside_app_data(self) -> None:
        for name in ("docker-compose.yml", "docker-compose.offline.yml", "docker-compose.release.yml"):
            text = (ROOT / name).read_text(encoding="utf-8")
            self.assertIn("/data/smartx-storage-forecast/app:/data", text)
            self.assertIn("/data/smartx-storage-forecast/upgrades:/data/upgrades", text)
            self.assertIn("/data/smartx-storage-forecast/backups:/data/backups", text)
            self.assertIn("/data/smartx-storage-forecast/exports:/data/exports", text)
            self.assertIn("/data/smartx-storage-forecast/compose-runtime:/data/compose-runtime", text)
            self.assertIn("/data/smartx-storage-forecast/project:/data/smartx-storage-forecast/project", text)
            self.assertIn("/data/smartx-storage-forecast/prometheus:/prometheus", text)
            self.assertNotIn("/data/smartx-capacity-insight-data", text)
            self.assertNotIn("/opt/smartx-storage-forecast", text)
            self.assertNotIn("- /data/compose-runtime:", text)
            self.assertNotIn("SMARTX_HOST_COMPOSE_RUNTIME_PATH: /data/compose-runtime", text)

    def test_pre_install_creates_runtime_artifact_directories(self) -> None:
        text = (ROOT / "pre_install.sh").read_text(encoding="utf-8")
        for value in (
            "/data/smartx-storage-forecast",
            "$INSTALL_ROOT/project",
            "$INSTALL_ROOT/app",
            "$INSTALL_ROOT/prometheus",
            "$INSTALL_ROOT/upgrades",
            "$INSTALL_ROOT/backups",
            "$INSTALL_ROOT/exports",
            "$INSTALL_ROOT/compose-runtime",
        ):
            self.assertIn(value, text)

    def test_upgrade_package_migrate_script_only_syncs_project_files(self) -> None:
        module = _load_build_module()
        with tempfile.TemporaryDirectory() as tmp:
            script_path = Path(tmp) / "migrate.sh"
            module.write_migrate_script(script_path, "v0.5.2")
            text = script_path.read_text(encoding="utf-8")

            self.assertIn('project_files = manifest.get("project_file_list") or []', text)
            self.assertIn("override_path.write_text", text)
            self.assertNotIn("migrate_legacy_artifacts", text)
            self.assertNotIn("/host-data", text)
            self.assertNotIn("/package-project", text)
            self.assertNotIn("docker-compose.runner-upgrade.yml.before-", text)
            self.assertNotIn("runner_override.unlink()", text)
            self.assertNotIn("copy_task_file_if_newer", text)

    def test_platform_package_rejects_web_api_image_without_v2_health_route(self) -> None:
        module = _load_build_module()
        original_run = module.run

        def fake_run(command, cwd=module.ROOT):
            if command[:2] == ["docker", "save"]:
                output = Path(command[command.index("-o") + 1])
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_bytes(b"fake image")
                return ""
            if command[:2] == ["docker", "run"]:
                return "legacy app without v2 health"
            return ""

        module.run = fake_run
        try:
            with tempfile.TemporaryDirectory() as tmp:
                with self.assertRaises(SystemExit) as raised:
                    module.build_package(
                        "v0.5.2",
                        min_version="v0.5.2",
                        output_dir=Path(tmp),
                        build_images=False,
                        include_frontend_build=False,
                        allow_existing_images=True,
                        check_version_metadata=False,
                    )
            self.assertIn("/api/system/health", str(raised.exception))
        finally:
            module.run = original_run

    def test_compose_splits_platform_and_runner_versions(self) -> None:
        for name in ("docker-compose.yml", "docker-compose.offline.yml", "docker-compose.release.yml"):
            text = (ROOT / name).read_text(encoding="utf-8")
            self.assertIn("SMARTX_IMAGE_TAG:-v0.5.2", text)
            self.assertIn("SMARTX_RUNNER_IMAGE_TAG:-v0.3.1", text)
            self.assertNotIn("upgrade-runner:${SMARTX_IMAGE_TAG", text)
            self.assertNotIn("SMARTX_IMAGE_TAG:-v0.4.0", text)
            self.assertNotIn(":local", text)

    def test_compose_project_name_is_consistent_across_runtime_and_upgrade(self) -> None:
        for name in ("docker-compose.yml", "docker-compose.offline.yml", "docker-compose.release.yml"):
            text = (ROOT / name).read_text(encoding="utf-8")
            self.assertTrue(text.startswith("name: smartx-hci-capacity-insight\n"))
            self.assertIn("SMARTX_COMPOSE_PROJECT_NAME: smartx-hci-capacity-insight", text)
            self.assertNotIn("name: smartx-storage-forecast_smartx-net", text)
            self.assertIn("name: smartx-hci-capacity-insight-net", text)
            self.assertNotIn("SMARTX_COMPOSE_PROJECT_NAME: smartx-capacity-insight", text)
        deployment_text = (ROOT / "docs/deployment.md").read_text(encoding="utf-8")
        self.assertIn("docker compose -f docker-compose.release.yml up -d", deployment_text)
        self.assertIn("docker compose -f docker-compose.offline.yml up -d", deployment_text)
        self.assertIn("smartx-hci-capacity-insight-net", deployment_text)

    def test_backend_images_carry_platform_and_runner_version_files(self) -> None:
        for name in ("backend/Dockerfile", "backend/Dockerfile.worker", "backend/Dockerfile.upgrade"):
            text = (ROOT / name).read_text(encoding="utf-8")
            self.assertIn("COPY VERSION ./VERSION", text)
            self.assertIn("COPY RUNNER_VERSION ./RUNNER_VERSION", text)

    def test_deployment_docs_use_explicit_platform_and_runner_tags(self) -> None:
        text = (ROOT / "docs/deployment.md").read_text(encoding="utf-8")

        self.assertNotIn("uses local `latest` image tags by default", text)
        self.assertNotIn("SMARTX_IMAGE_TAG=v0.3.1", text)
        self.assertNotIn("nazawsze/smartx-hci-capacity-insight-web-api:latest", text)
        self.assertNotIn("nazawsze/smartx-hci-capacity-insight-upgrade-runner:latest", text)
        self.assertIn("nazawsze/smartx-hci-capacity-insight-web-api:v0.5.2", text)
        self.assertIn("nazawsze/smartx-hci-capacity-insight-upgrade-runner:v0.3.1", text)

    def test_platform_upgrade_package_excludes_runner(self) -> None:
        text = (ROOT / "scripts/build_upgrade_package.py").read_text(encoding="utf-8")
        self.assertNotIn('"images/upgrade-runner.tar"', text)
        self.assertNotIn("and the offline upgrade-runner image", text)
        self.assertNotIn('("upgrade-runner",', text)

    def test_upgrade_runner_uses_standalone_runner_entrypoint(self) -> None:
        for name in ("docker-compose.yml", "docker-compose.offline.yml", "docker-compose.release.yml", "backend/Dockerfile.upgrade"):
            text = (ROOT / name).read_text(encoding="utf-8")
            self.assertIn("app.upgrade_runner.main", text)
        runner = (ROOT / "backend/app/upgrade_runner/main.py").read_text(encoding="utf-8")
        self.assertNotIn("app.v2.upgrade.service", runner)
        dockerfile = (ROOT / "backend/Dockerfile.upgrade").read_text(encoding="utf-8")
        self.assertIn("COPY backend/app/upgrade_runner ./app/upgrade_runner", dockerfile)
        self.assertIn("COPY backend/app/upgrade_protocol ./app/upgrade_protocol", dockerfile)
        self.assertNotIn("COPY backend/app ./app", dockerfile)

    def test_upgrade_runner_receives_host_paths_for_sandbox_mounts(self) -> None:
        for name in ("docker-compose.yml", "docker-compose.offline.yml", "docker-compose.release.yml"):
            text = (ROOT / name).read_text(encoding="utf-8")
            runner_section = text.split("  upgrade-runner:\n", 1)[1].split("  prometheus:\n", 1)[0]
            self.assertIn("SMARTX_HOST_PROJECT_PATH: /data/smartx-storage-forecast/project", runner_section)
            self.assertIn("SMARTX_HOST_DATA_PATH: /data/smartx-storage-forecast/app", runner_section)
            self.assertIn("SMARTX_HOST_BACKUPS_PATH: /data/smartx-storage-forecast/backups", runner_section)
            self.assertIn("SMARTX_HOST_COMPOSE_RUNTIME_PATH: /data/smartx-storage-forecast/compose-runtime", runner_section)
            self.assertIn("SMARTX_HOST_PROMETHEUS_DATA_PATH: /data/smartx-storage-forecast/prometheus", runner_section)
            self.assertIn("chmod 600 /data/smartx-storage-forecast/project/.env", runner_section)
            self.assertIn("exec python -m app.upgrade_runner.main", runner_section)

    def test_web_api_repairs_migrated_env_permissions_before_startup(self) -> None:
        for name in ("docker-compose.yml", "docker-compose.offline.yml", "docker-compose.release.yml"):
            text = (ROOT / name).read_text(encoding="utf-8")
            web_api_section = text.split("  web-api:\n", 1)[1].split("  collector-worker:\n", 1)[0]

            self.assertIn(
                'command: ["sh", "-c", "chmod 600 /run/smartx-runtime.env '
                '&& exec uvicorn app.v2.main:app --host 0.0.0.0 --port 8000"]',
                web_api_section,
            )
            self.assertIn("/data/smartx-storage-forecast/project/.env:/run/smartx-runtime.env", web_api_section)
            self.assertIn("/data/smartx-storage-forecast/project:/data/smartx-storage-forecast/project:ro", web_api_section)

    def test_v052_compose_uses_target_project_network_and_subnet(self) -> None:
        for name in ("docker-compose.yml", "docker-compose.offline.yml", "docker-compose.release.yml"):
            text = (ROOT / name).read_text(encoding="utf-8")
            self.assertTrue(text.startswith("name: smartx-hci-capacity-insight\n"))
            self.assertIn("name: smartx-hci-capacity-insight-net", text)
            self.assertIn("subnet: 10.249.251.0/24", text)
            self.assertNotIn("subnet: 10.249.249.0/24", text)

    def test_upgrade_runner_dependencies_do_not_pull_web_api_stack(self) -> None:
        text = (ROOT / "backend/requirements-upgrade.txt").read_text(encoding="utf-8")
        self.assertNotIn("fastapi", text)
        self.assertNotIn("pydantic", text)
        self.assertNotIn("python-multipart", text)

    def test_web_api_image_uses_slim_runtime_dependencies(self) -> None:
        dockerfile = (ROOT / "backend/Dockerfile").read_text(encoding="utf-8")
        requirements = (ROOT / "backend/requirements-api.txt").read_text(encoding="utf-8")
        v2_report_export = (ROOT / "backend/app/v2/reports/export/common.py").read_text(encoding="utf-8")

        self.assertNotIn("uvicorn[standard]", requirements)
        self.assertIn("uvicorn==0.34.0", requirements)
        self.assertNotIn("fonts-noto-core", dockerfile)
        self.assertIn("fonts-noto-cjk", dockerfile)
        self.assertIn("NotoSerifCJK-Regular.ttc", dockerfile)
        self.assertNotIn("NotoSerifCJK-Bold.ttc", dockerfile)
        self.assertNotIn("NotoSansCJK-Regular.ttc", dockerfile)
        self.assertIn("fc-cache -f", dockerfile)
        self.assertIn("__pycache__", dockerfile)
        self.assertIn("*.pyc", dockerfile)
        self.assertIn("find ./app -type d -name __pycache__", dockerfile)
        self.assertIn("find ./app -type f -name '*.pyc'", dockerfile)
        self.assertIn("-name tests", dockerfile)
        self.assertIn("-name test", dockerfile)
        self.assertNotIn(".dist-info", dockerfile)
        self.assertNotIn('[CHART_FONT_FAMILY, "Noto Serif", "DejaVu Serif"]', v2_report_export)
        self.assertIn('[CHART_FONT_FAMILY, "DejaVu Serif"]', v2_report_export)

    def test_frontend_docker_context_excludes_local_build_artifacts(self) -> None:
        dockerignore = ROOT / "frontend/.dockerignore"
        self.assertTrue(dockerignore.is_file())
        ignored = {line.strip() for line in dockerignore.read_text(encoding="utf-8").splitlines() if line.strip()}

        self.assertIn("node_modules", ignored)
        self.assertIn("dist", ignored)
        self.assertIn("coverage", ignored)
        self.assertIn("*.tsbuildinfo", ignored)

    def test_upgrade_override_uses_platform_release_images(self) -> None:
        text = (ROOT / "docker-compose.upgrade.yml").read_text(encoding="utf-8")
        self.assertIn("nazawsze/smartx-hci-capacity-insight-web-api:v0.5.2", text)
        self.assertIn("nazawsze/smartx-hci-capacity-insight-collector-worker:v0.5.2", text)
        self.assertIn("nazawsze/smartx-hci-capacity-insight-frontend:v0.5.2", text)
        self.assertNotIn("smartx-storage-forecast-web-api:v0.4.0", text)

    def test_runner_workflow_is_separate_from_platform_workflow(self) -> None:
        platform = (ROOT / ".github/workflows/docker-images.yml").read_text(encoding="utf-8")
        runner = (ROOT / ".github/workflows/upgrade-runner-image.yml").read_text(encoding="utf-8")
        self.assertNotIn("smartx-hci-capacity-insight-upgrade-runner", platform)
        self.assertIn('tags:\n      - "runner-v*"', runner)
        self.assertIn("type=raw,value=${{ steps.version.outputs.tag }}", runner)


if __name__ == "__main__":
    unittest.main()
