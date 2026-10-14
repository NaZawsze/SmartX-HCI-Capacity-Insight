# 采集接口异步化设计（pending #87 遗留）

- 日期：2026-10-14
- 来源：pending #87（「请求超时」误报的结构性修法）；2026-10-09 误报取证见 findings.md
- 状态：设计（待实施）

## 1. 背景与现状

**现象**：点「立即采集」后，HTTP 请求同步阻塞 **80–111 秒**（`.3` 实测 78–80s、`.12` 约 111s）。
前端 30s 超时必然先触发「请求超时」，而**后端其实继续跑完并成功**——是误报。
2026-10-09 已做**缓解**：采集专用超时放宽到 240s（< nginx 300s）+ 诚实文案「后台可能仍在执行…」。
**根因未除**：长同步请求本身不可靠（代理超时、浏览器中断、无进度、易重复点击）。

**代码位置**：
- `backend/app/v2/api/collection.py:104` `POST /api/collection/run` → 同步调用 `CollectionService.run_manual_collection`
- `backend/app/v2/collection/service.py:48` `run_manual_collection(...)` 同步执行全量采集
- `collection_runs` 表已有 `status/message/trigger/cycle_id/attempt/max_attempts`（`service.py:208` INSERT）
- **`GET /api/collection/runs/{run_id}` 与 `GET /api/collection/runs` 已存在**（`collection.py:116/126`）
  —— 轮询端点无需新建，这正是本设计能把改动面压小的原因。

## 2. 目标与口径

| 项 | 口径 |
| --- | --- |
| 提交即返回 | `POST /api/collection/run` 立即返回 **202** + `run_id`（不等待采集完成） |
| 状态可见 | 前端轮询**既有** `GET /api/collection/runs/{run_id}`；终态 `success` / `failed` 与原语义一致 |
| 单飞 | 沿用现有守卫：已有 `running` 采集时**拒绝新提交**（返回 409 + 可读提示，不排队） |
| 失败如实 | 采集异常照旧写 `collection_runs.message`（含「成功 N 个集群，失败 M 个」） |
| 兼容 | 保留**同步模式开关**（env，如 `SMARTX_COLLECTION_RUN_ASYNC=0` 回落同步）供排障；默认异步 |

## 3. 方案

1. **提交侧**：`POST /api/collection/run` → 先做单飞检查 → 插入 `collection_runs`（`status='running'`,
   `trigger='manual'`）→ 交给**后台执行**（web-api 侧线程；沿用现有任务执行模式，不引入新容器）→
   立即返回 `{run_id, status:"running"}`。
2. **执行侧**：后台线程调用既有 `run_manual_collection`，结束写终态（`success`/`failed` + message）。
   异常兜底：任何未捕获异常都必须落 `failed` + 异常摘要（**不允许静默**）。
3. **前端**：`POST` 成功后用 `run_id` 轮询 `GET /api/collection/runs/{run_id}`（间隔 3–5s，上限沿用
   采集超时 240s），显示「采集中…」进度与最终结果；240s 仍是兜底而非主路径。
4. **兼容**：`SMARTX_COLLECTION_RUN_ASYNC=0` 时走原同步路径（排障/回退用，一处分支）。

## 4. 边界与不做

- **不改采集逻辑本身**（Tower 调用、写库、Prometheus 合并、数据质量评估全不动）；
- **不引入新容器/新队列**（本项目 5 容器边界，AGENTS §6）；
- 不做「排队多个采集」（单飞语义保持不变）；
- 不改 `collection_runs` 表结构（现有列已够）。

## 5. 测试计划

| 用例 | 断言 |
| --- | --- |
| 提交即返回 | `POST` 在 **< 2s** 返回 202 与 `run_id`；响应体无全量采集结果 |
| 状态流转 | 轮询 `GET /runs/{id}`：`running` → `success`；message 含集群/VM 计数 |
| 单飞 | 采集中再提交 → 409 + 可读提示；不产生第二条 `running` 行 |
| 失败如实 | 模拟 Tower 不可达 → 终态 `failed` + 错误摘要（非静默、非 500） |
| 同步回退 | `SMARTX_COLLECTION_RUN_ASYNC=0` → 行为与现状一致（老用例全过） |
| 前端 | vitest：点按钮 → 显示采集中 → 轮询到成功；不再出现 30s 超时误报 |

## 6. 回滚

单点改动 + 一个 env 开关：`SMARTX_COLLECTION_RUN_ASYNC=0` 即回到同步；代码 `git revert` 亦无数据影响。
