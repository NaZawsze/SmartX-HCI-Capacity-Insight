# 设计：合并导入 tower_id 重映射 + 存量冗余清理（含同类问题盘点）

- 日期：2026-10-01
- 关联：task_plan #63；pending-tasks #63/#62；`docs/upgrade-strategy-issues.md` C2
- 状态：**设计待批准，未实施**（用户指示：先写 plan，代码与数据都不动）
- 现场取证：2026-10-01 `.3` 只读审计（见 §1）

## 1. 问题（用户视角 + 库内实证）

用户以「上传 + 合并数据」导入迁移包后发现数据对不上。`.3` 只读审计实证：

| 表 | 行数 | 去重后真实数 | 分布 |
| --- | --- | --- | --- |
| `vm_latest` | 590 | **244 台 VM** | tower_id 1/2/3 = 173/173/244，三组 VM 集合**完全相同** |
| `vm_volumes` | 89636 | **44744 个卷** | tower_id 1/2 = 各 44634（完整拷贝）、tower_id 3 = 368（现役） |

- `towers` 表只有一条（id=3，CHINATOWER）；`clusters` 表只有 (3, SMARTX-TT-WW)；
- 三组的 `cluster_id` 完全相同（cm551tvrv…）→ **同一个 Tower 的数据**，不是多个 Tower；
- tower_id 1/2 的行 updated_at 全部晚于现役 Tower 创建时间（05-22）→ 是**导入带进来的**，非本机采集。

**根因**：合并导入（`_merge_sqlite` / `_merge_data_sqlite`）把源库的 `tower_id`
（目标机 `towers` 表的**自增主键**，跨系统无意义）**原样照搬**进数据表；
源系统自己 Tower 换代残留的旧 ID 随包带入 → 同一台 VM 在目标库出现最多 3 份（三代并存）。
这是 #56「状态归属不唯一」的数据面实例：**用本地自增 ID 当跨系统身份**。

## 2. 同类问题盘点（"还可能有其他问题"的系统性回答）

逐表审计合并导入涉及的全部本地标识符：

| 数据 | 是否照搬源库本地 ID | 风险 | 结论 |
| --- | --- | --- | --- |
| `vm_latest.tower_id` | **是** | 三代冗余/跨系统错挂 | **本设计修复** |
| `vm_volumes.tower_id` | **是** | 同上（已实证 89268 行冗余） | **本设计修复** |
| `clusters.tower_id` | **是**（`_merge_clusters` 按 (tower_id, cluster_id) 写入） | **跨系统 ID 冲突时会把集群挂到错误的 Tower 上**（源 id=1 的 Tower 与目标 id=1 的另一 Tower 撞 ID）。`.3` 未命中纯属巧合（源现役 id=3 恰与目标相同且同身份） | **本设计修复**（随 Tower 映射一并重映射） |
| `towers` 合并本身 | 按 `INSERT OR IGNORE (id,…)` 逐 ID 插入 | 跨系统同 ID 不同身份 → 静默丢源 Tower；同 ID 同身份 → 恰好对上 | **本设计修复**（改按身份匹配） |
| `collection_runs` | 无 tower 引用 | 无 | 不动 |
| `metric_snapshots` | 单行全局快照（id=1），合并 INSERT OR IGNORE | 无 | 不动 |
| `tasks` / `users` / 升级状态表 | 设计上不参与合并 | 无 | 不动 |
| Prometheus blocks | 内容寻址（block UUID），无本地 ID | 无 | 不动 |
| Tower 凭据 | `.env` 成对迁移，合并不触碰 | 无（既有纪律） | 不动 |

**结论**：需要修的集中在「towers/clusters/vm_latest/vm_volumes 四张表对 `tower_id` 这一
本地自增 ID 的信任」；其余合并路径已核实安全。

## 3. 修复设计（代码侧）

### 3.1 核心机制：Tower 身份映射

合并时先建立 `源 tower_id → 目标 tower_id` 映射，再按映射写入：

1. 读源包 `towers` 全部行；对每行按 **(name, base_url)** 在目标 `towers` 找身份匹配：
   - 匹配到 → `映射[源id] = 目标现役id`（不插入，不产生重复 Tower）；
   - 未匹配 → 作为**新 Tower** 插入（让 AUTOINCREMENT 分配新 id），`映射[源id] = 新id`；
2. `clusters` 合并：`tower_id` 经映射写入（UNIQUE(tower_id, cluster_id) 去重语义不变）；
3. 数据表（`vm_latest` / `vm_volumes`）合并：`tower_id` 经映射写入；
4. 恒等场景（源目标 ID 恰好对齐且同身份）：映射为恒等 → 行为与现状完全一致，既有用例不回归。

### 3.2 对 `.3` 场景的效果（验证判据）

源包 towers 仅 id=3（与目标同身份）→ 映射 {3→3}；数据行 tower_id=1/2/3 中的 1/2
**不在映射中** → 它们引用的源 Tower 在包里不存在（源系统的换代残留）→ 处理口径：
**按 cluster_id 归属归一到映射后的现役 Tower**（数据行的 (tower_id, cluster_id) 中
cluster_id 是 Tower API 的全局标识，以目标 `clusters` 的归属为准重算 tower_id）。
落库时 PK 冲突（同 cluster+vm 已有现役行）由 `INSERT OR IGNORE` 自然去重——
**信息无损**（重复行内容一致或目标更新）。

> 实施细节：数据行重映射以 `cluster_id → (目标 towers 中该 cluster 的 tower_id)` 为准，
> 不依赖源 tower 行是否存在——这同时覆盖"源包自带孤儿数据"的情形。

### 3.3 兼容与边界

- **不改**包格式（manifest 不变）、不新增迁移步骤；旧包新包都能导；
- **不改**导出侧（导出的包本身合法）；
- `restore_archive_bytes` 的 overwrite 模式（整库替换）不走 merge、不受影响；
- 数据包（DATA_SCOPE）导入同样经过 `_merge_data_sqlite`，重映射一并生效。

## 4. 存量清理设计（数据侧，独立于代码修复）

`.3` 真库一次性修复（**用户确认后才执行**）：

| 步骤 | 内容 |
| --- | --- |
| 1 | VACUUM INTO 快照备份到 backups/（可回退），记录 sha256 |
| 2 | 沙箱演练：拷贝真库 → 执行清理 → 核对行数（vm_latest 590→244、vm_volumes 89636→368/44744 现役口径以执行时实查为准）+ `PRAGMA integrity_check` |
| 3 | 向用户提交影响面清单（精确到行数与删除口径），确认后对真库执行同等操作（停写窗口内，事务内完成） |
| 4 | 复核：API 层 VM/卷计数不变（244 台本来就只见 244）、integrity ok、任务中心正常 |

预期效果：消除冗余行；**界面数字不变**（244 台本来就只显示 244）；后续导入不再新增冗余。

## 5. 测试计划

| # | 用例 | 判据 |
| --- | --- | --- |
| T1 | 恒等映射回归 | 既有 merge 用例（源目标同 ID 同身份）结果与现状一致 |
| T2 | 三代冗余包（复刻 `.3` 实况：包内 vm_latest 含 tower 1/2/3、towers 仅 3） | 导入后 vm_latest 无 tower 1/2 行，全部归一到目标现役 Tower |
| T3 | 跨系统 ID 冲突（源 id=1 TowerX ≠ 目标 id=1 TowerY） | 源 TowerX 以新 ID 插入，集群挂到 TowerX 而非 TowerY |
| T4 | 新 Tower 导入（目标无此 Tower） | 新 Tower 分配新 ID，集群与数据正确挂靠 |
| T5 | vm_volumes 同映射 | 卷行归一，PK 冲突去重无信息丢失 |
| T6 | 数据包（DATA_SCOPE）导入路径同样生效 | — |
| T7 | `.3` 门禁 | 迁移定向用例 + 全量无回归 |
| T8 | 存量清理沙箱演练 | §4 步骤 2 的行数与 integrity 判据 |

## 6. 回滚

- 代码：单提交可 `git revert`；合并逻辑不改包格式，回滚后旧逻辑可读旧包；
- 数据：步骤 1 的 VACUUM INTO 快照整库回退。

## 7. 明确不做

- 不动 `.3` 真库（等待用户对 §4 影响面清单的确认）；
- 不在本设计内实施 #62 的结构性改造（本设计是它的数据面先导，结论回填 C2）；
- 不修改导出格式与包 manifest。
