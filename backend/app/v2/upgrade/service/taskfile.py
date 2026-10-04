from __future__ import annotations

"""Task file read/write and public task view helpers."""

import io
import json
import tarfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from app.v2.tasks.models import TaskStatus
from app.upgrade_runner.main import _action_steps as _runner_action_steps
from app.upgrade_runner.store import RevisionConflict, TaskStore

from ._compat import HTTPException, UploadFile

from .fs import _sha256_file

class TaskFileMixin:
    def _public_task(self, task: dict[str, Any]) -> dict[str, Any]:
        public = dict(task)
        public["task_id"] = str(task.get("task_id") or "")
        public["status"] = _public_status(str(task.get("status") or ""))
        # 包是否还在（2026-10-04）：`delete_package` 改为「只删包、保留记录」后，
        # 任务记录仍留在历史里（`started_at` 也仍在）。若前端仍按原条件显示
        # 「删除升级包」，就会变成「按钮还在、点了没反应」——比原来更糟。
        # 故显式暴露 `has_package`，由界面据此隐藏按钮或改文案。
        try:
            from .fs import has_upgrade_payload

            public["has_package"] = has_upgrade_payload(
                self.settings.upgrades_dir / public["task_id"]
            )
        except Exception:  # noqa: BLE001 - 视图不应因探测失败而报错
            public["has_package"] = True
        if task.get("status") == "recovery_required" and task.get("recovery_command") in {"continue", "rollback"}:
            public["status"] = "running"
        if str(task.get("status") or "") == "running":
            # US-25：把"执行中但没有任何 runner 持有"暴露出来，并给出可用的产品化操作
            try:
                from .runner_presence import task_lease_is_alive

                if not task_lease_is_alive(self.tasks.database, str(task.get("task_id") or "")):
                    public["runner_lost"] = True
                    public["available_recovery_actions"] = sorted(
                        set(public.get("available_recovery_actions") or []) | {"fail"}
                    )
            except Exception:  # noqa: BLE001 - 视图不应因判定失败而报错
                pass
        # US-31：任何 failed 任务都要能看到收尾指引，不只是走人工 recovery/fail 的那些。
        # 早期动作（如 image.load）失败是 runner 自行判定的，不经过任何人工入口，
        # 此前既无残留清单也无后续出路（.12 实测 available_recovery_actions 为 None）。
        if str(task.get("status") or "") == "failed":
            actions = set(public.get("available_recovery_actions") or [])
            if "cleanup_required" not in public:
                try:
                    public["residual_paths"] = public.get("residual_paths") or self._residual_legacy_paths()
                except Exception:  # noqa: BLE001 - 探测失败不应让任务列表报错
                    public["residual_paths"] = []
                public["cleanup_required"] = bool(public["residual_paths"])
            if public.get("cleanup_required") and public.get("residual_paths"):
                public["cleanup_guidance"] = (
                    f"环境可能处于半迁移状态，检测到残留路径：{'、'.join(public['residual_paths'])}。"
                    "请重新上传并执行一次完整升级，由升级后清理（post-cleanup）收尾；"
                    "在此之前不要开始新的升级任务。"
                )
            if not actions:
                # 失败任务永远保留 fail 入口，便于统一走产品化的收尾/取证流程
                public["available_recovery_actions"] = sorted(actions | {"fail"})
        public.setdefault("available_recovery_actions", None)
        if public["available_recovery_actions"] is None:
            public["available_recovery_actions"] = []
        public["package_filename"] = task.get("filename") or task.get("package_filename")
        public["uploaded_at"] = task.get("created_at") or task.get("uploaded_at")
        public["package_sha256"] = task.get("package_sha256") or task.get("uploaded_sha256") or _task_package_sha256(task)
        public["uploaded_sha256"] = task.get("uploaded_sha256") or public["package_sha256"]
        checks = task.get("checks") or []
        public["precheck_ok"] = task.get("status") == "precheck_passed"
        public["checks"] = task.get("checks") or []
        public["steps"] = _runner_action_steps(task) if task.get("execution_plan") else task.get("steps") or []
        public["logs"] = task.get("logs") or []
        components = _component_types_from_task(task)
        public["components"] = sorted(components)
        if components and components <= {"runner"}:
            public["kind"] = "component"
            public["component"] = "upgrade-runner"
        elif components and components <= {"observability"}:
            public["kind"] = "component"
            public["component"] = "prometheus"
        else:
            public["kind"] = "platform"
            public["component"] = None
        public["ok"] = bool(public["precheck_ok"] or public["status"] in {"succeeded", "running", "pending", "rolled_back"})
        if task.get("status") == "success":
            public.setdefault("finished_at", task.get("updated_at"))
        return public


    def _read_task_or_pending_record(self, task_id: str, task_dir: Path) -> dict[str, Any]:
        try:
            return _read_task_file(task_dir)
        except HTTPException as exc:
            if exc.status_code != 404:
                raise
        record = self.tasks.get_task(task_id)
        if not record or record.get("status") != TaskStatus.PENDING.value:
            raise HTTPException(status_code=404, detail="升级任务不存在。")
        return {
            "task_id": task_id,
            "status": "pending",
            "target_version": record.get("message") or "",
            "components": ["platform"],
            "checks": [],
            "steps": [],
            "logs": [],
        }


def _component_types(manifest: dict[str, Any]) -> list[str]:
    return [str(component.get("type")) for component in manifest.get("components") or [] if component.get("type")]



def _component_types_from_task(task: dict[str, Any]) -> set[str]:
    components = {str(component) for component in task.get("components") or [] if component}
    if components:
        return components
    manifest = task.get("manifest") if isinstance(task.get("manifest"), dict) else {}
    components = set(_component_types(manifest))
    if components:
        return components
    component = str(task.get("component") or "")
    if component == "upgrade-runner":
        return {"runner"}
    if component == "prometheus":
        return {"observability"}
    return set()



def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value or "").strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            try:
                parsed = datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)



def _first_task_timestamp(task: dict[str, Any], fields: tuple[str, ...]) -> float:
    for field in fields:
        parsed = _parse_datetime(task.get(field))
        if parsed is not None:
            return parsed.timestamp()
    return float("-inf")



def _history_task_sort_key(task: dict[str, Any]) -> tuple[float, str]:
    timestamp = _first_task_timestamp(
        task,
        ("created_at", "uploaded_at", "started_at", "finished_at", "updated_at"),
    )
    return timestamp, str(task.get("task_id") or "")



def _successful_package_sort_key(task: dict[str, Any]) -> tuple[float, str]:
    timestamp = _first_task_timestamp(
        task,
        ("finished_at", "uploaded_at", "created_at", "started_at", "updated_at"),
    )
    return timestamp, str(task.get("task_id") or "")



def _task_package_sha256(task: dict[str, Any]) -> str:
    uploaded = task.get("uploaded_path")
    if uploaded:
        path = Path(str(uploaded))
        if path.is_file():
            return _sha256_file(path)
    return str(task.get("package_sha256") or task.get("uploaded_sha256") or "")



def _step(key: str, title: str, status: str, message: str = "") -> dict[str, str]:
    return {"key": key, "title": title, "status": status, "message": message}



def _replace_step(steps: list[dict[str, Any]], key: str, status: str, message: str = "") -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for step in steps:
        if step.get("key") == key:
            next_step = dict(step)
            next_step["status"] = status
            if message:
                next_step["message"] = message
            result.append(next_step)
        else:
            result.append(step)
    return result



def _add_json(archive: tarfile.TarFile, arcname: str, payload: dict[str, Any], generated_at: datetime) -> None:
    content = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    info = tarfile.TarInfo(arcname)
    info.size = len(content)
    info.mtime = int(generated_at.timestamp())
    archive.addfile(info, io.BytesIO(content))



def _add_directory(archive: tarfile.TarFile, source: Path, arcname: str, *, skip_names: set[str]) -> None:
    if not source.exists():
        return
    for path in sorted(source.rglob("*")):
        relative = path.relative_to(source)
        if any(part in skip_names for part in relative.parts):
            continue
        archive.add(path, arcname=str(Path(arcname) / relative), recursive=False)



def _save_task_file(task_dir: Path, task: dict[str, Any]) -> None:
    expected_revision = int(task.get("revision") or 0) if (task_dir / "task.json").is_file() else None
    try:
        saved = TaskStore(task_dir).save(task, expected_revision=expected_revision)
        task["revision"] = saved["revision"]
    except RevisionConflict as exc:
        raise HTTPException(status_code=409, detail="升级任务状态已变化，请刷新后重试。") from exc



def _read_task_file(task_dir: Path) -> dict[str, Any]:
    path = task_dir / "task.json"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="升级任务不存在。")
    return TaskStore(task_dir).load()



def _public_status(status: str) -> str:
    return {
        "uploaded": "uploaded",
        "precheck_passed": "prechecked",
        "precheck_failed": "failed",
        "pending": "pending",
        "running": "running",
        "runner_restarting": "running",
        "recovery_required": "recovery_required",
        "rollback_running": "running",
        "rollback_failed": "failed",
        "success": "succeeded",
        "failed": "failed",
        "cancelled": "cancelled",
    }.get(status, status)



def _completed_runner_task_view(task: dict[str, Any]) -> dict[str, Any]:
    actions = task.get("execution_plan", {}).get("actions") or []
    terminal_statuses = {"success", "failed", "rollback_failed", "rolled_back", "recovery_required", "cancelled"}
    if not actions or str(task.get("status") or "") in terminal_statuses:
        return task
    if not all(str(action.get("status") or "") in {"succeeded", "skipped"} for action in actions):
        return task
    completed = dict(task)
    completed["status"] = "success"
    completed["recovery_status"] = "none"
    completed["available_recovery_actions"] = []
    return completed
