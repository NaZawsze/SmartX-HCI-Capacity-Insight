from __future__ import annotations

"""Upgrade package intake: upload, history, version, component catalog."""

import io
import json
import shutil
import tarfile
from pathlib import Path
from secrets import token_hex
from typing import Any
from app.v2.tasks.models import TaskStatus, TaskType
from app.upgrade_protocol.constants import RUNNER_CAPABILITIES, RUNNER_PROTOCOL_VERSION

from ._compat import HTTPException, UploadFile

from .fs import _now, _safe_extract, _sha256_file, _validate_members
from .precheck import _version_from_service_status
from .taskfile import _completed_runner_task_view, _component_types, _component_types_from_task, _history_task_sort_key, _read_task_file, _save_task_file, _task_package_sha256

from .constants import MANIFEST_NAME
from .runner_presence import RUNNER_PRESENCE_SOURCES

class IntakeMixin:
    async def upload_package(self, upload: UploadFile) -> dict[str, Any]:
        return self.upload_package_bytes(await upload.read(), filename=upload.filename or "upgrade.tar.gz")


    def upload_package_bytes(self, content: bytes, *, filename: str) -> dict[str, Any]:
        if not content:
            raise HTTPException(status_code=400, detail="升级包为空。")
        task_id = f"upgrade-{token_hex(8)}"
        task_dir = self.settings.upgrades_dir / task_id
        package_path = task_dir / "package"
        package_path.mkdir(parents=True, exist_ok=True)
        upload_path = task_dir / Path(filename).name
        upload_path.write_bytes(content)
        uploaded_sha256 = _sha256_file(upload_path)
        try:
            with tarfile.open(fileobj=io.BytesIO(content), mode="r:gz") as archive:
                _validate_members(archive)
                _safe_extract(archive, package_path)
        except (tarfile.TarError, OSError) as exc:
            shutil.rmtree(task_dir, ignore_errors=True)
            raise HTTPException(status_code=400, detail=f"无法读取升级包：{exc}") from exc
        manifest = _read_manifest(package_path / MANIFEST_NAME)
        components = _component_types(manifest)
        task = {
            "task_id": task_id,
            "status": "uploaded",
            "target_version": str(manifest.get("version") or ""),
            "components": components,
            "manifest": manifest,
            "filename": Path(filename).name,
            "package_path": str(package_path),
            "uploaded_path": str(upload_path),
            "uploaded_sha256": uploaded_sha256,
            "package_sha256": uploaded_sha256,
            "created_at": _now().isoformat(),
            "checks": [],
        }
        _save_task_file(task_dir, task)
        self.tasks.create_task(task_id, TaskType.UPGRADE, "上传升级包", status=TaskStatus.SUCCESS, progress=100, message=f"升级包已上传：{task['target_version']}")
        return self._public_task(task)


    def history(self, *, component_type: str | None = None) -> list[dict[str, Any]]:
        tasks: list[dict[str, Any]] = []
        for task_file in self.settings.upgrades_dir.glob("*/task.json"):
            task = _completed_runner_task_view(_read_task_file(task_file.parent))
            if component_type and component_type not in _component_types_from_task(task):
                continue
            tasks.append(task)
        tasks.sort(key=_history_task_sort_key, reverse=True)
        return [self._public_task(task) for task in tasks]


    def delete_package(self, task_id: str) -> dict[str, Any]:
        task_dir = self.settings.upgrades_dir / task_id
        task = _read_task_file(task_dir)
        if task.get("status") in {"running", "pending", "runner_restarting", "recovery_required", "rollback_pending", "rollback_running"}:
            raise HTTPException(status_code=400, detail="升级任务正在执行或需要恢复，不能删除。")
        shutil.rmtree(task_dir, ignore_errors=True)
        return {"ok": True, "task_id": task_id}


    def version(self) -> dict[str, str]:
        return {"version": self.settings.app_version}


    def component_version(self) -> dict[str, str]:
        return {"component": "upgrade-runner", "version": self._active_runner_version()}


    def component_catalog(self) -> dict[str, Any]:
        prometheus_status = self._inspect_service_by_name("prometheus")
        prometheus_version = _version_from_service_status(prometheus_status) or "-"
        runner_state = self._active_runner_state()
        runner_version = self._active_runner_version(runner_state)
        runner_capabilities = runner_state.get("capabilities", []) if runner_state else []
        compatible = bool(
            runner_state
            and runner_state.get("source") in RUNNER_PRESENCE_SOURCES
            and int(runner_state.get("protocol_version") or 0) >= RUNNER_PROTOCOL_VERSION
            and RUNNER_CAPABILITIES <= set(runner_capabilities)
        )
        return {
            "components": [
                {
                    "type": "runner",
                    "display_name": "升级中心组件",
                    "service": "upgrade-runner",
                    "version": runner_version,
                    "protocol_version": runner_state.get("protocol_version") if runner_state else None,
                    "capabilities": runner_capabilities,
                    "heartbeat_at": runner_state.get("heartbeat_at") if runner_state else None,
                    "compatible": compatible,
                    "executor": "web-api",
                    "upgradeable": True,
                    "status_message": "由 web-api 执行自升级，不修改业务库和历史指标。",
                },
                {
                    "type": "observability",
                    "display_name": "观测组件",
                    "service": "prometheus",
                    "version": prometheus_version,
                    "executor": "upgrade-runner",
                    "upgradeable": True,
                    "status_message": prometheus_status.get("error") or "由 upgrade-runner 执行升级，保留 Prometheus 历史指标。",
                },
            ]
        }


def _read_manifest(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise HTTPException(status_code=400, detail="升级包缺少 manifest.json。")
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="manifest.json 格式不正确。") from exc
    if manifest.get("schema_version") not in {"2", "3"}:
        raise HTTPException(status_code=400, detail="升级包 schema_version 必须为 2 或 3。")
    return manifest



def _is_real_platform_package_task(task: dict[str, Any]) -> bool:
    manifest = task.get("manifest") if isinstance(task.get("manifest"), dict) else {}
    if task.get("task_type") == "post_upgrade_cleanup" or manifest.get("package_type") == "post_upgrade_cleanup":
        return False
    if task.get("kind") == "component":
        return False
    if "platform" not in _component_types_from_task(task):
        return False
    return bool(task.get("package_filename") and (task.get("package_sha256") or task.get("uploaded_sha256") or _task_package_sha256(task)))
