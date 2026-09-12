# API 响应模型分批落地设计（Phase 49-14）

更新时间：2026-09-13
状态：设计完成，待实施（分 5 批，每批独立提交/部署）
关联：task_plan.md Phase 49 第 14 项；docs/pending-tasks.md P3

## 1. 目标与原则

目标：v2 API 全部 GET/列表类端点定义 Pydantic `response_model`，让 OpenAPI 文档即契约，逐步替代前端 `normalizeDashboardSummary` 等"猜结构"兜底。

原则：

1. **模型描述现状，不改变现状**：字段名、类型、可空性以当前实际返回为准（含历史 camelCase 混用），先固化再谈统一。
2. **每批一个提交 + .3 部署**；批内端点的响应做"金样本对比"（改前/改后各拉一次真实响应，序列化后键集与值类型 diff 为空）。
3. 前端 normalize 保留到对应批次完成后再删（该端点的前端测试同步改为断言真实结构）。
4. 写端点（POST/PUT body）不在本设计范围（已有部分请求模型）。

## 2. 分批计划

| 批次 | 端点 | 模型要点 | 依赖 |
| --- | --- | --- | --- |
| 批次 1（已有基础） | `/api/towers*`、`/api/towers/{id}/test` | TowerResponse/TowerTestResponse 已存在；补 `last_collection` 模型（已完成） | 无 |
| 批次 2 | `/api/dashboard/summary`、`/api/collection*`、`/api/tasks*`、`/api/me`、`/api/system/*` | DashboardSummary 全嵌套模型（totals/storage/kpis/capacity_risk 含 thresholds+evaluated_at/risk_clusters/top_clusters/towers/tower_runs/scope/scope.cluster_enabled/latest_run）；任务 severity/steps/links | 批次 1 |
| 批次 3 | `/api/vms*`、`/api/vm-volumes`、`/api/reports/latest`、`/api/reports/export` 列表类 | VM 趋势（含 freshness/gap 字段）、报表 payload 大对象（clusters/forecast 含新稳健字段/growth_rate 三窗口/data_quality） | 批次 2 |
| 批次 4 | `/api/admin/*` 读类（升级状态/历史/verification、迁移状态/健康检查） | admin 响应按域拆模型 | 批次 2 |
| 批次 5 | 写类响应收尾 + 删除前端对应 normalize | 清理 `api.ts` 中已覆盖端点的 normalize/兜底 | 全部 |

## 3. 实施规则

- 模型放各域模块内（api 拆分完成后在 `app/v2/api/<域>.py`；未拆分前放 `app/v2/api.py` 对应段）。
- 可空性：历史返回 `null` 的字段一律 `Optional[...] = None`；严禁把现状"顺手修正"。
- 大对象（报表 payload）允许用 `model_config = ConfigDict(extra="allow")` 过渡，二批收敛为精确字段。
- 金样本对比脚本：`scripts/check_response_contract.py <endpoint> <token>`（改前生成 `contracts/<name>.json`，改后 diff），存 `contracts/` 目录（.gitignore）。
- 每批验收：新模型单测（序列化键集断言）+ 金样本 diff 为空 + 前端该端点测试回归 + .3 部署健康。

## 4. 与前端的关系

- 批次 2~4 期间前端不动（normalize 兼容两种形态）。
- 批次 5 删除对应 normalize 与"旧字段 fallback"分支（如 `capacityRisk` 的 usedRatio 兜底、`cluster_growth_rate_per_day` 兼容），前端测试同步更新——这是唯一可能暴露历史前后端契约漂移的环节，出问题按契约漂移处理（记录 findings，后端修正）。

## 5. 风险与回滚

- 风险：response_model 序列化会**剔除未声明字段**，若模型遗漏实际返回字段则前端拿不到数据。缓解：批次内金样本对比 + `extra="allow"` 过渡 + 前端测试全绿才部署。
- 回滚：单批单提交，revert 即恢复。


## 附录 B：契约校验脚本规格与 normalize 清理映射

### B.1 `scripts/check_response_contract.py`（批次 2 起使用，随批次 2 一并提交）

- 仅标准库 + httpx（容器内已有）。
- 用法：`python scripts/check_response_contract.py save --base http://127.0.0.1:8000 --token <TOKEN> --out contracts/`；
  `python scripts/check_response_contract.py diff --base ... --token ... --dir contracts/`
- save：对 `--endpoints` 清单逐个 GET（带 Bearer），响应 JSON 原样存 `contracts/<slug>.json`。
- diff：重新拉取，与存档做**结构对比**（递归比较键集与值类型；数值只比较类型不比较值；列表比较长度模式与首元素结构），差异打印退出码 1。
- 端点清单与 .3 登录凭据由执行者按 AGENTS.md 获取（管理员账号）。
- `contracts/` 加入 .gitignore。

### B.2 前端 normalize 清理映射（批次 5）

| api.ts 函数 | 覆盖端点 | 清理动作 |
| --- | --- | --- |
| normalizeDashboardSummary | GET /api/dashboard/summary | 批次 2 模型落地后删除；capacityRisk 的 usedRatio 兜底、cluster_growth_rate_per_day 兼容分支同步删 |
| normalizeMetricItem | clusters/day_fastest_growing_vms/top_vms | 同上 |
| normalizeCapacityRisk | capacity_risk 字段 | 同上 |
| 其余 normalize* | 对应批次 | 各自批次内删 |

每个删除点必须同步更新引用它的前端测试断言（改为真实结构）。

### B.3 模型字段来源

- DashboardSummary 嵌套结构的字段清单以 `frontend/src/types.ts` 的 `DashboardSummary`/`capacity_risk`/`scope` 定义 + 后端 `DashboardService._build_summary` 返回键为准（两者已在 2026-09-12 对齐：含 thresholds/evaluated_at/cluster_enabled）。
- 报表 payload 以 `ReportService.latest_report` 返回键为准（含 cluster_growth_rate 三窗口与 forecast 稳健字段）。
- 类型不一致处（前端有、后端无）记入 findings.md 契约漂移清单，逐条裁决。
