# AI 措辞层设计（Phase 14 后续增强）

更新时间：2026-09-13
状态：设计完成，待实施
关联：task_plan.md Phase 14 后续增强；docs/pending-tasks.md P3 #16

## 1. 背景

报表的关键发现、运维建议、风险摘要等自然语言文案当前全部由**确定性规则模板**生成（common.py 的 `_customer_key_findings`/`_customer_operation_advice`/`_capacity_risk_summary` 等）。task_plan.md Phase 14 后续增强：如果后续引入 AI，可作为可选增强层，仅用于改写建议措辞；**基础报告必须保持离线规则可用**。

## 2. 目标

设计一个**可选的 AI 措辞增强层**：

- 输入：规则模板产出的建议措辞（文本）。
- 输出：改写后的建议措辞。
- 未配置 AI 服务时（默认），直接返回规则文案（离线回退，行为与现状一致）。
- 不实际接外部 AI（内网离线产品），接入点留待有 AI 服务时。

## 3. 方案

### 3.1 新模块 `backend/app/v2/reports/wording.py`

```python
def ai_wording_enabled() -> bool:
    # 由环境变量 SMARTX_AI_WORDING_ENDPOINT 控制（默认关闭）
    return bool(os.environ.get("SMARTX_AI_WORDING_ENDPOINT"))

def enhance_wording(text: str, *, context: dict[str, Any] | None = None) -> str:
    # 未配置 AI 服务时返回原文本（离线规则回退）
    if not ai_wording_enabled():
        return text
    # TODO: 接入 AI 服务（内网离线产品暂不实际调用）。
    # 未来在此调用外部/本地模型改写 text，失败时回退原文本。
    return text
```

### 3.2 接入点

在规则措辞函数里，对生成的每条建议文案调用 `enhance_wording`：

- `_customer_key_findings`（关键发现，list[str]）
- `_customer_operation_advice`（运维建议，list[tuple[str, list[str]]]）

`enhance_wording` 默认回退，因此接入后行为与现状一致。

### 3.3 配置

- `SMARTX_AI_WORDING_ENDPOINT`：AI 服务地址（未设置 = 关闭，默认）。
- 未来可扩展 `SMARTX_AI_WORDING_MODEL`、`SMARTX_AI_WORDING_TIMEOUT` 等。

## 4. 验收

- AI 关闭（默认）时，报表措辞输出与现状完全一致（测试断言）。
- `enhance_wording` 未配置时返回原文本。
- 全量 308 测试回基线。

## 5. 不做范围

- 不实际接入外部 AI 服务（内网离线产品）。
- 不改规则模板的生成逻辑（仅在其输出上做可选改写）。
- 不覆盖告警文案（容量告警/数据质量告警），后续如需再扩展。
