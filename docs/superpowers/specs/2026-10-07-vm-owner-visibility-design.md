# 虚拟机所有者与「虚拟机组」可见性设计 —— Phase 69

- 状态：**设计定稿（2026-10-07），待用户批准开工**；门 1（Tower 只读可读性）已通过。
- 来源：2026-10-07 用户需求——「准备测试 Tower 只读用户是否能读取到每台虚拟机对应的所有者，
  在我们容量监测平台上增加虚拟机所有者相关信息，并且在报表导出的表格内也加上所有者列」；
  同日确认「虚拟机组 = CloudTower 的 folder（文件夹），不是放置组」。
- 阻塞史：Tower 不可达期间已完成探针与门 1 判定；`.3` 现场（只读账号、测试集群 `SMTX_TEST`，
  4 台 VM）实测通过后定稿。

## 1. 范围与交付物

| # | 交付物 | 说明 |
| --- | --- | --- |
| D1 | **所有者** `owner` | CloudTower VM 标签 `system.cloudtower/owner` 的值（已是用户名） |
| D2 | **虚拟机组** `folder_name` | CloudTower VM 的 `folder.name`（用户口径「虚拟机组」；**不是** `vm_placement_group` 放置组） |
| D3 | 平台展示 | VM 页（列表行 + 详情卡）显示两字段；空值显示 `-` |
| D4 | 报表导出 | Word 与 Excel 的 VM 表格各加两列，表头「所有者」「虚拟机组」 |

不做：dashboard 概览卡片加列（保持卡片密度）；按所有者/虚拟机组筛选（后续按需立项）；
所有者变更历史（只存最新值，随采集更新）。

## 2. 门 1 结果（2026-10-07，`.3` 现场只读账号，探针实测，Tower id=4 SMTX_TEST）

| 问题 | 结论 |
| --- | --- |
| get-vms 是否含所有者 | ✅ **含**——藏在 `labels[]`：`key == "system.cloudtower/owner"`，`value` 即所有者 |
| 只读账号是否可见 | ✅ 可见（平台里配置的就是只读账号） |
| 所有者形态 | **直接是名字**（样例 `"root"`），**不需要 get-users 解析**（只读账号对 get-users 500 无权限，恰好不影响） |
| 空值形态 | 未设置的 VM **无该 label**（4 台中 3 台有、1 台无）→ 落 `NULL` |
| 虚拟机组 | `folder` = `{id, name}` 只读可读（3/4 台有值，1 台未归入文件夹）；`vm_placement_group` 为空且非本需求 |

原始证据：`labels: [{"id": "...", "key": "system.cloudtower/owner", "value": "root"}]` ×3 台 + 1 台无 labels。
探针：`scripts/probe_tower_vm_owner.py`（自动识别上述形态 + folder/placement 上报；两种模式、凭据不外显）。

## 3. 口径（实现与验收的唯一依据）

1. **owner**：取 `labels` 数组中**第一条** `key == "system.cloudtower/owner"` 的 `value`；
   值非字符串时 `str()` 化；无该标签或值为空 → `NULL`（**不猜、不填充**）。
   key 匹配区分大小写（按 Tower 实测原样）。
2. **folder_name**：取 `vm["folder"]["name"]`；`folder` 缺失/非对象/名字为空 → `NULL`。
   只存名字（展示与导出口径）；folder 的 `id` 不做存储（当前无跨库关联需求）。
3. **回收站 VM**：照常提取并落库（Tower 上标签可能保留原主）；展示与报表沿用既有
   `in_recycle_bin` 排除规则——本特性不改展示排除口径。
4. **敏感面**：所有者姓名属人员信息——**仅展示与导出**；不写日志、不进 Prometheus 标签。
5. **更新语义**：最新值覆盖（每次采集 upsert）；不做历史表。
6. **同源**：两字段与 VM 列表同一次 `get-vms` 调用返回，**不新增任何 API 依赖**；
   查询期零跨系统调用。

## 4. 改动面（实现级，逐文件）

### 4.1 采集与存储

| 文件 | 改动 |
| --- | --- |
| `backend/app/v2/cloudtower/client.py::_normalize_vm` | 增加两个提取：`"owner": _owner_from_labels(raw.get("labels"))`、`"folder_name": _folder_name(raw.get("folder"))`；新增两个模块级小函数（注释引用门 1 实测） |
| `backend/app/v2/collection/service.py` | vm 入库处带上两字段（`vm_latest` 的 INSERT/ON CONFLICT 列扩展） |
| `backend/app/v2/database.py` | `_ensure_column(conn, "vm_latest", "owner", "TEXT")`、`_ensure_column(conn, "vm_latest", "folder_name", "TEXT")`（与 in_recycle_bin 同款 **expand-only**） |
| `backend/app/v2/upgrade/migrations/registry.json` | 新增两条 `add_column_if_missing` 条目（`table/column/definition` 三键，与构建门禁 `verify_migrations_expand_only` 口径一致） |

### 4.2 API 与前端

| 文件 | 改动 |
| --- | --- |
| `backend/app/v2/api/vms.py`（`/api/vms`、`/api/vms/{vm_id}`） | 查询与响应带出两字段（空值为 `null`） |
| `backend/app/v2/api/models.py` | `VmDetailResponse` 等模型加 `owner: str | None`、`folder_name: str | None` |
| `docs/api.md` | 契约同步（`scripts/verify_api_docs.py` 必跑） |
| `frontend/src/types.ts` | VM 相关类型加两字段 |
| `frontend/src/pages/VmsPage.tsx` | VM 列表行 + 详情卡显示「所有者」「虚拟机组」；空值 `-`；过 `frontend-style-guide`（`:root` 变量、6/8px 圆角） |
| `frontend/src/pages/VmsPage.test.tsx` | 渲染用例：有值 / 空值 / 长名字截断 |

### 4.3 报表导出（用户明确要求的两列）

| 文件 | 改动 |
| --- | --- |
| `backend/app/v2/reports/service.py::_latest_vm_labels` | SELECT 增加 `owner, folder_name` 并进入 label map（键 `owner` / `folder_name`；两份报表共用同一映射） |
| `backend/app/v2/reports/export/word.py`（`_customer_vm_growth_table`） | 表头 `["排名","虚拟机名称","所有者","虚拟机组","当前容量","期初容量","增长量","增长率"]`（6→8 列）；`_docx_set_table_width` 宽度表同步；行值取 `labels.get("owner")/("folder_name")`，空 `-` |
| `backend/app/v2/reports/export/excel.py`（VM 两张表：增长量/增长率） | `amount_headers` / `ratio_headers` 同步 8 列；行值同源；列宽随列数调整 |
| `backend/app/v2/reports/templates/customer_report.xlsx` | **核对**：模板若含这两张表的预置表头/样式需同步；若表头完全由代码写入则不动（实施第一步先核对） |
| `backend/tests/`（报表相关） | 导出单测断言新列存在与取值 |

## 5. 验收标准（全部可执行）

| # | 判据 | 方法 |
| --- | --- | --- |
| A1 | 采集落库与塔一致 | `.3` 真机（现有只读测试塔 + 4 台 VM）跑一轮采集 → SQLite：Test1/2/3 `owner='root'`、Test4 `NULL`；Test1/2/3 `folder_name` 非空、Test4 `NULL` |
| A2 | API 透出 | `GET /api/vms`、`GET /api/vms/{id}` 返回两字段；空值为 `null`；`verify_api_docs` 通过 |
| A3 | 前端展示 | VM 页列表行与详情卡可见两字段、空值 `-`；vitest/tsc 全绿；`.3` 预览目视 |
| A4 | **报表两列** | Word 与 Excel 各导出真实报告：VM 表格表头含「所有者」「虚拟机组」，行值与 A1 一致；目视（含空值与长名字） |
| A5 | 回归 | `.3` 后端全量 + 前端门禁回到基线（1F 既有环境限制） |

## 6. 边界与风险

| 风险 | 处置 |
| --- | --- |
| `labels` 多条同 key / 值非字符串 | 取第一条匹配并 `str()`；单测覆盖 |
| `folder` 为对象但无 name / 直接缺席 | 均落 `NULL`；单测覆盖（Test4 即真实样例） |
| 报表 8 列后宽度/分页观感 | Word 宽度表与 Excel 列宽同步调整；目视判据 A4 |
| Excel 模板预置表头 | 实施第一步核对模板，必要时同步（见 §4.3） |
| 旧版本读新库 | expand-only：旧代码 SELECT 不引用新列，无感；旧包升级后新列随采集自动回填 |
| 所有者含特殊字符（中文/emoji） | 全链路 UTF-8；Word/Excel 字体回退已由既有样式处理 |

## 7. 测试计划（实施时逐项执行）

1. **单测（后端）**：`_owner_from_labels`（有/无 labels、无该 key、空值、多条同 key、非字符串值）；
   `_folder_name`（对象/缺 name/缺失/非对象）；`_ensure_column` 幂等；采集入库带值（fake 塔数据）；
   `_latest_vm_labels` 带出两键；Word/Excel 导出含两列（断言）。
2. **前端**：`VmsPage.test.tsx` 有值/空值/长名字；tsc + vitest 全量。
3. **真机（`.3`）**：一轮采集 → A1；预览目视 A3；两份报表导出 → A4。
4. **契约**：`scripts/verify_api_docs.py`；全量回归 A5。

## 8. 回滚

- 代码 `git revert` 即回退（前端/报表/API/采集各自独立可回）；
- **数据库两列保留**（expand-only，列无害；旧版本读写不受影响）；
- 不动 Tower 侧任何配置；采集失败时新列为 `NULL`，展示 `-`。

## 9. 排期与依赖

- **不与 v0.5.4 发布捆绑**（该候选的验证链已冻结）——随 v0.5.4 之后的下一版本交付；
- 无外部依赖（只读测试塔已就绪、字段路径已实测）；
- 实施顺序：采集/存储 →（A1）→ API/前端 →（A2/A3）→ 报表 →（A4）→ 全量回归。
