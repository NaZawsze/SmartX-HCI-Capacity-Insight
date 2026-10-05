from __future__ import annotations

import json
import logging
import os
import signal
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.upgrade_runner.actions import ActionContext, CommandExecutor, default_handlers
from app.upgrade_runner.engine import UpgradeEngine
from app.upgrade_runner.lease import LeaseManager
from app.upgrade_runner.store import TaskStore

logger = logging.getLogger(__name__)


@dataclass
class RunnerSettings:
    database_path: Path
    upgrades_path: Path
    data_path: Path
    exports_path: Path
    backups_path: Path
    compose_runtime_path: Path
    prometheus_path: Path
    project_path: Path
    compose_file: str
    compose_project: str
    runner_version: str = "v0.3.2"
    host_data_path: Path | None = None
    host_upgrades_path: Path | None = None
    host_backups_path: Path | None = None
    host_exports_path: Path | None = None
    host_compose_runtime_path: Path | None = None
    host_prometheus_path: Path | None = None
    host_project_path: Path | None = None

    @classmethod
    def from_environment(cls) -> "RunnerSettings":
        database_path = Path(os.environ.get("SMARTX_DB_PATH", "/data/smartx.db"))
        project_path = Path(os.environ.get("SMARTX_PROJECT_PATH", "/data/smartx-storage-forecast/project"))
        return cls(
            database_path=database_path,
            upgrades_path=Path(os.environ.get("SMARTX_UPGRADES_PATH", "/data/upgrades")),
            data_path=database_path.parent,
            exports_path=Path(os.environ.get("SMARTX_EXPORTS_PATH", "/data/exports")),
            backups_path=Path(os.environ.get("SMARTX_BACKUPS_PATH", "/data/backups")),
            compose_runtime_path=Path(os.environ.get("SMARTX_COMPOSE_RUNTIME_PATH", "/data/compose-runtime")),
            prometheus_path=Path(os.environ.get("SMARTX_PROMETHEUS_DATA_PATH", "/prometheus-data")),
            project_path=project_path,
            compose_file=os.environ.get("SMARTX_COMPOSE_FILE", "docker-compose.offline.yml"),
            compose_project=os.environ.get("SMARTX_COMPOSE_PROJECT_NAME", "smartx-hci-capacity-insight"),
            runner_version=os.environ.get("SMARTX_RUNNER_VERSION", "v0.3.2"),
            host_data_path=Path(os.environ.get("SMARTX_HOST_DATA_PATH", "/data/smartx-storage-forecast/app")),
            host_upgrades_path=Path(os.environ.get("SMARTX_HOST_UPGRADES_PATH", "/data/smartx-storage-forecast/upgrades")),
            host_backups_path=Path(os.environ.get("SMARTX_HOST_BACKUPS_PATH", "/data/smartx-storage-forecast/backups")),
            host_exports_path=Path(os.environ.get("SMARTX_HOST_EXPORTS_PATH", "/data/smartx-storage-forecast/exports")),
            host_compose_runtime_path=Path(os.environ.get("SMARTX_HOST_COMPOSE_RUNTIME_PATH", "/data/smartx-storage-forecast/compose-runtime")),
            host_prometheus_path=Path(
                os.environ.get("SMARTX_HOST_PROMETHEUS_DATA_PATH", "/data/smartx-storage-forecast/prometheus")
            ),
            host_project_path=Path(os.environ.get("SMARTX_HOST_PROJECT_PATH", str(project_path))),
        )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _replace_step(steps: list[dict[str, Any]], key: str, status: str, message: str = "") -> list[dict[str, Any]]:
    replaced = False
    next_steps: list[dict[str, Any]] = []
    for step in steps:
        if step.get("key") == key:
            copied = dict(step)
            copied["status"] = status
            copied["message"] = message
            next_steps.append(copied)
            replaced = True
        else:
            next_steps.append(dict(step))
    if not replaced:
        next_steps.append({"key": key, "title": key, "status": status, "message": message})
    return next_steps


def _has_unfinished_steps(task: dict[str, Any]) -> bool:
    return any(step.get("status") in {"pending", "running"} for step in task.get("steps") or [])


def _is_runner_component_task(task: dict[str, Any]) -> bool:
    components = {str(component) for component in task.get("components") or []}
    if components:
        return components <= {"runner"}
    manifest_components = {str(component.get("type")) for component in (task.get("manifest") or {}).get("components") or []}
    return bool(manifest_components) and manifest_components <= {"runner"}


PACKAGELESS_TASK_TYPES = {"post_upgrade_cleanup"}

#: W3：走自换路径的组件任务用的动作类型（只出现在 v0.3.2+ runner 执行的任务里）。
SELF_HANDOFF_ACTIONS = frozenset(
    {
        "component.verify",
        "component.image_load",
        "component.compose_writeback",
        "component.schedule_self_handoff",
    }
)


def _is_self_handoff_task(task: dict[str, Any]) -> bool:
    """该任务是否是走自换路径的组件升级任务（计划里含 `component.*` 动作）。"""
    if not _is_runner_component_task(task):
        return False
    actions = task.get("execution_plan", {}).get("actions") or []
    return any(str(action.get("type") or "") in SELF_HANDOFF_ACTIONS for action in actions)


def _is_self_handoff_scheduled(task: dict[str, Any]) -> bool:
    """该任务是否已调度自换、且还在等新 runner 收尾。

    只认 `self_handoff.scheduled` 这个**由旧 runner 在 handoff 之前写下**的标记；
    不从动作类型反推（动作类型只能说明"计划里有什么"，说明不了"走到了哪一步"）。
    """
    handoff = task.get("self_handoff")
    if not isinstance(handoff, dict) or not handoff.get("scheduled"):
        return False
    if str(task.get("status") or "") not in {"running", "runner_restarting"}:
        return False
    actions = task.get("execution_plan", {}).get("actions") or []
    return any(str(action.get("type") or "") in SELF_HANDOFF_ACTIONS for action in actions)


def _inject_self_handoff_anchor(
    settings: Any,
    task: dict[str, Any],
    *,
    executor: CommandExecutor,
) -> dict[str, Any]:
    """自换任务在**执行前**捕获回滚锚点并注入计划（W3 用户硬要求 b）。

    ## 为什么锚点必须在 writeback 之前拿

    `component.compose_writeback` 会把 `docker-compose.yml` 里的 runner image 行
    覆盖成新镜像。覆盖之后"上一版的 tag / 镜像 ID"在磁盘上就**再也读不到**了，
    而组件回滚（反向自换）恰恰只能靠这两个值。顺序反了，锚点里记到的就是新版本，
    回滚退化成"把新版本换回新版本"——看起来成功了，现场其实没回退。

    ## 为什么在整条任务的开头捕获，而不是紧贴 writeback

    锚点读的是「compose 里的 tag」与「运行中容器的镜像」，两者只被
    `component.compose_writeback` 改动；`component.verify` 与 `component.image_load`
    都不碰 project 目录。所以开头捕获与紧贴 writeback 捕获读到的值**完全相同**，
    而开头捕获少一处需要在 engine 里开的回调口子。

    ## 幂等

    已在 `self_handoff.rollback_anchor` 里有锚点时不重复捕获——任务被恢复重跑时
    沿用第一次捕获的值，避免"恢复到一半再捕一次"读到的是 writeback 后的新 tag。
    """
    handoff = task.get("self_handoff")
    if not isinstance(handoff, dict):
        handoff = {}
    if handoff.get("rollback_anchor"):
        return task
    from app.upgrade_runner.actions import ActionContext
    from app.upgrade_runner.selfhandoff import capture_component_rollback_anchor

    context = ActionContext(
        package_path=Path(str(task.get("package_path") or "")),
        project_path=Path(settings.project_path),
        data_path=Path(settings.data_path),
        upgrades_path=Path(settings.upgrades_path),
        backups_path=Path(settings.backups_path),
        exports_path=Path(settings.exports_path),
        compose_runtime_path=Path(settings.compose_runtime_path),
        prometheus_path=Path(settings.prometheus_path),
        compose_file=settings.compose_file,
        compose_project=settings.compose_project,
        executor=executor,
    )
    target_version = str((handoff.get("target_version") or task.get("target_version") or ""))
    anchor = capture_component_rollback_anchor(
        context, task, executor=executor, target_version=target_version
    )
    handoff["rollback_anchor"] = anchor
    handoff["target_version"] = target_version
    task["self_handoff"] = handoff
    # 注入到 writeback 与 handoff 两个动作的 params：writeback 侧留痕，handoff 侧是硬要求
    for action in task.get("execution_plan", {}).get("actions") or []:
        if str(action.get("type") or "") in {
            "component.compose_writeback",
            "component.schedule_self_handoff",
        }:
            action.setdefault("params", {})
            action["params"]["rollback_anchor"] = anchor
    return task


def _package_path_for_task(task: dict[str, Any], task_dir: Path) -> Path:
    package_path = task.get("package_path")
    if package_path:
        return Path(str(package_path))
    manifest_type = str((task.get("manifest") or {}).get("package_type") or "")
    task_type = str(task.get("task_type") or "")
    if task_type in PACKAGELESS_TASK_TYPES or manifest_type in PACKAGELESS_TASK_TYPES:
        return task_dir / "package"
    raise KeyError("package_path")


def _writeback_runner_compose_tag(settings: Any, task: dict[str, Any], logs: list[str]) -> list[str]:
    """US-32：组件升级收尾时把 compose 的 runner tag 对齐到**本次实际运行的镜像**。

    为什么必须在 runner 侧：web-api 的 project 目录是**只读挂载**（compose 里 `:ro`），
    它调用的同名回写函数写入必抛 OSError——`.14` 实测正是如此：runner 已升到 v0.3.2，
    compose 仍写 v0.3.1。而 upgrade-runner 对 project 目录是**可写**挂载。
    """
    try:
        from app.upgrade_runner.actions import reconcile_project_runner_tag, ActionContext
    except Exception as exc:  # noqa: BLE001 - 回写失败不得让组件升级判失败
        return [*logs, f"compose tag 回写跳过（导入失败）：{exc}"]

    project_path = Path(settings.project_path)
    context = ActionContext(
        package_path=project_path,
        project_path=project_path,
        data_path=Path(settings.data_path),
        upgrades_path=Path(settings.upgrades_path),
        backups_path=Path(settings.backups_path),
        exports_path=Path(settings.exports_path),
        compose_runtime_path=Path(settings.compose_runtime_path),
        prometheus_path=Path(settings.prometheus_path),
        compose_file=settings.compose_file,
        compose_project=settings.compose_project,
        executor=CommandExecutor(),
    )
    try:
        previous = reconcile_project_runner_tag(context, task)
    except Exception as exc:  # noqa: BLE001
        return [*logs, f"compose tag 回写失败：{exc}"]
    if previous:
        return [*logs, f"已对齐 compose runner tag：{previous} -> {_runner_image_from_task(task)}"]
    return logs


def _runner_image_from_task(task: dict[str, Any]) -> str:
    from app.upgrade_runner.actions import _runner_image_from_task as resolve

    return resolve(task)


def _compose_runner_tag_now(settings: Any) -> str:
    """读 project compose 里当前声明的 runner tag（读不到返回空串）。"""
    try:
        compose_path = Path(settings.project_path) / "docker-compose.yml"
        if not compose_path.is_file():
            return ""
        text = compose_path.read_text(encoding="utf-8")
    except OSError:
        return ""
    in_runner = False
    for line in text.splitlines():
        stripped = line.strip()
        if not in_runner:
            if stripped.startswith("upgrade-runner:"):
                in_runner = True
            continue
        if stripped.startswith("image:"):
            return stripped.split("image:", 1)[1].strip()
    return ""


def _runner_tag_aligned(settings: Any, task: dict[str, Any]) -> bool:
    """判断这个 runner 组件任务的 compose tag 是否已经对齐（幂等判据）。

    对齐定义：compose 里的 tag == 任务声明的 runner 镜像 tag。
    compose 读不到时返回 True（无从判断，不反复扰动现场）。
    """
    expected = _runner_image_from_task(task)
    if not expected:
        return True
    current = _compose_runner_tag_now(settings)
    if not current:
        return True
    return current == expected


def _apply_tag_writeback_if_needed(settings: Any, task: dict[str, Any]) -> dict[str, Any]:
    """已 success 的组件升级任务：仅在 compose tag 未对齐时回写，并留痕。"""
    logs = list(task.get("logs") or [])
    before = len(logs)
    task = _finish_runner_component_steps(
        task, task.get("logs") and logs[-1] or "组件升级完成。", settings
    )
    new_logs = task.get("logs") or []
    if len(new_logs) == before:
        return task
    task["logs"] = new_logs
    return task


def _finish_runner_component_steps(
    task: dict[str, Any], message: str, settings: Any = None
) -> dict[str, Any]:
    steps = list(task.get("steps") or [])
    steps = _replace_step(steps, "restart", "succeeded", "upgrade-runner 已重新启动")
    steps = _replace_step(steps, "healthcheck", "succeeded", "组件升级健康检查通过")
    updated_at = _now()
    task["status"] = "success"
    task["runner_resume_pending"] = False
    task["updated_at"] = updated_at
    task["finished_at"] = task.get("finished_at") or updated_at
    task["steps"] = steps
    logs = list(task.get("logs") or [])
    if message not in logs:
        logs.append(message)
    if settings is not None:
        # US-32：组件升级收尾对齐 compose tag（web-api 无写权限，只能由 runner 做）
        logs = _writeback_runner_compose_tag(settings, task, logs)
    task["logs"] = logs
    return task


ACTION_STEP_DEFINITIONS = [
    ("backup", "生成升级前数据备份", {"backup.create"}),
    ("load_images", "加载升级镜像", {"image.load"}),
    ("prepare_filesystem", "准备运行目录", {"filesystem.prepare"}),
    ("project_files", "同步项目文件", {"files.sync"}),
    ("task_state", "迁移升级任务状态", {"task.migrate_runtime_state", "task.sync_runtime_state"}),
    ("write_override", "写入服务镜像覆盖配置", {"compose.override"}),
    ("project_migrate", "迁移 Compose 项目和网络", {"compose.project_migrate"}),
    ("migration", "执行数据库迁移脚本", {"script.run_sandboxed"}),
    ("restart", "重启升级服务", {"compose.apply"}),
    ("healthcheck", "执行服务健康检查", {"health.http", "health.prometheus"}),
    ("post_upgrade_collection", "调度升级后自动采集", {"post_upgrade.schedule_collection"}),
    ("post_upgrade", "调度升级后清理", {"post_upgrade.schedule_cleanup"}),
    # W3 自换时代的组件升级步骤：锚点 → load 自身新镜像 → 写自身 compose → 调度 handoff。
    # 五个 key 与 impl-spec §W3 步骤 1 的 `steps=[verify, load, writeback, handoff, presence_wait]`
    # 一一对应；`presence_wait` 不在此列——它由 web-api 观察，不是 runner 的动作。
    ("self_handoff_verify", "校验组件包完整性", {"component.verify"}),
    ("self_handoff_load", "加载组件新镜像", {"component.image_load"}),
    ("self_handoff_writeback", "写入组件自身部署配置", {"component.compose_writeback"}),
    ("self_handoff_handoff", "调度执行器自换", {"component.schedule_self_handoff"}),
    (
        "runner_handoff",
        "切换 runner 运行目录",
        {"runner.handoff_target_runtime", "runner.schedule_target_runtime_handoff", "runner.stop_legacy_runtime"},
    ),
    (
        "legacy_cleanup",
        "清理旧环境残留",
        {
            "post_cleanup.precheck_target_health",
            "compose.stop_legacy_project",
            "network.remove_legacy",
            "filesystem.cleanup_legacy_paths",
            "filesystem.cleanup_target_app_residuals",
            "post_cleanup.verify",
            "legacy.cleanup",
        },
    ),
    ("rollback", "执行自动回滚", {"rollback.restore"}),
]


def _step_status(actions: list[dict[str, Any]]) -> str:
    statuses = {str(action.get("status") or "pending") for action in actions}
    if statuses & {"failed", "recovery_required"}:
        return "failed"
    if "running" in statuses:
        return "running"
    if actions and statuses <= {"succeeded", "skipped"}:
        return "succeeded"
    return "pending"


def _step_message(actions: list[dict[str, Any]]) -> str:
    failed = next((action for action in actions if action.get("error")), None)
    if failed:
        return str(failed.get("error") or "")
    total = len(actions)
    if total <= 1:
        action = actions[0] if actions else {}
        result = action.get("result") or {}
        params = action.get("params") or {}
        return str(result.get("path") or result.get("message") or params.get("image") or "")
    done = sum(1 for action in actions if str(action.get("status") or "") in {"succeeded", "skipped"})
    running = next((action for action in actions if action.get("status") == "running"), None)
    suffix = ""
    if running:
        params = running.get("params") or {}
        suffix = f"：{params.get('image')}" if params.get("image") else ""
    return f"已完成 {done}/{total}{suffix}"


def _action_steps(task: dict[str, Any]) -> list[dict[str, Any]]:
    actions = task.get("execution_plan", {}).get("actions") or []
    if not actions:
        return list(task.get("steps") or [])
    steps: list[dict[str, Any]] = []
    for key, title, types in ACTION_STEP_DEFINITIONS:
        related = [action for action in actions if action.get("type") in types]
        if not related:
            continue
        steps.append(
            {
                "key": key,
                "title": title,
                "status": _step_status(related),
                "message": _step_message(related),
            }
        )
    known_types = {action_type for _, _, action_types in ACTION_STEP_DEFINITIONS for action_type in action_types}
    for action in actions:
        if action.get("type") in known_types:
            continue
        steps.append(
            {
                "key": action.get("id"),
                "title": action.get("type"),
                "status": action.get("status") or "pending",
                "message": action.get("error") or "",
            }
        )
    return steps


def _action_progress(task: dict[str, Any], status: str) -> int:
    if status in {"success", "failed", "cancelled"}:
        return 100
    actions = task.get("execution_plan", {}).get("actions") or []
    if not actions:
        return 50 if status == "running" else 1
    finished = sum(1 for action in actions if str(action.get("status") or "") in {"succeeded", "skipped"})
    running = 0.5 if any(str(action.get("status") or "") == "running" for action in actions) else 0
    return min(95, max(1, round(((finished + running) / len(actions)) * 100)))


def _task_message(task: dict[str, Any]) -> str:
    status = str(task.get("status") or "")
    if status == "success":
        return "升级执行完成"
    if status == "rolled_back":
        return "升级失败，已自动回滚"
    if status == "recovery_required":
        return "升级需要人工恢复处理"
    if status == "rollback_failed":
        return "升级自动回滚失败"
    if status == "failed":
        return str(task.get("error") or "升级执行失败")
    running = next((step for step in _action_steps(task) if step.get("status") == "running"), None)
    if running:
        return str(running.get("title") or "正在执行升级任务")
    return "正在执行升级任务"


#: 上次成功镜像的**内容指纹**（task_id → 指纹）。进程内状态，runner 重启即重置——
#: 这正是想要的语义：重启后多投一次，好过升级结束时漏掉最后一次状态。
_project_mirror_signature: dict[str, tuple] = {}


def _project_signature(task: dict[str, Any]) -> tuple:
    """任务状态的**内容指纹**：顶层状态 + 每个步骤的状态序列。

    为什么用内容指纹而不是时间限流：engine 的 `on_update` 在每次 checkpoint 保存时
    都触发（热路径），而一次动作内部可能保存很多次——这些保存**不改变**任何步骤状态，
    对用户可见的进度也毫无变化。按内容去重恰好实现规格要求的「每步骤转换一次」：
    步骤 pending→running→succeeded 各写一次，步骤内部反复保存不写。

    试过时间限流（10s）并被既有用例否掉：那会把「加载镜像这一步已经开始」这种
    真实进展也一起吞掉（`test_runner_projects_action_progress_while_task_is_running`）。
    """
    steps = _action_steps(task)
    return (
        str(task.get("status") or ""),
        tuple((str(step.get("key")), str(step.get("status"))) for step in steps),
    )


def _project_task(database_path: Path, task: dict[str, Any], *, force: bool = False) -> None:
    """把任务状态**尽力**镜像进业务库 tasks 表（W2：兼容镜像，非事实源）。

    执行期的事实源是 task.json（runner 独占写），`tasks` 表由 web-api 独占投影
    （`app.v2.upgrade.projection`）。本函数只为 v0.5.3 web-api 保留——它不会自己投影，
    少了这条镜像，v0.5.3 + v0.3.2 组合（M4 格）的任务中心会看不到进度。

    **任何失败都不得冒泡**：镜像失败只记 warning。这与 W1 的 DB 心跳镜像同一处置——
    执行器绝不能因为一条只影响"旧版本界面显示"的兼容写而崩掉（#82 的教训）。
    """
    task_id = str(task.get("task_id") or "")
    signature = _project_signature(task)
    if not force and _project_mirror_signature.get(task_id) == signature:
        return
    try:
        _write_task_projection(database_path, task)
    except Exception:  # noqa: BLE001 - 兼容镜像失败无害
        logger.warning(
            "tasks 表兼容镜像失败（task=%s），已忽略；事实源 task.json 不受影响", task_id or "?"
        )
        return
    _project_mirror_signature[task_id] = signature


def _write_task_projection(database_path: Path, task: dict[str, Any]) -> None:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    status_map = {
        "success": "success",
        "rolled_back": "success",
        "failed": "failed",
        "rollback_failed": "failed",
        "recovery_required": "failed",
        "running": "running",
        "pending": "pending",
    }
    status = status_map.get(str(task.get("status")), str(task.get("status")))
    progress = _action_progress(task, status)
    message = _task_message(task)
    steps = _action_steps(task)
    # 必须**显式关闭**：`with sqlite3.connect(...)` 只提交事务、不关连接——
    # 这正是 US-28 的根因（`.12` 实测 52 个 fd、约 10 分钟写锁窗口）。
    # 本函数是长驻进程里被反复调用的写路径，泄漏会稳定复现同样的事故。
    connection = sqlite3.connect(database_path)
    try:
        with connection:
            connection.execute(
                """
                INSERT INTO tasks (id, type, status, title, progress, message, logs_json, steps_json, severity, created_at, updated_at, finished_at)
                VALUES (?, 'upgrade', ?, '执行系统升级', ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    status = excluded.status,
                    progress = excluded.progress,
                    message = excluded.message,
                    logs_json = excluded.logs_json,
                    steps_json = excluded.steps_json,
                    severity = excluded.severity,
                    updated_at = excluded.updated_at,
                    finished_at = excluded.finished_at
                """,
                (
                    task["task_id"],
                    status,
                    progress,
                    message,
                    json.dumps(task.get("logs") or [], ensure_ascii=False),
                    json.dumps(steps, ensure_ascii=False),
                    "critical" if status == "failed" else "info" if status == "success" else None,
                    task.get("created_at") or _now(),
                    _now(),
                    _now() if status in {"success", "failed"} else None,
                ),
            )
    finally:
        connection.close()


def _heartbeat_until_done(lease: LeaseManager, task_id: str, store: TaskStore, stop: threading.Event) -> None:
    while not stop.wait(5):
        try:
            lease.heartbeat(task_id, revision=int(store.load().get("revision") or 0))
        except Exception:
            return


#: 心跳写库遇 SQLite 锁时的重试参数。
#:
#: 根因（2026-10-04 `.12` 实测）：升级期间 web-api / runner 自身会写库持锁，
#: `upgrade_runner_state` 的 upsert 撞上 `sqlite3.OperationalError: database is locked`。
#: 该异常原先**一路冒泡到 `main()` 的 while 循环外**，进程直接退出（exit 0），
#: 靠 `restart: unless-stopped` 被拉起——`.12` 实测 `RestartCount=1`。
#: 风险：升级正进行中时 runner 反复退出可能拖慢甚至卡住任务；撞上重启上限会进入 crash-loop；
#: 崩溃发生在接管任务前会漏执行。
#:
#: 修法：锁是**短暂**的（写事务结束即释放），故短退避重试即可覆盖；
#: 重试仍失败则**不退出**——本轮跳过心跳，下一轮（3 秒后）自然重试。
HEARTBEAT_RETRY_DELAYS = (0.2, 0.5, 1.0, 2.0)


def _heartbeat_with_retry(lease: LeaseManager, runner_version: str) -> bool:
    """更新 runner 心跳；遇 SQLite 锁则短退避重试。返回是否成功。

    绝不向上抛异常：心跳写不进去只是一次心跳丢失，不该让 runner 进程退出。
    """
    for attempt, delay in enumerate((0.0, *HEARTBEAT_RETRY_DELAYS)):
        if delay:
            time.sleep(delay)
        try:
            lease.update_runner_state(runner_version)
            return True
        except sqlite3.OperationalError as exc:
            # 只对「锁/忙」重试；其它 OperationalError（如表不存在）重试无意义
            if "locked" not in str(exc) and "busy" not in str(exc):
                logger.warning("runner 心跳失败（非锁原因，跳过本轮）: %s", exc)
                return False
            logger.warning(
                "runner 心跳遇数据库锁，第 %d 次重试（%.1fs 后）: %s",
                attempt + 1,
                HEARTBEAT_RETRY_DELAYS[attempt] if attempt < len(HEARTBEAT_RETRY_DELAYS) else 0.0,
                exc,
            )
        except Exception:  # noqa: BLE001 - 心跳失败不得让 runner 退出
            logger.exception("runner 心跳失败，跳过本轮")
            return False
    logger.warning("runner 心跳重试耗尽，跳过本轮（进程继续运行）")
    return False


def run_pending_once(
    settings: RunnerSettings,
    *,
    executor: CommandExecutor | None = None,
    owner: str | None = None,
    handlers: dict[str, Any] | None = None,
) -> int:
    owner_id = owner or f"runner-{uuid.uuid4().hex}"
    lease = LeaseManager(settings.database_path, owner_id)
    _heartbeat_with_retry(lease, settings.runner_version)
    executed = 0
    settings.upgrades_path.mkdir(parents=True, exist_ok=True)
    for task_file in sorted(settings.upgrades_path.glob("*/task.json"), key=lambda path: path.stat().st_mtime):
        store = TaskStore(task_file.parent)
        task = store.load()
        status = str(task.get("status") or "")
        if status == "success" and _is_runner_component_task(task) and _has_unfinished_steps(task):
            task = _finish_runner_component_steps(task, f"upgrade-runner {settings.runner_version} 已重新启动，组件升级完成。", settings)
            result = store.save(task, expected_revision=int(task.get("revision") or 0))
            _project_task(settings.database_path, result)
            executed += 1
            continue
        # W3 自换收尾：**旧** runner 在 handoff 处被 SIGKILL，task.json 停在
        # `status=running`、`self_handoff.scheduled=true`。此刻有两个 runner 可能轮询到它：
        #
        # - **新** runner（版本 == target）→ 收尾。这是自换唯一的收尾点。
        # - **旧** runner（docker 还没替换掉它）→ 必须**跳过**。
        #
        # 旧 runner 若继续执行会重跑整条计划：再 load 一次镜像、再 writeback 一次、
        # **再调度一次 handoff**（多起一个 cutover 辅助容器）。所以这里不是"版本不匹配
        # 就继续执行"，而是"版本不匹配就一律不碰这条任务"。
        if _is_self_handoff_scheduled(task):
            if settings.runner_version == str((task.get("self_handoff") or {}).get("target_version") or ""):
                task = _finish_runner_component_steps(
                    task,
                    f"upgrade-runner {settings.runner_version} 自换完成。",
                    settings,
                )
                result = store.save(task, expected_revision=int(task.get("revision") or 0))
                _project_task(settings.database_path, result)
                executed += 1
            continue
        # US-32 兜底：组件升级任务可能**已经**被 web-api 收尾成 success（步骤全 succeeded、
        # 无 execution_plan），上面两条"未收尾"路径都不触发，于是 compose tag 永远对不齐
        # （`.14` 实测：runner=v0.3.2 但 compose 写 v0.3.1）。这里用"是否已对齐"做幂等判据：
        # **未对齐**才回写，已对齐则跳过（否则每次轮询都刷一遍日志）。
        # 注意条件是 `not _runner_tag_aligned(...)`——曾误写成 `_runner_tag_aligned(...)`，
        # 语义正好相反：已对齐时才回写，于是真要修的场景（未对齐）反被跳过。
        # 单元测试只测了辅助函数的返回值，没断言本分支的走向，单测全绿而真机不生效。
        if status == "success" and _is_runner_component_task(task) and not _runner_tag_aligned(settings, task):
            task = _apply_tag_writeback_if_needed(settings, task)
            result = store.save(task, expected_revision=int(task.get("revision") or 0))
            _project_task(settings.database_path, result)
            executed += 1
            continue
        if status not in {"pending", "running", "runner_restarting", "recovery_required"}:
            continue
        if status == "runner_restarting" and task.get("runner_resume_pending") and not task.get("execution_plan"):
            task = _finish_runner_component_steps(task, "upgrade-runner 已重新启动，组件升级完成。", settings)
            result = store.save(task, expected_revision=int(task.get("revision") or 0))
            _project_task(settings.database_path, result)
            executed += 1
            continue
        recovery_command = task.get("recovery_command")
        if status == "recovery_required" and recovery_command not in {"continue", "rollback"}:
            continue
        if not task.get("execution_plan"):
            continue
        if not lease.acquire(task["task_id"], revision=int(task.get("revision") or 0)):
            continue
        # W3：自换任务在执行前捕获回滚锚点并注入计划（必须早于 compose writeback）。
        if _is_self_handoff_task(task):
            task = _inject_self_handoff_anchor(
                settings, task, executor=executor or CommandExecutor()
            )
            try:
                task = store.save(
                    task, expected_revision=int(task.get("revision") or 0)
                )
            except Exception as exc:  # noqa: BLE001 - 锚点落盘失败不得静默开始自换
                logger.exception("自换锚点落盘失败，跳过本任务：%s", exc)
                lease.release(task["task_id"])
                continue
        if status == "recovery_required" and recovery_command == "rollback":
            selected_handlers = handlers or default_handlers()
            rollback_handler = selected_handlers.get("rollback.restore")
            if rollback_handler is None:
                task["status"] = "rollback_failed"
                task["error"] = "Runner 不支持 rollback.restore"
            else:
                project_backup_path = None
                project_files: list[dict[str, Any]] = []
                override_path = None
                backup_path = None
                backup_scope = None
                services: list[str] = []
                for completed in task.get("execution_plan", {}).get("actions") or []:
                    result = completed.get("result") or {}
                    if completed.get("type") == "backup.create":
                        backup_path = result.get("path")
                        backup_scope = result.get("scope")
                    elif completed.get("type") == "files.sync":
                        project_backup_path = result.get("backup_path")
                        project_files = list((result.get("checkpoint") or {}).get("files") or [])
                    elif completed.get("type") == "compose.override":
                        override_path = result.get("path")
                    elif completed.get("type") == "compose.apply":
                        services = [str(item) for item in result.get("services") or []]
                recovery_context = ActionContext(
                    package_path=_package_path_for_task(task, task_file.parent),
                    project_path=settings.project_path,
                    data_path=settings.data_path,
                    upgrades_path=settings.upgrades_path,
                    backups_path=settings.backups_path,
                    exports_path=settings.exports_path,
                    compose_runtime_path=settings.compose_runtime_path,
                    prometheus_path=settings.prometheus_path,
                    compose_file=settings.compose_file,
                    compose_project=settings.compose_project,
                    executor=executor or CommandExecutor(),
                    task_id=task["task_id"],
                    target_version=str(task.get("target_version") or "unknown"),
                    host_data_path=settings.host_data_path,
                    host_upgrades_path=settings.host_upgrades_path,
                    host_backups_path=settings.host_backups_path,
                    host_exports_path=settings.host_exports_path,
                    host_compose_runtime_path=settings.host_compose_runtime_path,
                    host_prometheus_path=settings.host_prometheus_path,
                    host_project_path=settings.host_project_path,
                )
                rollback_action = {
                    "id": "operator-rollback",
                    "type": "rollback.restore",
                    "params": {
                        "backup_path": backup_path,
                        "backup_scope": backup_scope,
                        "project_backup_path": project_backup_path,
                        "project_files": project_files,
                        "override_path": override_path,
                        "services": services,
                    },
                    "checkpoint": {},
                }
                try:
                    task["recovery_result"] = rollback_handler(rollback_action, recovery_context.as_dict())
                    task["status"] = "rolled_back"
                    task["recovery_status"] = "rolled_back"
                    task["available_recovery_actions"] = []
                except Exception as exc:
                    task["status"] = "rollback_failed"
                    task["recovery_status"] = "recovery_required"
                    task["error"] = str(exc)
                    task["available_recovery_actions"] = ["rollback", "fail"]
            task["recovery_command"] = None
            result = store.save(task, expected_revision=int(task.get("revision") or 0))
            _project_task(settings.database_path, result)
            lease.release(task["task_id"])
            executed += 1
            continue
        if status == "recovery_required":
            for action in task["execution_plan"]["actions"]:
                if action.get("status") == "recovery_required":
                    action["status"] = "pending"
            task["status"] = "pending"
            task["recovery_command"] = None
            task = store.save(task, expected_revision=int(task.get("revision") or 0))
        action_context = ActionContext(
            package_path=_package_path_for_task(task, task_file.parent),
            project_path=settings.project_path,
            data_path=settings.data_path,
            upgrades_path=settings.upgrades_path,
            backups_path=settings.backups_path,
            exports_path=settings.exports_path,
            compose_runtime_path=settings.compose_runtime_path,
            prometheus_path=settings.prometheus_path,
            compose_file=settings.compose_file,
            compose_project=settings.compose_project,
            executor=executor or CommandExecutor(),
            task_id=task["task_id"],
            target_version=str(task.get("target_version") or "unknown"),
            host_data_path=settings.host_data_path,
            host_upgrades_path=settings.host_upgrades_path,
            host_backups_path=settings.host_backups_path,
            host_exports_path=settings.host_exports_path,
            host_compose_runtime_path=settings.host_compose_runtime_path,
            host_prometheus_path=settings.host_prometheus_path,
            host_project_path=settings.host_project_path,
            current_container_id=os.environ.get("HOSTNAME", ""),
        )
        stop_heartbeat = threading.Event()
        heartbeat = threading.Thread(
            target=_heartbeat_until_done,
            args=(lease, task["task_id"], store, stop_heartbeat),
            daemon=True,
        )
        heartbeat.start()
        try:
            def project_update(updated: dict[str, Any]) -> None:
                # 按内容指纹去重（见 _project_signature）：步骤每次状态转换写一次，
                # 步骤内部的 checkpoint 保存不写。engine 的 on_update 是热路径，
                # 不去重就等于把 US-28 的写锁窗口原样搬回来。
                _project_task(settings.database_path, updated)

            result = UpgradeEngine(
                store,
                handlers=handlers or default_handlers(),
                context={**action_context.as_dict(), "database_path": str(settings.database_path)},
                on_update=project_update,
                # A5：平台回滚锚点要同时落状态文件（崩溃后新 runner 仍能读到"上一版是什么"）。
                checkpoint_sink=lambda task_id, payload: lease.save_checkpoint(task_id, payload),
            ).run()
            _project_task(settings.database_path, result, force=True)
            executed += 1
        finally:
            stop_heartbeat.set()
            heartbeat.join(timeout=1)
            lease.release(task["task_id"])
    return executed


def main() -> None:
    settings = RunnerSettings.from_environment()
    owner = f"runner-{uuid.uuid4().hex}"
    stop = False

    def request_stop(*_: object) -> None:
        nonlocal stop
        stop = True

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    while not stop:
        try:
            run_pending_once(settings, owner=owner)
        except Exception:  # noqa: BLE001 - 单轮失败不得让 runner 退出
            # 最后一道防线：此前任何未捕获异常（如心跳撞库锁）都会终止进程，
            # 靠 restart 策略拉起，升级中途反复重启有拖慢/卡住风险。
            # 这里改为记录后继续下一轮（3 秒后），runner 保持存活。
            logger.exception("runner 本轮执行异常，继续下一轮")
        time.sleep(3)


if __name__ == "__main__":
    main()
