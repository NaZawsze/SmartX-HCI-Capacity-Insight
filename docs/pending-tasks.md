# 未完成任务清单（按优先级）

快照时间：2026-09-13
维护规则：本文件是全项目未完成工作的合并视图；每完成一项同步更新本文件并在 task_plan.md 勾选；新任务立项时先加到 task_plan.md（关联设计文档），再登记到这里。详细口径以 task_plan.md 各 Phase 与 findings.md 为准，本文件只做队列索引。

**交给他 AI 实施？先读 [ai-handoff-guide.md](ai-handoff-guide.md)**（执行环境、提交策略、测试基线、陷阱清单、设计文档索引）。

## P0 — 发布流程（下一版发布前必须）

| # | 事项 | 来源 | 说明 |
| --- | --- | --- | --- |
| 1 | Release canary 发布验收闭环 | Phase 29 | ✅ 口径已闭环（2026-09-20 用户定发布节奏）：canary 环境结论 = 10.20.0.6 为 frp Tower 主机不作为 canary，生产等价验收由 .12 代行（Phase 30 部署验收 + 2026-09-19/09-20 两轮正规升级验收，v0.5.3 门禁全过）。剩余动作 = 用户明确说「发布 v0.5.3」后执行发布动作链（推送 dev2/main、tag、GitHub Release 附包 6accea95、状态翻转）+ 生产升级窗口（生产环境信息待用户提供）。发布节奏见 version-governance.md「发布节奏」节 |

## P1 — 数据正确性与产品缺口

| # | 事项 | 来源 | 说明 |
| --- | --- | --- | --- |
P1 全部完成（2026-09-13）：compose tag 覆盖风险经读码核实为「升级包管线已渲染字面量 tag」，收尾项（runner 默认 env CORS 清理、check_versions 防呆、文档、双版本渲染取证）已实施并验证。

P1 其余项（增长速率算法 Phase 31、预计耗尽算法增强、SQLite 治理、阈值/时区统一、Tower UI 改版含 TowerForm 抽取）已于 2026-09-12 完成并验证，见文末"已完成"与 progress.md。

## P2 — 运维与流程

| # | 事项 | 来源 | 说明 |
| --- | --- | --- | --- |
| 8 | Phase 30 部署/升级验收两项 | Phase 30 | ✅ 已完成（2026-09-15，10.20.11.12）：部署验收（任意目录名部署，project/network 固定）+ 升级验收（v0.5.2→v0.5.3 无第二套容器/网络） |
| 9 | 生产现场只读定位 | Phase 49-8 残留 | 总览绿色现象复现时抓 `/api/dashboard/summary` 请求状态与 `capacity_risk.level`；待生产现象复现 |
| 13 | Phase 24 采集重试/缺采收尾 | Phase 24 | 已实现，待一轮真实使用验证后关闭 |
| 17 | UPG-049 残留卫生项治理 | 2026-09-19 findings.md | ✅ 已完成（2026-09-19）：Prometheus legacy 扫描守卫（beb36d5+回归测试）、.12/.3 app/ 残留清理（各约 3G）、容器挂载与 .3 线上核对一致、runner 镜像 0aca32511008 更新至 .3/.12。交付包 ef10a7c8… 维持不变（prometheus 守卫随下次打包纳入） |
| 18 | UPG-050 app/ 挂载点目录误删致挂载消失 | 2026-09-19 findings.md | ✅ 已定案（2026-09-19）：app/{upgrades,…,smartx-storage-forecast} 为 dockerd 补建的挂载点载体（容器内被真实 bind 遮蔽），运行期 rm/mv 会拆掉全机对应挂载（当日多次"衰减"均为清理操作自伤）。已部署 `scripts/bind-mount-recover.sh`（check/recover）至 .3/.12，两机 recover 后挂载齐全、health 全绿。规则：容器运行期禁删/禁改该组目录 |
| 19 | Prometheus 400d retention 与报表 720 天图表窗口冲突 | 2026-09-19 findings.md | ✅ 已完成（2026-09-19，用户决策去 720 档）：`_normalize_chart_days` 集合删 720（传 720 回退 365，向后兼容）、前端窗口选项/类型同步、文档同步；导出链路核实不受影响（只收 period_days）。.3 全量 315 tests OK、vitest 86/86、真实 API 冒烟 chart_days=720→365 |
| 22 | UPG-050 载体目录物理锁（chattr +i） | task_plan 49-23 | ✅ 已实施并验证，**用户决策不采用常驻加锁（2026-09-20），.12 已解锁恢复原状**：bind-mount-recover.sh 增 lock/unlock + recover 自动解锁/复锁（127c31c+84d5c2f），.12 六步验证协议全部通过后按用户决策解锁；脚本能力保留备查，单台机器需要时可单独 `lock`（10.20.0.6 为 frp Tower 主机，不在范围） |
| 25 | 源码 compose 镜像 tag 字面量化（49-3 收尾） | task_plan Phase 49 第 3 项 | ✅ 已实施并验证（2026-09-20，提交 556a85f）：三源码 compose 全字面量化、check_versions 字面量断言+模板禁令、bridge 打包渲染修复并验证；.3 门禁 + build_tests 26 OK + 全量 330 OK；不重打交付包，e940e07c 冻结产物不受影响（随下次打包纳入） |
| 23 | .3 Tower 可达性恢复（环境） | 2026-09-19 findings.md | **待用户侧处理**：CHINATOWER/SMARTX-TT-WW 自 2026-09-12 网络不可达，采集连续失败，测试环境数据停在 09-12；`collection-freshness-stale` critical 告警挂起（探针端到端验证完成）。恢复可达后趋势自然恢复，告警按设计保留 |
| 26 | 数据迁移页 UI/文案优化 | 2026-09-20 用户反馈「界面不明所以，我自己都忘了做什么用的」 | **第一批已实施并验证（2026-09-20，提交 ff7c553）**：术语客户化（「导出配置迁移包→仅导出 Tower 配置」「下载当前 .env→下载恢复密钥」「补全缺失数据/覆盖导入→合并数据/整库替换」+动态后果提示行）、页底新增「使用说明」卡（五条大白话，含包+密钥成对保存与忘记密钥补救路径）、导出成功引导成对保存、后端任务标题/链接标签同步、UI 层 .env 字样退场（.env 不进包/0600/需登录边界不变）；.3 验证 tsc 0 / vitest 89 / 后端 335 OK（progress.md 49-26）。**追加（2026-09-20，f893d2c）**：升级页 Runner 状态拆分——「Runner 当前状态」（当前兼容性，绿/橙）与「升级包 Runner 要求」（选中包才显示，未选包明确提示）分开，消除 '-' 空态误判。**剩余（后续批次）**：三区结构重组（导出/导入/环境状态）、健康检查结果常驻化。梳理稿：docs/superpowers/specs/2026-09-20-migration-page-ux-review.md |
| 24 | 数据库定期自动备份能力 | 2026-09-20 用户问答；用户「我要终态」立项 49-25；同日用户决策「自动备份暂时不做，只做记录」 | **自动备份：暂不启用（2026-09-20 用户决策）**——能力已完成设计、实现与验证后按决策撤下代码（设计/验证记录保留：docs/superpowers/specs/2026-09-20-auto-backup-and-env-pairing-design.md、progress.md 49-25 两轮证据；方案：web-api 守护线程 SQLite VACUUM INTO 快照 + 同代 .env 成对滚动保管，`SMARTX_AUTO_BACKUP_*` 可调），后续需要时按设计文档恢复即可。**导出 .env 配对：已实现并验证（保留交付）**——迁移导出（全量/配置、同步/异步）自动生成同名 .env 快照（0600）+任务中心「配对 .env」下载链接，新增「下载当前 .env」入口与 `GET /api/admin/migration/env-file`，消除 SSH 手工拷贝。.3 验证：撤下后全量 335 tests OK；导出配对 live 下载 200（progress.md 49-25/49-25a）。边界：.env 不打进导出包的安全规则不变；异地备份仍为迁移包人工转存 |

## P3 — 工程健康度（不阻塞发布）

| # | 事项 | 来源 | 说明 |
| --- | --- | --- | --- |
| 14 | 拆分巨型文件 | Phase 49-13 | ✅ 已完成（2026-09-13）：api.py 域路由包、ServicePage 六域组件、export.py common/word/excel 包、upgrade/service Mixin 包，四文件独立提交部署，全量回归零新增 |
| 15 | API 增加响应模型 | Phase 49-14/49-16 | 全部完成（批次 1-4 响应模型 + 49-16 契约对齐：后端补发 kpis/latest_run/top_vms/tower_runs 与 item metric/value，前端删兼容 normalizer；金样本契约增量、55 前端测试、全量回归零新增） |
| 16 | 低优增强 | Phase 13/14/16 | ✅ 已完成（2026-09-13）：Excel 图表精修（容量趋势图+打印版式+横坐标优化）、task-worker 第 6 容器评估（实测不新增，见 docs/task-worker-evaluation.md）、AI 措辞层（接口+离线回退） |
| 20 | runner prepare 升级期在 app/ 下生成空骨架目录 | 2026-09-20 用户记录指令 | **仅记录，不排期修复（2026-09-20 用户决策）**：`filesystem_prepare` mkdir 循环在升级期会于 app/ 下生成空骨架目录（畸变路径、无数据复制、不阻塞升级，见 findings.md 619）。挂载健康时 mkdir 经真实挂载穿透到真实目录，无宿主可见副作用；危害仅限挂载已衰减场景下的目录噪音。若未来主动治理，方向为 mkdir 目标过滤挂载点同源候选 |
| 21 | 测试机环境卫生低优项（2026-09-20 盘点，能力已产品化） | 2026-09-20 progress 盘点；49-24 能力扩展（de77cef） | ✅ ① .12 已走产品「空间清理」功能完成（2026-09-20 用户明确口径：清理必须走正常功能，不做宿主手工运维）：运行产物清理释放 8.45G（16 项升级任务目录）+ 悬空镜像清理释放 12.88G（60 个 dangling），磁盘 57%→约 30%，健康全绿。③ 备份权限已修正。**剩余②**：.12 的 4 个旧项目名 tag 镜像（`nazawsze/smartx-storage-forecast-*`）当前产品功能覆盖不到（v0.5.3 在跑包只清 dangling），等 49-24 随下次发版火车交付后走产品「清理未使用镜像」完成；.3 同类清理已在 49-24 验证中做掉 |

P3 其余项（v1 死代码移除、helper 收敛、静默吞错清理、CORS 收紧）已于 2026-09-12/13 完成并验证，见文末"已完成"与 progress.md。

## 已完成（2026-09-12，备查）

- SQLite 治理：WAL + busy_timeout 5s + `tasks.updated_at`/`collection_runs.started_at/finished_at` 索引（.3 实库验证）。
- 容量阈值统一：`capacity_risk.thresholds` 由后端下发，DashboardPage 三处改读后端值（旧后端回退 0.75/0.8）。
- 日界时区统一：`_day_bounds` 按 settings.timezone 计算零点（Asia/Shanghai 与 UTC 断言覆盖）。

- 主动容量告警机制（采集后阈值检查 → 任务中心 warning/critical，确认去重）。
- 首页总览静默陈旧：前端 30s 超时/失败横幅/单飞、summary 60s TTL 缓存、`_in_enabled_scope` 三处 fail-closed、`cluster_enabled`/`evaluated_at` 字段。
- 采集频率：Tower 级"采集模式（每日定时/按间隔）"UI + worker 每 Tower 独立调度（含每日时间字段首次真正生效）。
- 前端风格规范文档化（frontend-style-guide.md）与新区块 token 统一。
- Phase 31 增长速率算法：核对确认后端三窗口（日/月/季）、前端三行卡片、Word/Excel 口径、单测均已落地（历史实现未更新状态）；findings 旧口径已修正；.3 真实数据验证三窗口输出与样本标记。
- 预计耗尽算法增强：`forecast_series` 新增 smoothed_slope_per_day / exhaustion_days_30d / recent_day_delta / spike_detected；Dashboard 风险行与报表预测行优先 30d 稳健口径并提示"近 24 小时增长异常"；.3 真实数据验证（spike=True 正确识别当日突增）。
- TowerForm 组件抽取：创建/编辑表单共用 TowerForm.tsx（表单状态类型、分区、采集/重试字段、payload 归一化），SettingsPage 收敛到 190 行；DashboardPage fallback 类型补齐新字段后 tsc 通过、16 tests 通过、容器强制重建。
- P3 卫生批次（commit d12028c，设计 p3-hygiene-batch-design.md）：
  - helper 收敛：series.py 规范 cluster_key/vm_key（四处副本删除）；parsing.int_or_none（database/migration 合并，语义不同者保留并注释）；export.py 字符串键变体保留。
  - 静默吞错：任务列表刷新失败进数据状态横幅（App tasksError 状态）；即发即忘类保留。
  - CORS：默认不挂中间件（同源部署无需），SMARTX_CORS_ORIGINS 显式白名单才启用；.3 的 .env 遗留 `SMARTX_CORS_ORIGINS=*` 已清理，实测 0 个 access-control 头、同源代理正常。
- P2 批次（commit 235f905+82e31c5，设计 p2-ops-batch-design.md）：
  - 基线产物化：`scripts/capture_baseline.py` capture/verify 闭环；.3 真机验证（vm_volumes 89636 行、SHA/integrity/counts 全过；错误路径防御拦截旧残留 /data/smartx.db）。
  - 数据新鲜度告警：DataQualityService 自适应阈值（2×最小采集周期，env 可覆盖）+ Prometheus 样本滞后 >15 分钟检查，进入既有"数据质量需关注"通道。
  - worker 重试调度化：统一采集结果管道（保存 metrics→数据质量→失败重试排期），三条采集路径（全局/每 Tower/升级后）共用；修复 per-tower 与升级后路径漏存 metrics 的回归（.3 实测 run 63 成功后 metric_snapshots 同步更新）；重试从 time.sleep 循环改为一次性 DateTrigger job。
  - 防御教训：/data/smartx.db 是 v0.5.1 时代旧残留，业务库在 /data/smartx-storage-forecast/app/smartx.db；脚本已加"无业务表即失败"防御。
