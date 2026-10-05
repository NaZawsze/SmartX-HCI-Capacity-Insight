"""W2：单写者规则（task.json 为事实源，tasks 表为 web-api 独占投影）。

工程规格：docs/superpowers/specs/2026-10-05-upgrade-architecture-v054-impl-spec.md §W2

## 问题

升级执行期 `tasks` 表有**两个写者**：runner 的 `_project_task`（main.py）与 web-api 的
`TaskService`。两边都写同一行，字段口径还不同（runner 自己算 `progress`/`steps`，
web-api 用 `update_task`），于是出现「任务显示成功但进度条不走」「web-api 写完被 runner
覆盖回去」这类症状。US-28 三类结构性根因之二的直接实例：**同一事实写在两处**。

## 规则

- **事实源 = `task.json`**（文件）。执行期 runner 独占写，web-api 只读。
- **`tasks` 表 = web-api 独占投影**。web-api 在 `status()` 与结算扫描时，发现 task.json
  比库内新就投影过去（status/message/progress/steps/updated_at）。
- runner 侧 `_project_task` 降级为 **best-effort 兼容镜像**（try/except + 低频），
  因为 v0.5.3 web-api 依赖它显示进度；v0.5.4 web-api 起以投影为准，镜像在收缩期移除。

## 为什么"file newer"判定要保守

用文件 mtime 与库内 `updated_at` 比大小看似简单，实则脆弱：两者时钟不同源
（容器与宿主）、mtime 粒度在部分文件系统上是秒级、任务保存与投影写入之间还有先后差。
一旦误判成"文件更旧"，投影会被跳过——而投影是 v0.5.4 唯一的进度来源，跳过即进度停滞。
故本实现采取：**只在能确定 task.json 更新时投影**，判据用 task.json 内部的
`revision` + `updated_at`，不依赖 mtime；不确定就不投影（宁可晚一步，不投影错版本）。
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.v2.tasks.models import TaskStatus, TaskType

logger = logging.getLogger(__name__)

PROJECTED_TITLE = "执行系统升级"

#: 终态集合：与 runner 侧 `_project_task` 的 status_map 保持一致。
#: `rolled_back` 映射成 success 是既有语义——「回滚成功」对用户是任务达成，
#: 详情由 steps/message 呈现。
STATUS_MAP = {
    "success": TaskStatus.SUCCESS.value,
    "rolled_back": TaskStatus.SUCCESS.value,
    "failed": TaskStatus.FAILED.value,
    "rollback_failed": TaskStatus.FAILED.value,
    "recovery_required": TaskStatus.FAILED.value,
    "running": TaskStatus.RUNNING.value,
    "pending": TaskStatus.PENDING.value,
}

_FINISHED = {TaskStatus.SUCCESS.value, TaskStatus.FAILED.value}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def project_state(task: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    """把 task.json 折叠成 tasks 表的一行（纯函数，便于单测）。

    progress 与 steps 的算法**直接复用 runner 侧实现**（`_action_progress` /
    `_action_steps`）。刻意不重写一份：两边各算一套，"页面显示的进度"与"runner 记的进度"
    会在某些任务形状上分叉，而这种分叉极难定位（数据都对，只是差一点）。
    """
    from app.upgrade_runner.main import _action_progress, _action_steps, _task_message

    raw_status = str(task.get("status") or "")
    status = STATUS_MAP.get(raw_status, raw_status)
    progress = _action_progress(task, status)
    reference = now or datetime.now(timezone.utc)
    finished = status in _FINISHED
    return {
        "status": status,
        "progress": progress,
        "message": _task_message(task),
        "logs": list(task.get("logs") or []),
        "steps": _action_steps(task),
        "severity": "critical" if status == TaskStatus.FAILED.value else "info" if status == TaskStatus.SUCCESS.value else None,
        "created_at": str(task.get("created_at") or reference.isoformat()),
        "updated_at": str(task.get("updated_at") or reference.isoformat()),
        # finished_at 必须来自 task.json 的**确定值**，不能用"投影这一刻"。
        # 用当前时刻会让每次 status 轮询都算出一个新值 → 内容比较判为不一致 →
        # 重复投影每次都重写一行，幂等性失效（实测：updated_at 每次轮询都在变）。
        # task.json 没写 finished_at 时退回 updated_at（同样是确定值）。
        "finished_at": (
            str(task.get("finished_at") or task.get("updated_at") or reference.isoformat())
            if finished
            else None
        ),
    }


#: 终态（吸收态）：一旦到达就不得被非终态覆盖。
_TERMINAL = frozenset(_FINISHED)


def should_project(
    task: dict[str, Any],
    row: dict[str, Any] | None,
    *,
    state: dict[str, Any] | None = None,
) -> bool:
    """是否要把 task.json 投影进 tasks 表。

    ## 判据（按顺序，先命中先返回）

    1. **库内没有该行** → 投影。
    2. **终态吸收**：库内已是终态而投影结果不是终态 → **不投影**。
       终态一旦写下就不能被"更旧的执行中状态"拉回去（任务中心不允许成功→运行→成功的抖动）。
    3. **时间明确更旧**（task.json 的 `updated_at` 早于库内）且投影结果**不是终态** → 不投影。
       防止陈旧文件覆盖新内容（实测踩到过：runner 在别的进程里收尾后，
       task.json 的时间可能早于 web-api 写库的时刻）。
    4. **内容不一致** → 投影。这一条是主力判据：**终态必须能穿透时间差写进去**
       （实测 `test_v2_upgrade` 里 task.json 的 `updated_at` 是个 2026-07 的固定值，
       却要求把 tasks 表从 running 推到 success——只比时间会永远漏掉）。
    5. **revision 更新**（时间相同且库内记了 `task_revision`）→ 投影，
       用来推进投影记账；老库未 expand 时该键缺失，本条不生效（否则重复投影每次都命中）。

    为什么不用文件 mtime：容器与宿主时钟不同源、部分文件系统 mtime 只有秒级，
    而误判"更旧"的后果是**投影被跳过**——而投影是 v0.5.4 唯一的进度来源。
    故只用 task.json 内部的 `updated_at` + `revision`，并以内容比较兜底。
    """
    if not row:
        return True
    projected = state or project_state(task)
    status = projected["status"]
    file_updated = _parse(task.get("updated_at"))
    row_updated = _parse(row.get("updated_at"))

    # 2. 真终态吸收：库内这一行**已收尾**（finished_at 非空）而投影结果不是终态 → 不投影。
    #    必须看 finished_at 而不是只看 status：预检查通过时 web-api 也会写
    #    status=success，但那是"检查通过"不是"执行完成"（finished_at 为空）。
    #    只看 status 会把刚通过预检查的任务判成已收尾，从而拒绝后续所有进度投影。
    if _row_is_finished(row) and status not in _TERMINAL:
        return False

    if file_updated is not None and row_updated is not None:
        # 3. task.json 明确更新 → 投影
        if file_updated > row_updated:
            return True
        # 4. task.json 明确更旧且**不是终态** → 不投影（防陈旧文件把进度/日志拉回去）
        if file_updated < row_updated and status not in _TERMINAL:
            return False

    # 5. 内容不一致 → 投影（主力判据：终态必须能穿透时间差写进去）
    if _content_differs(row, projected):
        return True
    # 6. 时间相同且库内记了已投影 revision → 用单调 revision 细分
    if "task_revision" in row and file_updated is not None and row_updated is not None:
        return int(task.get("revision") or 0) > int(row.get("task_revision") or 0)
    return False


def _row_is_finished(row: dict[str, Any]) -> bool:
    """库内那一行是否**已收尾**（终态 + 有 finished_at）。"""
    return str(row.get("status") or "") in _TERMINAL and bool(row.get("finished_at"))


def _content_differs(row: dict[str, Any], projected: dict[str, Any]) -> bool:
    """按投影结果逐列比较库内那一行。"""
    for column, value in (
        ("status", projected["status"]),
        ("progress", projected["progress"]),
        ("message", projected["message"]),
    ):
        if column in row and row[column] != value:
            return True
    for column, value in (("logs_json", projected["logs"]), ("steps_json", projected["steps"])):
        if column not in row:
            continue
        try:
            current = json.loads(row[column]) if row[column] else []
        except (TypeError, ValueError):
            return True
        if current != value:
            return True
    # finished_at 参与比较：它是「真终态」的标记。
    # 少了这一列的比较，库内那行 finished_at 为空而 task.json 已收尾时，
    # 内容看起来一致 → 投影被跳过 → 任务中心永远缺 finished_at。
    if "finished_at" in row and row["finished_at"] != projected["finished_at"]:
        return True
    return False


def has_revision_column(database: Any) -> bool:
    """`tasks.task_revision` 是否可用（老库尚未 expand 时的探测）。"""
    try:
        with database.connection() as conn:
            return "task_revision" in {row[1] for row in conn.execute("PRAGMA table_info(tasks)").fetchall()}
    except Exception:  # noqa: BLE001 - 探测失败按"没有该列"，退回时间判定
        return False


def project_if_newer(
    database: Any,
    task: dict[str, Any],
    *,
    now: datetime | None = None,
) -> bool:
    """把 task.json 投影进 tasks 表。已是最新则跳过（幂等）。

    直接走 SQL 而不经 `TaskService.update_task`：后者要求行已存在（否则 KeyError），
    而 runner 首个投影回调就发生在 web-api 还没建行的时刻。
    """
    task_id = str(task.get("task_id") or "")
    if not task_id:
        return False
    row = _read_row(database, task_id)
    # 列是否存在必须**独立**判定：`_read_row` 在读不到行时返回 None，
    # 若据此推断"有该列"，老库（尚未 expand）第一次投影就会因列不存在而报错。
    has_revision = has_revision_column(database)
    state = project_state(task, now=now)
    if not should_project(task, row, state=state):
        return False
    revision_value = int(task.get("revision") or 0) if has_revision else 0
    columns = [
        "id",
        "type",
        "status",
        "title",
        "progress",
        "message",
        "logs_json",
        "steps_json",
        "severity",
        "created_at",
        "updated_at",
        "finished_at",
    ]
    values: list[Any] = [
        task_id,
        TaskType.UPGRADE.value,
        state["status"],
        PROJECTED_TITLE,
        state["progress"],
        state["message"],
        json.dumps(state["logs"], ensure_ascii=False),
        json.dumps(state["steps"], ensure_ascii=False),
        state["severity"],
        state["created_at"],
        state["updated_at"],
        state["finished_at"],
    ]
    # title 也要投影：任务中心里这条记录的标题应始终是"执行系统升级"，
    # 而 web-api 在预检查阶段先写入的是"升级预检查"。不覆盖会让用户在任务列表
    # 看到"升级预检查"却带着 100% 的执行进度。
    updates = [
        "title = excluded.title",
        "status = excluded.status",
        "progress = excluded.progress",
        "message = excluded.message",
        "logs_json = excluded.logs_json",
        "steps_json = excluded.steps_json",
        "severity = excluded.severity",
        "finished_at = excluded.finished_at",
    ]
    # updated_at 只在 task.json 明确给了时才覆盖：否则每次 status 轮询都会写进
    # "投影这一刻"，行内容永远在变 → 幂等性失效（实测 updated_at 每轮都不同）。
    if task.get("updated_at"):
        updates.append("updated_at = excluded.updated_at")
    if has_revision:
        columns.append("task_revision")
        values.append(revision_value)
        updates.append("task_revision = excluded.task_revision")
    placeholders = ", ".join("?" * len(columns))
    with database.connection() as conn:
        conn.execute(
            f"""
            INSERT INTO tasks ({", ".join(columns)})
            VALUES ({placeholders})
            ON CONFLICT(id) DO UPDATE SET
                {", ".join(updates)}
            """,
            values,
        )
    return True


#: 内容比较需要的列（时间不可比时逐列比对）。
_CONTENT_COLUMNS = ("status", "progress", "message", "logs_json", "steps_json", "finished_at")


def _read_row(database: Any, task_id: str) -> dict[str, Any] | None:
    """读库里那一行（**不改表结构**）。

    不在这里 `ALTER TABLE`：投影是读路径上的高频操作，让它顺带改 schema 会让
    「只读判定」变成「可能写 schema」，并发下难以推理。列的创建在
    `database.initialize()`（expand-only `_ensure_column`）里完成。
    """
    has_revision = has_revision_column(database)
    columns = [*_CONTENT_COLUMNS, "updated_at"]
    if has_revision:
        columns.append("task_revision")
    selected = ", ".join(columns)
    try:
        with database.connection() as conn:
            row = conn.execute(f"SELECT {selected} FROM tasks WHERE id = ?", (task_id,)).fetchone()
    except Exception:  # noqa: BLE001 - 读不到就当成"没有行"，让投影补齐
        return None
    if row is None:
        return None
    if hasattr(row, "keys"):
        return {column: row[column] for column in columns if column in row.keys()}
    return dict(zip(columns, row))
