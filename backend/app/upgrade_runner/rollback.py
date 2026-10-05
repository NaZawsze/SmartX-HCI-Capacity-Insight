"""平台升级回滚机制（设计 v1 §5.0 / impl-spec §W5 场景 A，US-17 关闭的地基）。

## 这一层负责什么

三件共用的事，都放在 runner 侧（web-api 只做手动入口 B8）：

1. **回滚锚点**：首次 `compose.apply` **之前**捕获「上一版是什么」，四要素缺一不可——
   `previous_version`、旧镜像 tag + 镜像 ID、备份路径 + SHA、升级前迁移/计数快照。
2. **触发判定**：只有 `compose.apply` / `health.*` / `post_upgrade.*` 失败才回滚，
   且必须 manifest 显式 `rollback_on_failure: true`（缺省 false，老 manifest 行为不变）。
3. **回滚子流程**：复用现有动作实现（override 旧 tag → apply → health），**不新增计划词汇**；
   回滚后再过一次业务计数守卫，确认数据没被回滚动作本身弄坏。

## 为什么锚点必须在 apply 前捕获

`compose.override` 写的是**期望镜像**，`compose.apply` 之后运行容器就是新镜像；
`files.sync` 还可能把 project compose 一起换掉。等失败信号（health 挂了）才去读
"上一版是什么"，读到的是新版本——回滚会变成"把新版本换回新版本"。
`backup.create` 同理：它产出的 tar 是回滚**数据**的唯一来源，路径必须与锚点一起固化，
否则任务里存的可能是另一次升级的备份。

## 为什么复用组件锚点的机制而不是再造一套

W3 已经为自换（组件升级）做过同形态的锚点捕获（`capture_component_rollback_anchor`），
docker 事实探测（容器 ID、镜像 ID、容器内版本文件）也在 `selfhandoff` 里。
本模块直接复用那三个原语，避免两套探测口径在同一个 runner 里分叉——
分叉的后果是"组件回滚能回、平台回滚回不回去"这种极难定位的差异。
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.upgrade_runner.selfhandoff import (
    container_file_value,
    image_id_of_container,
    image_id_of_tag,
    running_service_container_id,
)

logger = logging.getLogger(__name__)

#: 只有这些步骤失败才值得回滚。`image.load` / `filesystem.*` / `files.sync` 阶段失败**不回滚**：
#: 那时旧容器根本没动，"回滚"等于凭空制造一次重建（设计 v1 §5.1 触发条件严格化）。
ROLLBACK_TRIGGER_ACTIONS = frozenset(
    {
        "compose.apply",
        "health.http",
        "health.prometheus",
    }
)
ROLLBACK_TRIGGER_PREFIXES = ("post_upgrade.",)

#: 业务计数守卫要比对的表（与 `_db_counts` 同一套口径，不另立标准）。
COUNT_GUARD_TABLES = ("towers", "clusters", "vms", "volumes")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def rollback_on_failure_enabled(task: dict[str, Any]) -> bool:
    """manifest.rollback_on_failure 开关，**缺省 false**。

    缺省 false 是兼容决定：v0.5.3 及更早的平台包 manifest 里没有这个字段，
    如果按 true 处理，这些包升级失败时会突然开始自动回滚——而它们的计划是由老编译器
    生成的、根本没有锚点，回滚会退化成"删 override + 盲目 force-recreate"（US-26 的形态）。
    v0.5.4 起的平台包 manifest 显式写 true。
    """
    manifest = task.get("manifest")
    if not isinstance(manifest, dict):
        return False
    return bool(manifest.get("rollback_on_failure"))


def is_rollback_trigger(action_type: str) -> bool:
    """该步骤失败是否属于回滚触发面。"""
    kind = str(action_type or "")
    return kind in ROLLBACK_TRIGGER_ACTIONS or kind.startswith(ROLLBACK_TRIGGER_PREFIXES)


def _apply_scope_services(task: dict[str, Any]) -> list[str]:
    for item in (task.get("execution_plan") or {}).get("actions") or []:
        if isinstance(item, dict) and str(item.get("type") or "") == "compose.apply":
            return [str(value) for value in (item.get("params") or {}).get("services") or [] if value]
    return []


def _completed_backup(task: dict[str, Any]) -> dict[str, Any]:
    for item in (task.get("execution_plan") or {}).get("actions") or []:
        if isinstance(item, dict) and str(item.get("type") or "") == "backup.create":
            result = item.get("result") or {}
            if result.get("path"):
                return {
                    "path": str(result.get("path")),
                    "sha256": str(result.get("sha256") or ""),
                    "scope": str(result.get("scope") or "platform"),
                }
    return {}


def _expected_images(task: dict[str, Any]) -> dict[str, str]:
    """计划期望镜像（与 W4 `compose_apply` 同一权威来源：compose.override 动作）。"""
    mapping: dict[str, str] = {}
    for item in (task.get("execution_plan") or {}).get("actions") or []:
        if not isinstance(item, dict) or str(item.get("type") or "") != "compose.override":
            continue
        for image in (item.get("params") or {}).get("images") or []:
            if isinstance(image, dict) and image.get("service") and image.get("image"):
                mapping[str(image["service"])] = str(image["image"])
    return mapping


def _db_counts_snapshot(database: Path) -> dict[str, int]:
    """升级前的业务计数快照（回滚后据此判断数据是否被动过）。"""
    counts = {table: 0 for table in COUNT_GUARD_TABLES}
    if not Path(database).is_file():
        return counts
    import sqlite3

    try:
        with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as connection:
            for table in COUNT_GUARD_TABLES:
                try:
                    row = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
                except sqlite3.Error:
                    continue
                counts[table] = int(row[0]) if row else 0
    except sqlite3.Error as exc:  # noqa: BLE001 - 计数快照失败不该让升级失败
        logger.warning("回滚锚点：读取业务计数失败（%s），计数按 0 记", exc)
    return counts


def _applied_migrations_snapshot(database: Path) -> list[str]:
    """升级前已执行迁移快照（expand-only 纪律的可回滚边界）。"""
    path = Path(database)
    if not path.is_file():
        return []
    import sqlite3

    for table in ("schema_migrations", "upgrade_migrations"):
        try:
            with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as connection:
                rows = connection.execute(f"SELECT version FROM {table} ORDER BY version").fetchall()
            return [str(row[0]) for row in rows]
        except sqlite3.Error:
            continue
    return []


def capture_platform_rollback_anchor(
    context: Any,
    task: dict[str, Any],
    *,
    executor: Any,
    target_version: str,
    checkpoint_sink: Any = None,
) -> dict[str, Any]:
    """捕获平台升级的回滚锚点。**必须在首次 `compose.apply` 之前调用**。

    与组件锚点（`capture_component_rollback_anchor`）同形态，但服务集合不同：
    平台锚点要记的是**三件套的旧镜像**，因为回滚就是把三件套指回旧 tag。
    """
    project = str(getattr(context, "compose_project", "") or "")
    services = _apply_scope_services(task)
    images: dict[str, dict[str, str]] = {}
    for service in services:
        container_id = running_service_container_id(executor, project, service)
        running_ref = ""
        if container_id:
            try:
                running_ref = executor.output(
                    ["docker", "inspect", "--format", "{{.Config.Image}}", container_id]
                ).strip()
            except Exception as exc:  # noqa: BLE001 - 探测失败只让锚点不完整
                logger.warning("回滚锚点：读取 %s 运行镜像引用失败（%s）", service, exc)
        images[service] = {
            # compose 里声明的 image（apply 要覆盖的那个值）
            "tag": _compose_image_for(context, service) or running_ref,
            # 运行中容器的不可变镜像 ID：tag 被移动后仍能定位镜像本体
            "image_id": image_id_of_container(executor, container_id),
            # 按引用查到的镜像 ID：与上一项不一致说明 tag 在容器运行期间被移动过
            "image_id_by_tag": image_id_of_tag(executor, running_ref),
            "running_ref": running_ref,
            "container_id": container_id,
        }

    previous_version = ""
    web_api_container = running_service_container_id(executor, project, "web-api")
    if web_api_container:
        previous_version = container_file_value(executor, web_api_container, "/app/VERSION")
    database = Path(getattr(context, "data_path", "")) / "smartx.db"
    anchor = {
        "kind": "platform",
        "previous_version": previous_version,
        "target_version": str(target_version or ""),
        "services": services,
        "images": images,
        "backup": _completed_backup(task),
        "expected_images": _expected_images(task),
        "pre_upgrade": {
            "counts": _db_counts_snapshot(database),
            "applied_migrations": _applied_migrations_snapshot(database),
            "database": str(database),
        },
        "captured_at": _now(),
    }
    missing = [name for name in ("previous_version", "backup") if not anchor[name]]
    if missing:
        # 不抛：锚点缺失只影响回滚能力，不该让升级本身失败（与组件锚点同一姿态）。
        logger.warning(
            "平台回滚锚点不完整（缺 %s）：失败时不会自动回滚。锚点=%s",
            "、".join(missing),
            json.dumps(anchor, ensure_ascii=False),
        )
    logger.warning("平台回滚锚点已捕获：%s", json.dumps(anchor, ensure_ascii=False))
    if checkpoint_sink is not None:
        try:
            checkpoint_sink(task.get("task_id"), {"platform_rollback_anchor": anchor})
        except Exception:  # noqa: BLE001 - 状态文件写入失败不该让升级失败
            logger.exception("平台回滚锚点写入状态文件失败（忽略）")
    return anchor


def _compose_image_for(context: Any, service: str) -> str:
    """读 project compose 里某服务当前的 image 声明。"""
    compose_path = Path(getattr(context, "project_path", "")) / str(
        getattr(context, "compose_file", "") or "docker-compose.yml"
    )
    if not compose_path.is_file():
        return ""
    in_service = False
    try:
        lines = compose_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""
    for line in lines:
        stripped = line.strip()
        if not in_service:
            if stripped.startswith(f"{service}:"):
                in_service = True
            continue
        if line[:1].strip() == "" and stripped.endswith(":") and not stripped.startswith("#"):
            break
        if stripped.startswith("image:"):
            return stripped.split("image:", 1)[1].strip()
    return ""


def anchor_rollback_override_images(anchor: dict[str, Any]) -> list[dict[str, str]]:
    """回滚时要写回 override 的旧镜像列表（`compose.override` 的 images 形状）。

    只取**有旧 tag** 的服务；缺 tag 的服务宁可留在原地也不要换成空 image
    ——那会让 compose 把它当成"没有镜像"而报错，回滚反而失败。
    """
    images: list[dict[str, str]] = []
    for service, facts in (anchor.get("images") or {}).items():
        tag = str((facts or {}).get("tag") or "")
        if tag:
            images.append({"service": str(service), "image": tag})
    return images


def business_count_guard(anchor: dict[str, Any], database: Path) -> dict[str, Any]:
    """回滚后的业务计数守卫：与锚点里的升级前快照逐表比对。

    判据取「不得减少」而不是「完全相等」：回滚窗口内采集照常进行，
    新增的塔/卷是正常业务增长，少了才是数据损坏（这与 `_counts_not_less_than_source`
    的既有口径一致）。
    """
    before = dict((anchor.get("pre_upgrade") or {}).get("counts") or {})
    after = _db_counts_snapshot(Path(database))
    regressions: dict[str, dict[str, int]] = {}
    for table, baseline in before.items():
        try:
            expected = int(baseline)
        except (TypeError, ValueError):
            continue
        actual = int(after.get(table, 0))
        if actual < expected:
            regressions[table] = {"before": expected, "after": actual}
    return {
        "ok": not regressions,
        "before": before,
        "after": after,
        "regressions": regressions,
    }