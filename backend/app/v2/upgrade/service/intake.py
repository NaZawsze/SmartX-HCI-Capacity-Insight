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
from .taskfile import _completed_runner_task_view, _component_types, _component_types_from_task, _history_task_sort_key, _read_task_file, _save_task_file, _task_package_sha256

from .constants import MANIFEST_NAME
from .precheck import (
    COMPRESSED_ARCHIVE_EXPANSION,
    _version_from_service_status,
    human_bytes,
    required_upgrade_bytes,
)
from .runner_presence import RUNNER_PRESENCE_SOURCES

class IntakeMixin:
    async def upload_package(self, upload: UploadFile) -> dict[str, Any]:
        return self.upload_package_bytes(await upload.read(), filename=upload.filename or "upgrade.tar.gz")


    def _precheck_upload_space(self, content: bytes) -> None:
        """上传前检查磁盘是否装得下，不够则抛 400 并给出可读提示。

        口径与 precheck 的 `disk_space` 检查**完全一致**——直接复用它的
        `package_payload_bytes`（压缩包按 `COMPRESSED_ARCHIVE_EXPANSION` 估膨胀）
        与 `required_upgrade_bytes`（payload + headroom），只是把时机提前到写盘之前，
        让 ENOSPC 变成一句「磁盘空间不足：X 可用 Y GiB，升级需要 Z GiB」。

        局部导入是为了避免 intake ↔ precheck 的模块级循环依赖。
        """
        from .precheck import (  # noqa: PLC0415 - 避免模块级环
            required_upgrade_bytes,
        )

        # 阈值与判定顺序对齐 precheck 的 disk_space 检查（同函数、同常量、同去重逻辑），
        # 差别只在「算required 用的输入」：上传阶段只有压缩包字节，用膨胀系数估解包量。
        required = required_upgrade_bytes(
            int(len(content)) * COMPRESSED_ARCHIVE_EXPANSION,
            int(self.settings.upgrade_disk_headroom_bytes),
        )
        worst: tuple[str, int] | None = None
        seen_devices: set[int] = set()
        for path in (self.settings.upgrades_dir, self.settings.backups_dir, Path("/")):
            try:
                if path.stat().st_dev in seen_devices:
                    continue
                seen_devices.add(path.stat().st_dev)
                free = shutil.disk_usage(path).free
            except OSError:
                continue
            if free < required and (worst is None or free < worst[1]):
                worst = (str(path), int(free))
        if worst is not None:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"磁盘空间不足：{worst[0]} 可用 {human_bytes(worst[1])}，"
                    f"上传该升级包需要 {human_bytes(required)}"
                    f"（含解包空间与安全余量）。"
                    f"请先到「系统 → 空间清理」释放空间，或改用更大的磁盘。"
                ),
            )

    def upload_package_bytes(self, content: bytes, *, filename: str) -> dict[str, Any]:
        if not content:
            raise HTTPException(status_code=400, detail="升级包为空。")
        task_id = f"upgrade-{token_hex(8)}"
        task_dir = self.settings.upgrades_dir / task_id
        # 上传前置空间检查（2026-10-04）：磁盘预检查在 precheck 阶段才跑，
        # 那时包已落盘（242M 包 + 611M 解包 = 853M）。磁盘真不够时用户会在
        # 「写盘」这一步撞上 ENOSPC，只看到一句底层 IO 报错。
        # 这里提前用**同一个** required_upgrade_bytes 口径给出可读提示。
        self._precheck_upload_space(content)
        # 从建目录到落 task.json 整段包进 try：任何一步失败都必须删掉 task_dir。
        #
        # 缺陷（2026-10-04 追查）：原先只有 tar 解析失败那一条分支会 rmtree，
        # 而「建目录 → 写 200M 包 → 解包 → 读 manifest → 写 task.json」之间还有 4 个
        # 未受保护的点（write_bytes / _read_manifest / _component_types / _save_task_file）。
        # 磁盘满或 manifest 异常时任一失败，都会留下「有package/ 但无 task.json」的残缺目录——
        # 它在升级中心历史里读不出内容（history 只扫 */task.json），空间清理又会把它
        # 当散落包整删。三台机器当时都没出现，只因还没撞上磁盘满。
        try:
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
        except Exception:
            # 半成品目录一律不留：既不占磁盘，也不污染历史与清理判定
            shutil.rmtree(task_dir, ignore_errors=True)
            raise
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
