# 虚拟机所有者可见性（VM Owner）设计 —— Phase 69

- 状态：**待门 1（Tower 可达 + 只读可见性）通过后实施**；本文为设计草案，口径与边界先行定稿。
- 来源：2026-10-07 用户需求——「准备测试 Tower 只读用户是否能读取到每台虚拟机对应的所有者，
  在我们容量监测平台上增加虚拟机所有者相关信息，并且在报表导出的表格内也加上所有者列」。
- 现状：Tower（`10.20.11.7:4433`）当前**不可达**（TCP 端口开、HTTPS 无响应，2026-10-07 `.12` 实测），
  实施被门 1 阻塞；探针工具已就绪（`scripts/probe_tower_vm_owner.py`），塔恢复后一条命令出结论。

## 1. 目标与验收

| # | 目标 | 验收判据 |
| --- | --- | --- |
| G1 | **只读账号**能读到每台 VM 的所有者 | 探针（只读账号）= `get-vms` 原始返回含所有者字段且非空；否则走「门 1 失败台阶」（见 §5） |
| G2 | 容量监测平台展示 VM 所有者 | VM 列表/详情可见「所有者」；空值显示 `-`；过 frontend-style-guide（`:root` 变量、6/8px 圆角） |
| G3 | 报表导出表格含「所有者」列 | Word 与 Excel 导出均含该列；列名与平台展示一致 |
| G4 | 数据来源可追溯 | 采集链路注释 + 本设计「口径」节记录字段来源与解析方式 |

## 2. 门 1：待验证清单（探针直接回答）

1. `get-vms` 原始返回是否含所有者字段（键名/形态：字符串？`{id,name}` 对象？用户 ID？）；
2. **只读账号**调用时是否可见（部分环境对只读账号裁剪字段）；
3. 若为**用户 ID**：`get-users`（试探端点）是否可用、只读账号是否有权解析出名字；
4. 空值率与稳定性（抽样多台 VM；回收站 VM 是否带所有者）。

探针命令（两种模式，均在 web-api 容器内跑，复用产品 `CloudTowerClient`）：

```bash
# A. 只读账号测试（凭据只经环境变量，不进任何留痕）
TOWER_URL=https://<tower>:4433 TOWER_USER=<ro-user> TOWER_PASSWORD=<...> \
  python3 scripts/probe_tower_vm_owner.py --probe-users

# B. 复用现场已配置的 Tower（凭据从产品库解密，绝不外显；用于定位"字段是否存在"）
python3 scripts/probe_tower_vm_owner.py --configured --probe-users
```

`.3` 容器 harness 可用（与回归同一口径）：`docker run --rm --network=host -v <repo>:/w -w /w
-e PYTHONPATH=/w/backend --entrypoint python <web-api 镜像> scripts/probe_tower_vm_owner.py …`。

## 3. 口径（门 1 通过后按此实现，避免二次争议）

- **字段落库**：`vm_latest` 追加 `owner TEXT`（**expand-only**：`_ensure_column` + migrations registry
  `add_column_if_missing` 条目），值取「塔上显示的那个所有者」——若塔给的是 ID 且有解析路径，
  落 `owner_id`（可加 `owner_name` 冗余列，二者并列，页面/报表只用 `owner_name`，为空回退 `owner_id`）。
- **空值语义**：字段缺失/为空一律显式存 `NULL`，展示为 `-`；**不猜、不填充**。
- **回收站 VM**：与 `in_recycle_bin` 既有一致——数据保留、页面按现有规则排除展示；报表沿用同样排除口径。
- **敏感面**：所有者姓名属人员信息——**仅展示与导出**；不写日志、不进遥测；（如后续要做筛选，按精确匹配）。
- **口径权威**：以 `get-vms` 的原始返回为准（与采集同源，不新增 API 依赖；若必须 `get-users` 解析，
  解析在采集期完成并落库，查询期零跨系统调用）。

## 4. 改动面（预估，待门 1 后细化）

| 层 | 文件（预估） | 内容 |
| --- | --- | --- |
| 采集 | `backend/app/v2/collection/service.py`、`parsing.py`、`cloudtower/client.py` | 归一 owner 字段；必要时解析用户表 |
| 存储 | `backend/app/v2/database.py`（`_ensure_column`）、`migrations/registry.json` | `vm_latest.owner_(id/name)` 加列（expand-only） |
| API | VM 列表/趋势/详情相关端点的 vm payload | 透出 owner 字段（契约同步 `docs/api.md` + `verify_api_docs.py`） |
| 前端 | VM 页/详情组件、`types.ts` | 「所有者」列/字段（style-guide；空值 `-`） |
| 报表 | `backend/app/v2/reports/export/*`、`templates/*`、`wording.py` | Word/Excel 表格加「所有者」列 |
| 文档 | 本文件、`docs/releases/CHANGELOG.md`、`docs/api.md`、doc-map | 随实施更新 |

## 5. 门 1 失败台阶（预先决策，避免临时扯皮）

- **字段不存在**：向用户如实汇报探针输出；候选替代路径（择一验证）：①`get-vms` 的 `effect`/关联展开；
  ②CloudTower 侧「用户/组织」接口反查（权限门槛更高）；③放弃该功能并把结论写回 pending（不做半成品）。
- **只读账号不可见但管理员可见**：功能对「只读采集」失效——同上，如实汇报，由用户决策是否改为
  要求一个具备读权限的专用账号（并在交付文档写清权限要求）。

## 6. 测试计划（实施时执行）

1. 单测：归一逻辑（owner 三形态：字符串/对象/缺失）fixture 化；`_ensure_column` 幂等；报表列存在性。
2. `.12` 真机：真实 Tower 采集一轮 → SQLite `owner` 非空率符合预期（与探针一致）→ 页面目视（`.12` UI）。
3. 报表：Word/Excel 各导出一份，目视「所有者」列位置与空值渲染。
4. 前端：vitest + tsc；空值/长名字截断用例。
5. 回归：`.3` 全量 + build_tests（若动打包侧无；本功能不动打包）。

## 7. 回滚

- 代码 `git revert` 即回退；**数据库加列保留**（expand-only，列无害；旧版本读写不受影响）。
- 不动 Tower 侧任何配置；采集失败不影响既有列（owner 为 NULL，展示 `-`）。
