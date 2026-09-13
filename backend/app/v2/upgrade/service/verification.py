from __future__ import annotations

"""Upgrade verification and runtime service inspection."""

import json
from typing import Any

from .intake import _is_real_platform_package_task
from .precheck import _service_from_docker_ps_item, _version_from_env, _version_from_image, _version_from_service_status
from .taskfile import _successful_package_sort_key

class VerificationMixin:
    def verification(self) -> dict[str, Any]:
        success_packages = [task for task in self.history() if task.get("status") == "succeeded" and _is_real_platform_package_task(task)]
        latest_package = max(success_packages, key=_successful_package_sort_key, default=None)
        services, service_status_error, actual_compose_project = self._runtime_services()
        prometheus_version = next((_version_from_service_status(service) for service in services if service.get("service") == "prometheus"), None)
        if not prometheus_version:
            prometheus_version = _version_from_service_status(self._inspect_service_by_name("prometheus")) or "-"
        return {
            "app_version": self.settings.app_version,
            "runner_version": self._active_runner_version(),
            "prometheus_version": prometheus_version,
            "compose_project": actual_compose_project,
            "compose_file": self.settings.compose_file,
            "package": {
                "task_id": latest_package.get("task_id"),
                "version": latest_package.get("target_version"),
                "filename": latest_package.get("package_filename"),
                "sha256": latest_package.get("package_sha256") or latest_package.get("uploaded_sha256"),
                "uploaded_at": latest_package.get("uploaded_at"),
                "finished_at": latest_package.get("finished_at"),
            }
            if latest_package
            else None,
            "service_status_error": service_status_error,
            "services": services,
        }


    def _runtime_services(self) -> tuple[list[dict[str, Any]], str | None, str]:
        compose_error: Exception | None = None
        try:
            output = self.executor.output(["docker", "compose", "-f", self.settings.compose_file, "--project-name", self.settings.compose_project_name, "ps", "--format", "json"], cwd=self.project_path)
        except Exception as exc:
            compose_error = exc
            output = ""
        services: list[dict[str, Any]] = []
        for raw_line in output.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            service = str(item.get("Service") or item.get("Name") or "")
            container = str(item.get("Name") or item.get("Container") or service)
            if not service:
                continue
            services.append(self._inspect_container(service, container, fallback_status=str(item.get("State") or item.get("Status") or "")))
        if services:
            return services, None, self.settings.compose_project_name
        fallback_services = self._runtime_services_from_docker_ps()
        if fallback_services:
            return fallback_services, None, self.settings.compose_project_name
        actual_project = self._current_compose_project()
        if actual_project and actual_project != self.settings.compose_project_name:
            fallback_services = self._runtime_services_from_docker_ps(actual_project)
            if fallback_services:
                return fallback_services, None, actual_project
        if compose_error is not None:
            return [], f"Docker 状态读取失败：{compose_error}", self.settings.compose_project_name
        return services, None, self.settings.compose_project_name


    def _runtime_services_from_docker_ps(self, compose_project: str | None = None) -> list[dict[str, Any]]:
        project = compose_project or self.settings.compose_project_name
        try:
            output = self.executor.output(
                [
                    "docker",
                    "ps",
                    "-a",
                    "--filter",
                    f"label=com.docker.compose.project={project}",
                    "--format",
                    "{{json .}}",
                ],
                cwd=self.project_path,
            )
        except Exception:
            return []
        services: list[dict[str, Any]] = []
        for raw_line in output.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            service = _service_from_docker_ps_item(item)
            container = str(item.get("Names") or item.get("Name") or item.get("Container") or service)
            if not service or not container:
                continue
            services.append(self._inspect_container(service, container, fallback_status=str(item.get("State") or item.get("Status") or "")))
        order = {service: index for index, service in enumerate(["web-api", "collector-worker", "frontend", "prometheus", "upgrade-runner"])}
        return sorted(services, key=lambda item: order.get(str(item.get("service")), 99))


    def _current_compose_project(self) -> str | None:
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
        labels = (inspected.get("Config") or {}).get("Labels") or {}
        project = labels.get("com.docker.compose.project")
        return str(project).strip() if project else None


    def _inspect_service_by_name(self, service: str) -> dict[str, Any]:
        container = f"{self.settings.compose_project_name}-{service}-1"
        return self._inspect_container(service, container)


    def _inspect_container(self, service: str, container: str, *, fallback_status: str = "") -> dict[str, Any]:
        result = {
            "service": service,
            "container": container,
            "status": fallback_status,
            "running": fallback_status == "running",
            "image": "",
            "image_id": "",
            "app_version": None,
            "started_at": None,
            "error": None,
        }
        try:
            output = self.executor.output(["docker", "inspect", container], cwd=self.project_path)
            payload = json.loads(output or "[]")
            inspected = payload[0] if payload else {}
        except Exception as exc:
            result["error"] = str(exc)
            return result
        config = inspected.get("Config") or {}
        state = inspected.get("State") or {}
        env = config.get("Env") or []
        image = str(config.get("Image") or "")
        status = str(state.get("Status") or fallback_status)
        result.update(
            {
                "status": status,
                "running": bool(state.get("Running")) or status == "running",
                "image": image,
                "image_id": str(inspected.get("Image") or ""),
                "app_version": _version_from_env(env) or _version_from_image(image),
                "started_at": state.get("StartedAt"),
            }
        )
        return result
