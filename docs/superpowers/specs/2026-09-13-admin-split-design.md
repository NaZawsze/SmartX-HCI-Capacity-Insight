# admin.py 二次拆分设计（49-13 后续维护）

更新时间：2026-09-13
状态：设计完成，待实施
关联：task_plan.md Phase 49 第 13 项后续维护；docs/pending-tasks.md P3

## 1. 背景

49-13 拆分巨型文件时，`backend/app/v2/api/admin.py`（547 行，43 条路由）按设计只"搬家 + 分节注释"，明确"响应模型批次落地时再细化"。49-14/49-16 响应模型批次已全部完成（43 条路由已带 `response_model=`），二次拆分时机已到。

## 2. 原则

- **纯结构重构**：不改任何行为、不改路由路径与 payload、不改对外接口。
- 兼容优先：`from app.v2.api import admin` + `admin.router` 保持可用（`api/__init__.py` 第 3/31 行依赖）。
- 验收：拆分前后 `/openapi.json` 的 `(method, path)` 集合 diff 为空；全量 308 测试回基线。

## 3. 目标结构

```text
app/v2/api/admin/
├── __init__.py        # router = APIRouter(); include 各域子 router（对外路径不变）
├── exports.py         # GET /api/admin/exports/{category}/{filename}（1 条）
├── migration.py       # /api/admin/migration*（8 条）
├── system_admin.py    # /api/admin/system/*（10 条；命名避开现有 api/system.py）
└── upgrade.py         # /api/admin/upgrade*（16 条）+ /api/admin/component-upgrade*（8 条）
```

- 各子模块按需引入 deps/models/service，`router = APIRouter()`。
- `bearer = HTTPBearer(auto_error=False)` 在原 admin.py 中定义但从未使用（死代码），保留在 `__init__.py` 中避免任何行为变化。
- 路由 include 顺序保持原文件顺序：exports → migration → system_admin → upgrade。

## 4. 验收

- 拆分前后 `/openapi.json` 的 `(method, path)` 集合 diff 为空。
- 全量 308 测试回基线（10 个环境性错误已修复，现为 308 全绿）。
- 健康检查正常。

## 5. 不做范围

- 不改任何函数逻辑、命名、payload 字段。
- 不拆 models.py（49 个模型保持集中，后续按需再细化）。
