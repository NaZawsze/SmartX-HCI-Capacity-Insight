# 设计：五问题批次——采集调度停摆 / 新鲜度语义 / 迁移页文案样式 / 已分配口径

- 日期：2026-10-02
- 关联：task_plan #65；pending-tasks #72/#73/#74/#75；`docs/functional-modules.md` §4/§8
- 状态：**设计待批准，未实施**（用户指示：先检查写进 plan，再写设计文档）
- 来源：用户页面截图五点质询

## 问题 1：定时采集调度停摆（#72，🔴 真 bug）

### 现象与取证

`.3` Tower（60 分钟间隔、启用）自 09-12 后 **collection_runs 里零次 scheduled 触发**：
09-12 15:20 scheduled 成功 → Tower 断联期无 scheduled（连失败的都没有）→ 10-01 22:13 的成功
是手动触发 → 此后再无任何采集。worker 容器历经多次重建，问题跨重启持续。

### 根因（代码定位）

1. worker 启动**不直接执行** `sync_collection_schedules()`——只注册了一个 60 秒周期的
   `collection-schedule-sync` 任务，首次同步依赖它；
2. `_run_schedule_sync` / `_run_tower_collection` 均 `except Exception: return`——
   首次同步若撞上 US-28 类 SQLite 锁窗口或任何异常，**静默失踪且永不重试到成功可见**；
3. worker 无 logging 配置 + 全程零日志——失败了也无法观测（US-30 已发现同款可观测性缺口）。

### 修复设计

1. **启动即同步**：`scheduler.start()` 前直接调用 `sync_collection_schedules(...)`，
   失败重试（间隔 30s、最多 5 次），仍失败则 `logger.error` 显式报出；
2. **异常不吞**：`_run_schedule_sync` / `_run_tower_collection` 的 except 改为
   `logger.exception(...)` 后再 return；
3. **补 logging 配置**：worker main 里配置基础 logging（INFO 级 + stderr），与 US-30 的
   `logger.warning` 打通；
4. **可观测校验**：修后 `.3` 重启 collector-worker，1 小时内应出现 `scheduled` 触发的
   collection_run（或至少日志可见 job 已注册）。

## 问题 2：数据新鲜度提示语义（#73，🟡 语义 + 决策项）

### 现象

最后成功采集 = 10-01 22:14（手动触发，真实），截图时已 14+ 小时 → 横幅「数据未更新」+
时间戳黄色；同时采集状态卡显示「正常」。用户质询：①怎么就黄了，不应 24 小时吗？②正常和
未更新并存很矛盾。

### 取证

- 阈值口径：`freshness_threshold_minutes = max(2×启用 Tower 最小采集间隔, 60)` ——
  60 分钟 Tower → **2 小时**即黄。这是 49-20/49-37 的设计（自适应间隔，漏 2 个周期即报），
  时间戳显示**无时区 bug**（22:14 = 14:13 UTC +8，前端转换正确）；
- 黄得"对"但根源在问题 1（调度停摆导致真停摆）；阈值本身有产品决策空间。

### 修复设计

1. **横幅文案改为自解释**：「数据未更新：已约 X 小时未成功采集（阈值 Y 小时）」——
   消除"正常 vs 未更新"的矛盾感（采集状态卡描述的是最后一次采集本身，横幅描述的是新鲜度）；
2. **阈值口径（决策项，默认方案 A）**：
   - A（保持现状）：2×最小采集间隔自适应——小时级采集漏 2 个周期即提示，及时性最好；
   - B：放宽为 24h 固定——只在"整天没采集"时提示；
   - C：阈值与告警分级——超阈值先提示（黄色），超 24h 升级 critical 告警（已有探针机制）。
   用户已表达 24h 预期；若选 C 则黄色提示阈值仍自适应、critical 门槛 24h。
3. **黄色语义保留**（stale 状态本身正确），仅文案与分级调整。

## 问题 3：迁移页文案重复（#74-①）

### 现象与修复

「导出迁移包」卡描述、hint 段、页底使用说明三处重叠。修复：
- 卡描述保留一句话定位（"完整备份，含 Tower 配置、库内监测数据与全部历史指标"）；
- **hint 段改为三入口对比表**（一段话 → 三行小表：内容 / 恢复密钥 / 适用场景），
  作为唯一权威说明；
- 页底使用说明删去与 hint 重复的导出条目，只保留导入、环境状态、密钥保管三条。

## 问题 4：环境状态与使用说明间距（#74-②）

截图对比：两卡间距消失。排查 `.service-migration-guide` / `.service-operation-card`
的 margin（疑似某卡片底 margin 被内部 auto-scrollbar 容器高度影响）。修复以预览截图目视
为准（正常态间距恢复），不改布局结构。

## 问题 5：下载恢复密钥弹窗的平台密码表述（#74-③）

弹窗与错误提示的「平台登录密码」改为「**本系统（存储监测平台）的登录密码**」，
并在弹窗正文补一句「不是 CloudTower 的密码」。错误提示同步。

## 问题 6：已分配容量口径错位（#75，🟡 需口径对齐）

### 取证（Tower API 原始返回）

- 容量条三值来源不一致：已使用 35.16 TiB / 总容量 219.18 TiB 来自
  **get-cluster-storage-info**（全集群口径）；已分配 8.12 TiB 来自
  **get-clusters 的 `perf_allocated_data_space`**（仅**性能层**）；
- Tower 原始返回：`perf_allocated_data_space = perf_used_data_space`（性能层内两者相等，
  9.32 TB）、`perf_total_data_capacity` 18.5 TiB、`logical_used_data_space` 20.5 TiB、
  `max_physical_data_capacity` 400 TiB——分层语义明确；
- **get-cluster-storage-info 里没有集群级 allocated 字段**（只有 total/used/free）。

### 修复设计（决策项，默认方案 A）

- **A（推荐）：已分配改用 `total_data_capacity - free_data_space`**（全集群口径自洽，
  219.18 − 202.33 = 16.85 TiB，与已使用/总容量同源同框，语义="已供给/已写入的分配量"）；
- B：保留 perf 层值但展示标注「性能层已分配」；
- C：下架已分配展示。
- 实施时用 CloudTower 界面的"已分配"数值对照验证（用户提供或截 CloudTower 页面）。

## 测试计划

| # | 用例 | 判据 |
| --- | --- | --- |
| T1 | worker 启动同步 + 异常落日志 | 重启 collector-worker 后日志可见同步成功/失败原因；1 小时内出现 scheduled run |
| T2 | 新鲜度横幅文案 | 「已约 X 小时未成功采集（阈值 Y 分钟）」格式；阈值口径按决策项 |
| T3 | 迁移页文案去重 | 三处说明合并后预览目视；hint 为唯一权威对比表 |
| T4 | 卡片间距 | 预览截图与正常态一致 |
| T5 | 密钥弹窗平台名 | 弹窗/错误提示含「存储监测平台」与「非 CloudTower」 |
| T6 | 已分配口径 | 按决策项实现；数值与 CloudTower 界面一致（或口径标注清晰） |
| T7 | 门禁 | 后端定向 + 全量无回归；前端 tsc/vitest；预览目视 |

## 回滚

文案/CSS 改动直接 revert；调度启动同步为行为增强（失败即显式报错），revert 即回旧行为；
已分配口径改动单提交可回退。
