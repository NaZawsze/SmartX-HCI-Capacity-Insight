"""W3：runner 自换组件升级（kubeadm/Omaha 形态）。

工程规格：docs/superpowers/specs/2026-10-05-upgrade-architecture-v054-impl-spec.md §W3
设计：docs/superpowers/specs/2026-10-05-upgrade-architecture-v054-design-v2.md §2.2
测试：T11（v0.3.2→v0.3.3-rc 自换实测：停机 ≤30s、presence ≤60s、web-api 零编排）

## 目标形态

组件升级 = **runner 自己把自己换掉**：load 新镜像 → 写自身 compose → 调度 handoff →
旧容器被替换、新 runner 起来回报 presence。web-api 退出整套编排
（stop / 交接 / 守卫），US-04 那类事故（源端编排杀新 runner）结构性消失。

## 本模块负责的两件事

1. **回滚锚点捕获**（`capture_component_rollback_anchor`）：必须在 compose writeback
   **之前**。writeback 会把 compose 里的 tag 改成新版本，改完旧值就没了——
   锚点是组件回滚唯一依据（反向自换回旧 tag），因此捕获与 writeback 必须是
   "先取后改"的两步，不能合并成一个动作。
2. **收尾判定**（`component_handoff_finished`）：`schedule_target_runtime_handoff`
   之后旧 runner 的代码**不会执行**，一切收尾走新 runner 启动路径
   （`_finish_runner_component_steps`）。本函数就是那条路径上的判据。

## 自换窗口的并发前提

handoff 之后、docker 真正替换容器之前，新旧 runner 会**短暂并存**（各一个进程，
写同一个状态文件）。因此：
- 状态文件用 `os.replace` 原子替换、last-writer-wins，不会出现半截 JSON；
- presence 判定必须容忍 `instance_id` 变化与心跳跳变（`runner_presence` 按
  30s 陈旧阈值判定，正常自换 ~15s，不该误判）；
- 旧 runner 退出前若还在写 DB 兼容镜像，那是**已知的噪声源**（用户 2026-10-05
  明确点名：presence 抖动时第一嫌疑就是它），故收尾判定不得依赖 DB 镜像。

## 不做什么

- 不新增动作类型。复用 v0.3.1 已有的 `image.load` / `compose.override` /
  `runner.schedule_target_runtime_handoff`（动作词汇冻结，impl-spec §0.3）。
- 不删旧编排路径。`v0.5.3 + v0.3.1 → v0.3.2` 这一跳（矩阵 M3 格）仍走旧编排，
  自换时代从 v0.3.2 起生效。
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: presence 等待上限（秒）。规格 §W3 步骤 4 的"presence 超时 120s"。
#: 这是**上限不是目标**——正常自换 ~15s（用户 2026-10-05 明确要求不得当目标）。
PRESENCE_WAIT_TIMEOUT_SECONDS = 120

#: 预期自换时长（秒），仅用于日志与告警分级：超过它说明自换偏慢，但**不改变判定**。
EXPECTED_HANDOFF_SECONDS = 15

#: compose writeback 的目标文件（与 US-32 对账同一份文件）。
COMPOSE_FILENAME = "docker-compose.yml"

_IMAGE_LINE = re.compile(r"^(?P<prefix>\s*image:\s*)(?P<image>\S+)\s*$")


#: 动作结果里的哨兵键：`runner.schedule_target_runtime_handoff` 返回它时，
#: `UpgradeEngine` 必须在**该动作返回点**立刻停止，不再写任何状态。
#:
#: 为什么需要显式哨兵而不是"约定 handoff 是最后一个动作"：
#: engine 在动作返回后会做三件必然出问题的事——把动作标记 succeeded、跑 compose tag
#: 对账、把任务置 success。handoff 之后旧 runner 进程随时会被 docker 替换掉，
#: 这些写会变成"写到一半被 SIGKILL"，留下 revision 与实际状态不一致的 task.json
#: （US-24 的崩溃循环就是这么来的）。约定无法阻止引擎继续执行，哨兵可以。
HANDOFF_FINAL_KEY = "handoff_final"


def handoff_final_result(**payload: Any) -> dict[str, Any]:
    """构造带"到此为止"哨兵的动作返回值。"""
    return {HANDOFF_FINAL_KEY: True, **payload}


def is_handoff_final(result: dict[str, Any] | None) -> bool:
    """动作结果是否要求引擎立即停止（不再写任何状态）。"""
    return bool(isinstance(result, dict) and result.get(HANDOFF_FINAL_KEY))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _runner_image_in_compose(compose_path: Path) -> str:
    """读 project compose 里 upgrade-runner 当前的 image 声明。

    逐行状态机而非正则扫全文：真实 compose 在 `upgrade-runner:` 之后先有 `build:` 块，
    `image:` 位置不固定（US-26-4 已踩过一次，用正则会取错行或取不到）。
    """
    try:
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
        # 顶格的新服务名 = 已离开 upgrade-runner 块
        if line[:1].strip() == "" and stripped.endswith(":") and not stripped.startswith("#"):
            break
        if stripped.startswith("image:"):
            return stripped.split("image:", 1)[1].strip()
    return ""


def running_service_container_id(
    executor: Any, compose_project: str = "", service: str = "upgrade-runner"
) -> str:
    """当前运行中某服务的容器 ID（**限定 compose project**）。

    ## 为什么必须限定 project

    只按 service 名 `com.docker.compose.service=upgrade-runner` 过滤会命中**同机所有 project**
    的 runner 容器。`.3` 实测：自换锚点抓到的 `previous_version` 是 `v0.5.1`——
    那是 `.3` 上另一个 project（`smartx-hci-capacity-insight`）的 runner，不是本 project 的
    `v0.3.2`。后果不是显示问题，而是**组件回滚锚点记成别人的版本与镜像 ID**，
    反向自换会换到一个完全不相干的版本。

    这在客户机上不是边角情况：`v0.5.1u2 → v0.5.2` 桥接链的**常态**就是同机同时存在
    旧 project 的 runner 与新 project 的 runner（AGENTS §7 的引导步骤明确如此）。

    口径与 web-api 侧 `_active_runner_state_from_docker` 对齐（那里按 project 优先排序），
    但本函数更严格：**project 不匹配直接不认**，而不是排在后面。
    """
    filters = ["--filter", f"label=com.docker.compose.service={service}"]
    expected = str(compose_project or "").strip()
    if expected:
        filters.extend(["--filter", f"label=com.docker.compose.project={expected}"])
    try:
        output = executor.output(
            ["docker", "ps", *filters, "--format", "{{.ID}} {{.Label \"com.docker.compose.project\"}}"]
        )
    except Exception as exc:  # noqa: BLE001 - 探测失败不得让组件升级判失败
        logger.warning("自换锚点：探测运行中 %s 容器失败（%s），该项留空", service, exc)
        return ""
    candidates = [line.split() for line in output.splitlines() if line.strip()]
    if not candidates:
        if expected:
            # 过滤条件已含 project，查不到就是真的没有；记一条便于排障（不当作错误）
            logger.warning("自换锚点：未找到 project=%s 下运行中的 %s 容器", expected, service)
        return ""
    # 同 project 内可能有多个（如 --force-recreate 期间的短暂并存），取 ID 最小者保证稳定
    candidates.sort()
    return candidates[0][0]


def image_id_of_container(executor: Any, container_id: str) -> str:
    if not container_id:
        return ""
    try:
        output = executor.output(
            ["docker", "inspect", "--format", "{{.Image}}", container_id]
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("自换锚点：读取容器镜像 ID 失败（%s），该项留空", exc)
        return ""
    return output.strip()


def image_id_of_tag(executor: Any, image: str) -> str:
    if not image:
        return ""
    try:
        output = executor.output(["docker", "image", "inspect", "--format", "{{.Id}}", image])
    except Exception as exc:  # noqa: BLE001
        logger.warning("自换锚点：读取镜像 %s 的 ID 失败（%s），该项留空", image, exc)
        return ""
    return output.strip()


def container_file_value(executor: Any, container_id: str, path: str) -> str:
    """读容器内某个文件的内容（版本号等）。读不到就返回空串，绝不抛。"""
    if not container_id:
        return ""
    try:
        return executor.output(
            ["docker", "exec", container_id, "sh", "-lc", f"cat {path} 2>/dev/null || true"]
        ).strip()
    except Exception as exc:  # noqa: BLE001
        logger.warning("读取容器 %s 内 %s 失败（%s），该项留空", container_id, path, exc)
        return ""


def _running_runner_container_id(executor: Any, compose_project: str = "") -> str:
    return running_service_container_id(executor, compose_project, "upgrade-runner")


def _image_id_of_container(executor: Any, container_id: str) -> str:
    return image_id_of_container(executor, container_id)


def _image_id_of_tag(executor: Any, image: str) -> str:
    return image_id_of_tag(executor, image)


def capture_component_rollback_anchor(
    context: Any,
    task: dict[str, Any],
    *,
    executor: Any,
    target_version: str,
) -> dict[str, Any]:
    """捕获组件回滚锚点。**必须在 compose writeback 之前调用**。

    为什么必须先取：writeback 会把 `docker-compose.yml` 里的 runner image 改成
    `target_version` 对应的镜像。改完之后，"上一版是哪个 tag / 哪个镜像 ID"就再也
    读不出来了——而反向自换（组件回滚）恰恰只能靠这两个值。顺序反了，
    锚点里就只会记到新版本，回滚变成"把新版本换回新版本"。

    三项内容（缺一不可）：
    - `previous_version`：当前实际运行的 runner 版本（不是 compose 里写的——
      compose 可能长期滞后于运行态，US-26/32 的多事实源现场）；
    - `previous_image_tag`：compose 里当前声明的 image（writeback 要覆盖的那个值）；
    - `previous_image_id`：当前运行镜像的不可变 ID（tag 被移动后仍能定位镜像本体）。
    """
    container_id = _running_runner_container_id(executor, getattr(context, "compose_project", ""))
    image_id = _image_id_of_container(executor, container_id)
    previous_tag = _runner_image_in_compose(Path(context.project_path) / COMPOSE_FILENAME)
    previous_version = container_file_value(executor, container_id, "/app/RUNNER_VERSION")
    if not previous_version:
        # 容器不可 exec（正在重启/已退出）时退回从镜像 tag 推断，保底不留空
        match = re.search(r":(v[0-9][0-9A-Za-z._-]*)$", previous_tag or "")
        previous_version = match.group(1) if match else ""
    anchor = {
        "previous_version": previous_version,
        "previous_image_tag": previous_tag,
        "previous_image_id": image_id,
        "container_id": container_id,
        "target_version": str(target_version or ""),
        "captured_at": _now(),
    }
    missing = [key for key in ("previous_version", "previous_image_tag") if not anchor[key]]
    if missing:
        # 不抛异常：锚点缺失会让组件升级整体失败，而"没有锚点"只影响回滚能力。
        # 记 warning 让它出现在日志里，比让升级失败更符合用户预期。
        logger.warning(
            "自换锚点不完整（缺 %s）：组件回滚将不可用。锚点=%s",
            "、".join(missing),
            json.dumps(anchor, ensure_ascii=False),
        )
    logger.warning("组件自换锚点已捕获：%s", json.dumps(anchor, ensure_ascii=False))
    return anchor


def component_handoff_finished(
    task: dict[str, Any],
    *,
    runner_version: str,
    expected_version: str,
) -> bool:
    """新 runner 启动后判定"自换是否已完成"。

    只看**版本**是否到达目标值：这是唯一能证明"新代码确实在跑"的证据。
    instance_id 变化、心跳跳变都不作判据（自换窗口内新旧 runner 短暂并存，
    两者都会刷新同一个状态文件，见模块 docstring）。
    """
    expected = str(expected_version or "").strip()
    if not expected:
        return False
    return str(runner_version or "").strip() == expected


def presence_reached_target(
    state_file: dict[str, Any] | None,
    *,
    target_version: str,
    previous_instance_id: str = "",
) -> bool:
    """状态文件里是否已出现目标版本的 runner presence。

    与 `component_handoff_finished` 的区别：后者是**新 runner 进程自己**的视角
    （读自己的 RUNNER_VERSION），本函数是**外部观察者**（web-api / 旧 runner）
    读状态文件的视角。两者都要，因为：
    - 新 runner 启动时状态文件可能还带着旧 runner 最后一笔心跳（last-writer-wins）；
    - 只看版本号相等会在"旧 runner 版本号恰好相同"（同版本重装）时误判完成。
    故额外要求 `instance_id` 与自换前不同——除非调用方没给 previous_instance_id。
    """
    if not state_file:
        return False
    if str(state_file.get("runner_version") or "").strip() != str(target_version or "").strip():
        return False
    if previous_instance_id and str(state_file.get("instance_id") or "") == previous_instance_id:
        # 版本对但还是同一个进程在写：同版本重装场景，不能算自换完成
        return False
    return True


def handoff_outcome_message(
    *,
    waited_seconds: float,
    reached: bool,
) -> str:
    """自换结果的可读结论（任务中心与日志共用）。"""
    if reached:
        if waited_seconds > EXPECTED_HANDOFF_SECONDS:
            return (
                f"runner 自换完成（耗时 {waited_seconds:.0f}s，超过预期 {EXPECTED_HANDOFF_SECONDS}s，"
                "但在上限内）"
            )
        return f"runner 自换完成（耗时 {waited_seconds:.0f}s）"
    return (
        f"runner 自换未在 {PRESENCE_WAIT_TIMEOUT_SECONDS}s 内回报 presence"
        f"（已等 {waited_seconds:.0f}s）。升级执行器可能已退出，"
        "请检查 upgrade-runner 容器状态；必要时由 web-api 兜底重建。"
    )
