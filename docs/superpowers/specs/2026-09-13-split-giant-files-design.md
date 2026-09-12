# 拆分巨型文件设计（Phase 49-13）

更新时间：2026-09-13
状态：设计完成，待实施（四个文件各自独立提交/部署，可穿插在功能迭代之间）
关联：task_plan.md Phase 49 第 13 项；docs/pending-tasks.md P3

## 1. 原则

- **纯结构重构**：不改任何行为、不改对外接口、不改路由路径与 payload。
- 兼容优先：包拆分后保留原 import 路径（`__init__.py` 再导出），调用方零改动。
- 一个文件一个提交 + 一次 .3 部署验证；任意一步可独立 revert。
- 验证门槛：改动前后 OpenAPI 路由清单一致（api 拆分用脚本对比 `/openapi.json` 的 path+method 集合）；后端全量测试；前端目标测试 + 构建；.3 健康检查。

## 2. `backend/app/v2/api.py`（1112 行，69 条路由）→ 包

目标结构：

~~~text
app/v2/api/
├── __init__.py        # router = APIRouter(); include 各域子 router（对外路径不变）
├── deps.py            # 现有 get_*_service 依赖与公共 Annotated 别名
├── auth.py            # /api/auth/login、/api/me（3 条）
├── towers.py          # /api/towers*（7 条 + test/clusters/sync）
├── dashboard.py       # /api/dashboard/summary（1 条）
├── vms.py             # /api/vms*、/api/vm-volumes（5 条）
├── reports.py         # /api/reports*（4 条）
├── collection.py      # /api/collection*（3 条）
├── tasks.py           # /api/tasks*（5 条）
├── system.py          # /api/system/*（1 条）
└── admin.py           # /api/admin/*（43 条；内部再按 upgrade/migration/system 分节注释）
~~~

- `admin.py` 首批不继续拆（43 条在同一响应模型批次里还会动），只搬家 + 分节注释；响应模型批次落地时再细化。
- 验收：拆分前后 `/openapi.json` 的 `(method, path)` 集合 diff 为空；`from app.v2.api import router` 与 `from app.v2.api import xxx` 兼容（`__init__` 再导出）。

## 3. `backend/app/v2/reports/export.py`（3720 行）→ 包

现状函数分布：`_customer_*`（Word 客户版模板）、`_xlsx_*/_write_xlsx_template_*/_setup_*`（Excel 模板）、43 个 `_*` 公共助手（字节数/百分比标签、颜色、集群命名、数据质量状态等）、3 个 `build_report_*` 公共入口。

目标结构：

~~~text
app/v2/reports/export/
├── __init__.py        # 再导出 build_report_word / build_report_excel 等公共入口
├── common.py          # 公共助手（标签格式化、颜色常量、集群名、数据质量文案）
├── word.py            # Word 客户版（_customer_*、封面/摘要/矩阵/建议）
├── excel.py           # Excel 客户版（_xlsx_*、_write_xlsx_template_*、_setup_*）
└── legacy.py          # 其余未归类函数（逐步消化）
~~~

- `common.py` 的助手在 word/excel 间以 `from .common import` 引用，禁止循环导入（公共助手不得 import word/excel）。
- 验收：`grep "from app.v2.reports.export import"` 全部调用方零改动；Word/Excel 导出各真实跑一次（.3 导出产物人工抽查 + 既有 export 测试回归）。

## 4. `backend/app/v2/upgrade/service.py`（1791 行，UpgradeService 55 方法）→ Mixin 拆分

选择 Mixin 方案（而非拆服务类）：UpgradeService 的状态字段（database/settings/tasks/prometheus）被全部方法共享，Mixin 拆分零行为风险且 import 路径稳定。

~~~text
app/v2/upgrade/service/
├── __init__.py        # class UpgradeService(... mixins 组合)（原类名/构造签名不变）
├── intake.py          # upload_package_bytes / delete_package / history / version / component_version
├── precheck.py        # precheck
├── execution.py       # start / status / cancel / runner 提交与状态同步
├── cleanup.py         # create/retry/status post_upgrade_cleanup 三方法
├── verification.py    # verification / latest_package / 包身份校验
└── fs.py              # _safe_extract / _remove_path / _backup_existing_project_path 等模块级助手
~~~

- 验收：`UpgradeService` 构造签名与公开方法集合不变（脚本对比 `dir()`）；既有 upgrade 测试回归。

## 5. `frontend/src/pages/ServicePage.tsx`（2305 行）→ 域组件

页面四大域：升级中心（上传/预检查/任务/恢复控制）、服务状态（组件状态/重启）、空间清理（扫描/清理/SQLite 备份清理）、数据迁移（导出/导入/配置迁移）。

~~~text
frontend/src/components/service/
├── UpgradeCenterSection.tsx
├── ServiceStatusSection.tsx
├── CleanupSection.tsx
├── MigrationSection.tsx
└── shared.tsx            # 页内公共小组件
ServicePage.tsx 收敛为：状态编排 + 四个 Section 的组装（目标 ≤400 行）。
~~~

- 拆分前先在文件内标注段落边界（现有代码按域注释分块）；props 走显式接口，不引入全局状态。
- 验收：现有 ServicePage 测试迁移后全绿；tsc 通过；页面功能人工抽查（上传/重启/清理/迁移各一次）。

## 6. 实施顺序与节奏

1. api.py（最小行为风险，为响应模型批次铺路）
2. ServicePage.tsx（前端独立，随时可做）
3. export.py（导出产物需人工抽查，安排在无发布压力时）
4. upgrade/service.py（Mixin 拆分，放最后）

每个文件：独立提交（`refactor: split xxx`）→ .3 构建部署 → 该文件对应验收 → 标记。四个全部完成后本项关闭。

## 7. 不做范围

- 不借此机会改任何函数逻辑、命名、payload 字段。
- admin.py 的二次拆分、export legacy 的消化归入后续维护，不在本项验收内。
