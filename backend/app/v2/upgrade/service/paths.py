from __future__ import annotations

"""Host path resolution and override/backup writers."""

import json
import os

import shutil
import tarfile
from pathlib import Path
from typing import Any

from ._compat import HTTPException, UploadFile

from .fs import _backup_existing_project_path, _now
from .precheck import _runner_bootstrap, _runner_bootstrap_target_root, _runner_only, _runtime_network_name
from .taskfile import _add_directory, _add_json

from .constants import MANIFEST_NAME

class PathsMixin:
    def _create_upgrade_backup(self, task: dict[str, Any]) -> Path:
        generated_at = _now()
        version = str(task.get("target_version") or "unknown").replace("/", "-")
        self.settings.backups_dir.mkdir(parents=True, exist_ok=True)
        path = self.settings.backups_dir / f"upgrade-{version}-before-{generated_at.strftime('%Y%m%d%H%M%S')}.tar.gz"
        manifest = {
            "format": "smartx-capacity-insight-v2-upgrade-backup",
            "version": 1,
            "generated_at": generated_at.isoformat(),
            "source_task_id": task.get("task_id"),
            "target_version": task.get("target_version"),
            "components": task.get("components", []),
        }
        with tarfile.open(path, mode="w:gz") as archive:
            _add_json(archive, MANIFEST_NAME, manifest, generated_at)
            if self.settings.sqlite_path.exists():
                archive.add(self.settings.sqlite_path, arcname="app/smartx.db", recursive=False)
            _add_directory(archive, self.settings.prometheus_data_dir, "prometheus", skip_names={"chunks_head", "lock", "queries.active", "wal"})
        return path


    def _sync_project_files(self, task: dict[str, Any]) -> Path | None:
        if not task.get("manifest", {}).get("project_files"):
            return None
        package_project = Path(task["package_path"]) / "project"
        if not package_project.is_dir():
            return None
        version = str(task.get("target_version") or "unknown").replace("/", "-")
        backup_dir = self.settings.backups_dir / f"project-files-before-{version}-{_now().strftime('%Y%m%d%H%M%S')}"
        for source in sorted(package_project.rglob("*")):
            if source.is_dir():
                continue
            relative = source.relative_to(package_project)
            target = self.project_path / relative
            backup = backup_dir / relative
            _backup_existing_project_path(target, backup)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        return backup_dir


    def _write_upgrade_override(self, images: list[dict[str, Any]]) -> Path:
        self.settings.compose_runtime_dir.mkdir(parents=True, exist_ok=True)
        path = self.settings.compose_runtime_dir / "docker-compose.upgrade.yml"
        return self._write_override(path, images)


    def _write_runner_override(self, manifest: dict[str, Any], images: list[dict[str, Any]]) -> Path:
        self.settings.compose_runtime_dir.mkdir(parents=True, exist_ok=True)
        bootstrap = _runner_bootstrap(manifest)
        path = self.settings.compose_runtime_dir / (
            "docker-compose.runner-bootstrap.yml" if bootstrap else "docker-compose.runner-upgrade.yml"
        )
        runner_image = next((str(image["image"]) for image in images if image.get("service") == "upgrade-runner"), "")
        if not runner_image:
            raise HTTPException(status_code=400, detail="Runner 组件包缺少 upgrade-runner 镜像。")
        project_name = str(bootstrap.get("target_project") or self.settings.compose_project_name) if bootstrap else self.settings.compose_project_name
        network_name = (
            str(bootstrap.get("target_network") or _runtime_network_name(project_name))
            if bootstrap
            else _runtime_network_name(project_name)
        )
        subnet = str(bootstrap.get("target_subnet") or "").strip() if bootstrap else ""
        host_data_path = self._host_data_path()
        host_upgrades_path = self._host_upgrades_path()
        host_backups_path = self._host_backups_path()
        host_exports_path = self._host_exports_path()
        host_compose_runtime_path = self._host_compose_runtime_path()
        host_prometheus_path = self._host_prometheus_path()
        host_project_path = self._host_project_path()
        target_root_path = _runner_bootstrap_target_root(bootstrap)
        target_root_volume = f"      - {target_root_path}:{target_root_path}\n" if target_root_path else ""
        network_block = (
            f"""  smartx-net:
    name: {network_name}
    ipam:
      config:
        - subnet: {subnet}
"""
            if subnet
            else f"""  smartx-net:
    external: true
    name: {network_name}
"""
        )
        content = f"""services:
  upgrade-runner:
    image: {runner_image}
    command: ["python", "-m", "app.upgrade_runner.main"]
    environment:
      TZ: Asia/Shanghai
      SMARTX_PROJECT_PATH: {self.project_path}
      SMARTX_COMPOSE_FILE: {self.settings.compose_file}
      SMARTX_COMPOSE_PROJECT_NAME: {project_name}
      SMARTX_DB_PATH: /data/smartx.db
      SMARTX_UPGRADES_PATH: /data/upgrades
      SMARTX_BACKUPS_PATH: /data/backups
      SMARTX_EXPORTS_PATH: /data/exports
      SMARTX_COMPOSE_RUNTIME_PATH: /data/compose-runtime
      SMARTX_PROMETHEUS_DATA_PATH: /prometheus-data
      SMARTX_HOST_DATA_PATH: {host_data_path}
      SMARTX_HOST_UPGRADES_PATH: {host_upgrades_path}
      SMARTX_HOST_BACKUPS_PATH: {host_backups_path}
      SMARTX_HOST_EXPORTS_PATH: {host_exports_path}
      SMARTX_HOST_COMPOSE_RUNTIME_PATH: {host_compose_runtime_path}
      SMARTX_HOST_PROMETHEUS_DATA_PATH: {host_prometheus_path}
      SMARTX_HOST_PROJECT_PATH: {host_project_path}
    volumes:
      - {host_project_path}:{self.project_path}
      - {host_data_path}:/data
      - {host_upgrades_path}:/data/upgrades
      - {host_backups_path}:/data/backups
      - {host_exports_path}:/data/exports
      - {host_compose_runtime_path}:/data/compose-runtime
      - {host_prometheus_path}:/prometheus-data
{target_root_volume.rstrip()}
      - /var/run/docker.sock:/var/run/docker.sock
    networks:
      - smartx-net
    restart: unless-stopped

networks:
{network_block.rstrip()}
"""
        path.write_text(content, encoding="utf-8")
        return path


    def _write_task_override(self, manifest: dict[str, Any], images: list[dict[str, Any]]) -> Path:
        if _runner_only(manifest):
            return self._write_runner_override(manifest, images)
        return self._write_upgrade_override(images)


    def _write_override(self, path: Path, images: list[dict[str, Any]]) -> Path:
        lines = ["services:"]
        for image in images:
            service = str(image["service"])
            lines.extend([f"  {service}:", f"    image: {image['image']}"])
            if service == "upgrade-runner":
                lines.append('    command: ["python", "-m", "app.upgrade_runner.main"]')
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path


    def _sync_runner_image_into_compose_files(self, runner_image: str) -> list[str]:
        """US-26：runner 组件升级成功后，把新 tag 回写到所有会被 `docker compose up` 读到的文件。

        此前只有 `compose-runtime/docker-compose.runner-bootstrap.yml` 记录新 tag，而
        `project/docker-compose.yml` 与 `compose-runtime/docker-compose.runner-upgrade.yml`
        保持旧 tag —— tag 没有单一事实源，下一次平台升级会按旧 tag 把 runner 拉回去。
        回写后「project compose 为准，runtime compose 与其一致」。

        用逐行状态机而非整块正则：真实 compose 里 `upgrade-runner:` 之后可能还有 `build:`/
        `env_file:` 等多行键，`image:` 位置不固定。
        """
        if not runner_image:
            return []
        updated: list[str] = []
        candidates = [
            self.project_path / "docker-compose.yml",
            self.settings.compose_runtime_dir / "docker-compose.runner-upgrade.yml",
        ]
        for candidate in candidates:
            try:
                if not candidate.is_file():
                    continue
                lines = candidate.read_text(encoding="utf-8").splitlines(keepends=True)
            except OSError:
                continue
            in_runner = False
            changed = False
            for index, line in enumerate(lines):
                stripped = line.strip()
                if not in_runner:
                    if stripped == "upgrade-runner:" or stripped.startswith("upgrade-runner:"):
                        in_runner = True
                    continue
                # 已离开 upgrade-runner 服务块（下一个同级键或 services 之外）
                if line[:1].strip() == "" and stripped and ":" in stripped and not stripped.startswith("#"):
                    if not line.startswith((" ", "\t")):
                        break
                if stripped.startswith("image:"):
                    current = stripped.split("image:", 1)[1].strip()
                    if current == runner_image:
                        changed = False
                        break
                    prefix = line[: line.index("image:") + len("image:")]
                    newline = "\n" if line.endswith("\n") else ""
                    lines[index] = f"{prefix} {runner_image}{newline}"
                    changed = True
                    break
            if not changed:
                continue
            try:
                candidate.write_text("".join(lines), encoding="utf-8")
            except OSError:
                continue
            updated.append(str(candidate))
        return updated


    def _host_data_path(self) -> Path:
        return self._host_path("SMARTX_HOST_DATA_PATH", "/data", "/data/smartx-storage-forecast/app")


    def _host_upgrades_path(self) -> Path:
        return self._host_path("SMARTX_HOST_UPGRADES_PATH", "/data/upgrades", "/data/smartx-storage-forecast/upgrades")


    def _host_backups_path(self) -> Path:
        return self._host_path("SMARTX_HOST_BACKUPS_PATH", "/data/backups", "/data/smartx-storage-forecast/backups")


    def _host_exports_path(self) -> Path:
        return self._host_path("SMARTX_HOST_EXPORTS_PATH", "/data/exports", "/data/smartx-storage-forecast/exports")


    def _host_compose_runtime_path(self) -> Path:
        return self._host_path("SMARTX_HOST_COMPOSE_RUNTIME_PATH", "/data/compose-runtime", "/data/smartx-storage-forecast/compose-runtime")


    def _host_prometheus_path(self) -> Path:
        return self._host_path("SMARTX_HOST_PROMETHEUS_DATA_PATH", "/prometheus-data", "/data/smartx-storage-forecast/prometheus")


    def _host_project_path(self) -> Path:
        return self._host_path("SMARTX_HOST_PROJECT_PATH", str(self.project_path), "/data/smartx-storage-forecast/project")


    def _host_path(self, env_name: str, destination: str, fallback: str) -> Path:
        configured = os.environ.get(env_name)
        if configured:
            return Path(configured)
        mounted = self._container_mount_source(destination)
        if mounted:
            return Path(mounted)
        return Path(fallback)


    def _container_mount_source(self, destination: str) -> str | None:
        try:
            container_id = self.hostname_path.read_text(encoding="utf-8").strip()
        except OSError:
            return None
        if not container_id:
            return None
        try:
            output = self.executor.output(["docker", "inspect", container_id], cwd=self.project_path)
            payload = json.loads(output or "[]")
        except Exception:
            return None
        inspected = payload[0] if payload else {}
        for mount in inspected.get("Mounts") or []:
            if mount.get("Destination") == destination and mount.get("Source"):
                return str(mount["Source"])
        return None
