# 更新说明

本文档记录 SmartX HCI Capacity Insight 各版本的主要变化。项目介绍、部署方式和基础使用说明仍以根目录 README 和 docs 文档为准。

## v0.5.3（候选，未发布）

状态：**候选，未发布**。已正式发布的平台版本为 v0.5.2；v0.5.3 的发布动作（推送、打 tag、创建 release、对外交付）待用户明确指令。

构建与验证记录（2026-09-13 首次打包；2026-09-19 因 UPG-049 修复重打包 `ef10a7c8…` 并在 .12 完成全链路验收；2026-09-19 第二次重打包 `e940e07c…` 门禁通过但升级验收暂缓未执行；2026-09-20 全新完整构建 `6accea95…`（dev2 ff1bd52，收编 49-3/49-23 与全部治理改动），并于 10.20.11.12 完成 v0.5.2（基线重建）→v0.5.3 正规升级全流程验收——task `upgrade-b45996653f6955b6` 主任务+post-cleanup 均 succeeded，8 项验收通过；2026-09-25 重打包 `4a3c7bbd…`（dev2 cdfe600，收编迁移页三区重构、报表图表优化、容量告警等 09-21 批次 40 提交），.3 全门禁通过但 .12 正规升级验收未执行；2026-09-27 重打包 `54aa8807…`（dev2 0a41775，收编 49-36~49-48 批次：已分配容量展示、手动采集快照合并与看板过期标注、报表增长窗口口径、回收站 VM 口径与生命周期同步、新建/增长 VM 口径统一、报表与趋势图已分配容量线、趋势图配色互换），.3 全门禁通过（362 后端测试/26 构建测试/107 前端测试、api.md 77=76、外发文档扫描 PASS、包身份、SHA 校验、敏感成员 0），**该包后被第四轮 `e1c0fde8…` 取代（.12 验收已由第四轮完成）**）

### 更新摘要

v0.5.3 是 v0.5.2 之后的平台版本候选（未发布），主要内容：①总览可靠性与主动告警（首页静默陈旧修复、容量阈值主动告警、采集频率分钟级可配置）；②报表产品化（预测区间、Excel 图表精修、VM 页千台规模加固）；③Tower 设置页完整改版；④升级链路修复（UPG-049）与挂载运维工具（UPG-050）；⑤工程健康度（巨型文件拆分、v1 死代码移除、SQLite 治理、CORS 收紧、前后端契约对齐、API 响应模型）与测试环境治理。

### 新增

- **主动容量告警（49-8）**：每次采集完成后按集群检查容量阈值（使用率比率 + 剩余绝对空间），跨阈值生成任务中心 warning/critical 告警（复用 severity 体系，去重与升级新建）。
- **采集频率分钟级可配置（49-8）**：Tower 设置页新增「采集间隔 - 分钟」（默认 60，0 = 使用该 Tower 每日计划采集时间），worker 按 Tower 独立调度；顺带修复「每日采集时间」字段从未接入调度器的遗留缺陷。
- **采集停摆主动告警（49-20）**：web-api 新增采集新鲜度探针（默认 10 分钟周期，`SMARTX_FRESHNESS_PROBE_INTERVAL_SECONDS` 可调、≤0 关闭），太久没有成功采集记录（阈值 max(2×启用 Tower 最小采集间隔, 60 分钟)）即写任务中心告警 `collection-freshness-stale`，覆盖 collector-worker 容器整体挂掉/卡死时 worker 侧检查全部停摆的盲区。
- **预测区间与预期管理（49-21）**：报表预测由单线改为含预测上下界（`band_half_width_now`/`band_half_width_per_day`，95% 区间线性近似），图表绘制「预测上限/预测下限」；客户文案统一为大白话「预测值可能会有偏差，以实际为准」，不引入统计术语；预测模型保持线性趋势外推（评估结论：季节性模型在数据跨度与产品定位下不采纳）。
- **Tower 设置页完整改版（49-11）**：添加 Tower 向导化分组表单（连接认证/采集策略分区、认证方式互斥、保存前测试连接）、创建/编辑共用 TowerForm 组件、集群管理独立分区、删除确认对话框、Tower 列表健康徽标；含创建前测试连接 API、最近采集字段、创建响应集群列表三项后端配合。
- **VM 页千台规模加固（49-19）**：`/api/vm-volumes` 支持服务端分页与 vm/used/occupied 排序（occupied 按副本/EC 系数口径），新增 `GET /api/vm-volumes/usage-summary` 聚合接口；前端 VM 列表分页（100/页）+ 全量卷表服务端分页（200/页），5000 VM / 76 万卷规模可用。
- **Excel 报表图表精修**：容量趋势 Sheet 增加集群容量使用趋势折线图（与 Word 风格统一）、打印版式（横向/fit-to-page）、横坐标按时间跨度优化显示间隔。
- **AI 措辞层（可选）**：新增 `app/v2/reports/wording.py` 措辞增强接口，未配置 AI 服务时回退离线规则文案（行为与现状一致）；接入点留待有 AI 服务时。
- **空间清理能力扩展（49-24）**：镜像清理由"仅悬空镜像"扩展为"悬空 ∪ 未被任何容器引用的非平台镜像"（按 ID 选择删除，服务端删除前复核 fail-closed，`docker image rm` 不带 `-f`）；本产品仓库（`smartx-hci-capacity-insight-*`）旧版本镜像列受回滚保护清单（rollback_restore 依赖本地旧镜像），产品内不提供删除；运行产物清理新增升级任务在跑守卫（pending/running 时拒绝清理，防删在跑任务上传包）；「保留最近 N 个升级任务」仅保留为 API 层参数（默认 0=全部清理），客户界面不暴露（2026-09-21 用户决策：界面选项过繁）。
- **导出 .env 配对终态（49-25）**：数据迁移导出（全量/配置，同步与异步路径）自动生成与迁移包同名的 `.env` 配对快照（0600，同代保管），任务中心附「配对 .env（恢复时必须同代使用）」下载链接；服务管理 → 数据迁移新增「下载当前 .env」入口与 `POST /api/admin/migration/env-file` 接口，消除恢复前 SSH 手工拷贝 `.env` 的步骤；下载前须重新输入平台登录密码（后端校验当前用户密码，错误返回 403），并在弹窗中提示密钥保管安全要求（2026-09-20 49-26f 强化）。
- **集群「已分配容量」展示（49-36/49-46）**：每塔一次 `get-clusters` 取 `perf_allocated_data_space`（含副本 + 精简按厚制备，可超总容量，缺失按 0），写入新指标 `smartx_cluster_storage_allocated_bytes`；总览 ZBS 容量条新增浅蓝「已分配」段与「已分配 X · Y%」数值区（分母为总容量，可 >100%）；报表集群预测行同步显示 `已分配 {值} · {比例}%`（49-46）。
- **趋势图「已分配容量」线（49-46b）**：集群容量趋势图新增已分配容量水平虚线，**图例默认关闭**（可手动打开），仅在打开时计入 y 轴上限，避免「已分配 > 总容量」把实际容量曲线压扁。
- **报表容量增长窗口口径（49-39）**：增长速率改为按所选窗口内**真实成功采集**计算，窗口内无成功采集显示 `-/单位` 并把标题标为黄色「数据不足」，不再用陈旧数据算出误导性速率。
- **回收站 VM 生命周期记录（49-47）**：`vm_latest` 新增 `in_recycle_bin`/`original_name`/`deleted_at` 三列（新库建表 + 既有库升级，旧行回填 0）；采集不再丢弃回收站 VM 而是记录标记/原名/删除时间，采集**成功**后核对——`in_recycle_bin=1` 且 Tower 已不再返回（retain 到期彻底删除）即同步删除本地行；采集失败一律不核对、普通行缺失不删。
- **看板数据过期标注（49-37）**：采集状态卡常驻「最后成功采集」时间，数据新鲜度为 stale 时顶部出现过期提示条与徽标，采集失败/超时不再表现为"静默停摆"。

### 修复

- **首页总览静默陈旧（49-8/49-9）**：summary 刷新失败/超时显示「数据截至 HH:mm，刷新失败」提示并保留旧数据（fetch 加 30s 超时）；summary 慢查询治理（60s TTL 缓存）；消除双重轮询；`_in_enabled_scope` 空集放行改为 fail-closed 并统一 dashboard/vms/reports 三处为公共函数；容量阈值统一由后端下发（前端三处改读后端值）；`capacity_risk` payload 增加 `evaluated_at` 与最后采集成功时间。
- **升级链路（UPG-049）**：runner `filesystem.prepare` 不再把与在线库同文件的 legacy 候选误判为 legacy 源；此前任何 v0.5.2 目标布局机器带 Tower 凭据升级 v0.5.3 会被凭据配对策略硬失败。真实 legacy 机器迁移行为不变。
- **报表图表窗口收紧（49-18）**：Prometheus retention 400d 与 720 天图表窗口冲突（部署超 400 天后图表前段必空），`chart_days` 档位收紧为 7/30/90/365，旧客户端传 720 回退 365；导出链路（只收 `period_days`）不受影响。
- **任务投影同步（49-5）**：`post_upgrade_cleanup_status()` 在子任务终态时回写父 task.json，修复顶层字段与 post-cleanup 子任务实际状态不一致。
- **前后端契约对齐（49-14/49-16）**：后端补发 `kpis`/`latest_run`/`top_vms`/`tower_runs` 与 item `metric`/`value`/`previous_value`，前端删除兼容 normalizer。
- **报表趋势图交互优化（49-26g~49-26l）**：修复切换统计窗口时图表重画两次；切换时增加加载反馈，数据到达一次性换图；按用户提议增加形变动画（线条平滑滑到新位置，不整图重挂）；7/30/90/365 四档内存缓存（命中即时显示+后台静默刷新，手动刷新/集群范围变更时失效）；四档均显示「当日容量」黄色节点与数值标注（实际序列末点，图例与悬停提示排除该系列）；横轴日期标签改为按实际类目数自适应（数据历史短于窗口时不再只剩 1-2 个日期，目标约 10 个均匀标签），365 天档在数据跨度不足半年时显示「月-日」格式。
- **数据迁移页三区结构重组（49-26p）**：页面重组为「导出迁移包 / 迁移包导入 / 环境状态」三区——导出区突出主路径并给配置导出次要入口；导入方式改为可选卡片（整库替换红色危险态 + 确认勾选不变），提示条带「去服务重启」直达；健康检查常驻化为环境状态卡（进入页面自动只读体检：业务库/历史指标/完整性），原按钮降级为「重新检查」。
- **数据迁移页布局与密钥流程修订（49-26q）**：①导出两按钮移回页头右侧（PageHeader action），修正重组后落在卡内左侧的问题；②「使用说明」卡头与其它三区统一（标题 16px + 分隔线），修正字号不一致；③去掉「导出即自动生成/可下载恢复密钥」的表述，改为导出迁移包成功后弹「还需下载恢复密钥」确认框（[下载恢复密钥]/[取消]），点「下载恢复密钥」须输入平台登录密码才真正下载——让密码门控对密钥下载真实生效；服务器侧配对 `.env` 留档与任务中心链接、`env-file` 密码接口保持不变。
- **报表接口查询去重（49-26m）**：`/api/reports/latest` 单请求内相同的 Prometheus 查询（窗口序列与新建 VM 统计重复拉取同一序列）按 (query, start, end, step) 请求内去重，输出与行为不变；.3 同进程 A/B 实测中位耗时 555ms→288ms（约 -48%），Prometheus 调用 15→10。
- **手动采集清空指标快照（49-37）**：`run_manual_collection` 与 API 手动采集路径改为与采集前旧快照合并后落盘（`merge_metrics_text` 下沉公共模块，worker 侧保留双保险），修复一次全失败采集把 `metric_snapshots` 抹成表头导致 `/metrics` 无样本、看板归零的问题。
- **回收站 VM 不再混入新建/增长列表（49-40）**：展示侧过滤 `in-recycle-bin-` 前缀 VM；看板「虚拟机」KPI 计数按用户 2026-09-26 决定**保留**（删除的虚拟机也应该记录，暂无显示需求）。
- **集群趋势图断档断开（49-41）**：实际容量序列改为连续日网格 + 缺采日填 `null`（曲线在断档处断开，不再有跨越断档的斜线），后端图表序列截到最后一次成功采集。
- **新建 VM 与增长口径统一（49-42/49-43/49-44/49-45）**：新建 VM 按 `vm_id` 全历史最早样本判定（断档恢复不再把老 VM 判成新建，本月新建 199→6）；概览与报表同源共用 `app/v2/vms/new_vm.py`、`app/v2/vms/growth.py`（窗口定义/计算/展示规则统一，同 30 天窗口两页结果一致，修复概览 0 条 vs 报表 66 条）；周期边界下沉共享实现，报表增长列表修复 series tail 兜底泄漏回收站 VM。
- **趋势图配色互换与调色板错位修复（49-48/49-48b）**：按用户要求交换「实际容量」与「已分配容量」颜色（实际=主蓝 `--blue`、已分配=青）；同时把全部六个系列改为**显式配色**——ECharts 调色板只给未显式配色的系列按顺序发色，只改一个会让后续系列整体错位（首版曾导致历史预测与已分配容量同为青色）。

- **执行期间 runner 在场判定（US-08，49-57）**：升级执行期**实例心跳不刷新**（`upgrade_runner_state.heartbeat_at` 只在任务开始那一刻写一次，`.3` 实测整段执行约 75s 冻结），而"心跳新鲜"阈值是 30s —— 导致执行期并发预检查报"未检测到 upgrade-runner 心跳"、升级页"Runner 版本（满足/不满足平台要求）"显示不满足。修复：web-api 把 runner 的**第二条心跳通道**（执行期每 5s 续租的 `upgrade_task_leases`）也算作在场证据，来源标记 `task_lease`，预检查协议校验、组件目录与 `/api/system/health` 的 runner 版本判定共用同一逻辑。不改 runner、不升 runner 版本；runner 重启窗口无租约时仍如实报"未检测到心跳"。

- **升级任务运行产物自动清理（US-09，49-56）**：web-api 新增升级产物清理守护线程（默认每 6 小时，`SMARTX_UPGRADE_HOUSEKEEPING_INTERVAL_SECONDS`），按 TTL（默认 7 天，`SMARTX_UPGRADE_ARTIFACT_TTL_DAYS`，`0` 关闭）+ 始终保留最新 N 个（默认 3，`SMARTX_UPGRADE_ARTIFACT_KEEP_RECENT`）自动删除**从未执行过**任务（`precheck_failed`/`uploaded`）的包内容——原始压缩包与解包目录（单个失败任务约 800 MiB）；**保留 `task.json` 与任务中心记录**，并写入 `package_cleaned_at`。执行过/失败/回滚类任务目录不自动清理（取证需要），存在进行中升级时整轮跳过；包内容被清理后再预检查会得到明确提示「请重新上传」而不是路径异常。

- **升级预检查补磁盘空间硬校验（US-07，49-55）**：`precheck` 新增 `disk_space` 项——需要空间 = 升级包内容（解包目录文件求和；给 `.tar.gz` 时按 ×3）+ 预留（默认 2 GiB，`SMARTX_UPGRADE_DISK_HEADROOM_BYTES` 可覆盖，`0` 表示不额外预留），按文件系统去重后检查 `upgrades/`、`backups/` 与根文件系统（docker 镜像存储），不足即 `precheck_failed`，message 给出「哪个路径、可用多少、需要多少」与估算构成。此前空间不足会在 `image.load`/备份阶段失败，留下半升级现场（镜像只加载一半、备份不完整）。

- **升级顺序敏感：post-cleanup 健康断言（US-05，49-52）**：升级包 manifest `required_health` 移除 `runner_version` 等值断言（保留平台 `version`+三项 checks）——合法终态有两种（runner 基线直升 / 先升 runner 再升平台），等值断言会让"先升 runner"顺序在 post-cleanup 误判失败、旧环境不清理。runner 侧空字段自动跳过校验，无需升级 runner。
- **并发升级无互斥（US-23，49-52）**：`start` 增加单飞守卫——已有升级处于 pending/running/runner_restarting/recovery_required/rollback_* 时拒绝开始新升级（平台与组件两个入口共用 `start()` 一处覆盖；`post-cleanup retry`/`recovery`/`rollback` 同守卫，cancel/delete 不拦）；类级锁消除并发 start 的扫描-认领竞态窗口（两个并发 start 恰好一个成功）。修复前第二个任务会在被第一个改动过的环境上按旧计划执行。

### 工程与运维
- **DockerHub runner `v0.3.1`/`latest` 补齐（2026-09-27）**：发布资产 `d10e15cf…` 对应的镜像本体已 push 到 `nazawsze/smartx-hci-capacity-insight-upgrade-runner`（digest `90eb5a42…`），`latest` 同步指向它；核对 `RUNNER_VERSION=v0.3.1`、25 个动作、无 `post_upgrade.schedule_collection`、`actions.py` md5 `573dd04b…`。已知债务：该镜像无对应 git 提交、CI 无法复现（决定不补源码）。此前 DockerHub 只有 `latest`(06-05)、`runner-sha-31a1209`/`v0.3.0`(06-12)，**`v0.3.1` 从未推过**。
- **runner 交付一致性硬门禁（49-54，2026-09-27，#47② / US-02）**：新增 `scripts/verify_runner_delivery_consistency.py`，把发布前靠人工执行的「三处同源核对」做成一条命令——C1 仓库 `RUNNER_VERSION`；C2 动作表（AST 静态提取 `default_handlers()`，不启动容器）；C3 三个源码 compose 字面量 tag；C4 组件包 manifest 版本与镜像归档 SHA256（`min_runner_version` 按下界校验）；C5 **离线解析包内镜像归档，比对镜像内 `app/RUNNER_VERSION` 与 `app/app/upgrade_runner/actions.py` 的 md5 与仓库一致**（证明"这个包出自这份源码"，堵住"同版本号不同能力"）；C6 DockerHub tag 200（默认关闭，需 `--check-dockerhub`）。默认全离线、零副作用（不 `docker load`、不碰本地镜像 tag）。任一 FAIL 即非零退出，SKIP 必须显式列出（不把"没检查"当成"已通过"）。配对单测 22 例；发布门禁步骤 4 改为调用本脚本。`.3` 实证：`v0.3.2` 组件包全绿；`v0.3.1` 组件包（`dd096bf2…`）正确 FAIL——它的**动作集与仓库相同（26 个）但 `actions.py` md5 与版本号不同**，正说明只比动作表抓不到这类漂移。

- **巨型文件拆分（49-13）**：`app/v2/api.py` → 域路由包（74 条路由 path+method 一致）；`frontend/src/pages/ServicePage.tsx`（2305 行）→ `components/service/` 六域组件；`app/v2/reports/export.py` → `export/` 包（common/word/excel/legacy）；`app/v2/upgrade/service.py` → Mixin 包（公开方法集合不变）。`admin.py` 二次拆分为域子模块包。
- **v1 死代码移除（49-12）**：删除 v1 专属模块约 4800 行；export legacy 消化删除 60 处不可达死代码（约 1264 行）。
- **SQLite 治理**：vm_latest/vm_volumes/collection_runs/tasks 索引 + WAL + busy_timeout 5s（.3 实库验证）。
- **CORS 收紧**：默认不挂 CORS 中间件，`SMARTX_CORS_ORIGINS` 白名单显式启用。
- **采集链路健壮化**：worker 采集重试调度化；数据新鲜度链路监控。
- **API 响应模型（49-14 批次 1-4）**：towers → dashboard/tasks → vms/reports → admin 读类分批落地，金样本对比验收。
- **升级包 compose 字面量 tag（49-15）**：读码核实包构建管线已渲染字面量 tag；收尾 runner 默认 env CORS 遗留清理。
- **源码 compose 全字面量化（49-3）**：三个源码 compose 的镜像引用（registry+tag）全部字面量化，与升级包同一不变量——现场 `.env` 无法再让源码部署静默漂移到旧镜像；`check_versions` 门禁改为字面量断言 + 模板变量禁令（模板回潮即 fail-fast）；bridge（<v0.5.2）打包路径验证保持 legacy 命名与 runner v0.3.0 基线。
- **运维工具（UPG-050 定案）**：新增 `scripts/bind-mount-recover.sh`：`app/` 下挂载点目录体检（check，附锁状态报告）与全服务一键恢复（recover，自动解锁→重建→自动复锁），以及载体目录物理锁（lock/unlock，chattr +i，防误删载体；实测 dockerd 可在锁定目录正常建立挂载；验证后按用户决策未默认启用，能力保留备查）。容器运行期禁止 rm/mv `app/{upgrades,backups,exports,compose-runtime,smartx-storage-forecast}`（它们是 dockerd 补建的挂载点载体）。
- **task-worker 第 6 容器评估**：实测报表导出期间 web-api 响应仅 +40ms，空间清理/迁移导出无影响，结论保持 5 容器模块化单体。
- **测试环境治理**：构建测试移到宿主机跑（26 tests OK），deployment_config 改 unittest（无 pytest 依赖），容器内全量测试全绿。
- **文档与门禁（49-17 等）**：`docs/troubleshooting.md`、`docs/backup-recovery.md`、`docs/release-acceptance.md` Release Day 五步清单；`scripts/verify_api_docs.py`（API 文档防漂移）、`verify_release_docs_safe.py`（对外文档脱敏扫描）、`verify_full_upgrade_chain.py`（一键链路回归）、`capture_baseline.py`（标准业务基线固化与校验）。

### 验证说明
- **2026-09-27 第四轮最终候选 `e1c0fde8…`（.12 完整验收全过）**：基线 v0.5.1/runner v0.3.0 → `u2 upgrade-1ea87b5c → runner v0.3.1 upgrade-2cf232b7（已发布 d10e15cf）→ v0.5.2 upgrade-5cae8764` 全绿 → **发布版 v0.3.1 直升 v0.5.3：task `upgrade-666284beec04cc87` succeeded**（升级计划 12 个动作、不含 `post_upgrade.schedule_collection`；post-cleanup succeeded；平台自建标记 `source=target_worker_compatibility`；升级后采集任务已创建，Tower `Connection refused` 记为环境限制）→ 8 项验收（runner=v0.3.1）全过 → 组件升级 runner v0.3.2 后 **runner 存活 90 秒（同 project 停机修复生效，修复前 10 秒必死）**、8 项复验 runner=v0.3.2 全过、新预检查 `runner_actions: 升级计划 14 个动作全部支持`。`.3` 门禁：`--check-version`/identity/`.sha256`/敏感 0、后端 377 tests OK、构建 26 OK。

- **2026-09-27 候选包 `54aa8807…` 升级链路回归 + `.12` 正规升级验收（全过）**：`10.20.11.12` 恢复真实 `v0.5.1 + runner v0.3.0` 基线（业务夹具 users1/towers1/vm_latest556/vm_volumes89588）→ `verify_full_upgrade_chain.py` 三步 `v0.5.1u2 → runner v0.3.1 → v0.5.2` 全 succeeded（节点 1/2/3 验收 + post-cleanup succeeded）→ 本包正规升级 task `upgrade-72bfb3f52317ef7f` **succeeded、post-cleanup succeeded** → 8 项验收：health `v0.5.3/v0.3.1` 连测两次三 checks 全 true、5 容器镜像 tag 正确、project/network `smartx-hci-capacity-insight(-net)` subnet `10.249.251.0/24`、SQLite 行数与基线**完全一致**且 integrity ok、Prometheus 挂载目标目录 `/-/ready` 200、`.env` 0600 且 sha 全程未变、7 个 legacy 路径全部 missing、UI 8080=200。已知限制：升级后自动采集因 Tower `10.20.0.6` 不可达失败（环境限制非缺陷）。**附带结论（当日记录，已被同日随后的方案 A 与第四轮取代）：链路第 2 步需用含 `post_upgrade.schedule_collection` 的 runner 组件包（`dd096bf2…`）**，2026-06/07 的旧 runner 包缺该动作会在 v0.5.3 切换后失败，详见 findings.md。方案 A（49-49）实施后升级计划不再下发该动作，链路第 2 步恢复使用**已发布** runner 资产 `d10e15cf…` 并于第四轮全绿——验收基线一律以已发布资产为准（见 release-acceptance.md 与下方第四轮记录）。
- **2026-09-27 候选包 `54aa8807…`（dev2 0a41775）包静态门禁**（10.20.11.3）：`--check-version` OK（v0.5.3）；宿主机构建测试 **26 OK**；web-api 容器内全量 **362 tests OK (skipped=1)**（235s）；前端 `tsc -b --force` exit 0、vitest **107 passed（11 files）**；`verify_api_docs` 77 条=76 路由一致；`verify_release_docs_safe` PASS；`verify_upgrade_package_identity` exit 0（版本文件/镜像 tag/内部版本一致）；`.sha256` 文件 `sha256sum -c` OK；包内敏感成员扫描 0（无 `.env`/`.db`/`.sqlite`）；部署后 health `v0.5.3/v0.3.1` 三 checks 全 true、web 200、五容器在位。
- 全量后端测试：容器内 330 tests 全绿（第二次重打包后；含 Excel 图表、AI 措辞层、新鲜度探针、预测带测试）。
- 前端：tsc 干净、89 测试全绿。
- 真实 Word/Excel 导出验证通过（容量趋势 Sheet 含图表 + 打印版式）。
- 升级链路：v0.5.2 → v0.5.3 正常升级流程验证通过两轮——2026-09-19 以 ef10a7c8 包（task `upgrade-e1fe8a62ea767ab7`）；2026-09-20 以全新构建 6accea95 包（task `upgrade-b45996653f6955b6`，v0.5.2 基线先经 tag 换回重建、数据/.env/Prometheus 逐项核对保全后走 API 上传→预检查→升级→post-cleanup，主任务与清理均 succeeded，证据见 upgrade-package-ledger.md 与 progress.md）。第二次重打包（e940e07c）仅完成包静态门禁即被 6accea95 取代，未走升级验收（已补台账）。已知限制：测试环境 Tower（10.20.0.6，frp 接入）网络不可达，升级后自动采集失败为环境限制非缺陷。历史注记：2026-09-13 首次验收时 .3 的 .env 曾被仓库同步覆盖导致 Tower 凭据 key 丢失（UPG-042 保护正确拦截），属操作事故而非产品缺陷，凭据重配后恢复。

- **升级顺序写死（US-04 缓解）**：**先升平台（v0.5.3），再做 runner 组件升级（开发线现为 v0.3.3）**。v0.5.2 源端 web-api 在组件升级时无条件 stop upgrade-runner（US-04，源端老镜像无法修改），先升 runner 会导致新 runner 被停止；v0.5.3 平台侧已加同 project 守卫（US-11），按顺序交付即无此问题。
- **2026-09-27 49-52 实施验证（第五轮候选 `b9560eee…`，`.3`）**：后端全量 **386 tests OK (skipped=2)**（含 `test_upgrade_single_flight.py` 9 用例）、build_tests **26 OK**、`tsc -b` exit 0、vitest **107 passed（11 files）**、`verify_api_docs` 77 条一致、`verify_release_docs_safe` PASS；候选包 `.3:/data/upgrade-packages/v053-r5-20260927/`：`--check-version` OK、identity OK（web-api v0.5.3 / runner 基线 v0.3.1）、`.sha256` OK、敏感成员 0、manifest `required_health` 无 `runner_version`。**`.12` MVP 验收（M3-08/M3-10 先 runner 后平台、重复 start、平台先回归）待用户授权执行**。
- **2026-09-27 `.12` 全链路演练（从 v0.5.1u2 起，用户授权）**：`v0.5.1 → u2 → runner v0.3.1(已发布 d10e15cf) → v0.5.2(692aca8b) → v0.5.3 候选 r5(b9560eee) → runner v0.3.2(本地包 3d99599c)` 逐步 succeeded，v0.5.2 与 v0.5.3 两处 post-cleanup success；业务数据（users1/towers1/clusters1/vm_latest556/vm_volumes89588）**全程未丢失**、integrity ok、`.env` sha 未变、legacy 路径全清、目标 network/subnet 正确；8 项验收在 r5 与 r5+v0.3.2 两次全过；**US-23「重复 start → 400」实测通过**。演练副产品是两个新缺陷（US-24/US-25），见下。

- **2026-09-28 `.12` 复验 r6 候选（`6253810b…`，用户授权）**：客户形态起点（v0.5.2 + 已发布 runner v0.3.1，11 个任务目录占 7.5G、13 悬空镜像）→ **平台先直升 v0.5.3 task `upgrade-b07795625cf0d681` succeeded（360s）+ 8 项验收全过**（SQLite 556/89588 与升级前完全一致、`.env` sha 未变、7 条 legacy 路径全清）；**重复 start → 400**（US-23）；**US-25 卡死逃生**：runner 被中断后 t=35s `runner_lost`+`actions=['fail']` → `recovery/fail` 200 → 守卫释放；**同版本重装 task `upgrade-26856095c44869d1` 44s succeeded、attempt 最大 1、runner 重启 0**（US-24 确认修复，装 `c69e2129…` runner 后）。
- **平台包会把 runner 静默降回包内 tag（本轮新发现，US-26）**：runner 组件升级只把新 tag 写进 `compose-runtime/docker-compose.runner-bootstrap.yml`，平台包内的 compose 仍是旧 tag；平台升级按包内 compose 重建 runner → 组件升级成果被覆盖（实测 v0.3.2 → v0.3.1，无提示）。与「runner 随下一版交付」冲突，需在下个版本交付前定口径。
- **卡死逃生门不清理半迁移残留（US-27）**：`recovery/fail` 只改任务状态，被中断升级留下的旧路径（`/data/upgrades/<task>/package`、空骨架数据目录）仍在，需再跑一次成功升级由 post-cleanup 收尾；数据红线本次未受损。
- **组件升级后约 10 分钟 SQLite 写锁窗口（US-28）**：runner 空闲态仍持有大量未关闭 DB 连接（实测 52 个 fd），rollback journal 模式下独占写锁，期间 web-api 写操作（如升级预检查）直接 500 `database is locked`，需重试或等待。
### 已知问题与未解决事项（截至 2026-09-27）

- **同版本重装（已在目标布局）会卡死（US-24，2026-09-27 `.12` 实测；🟢 已修（并入 v0.3.2）：`engine._save` inode 判等跳过同文件 mirror 写，单测 4 例；随下一版 runner 交付复验）**：`v0.5.3 → v0.5.3` 同版本重装推进到 `compose.override` 后卡住，runner 反复 `RevisionConflict` 崩溃重启（实测 17 次）。根因在 runner：`engine._save()` 在 `task.migrate_runtime_state` 之后对与主 store 同一文件的 mirror 再写一遍，revision 每次 +2 → 下次保存必冲突。修复需改 runner → 须先经用户同意并 bump 版本（v0.3.3）+ 重交付组件包（待决，见 pending-tasks #48）。
- **M3-08（v0.5.1u2 × 先 runner 后平台）不做（2026-09-28 用户）**：支持链路只有「先平台、后 runner」，runner-first 不是受支持路径，且需要不随本次发布的 runner 组件（开发线 v0.3.3）；该格与 M3-10 一并记 N/A。US-05 的修复按「代码 + manifest 实证的防御性修复」记录，不写「顺序无关已实测」。
- **卡在 `running` 的任务没有产品化出路（US-25，2026-09-27 `.12` 实测；🟢 已修 2026-09-28：`recovery/{tid}/fail` 接受「running 且无活租约」的任务，视图暴露 `runner_lost` + `available_recovery_actions=["fail"]`，单测 7 例）**：`cancel` 只接受 pending、`recovery/fail` 只接受 recovery_required → 一旦任务卡在 running，后续升级会被单飞守卫永久拒绝，只能宿主手工干预。修复方向：恢复通道覆盖「长时间无有效租约的 running 任务」（web-api 侧，见 pending-tasks #49）。
- **2026-09-28 第六轮候选 `6253810b…`（`.3` 门禁通过，`.12` 复验待执行）**：相对第五轮收编 **US-07**（预检查磁盘空间硬校验）、**US-09**（升级任务产物自动清理）、**US-08**（执行期 runner 在场判定，接受任务租约通道）、**US-25**（卡死 `running` 任务的产品化出路）。构建记录：`--check-version` OK、宿主机 build_tests **26 OK**、identity exit 0、敏感成员 0；runner 组件包同时重建为 **v0.3.2**（含 US-24 修复；该版本从未交付，修复直接并入、**不 bump**；新包 SHA `c69e2129…`，旧开发包 `3d99599c…` 已被取代）。构建门禁：宿主机 build_tests **26 OK**、`--check-version` OK、identity OK、交付一致性门禁（`verify_runner_delivery_consistency.py --package`）**C1–C5 全 PASS**、容器内全量 **461 tests OK (skipped=2)**、两包敏感成员 **0**。
- **当前候选包（前一版）为第五轮 `b9560eee…`（`v0.5.3-r5`，2026-09-27）：`.3` 门禁全过（386 后端测试 / 26 构建测试 / tsc / vitest / identity / 敏感 0），`.12` MVP 验收（M3-08/M3-10 先 runner 后平台 → post-cleanup 必须成功、重复 start → 400、平台先回归）待用户授权执行**；其前序 `54aa8807…` 已由第四轮 `e1c0fde8…` 取代，第四轮包完成了 `.3` 门禁、`.12` v0.5.1 基线升级链路回归与正规升级 8 项验收。发布动作本身（推送、打 tag、release、对外交付）仍待用户明确指令。
- **runner 交付决策（2026-09-28 用户已决）**：**runner 组件不随本次 v0.5.3 发布交付（开发线 `v0.3.2`，含 US-24 修复），与下一个版本一起发**——本次只发平台包，平台包渲染的 runner 基线是**已发布 `v0.3.1`**（`.12` 实测直升 + post-cleanup 成功）；发布材料（含 OVA 说明）不得把 v0.3.2 写成本次交付物，交付物 compose 必须落 `v0.3.1`；US-24 的 runner 修复**已落地（并入 v0.3.2）**，随下一版 runner 交付并在 `.12` 复验。原始情况记录：①v0.5.3 升级本身**不再需要** `post_upgrade.schedule_collection`（方案 A，49-49），已发布 runner `v0.3.1`（Release 资产 `d10e15cf…`）即可直升；②但仓库开发线已按规矩 bump 到 `runner v0.3.2`（含 `post_upgrade.schedule_collection` 与 7~9 月修复），三个源码 compose 已写 `upgrade-runner:v0.3.2`，而**该版本目前无 git tag（`runner-v0.3.2`）、无 DockerHub 镜像、无随发布交付的组件包资产**（现有 `v0.3.2` 组件包仅存在于 `.3` 本地构建目录）。是否随本次发布一并交付（补 tag / 镜像 / 资产），待用户决定；若不交付，源码 compose 与部署文档须回退到已发布 `v0.3.1`。历史旧包（2026-06-28 `a112f6e1…`、2026-07 `d10e15cf…`）均不含该动作，详见 findings.md 2026-09-27。

- **测试环境 Tower（CHINATOWER/SMARTX-TT-WW）自 2026-09-12 网络不可达**：采集连续失败，容量数据停在 09-12；`collection-freshness-stale` critical 告警挂起（49-20 探针的端到端真实验证）。属环境限制非缺陷，待恢复可达性（pending-tasks #23，需用户侧处理）。
- **数据库无周期性自动备份**：现有备份均为事件驱动（升级前/清理前/手工）。是否立项"定期自动备份 + 恢复演练"待用户决策（pending-tasks #24）。
- **AI 措辞层未接实际 AI 服务**：设计即为可选增强，未配置时回退离线规则文案（行为与旧版一致），接入点留待有 AI 服务。
- **runner prepare 升级期在 app/ 下生成空骨架目录**：仅宿主机侧目录噪音，不阻塞升级、无数据复制；按用户决策仅记录不修复（pending-tasks #20）。
- **已接受的取舍**：前端 token 存 localStorage（内网离线产品，暂不改）。
- **生产现场「总览绿色」现象定位**：待生产现象复现时只读定位 `/api/dashboard/summary` 请求状态与 `capacity_risk.level`（pending-tasks #9）。

## v0.5.2

发布日期：2026-08-12（GitHub Release `v0.5.2` published 2026-08-12T06:36:06Z；原写 2026-07-17 与实际发布动作不符，2026-09-27 依 API 实测修正。注意：该 Release 的 runner 资产 `d10e15cf…` 是 2026-07-09 上传的，早于发布日期）

### 更新摘要

v0.5.2 是 v0.5.1u2 之后的正式平台版本。它基于 `v0.5.1u2` 桥接包、`upgrade-runner v0.3.1` 组件包完成完整升级链路验证，并把运行目录统一收敛到 `/data/smartx-storage-forecast` 单根目录。平台三件套使用 `v0.5.2` 镜像 tag，`upgrade-runner` 使用 `v0.3.1`。

### CloudTower 版本范围

- 数据采集和连接使用 CloudTower v2 HTTP API（`/v2/api/login`、`/v2/api/get-clusters`、`/v2/api/get-cluster-storage-info`、`/v2/api/get-vms`、`/v2/api/get-vm-volumes`）。
- 需要 CloudTower（SMTX OS）提供并支持上述 v2 API 端点；已在现场 CloudTower 实例（`CHINATOWER`）完成采集验证。

### 新增与优化

- 正式支持升级链路：`v0.5.1 + runner v0.3.0 -> v0.5.1u2 -> runner v0.3.1 -> v0.5.2`，全程通过正常升级接口验证。
- Compose project/network 迁移：从旧 `smartx-storage-forecast` / `smartx-storage-forecast_smartx-net`（`10.249.249.0/24`）迁移到 `smartx-hci-capacity-insight` / `smartx-hci-capacity-insight-net`（`10.249.251.0/24`）。
- 运行目录统一收敛到 `/data/smartx-storage-forecast/{project,app,prometheus,upgrades,backups,exports,compose-runtime}`，旧 `/opt`、旧 `/data/*` 和旧 `/prometheus-data` 在升级后自动清理。
- SQLite、Prometheus、`.env` 与 Tower 加密凭据成对迁移保护；目标 `.env` 权限要求为 `0600`，凭据与密钥不配套时升级硬失败。
- 升级完成后自动触发一次采集，作为独立任务进入任务中心；自动采集失败不改写平台升级成功状态。
- Prometheus 作为平台 Compose 服务随 v0.5.2 重建，不再单独拆成组件升级包。
- 升级任务历史排序、verification 包身份读取和任务中心投影稳定化。
- 报表导出改为全量虚拟机（不再截断 Top100），并修复部分虚拟机名称刷新问题。

### 验证说明

- 使用带业务数据、Tower 凭据和 Prometheus 历史的基线在测试机完整链路通过：主升级、runner 组件升级、升级后清理、升级后自动采集均成功。
- 使用空业务库基线在另一台测试机完整链路通过，验证升级、目录迁移、任务闭环和自动采集流程。
- 当前正式升级包：
  - `smartx-capacity-insight-upgrade-v0.5.1u2.tar.gz`（SHA256 `d5f277167445e7636ddfba16b4f780b40d59952467bb1c8e72d2469b43ee0a49`）
  - `smartx-upgrade-runner-v0.3.1.tar.gz`（SHA256 `d10e15cf7b516d172ebe2f1bc37621f9cf32d8ab3abd548f808ae5c5de151d2c`）
  - `smartx-capacity-insight-upgrade-v0.5.2.tar.gz`（SHA256 `692aca8b58ad8199c43c02a3771fa4fd7a62f1d7bbf4f198af4bd2e4b2c67733`）

## v0.5.1u2

发布日期：2026-06-29

### 更新摘要

v0.5.1u2 是面向已发布 v0.5.1 / v0.5.1u1 现场环境的桥接平台包。它不改变 compose project/network，只为后续 `upgrade-runner v0.3.1` 组件升级和 `v0.5.2` 平台迁移铺路。

### 新增与优化

- 修复 active runner 版本报告：页面/接口优先读取 runner 心跳或运行中 runner 容器的版本，不再用 web-api 内置基线版本冒充当前 runner。
- 修复组件升级任务显示：runner 组件升级后能正确显示执行步骤和进度。
- 支持从 `v0.5.1u1` 升级到 `v0.5.1u2`。
- 兼容 runner v0.3.0 能力集，桥接包可被旧 runner 预检查通过。
- 修复 runner 自升级后任务状态投影：已完成任务不再被误判为可再次执行。

## v0.5.1u1

发布日期：2026-06-24

### 更新摘要

v0.5.1u1 修复 Compose project 发现问题，保证 release 部署时能正确识别运行中的 compose project。

## v0.5.1

发布日期：2026-06-23

### 更新摘要

v0.5.1 修复报表增长 VM 名称显示问题，并完成 v0.5.1 平台升级包发布。

## v0.5.0

发布日期：2026-06-06

### 更新摘要

v0.5.0 是 v2 受控重建版本，保持 v1 的业务能力和页面风格，同时重建后端模块边界、任务中心、数据迁移灾备、升级中心和服务管理。平台版本使用 `v0.5.0`，`upgrade-runner` 作为独立组件升级到 `v0.3.0`。

### 新增与优化

- 平台版本统一为 `v0.5.0`，平台三件套使用 `v0.5.0` 镜像 tag。
- `upgrade-runner` 组件版本统一为 `v0.3.0`，不跟随平台版本 tag。
- v2 后端重建认证、Tower、采集、Dashboard、VM、报表、迁移、升级和服务管理模块。
- Dashboard 容量风险按单集群使用率判断，任一集群超过 80% 即高风险。
- 日增长、本日新建 VM、月增长、本月新建 VM 使用稳定 VM UUID 口径，展示名称优先使用最新采集名称。
- 月增长 VM 要求样本跨度满 30 天；刚部署不足 30 天时月增长榜为空。
- Word/Excel 报表复用页面数据口径，保存到 `/data/smartx-storage-forecast/exports/reports`，任务中心提供下载链接。
- 数据迁移导入前强制备份当前系统，迁出/迁入文件留存在 `/data/smartx-storage-forecast/exports` 对应目录。
- 升级中心 manifest 支持 platform、runner、observability 组件类型，平台升级、runner 组件升级和 Prometheus 组件升级分离。
- 服务管理页包含数据迁移、服务重启、升级中心和空间清理。
- Docker Compose 平台 tag 与 runner tag 分离，离线和 release compose 默认使用明确版本，不再依赖 `latest`。
- 2026-06-11 内部修补：任务中心确认 warning/critical 告警时不再刷新 `updated_at`，避免历史任务确认后跳回列表顶部。
- 2026-06-11 内部修补：升级包构建器支持 v2 跨版本累计 SQLite migration；当前 `v0.5.0` 正式包无 schema 迁移时不包含迁移脚本，也不声明 `script.sandbox.v1`。
- 2026-06-11 内部修补：迁移注册表支持严格校验、幂等 SQL 和 `add_column_if_missing`，未来跨过 schema 变化版本时按 `source_version < step.version <= target_version` 选择并执行中间迁移步骤。

### 升级策略

- 平台升级继续由 `upgrade-runner v0.3.0` 执行。
- 平台升级包只面向 v2 同架构后续升级；v1/v0.4.x 通过新装 v2 后导入数据迁移包兼容。
- 如果仅更新业务平台，不需要更新 runner。
- 如果升级流程、manifest、compose、volume、网络或 runner 自身能力变化，先发布 runner 组件包，再发布平台升级包。

## v0.4.1

发布日期：2026-06-05

### 更新摘要

v0.4.1 聚焦版本治理和升级边界收敛，将平台版本与 `upgrade-runner` 组件版本彻底拆分，避免 runner 被错误打上平台版本 tag。

### 新增与优化

- 平台版本统一为 `v0.4.1`，平台三件套使用 `v0.4.1` 镜像 tag。
- 新增根目录 `RUNNER_VERSION`，当前 runner 组件版本为 `v0.2.2`。
- `docker-compose.offline.yml` 和 `docker-compose.release.yml` 拆分 `SMARTX_IMAGE_TAG` 与 `SMARTX_RUNNER_IMAGE_TAG`。
- 平台升级包只包含 `web-api`、`collector-worker`、`frontend`，不再包含 `upgrade-runner.tar`。
- 后端镜像统一内置 `VERSION` 和 `RUNNER_VERSION`，平台版本与 runner 组件版本都优先读取镜像内文件。
- 修正部署文档，离线部署不再描述为 `latest` 默认 tag，并明确平台 tag 与 runner tag 分开配置。
- `scripts/build_runner_component_package.py` 默认读取 `RUNNER_VERSION`。
- GitHub Actions 拆分 runner 构建：平台 workflow 不再构建 runner，runner 仅通过 `runner-v*` tag 或手动 workflow 构建。
- 新增 `docs/version-governance.md`，记录版本模型、发版检查清单和 DockerHub 错误 tag 清理方法。

### 升级策略

- 平台升级继续由 `upgrade-runner v0.2.2` 执行。
- 如果仅更新业务平台，不需要更新 runner。
- 如果升级流程、manifest、compose、volume、网络或 runner 自身能力变化，先发布 runner 组件包，再发布平台升级包。

## v0.4.0

发布日期：2026-06-02

### 更新摘要

v0.4.0 聚焦首页容量风险展示、升级包生成规范和升级后核验能力，明确平台升级与 `upgrade-runner` 组件升级的边界。

### 新增与优化

- 首页顶部新增独立容量风险卡片，Tower 与集群卡片保持独立并对齐展示。
- 新增根目录 `VERSION`，作为版本号单一来源。
- 新增 `scripts/build_upgrade_package.py`，用于统一生成平台升级包、manifest、release-notes、镜像 tar 和 sha256 文件。
- 升级中心新增“平台状态”，展示当前软件版本、升级中心版本、运行服务镜像、服务状态、最近成功升级包版本和 SHA256。
- 新增 `docs/upgrade-runner-lifecycle.md`，说明 `upgrade-runner` 生命周期、组件升级策略和何时需要升级 runner。
- `docker-compose.release.yml` 默认镜像标签更新为 `v0.4.0`。

### 升级策略

- 平台升级包默认只升级 `web-api`、`collector-worker` 和 `frontend`。
- `upgrade-runner` 不随每个业务版本强制升级；只有升级流程、manifest 格式、compose/volume/network 模型或组件拓扑变化时，才通过组件升级单独更新。

## v0.3.3u2

发布日期：2026-06-01

### 更新摘要

v0.3.3u2 聚焦客户报表可读性、导出文档细节和升级可靠性，优化 Word/Excel 报表的目录、排序、高风险 VM 标识、时区显示和趋势图纵坐标，并修复升级前备份包含升级包自身导致备份阶段过慢的问题。

### 新增与优化

- Word 报表新增集群目录，支持按集群章节快速定位。
- Word/Excel 的 VM TOP100 表格新增排名列，并在表头标明增长量或增长率降序。
- Excel TOP100 区域改为表格结构，支持表头筛选和排序。
- 增长率超过 20% 且增长量大于 100 GiB 的 VM 在 Word/Excel 中使用红色底纹标识。
- 报表生成时间显式使用 `SMARTX_COLLECTION_TIMEZONE`，默认按 `Asia/Shanghai` 显示，避免容器 UTC 导致时间慢 8 小时。
- Word 报表容量趋势图纵坐标改为按数据范围自动留白，避免趋势线贴边。
- Word 集群章节页脚显示 `Tower-集群名称集群 · 生成时间`。
- 报表容量增长速率改为 7 天平均，并支持 7/30/90/365/720 天图表窗口切换。
- 数据迁移和升级前备份排除 `upgrades`、`backups` 运行目录，避免备份包含升级包自身。

### 升级包目录结构

```text
manifest.json
release-notes.md
images/
  web-api.tar
  collector-worker.tar
  frontend.tar
```

`manifest.json` 关键字段：

```text
product: smartx-storage-forecast
version: 0.3.3u2
min_version: 0.3.2
database_migration: false
images: web-api、collector-worker、frontend 镜像 tar 的 service、image、file、sha256
restart_services: web-api、collector-worker、frontend
```

### 验证说明

- 已在测试机使用本地升级包完成一次平台升级验证。
- 升级任务完成后 `web-api`、`collector-worker`、`frontend` 均正常 recreate/start。
- `web-api`、`frontend`、`prometheus` HTTP 健康检查均返回 200。

## v0.3.3

发布日期：2026-05-27

### 更新摘要

v0.3.3 聚焦升级中心体验和 upgrade-runner 组件独立升级能力，将平台升级与组件升级拆分，避免升级执行器在平台升级过程中重启自身。

### 新增与优化

- 将服务管理中的“系统升级”改为“升级中心”，下设平台升级、组件升级和升级历史。
- 保留平台升级能力，用于升级 `web-api`、`frontend`、`collector-worker` 等平台服务。
- 新增组件升级能力，第一版只支持单独升级 `upgrade-runner`。
- 新增组件升级接口，支持上传组件包、预检查、开始升级、状态查询、历史和删除未执行包。
- `upgrade-runner` 当前版本默认显示为 `v0.1.0`，升级成功后会记录到 `/data/upgrade-runner.version`。
- 组件升级由 `web-api` 直接执行 Docker 操作，只重启 `upgrade-runner`，不修改业务库、历史指标和数据卷。
- 平台升级与组件升级历史合并展示，并接入右上角任务中心进度。
- 优化升级执行步骤展示：升级开始后即展示完整步骤，运行中显示 loading，成功显示绿色勾，未执行显示空心圆。

### 组件升级包目录结构

```text
manifest.json
release-notes.md
images/
  upgrade-runner.tar
```

`manifest.json` 关键字段：

```text
product: smartx-upgrade-runner
component: upgrade-runner
version: 目标组件版本
min_version: 最低兼容组件版本
images: upgrade-runner 镜像 tar 的 service、image、file、sha256
restart_services: upgrade-runner
release_notes: 页面展示的组件升级说明
```

### 兼容说明

- 平台升级包默认仍不包含 `upgrade-runner`，避免平台升级任务过程中中断执行器。
- 组件升级不生成业务数据备份，因为它不修改业务数据库、Prometheus 历史指标和持久化 volume。
- 组件升级会在平台升级任务运行中被拦截，防止并发重启冲突。

## v0.3.2

发布日期：2026-05-27

### 更新摘要

v0.3.2 聚焦离线部署、/data 持久化目录和数据迁移可靠性，修复迁移到新系统后历史指标可能没有随业务库完整恢复的问题。

### 新增与优化

- 新增 `docker-compose.release.yml`，用于直接运行 GitHub Actions 构建好的远端镜像。
- 新增 `docker-compose.offline.yml`，默认使用本地 `latest` 镜像并设置 `pull_policy: never`，适合无外网或不允许拉取镜像的环境。
- 持久化数据统一迁移到宿主机 `/data/smartx-storage-forecast`：业务库位于 `app`，Prometheus 指标位于 `prometheus`。
- 系统升级预检查改为校验新的 `/data/smartx-storage-forecast` 绑定挂载，并按当前 `SMARTX_COMPOSE_FILE` 读取实际 compose 文件。
- 数据迁移补全导入优化：当目标 Prometheus 目录没有历史 block 时，会完整导入迁移包中的历史指标数据；已有历史 block 时只补充缺失 block，不覆盖现有指标。
- 更新平台版本号到 `0.3.2`，确保系统升级页显示和预检查版本判断准确。

### 升级包目录结构

v0.3.2 离线升级包生成路径示例：

```text
/data/upgrade-packages/smartx-capacity-insight-upgrade-v0.3.2.tar.gz
```

压缩包内部结构：

```text
manifest.json
release-notes.md
images/
  web-api.tar
  collector-worker.tar
  frontend.tar
scripts/
  migrate.sh              # 可选，仅当 manifest.database_migration=true 时需要
```

`manifest.json` 关键字段：

```text
product: smartx-storage-forecast
version: v0.3.2
min_version: 0.2.0
database_migration: false
images: 每个服务镜像 tar 的 service、image、file、sha256
restart_services: web-api、collector-worker、frontend
release_notes: 页面展示的升级说明
```

说明：v0.3.2 升级包为了兼容旧版本预检查，只在 `manifest.images` 中放入 `web-api`、`collector-worker` 和 `frontend`。`upgrade-runner` 镜像仍会随 `v0.3.2` tag 由 GitHub Actions 自动构建发布；升级到 v0.3.2 后，后续升级包可以包含 `upgrade-runner` 镜像，但默认不在同一次升级任务里重启执行器，避免任务过程中中断自身。

### 兼容说明

- 默认补全导入仍不覆盖当前业务库已有 Tower、集群和采集记录。
- 覆盖导入仍会整体替换当前业务库和 Prometheus 指标目录，执行前需要确认。
- 从旧 named volume 部署切换到 `/data/smartx-storage-forecast` 前，需要先迁移旧 volume 数据。

## v0.3.0

发布日期：2026-05-27

### 更新摘要

v0.3.0 聚焦平台运维能力，新增独立的服务管理页面、数据迁移导入导出、数据服务手动重启，以及第一版离线在线升级能力。升级功能采用“上传升级包、预检查、选中包后执行升级”的模式，避免直接覆盖数据卷或环境配置。

### 新增功能

- 新增“服务管理”独立页面，入口位于主导航“设置”之后。
- 服务管理页按平台运维场景分为：数据迁移、服务重启、系统升级、升级历史。
- 数据迁移支持导出迁移包，用于在同套系统之间迁移采集数据。
- 数据迁移支持补全导入，默认只补齐缺失数据，保留当前系统已有数据。
- 数据迁移支持覆盖导入，但需要显式确认。
- 服务重启页支持手动重启 `web-api`、`collector-worker` 和 `prometheus`，用于迁移导入后让数据完全生效。
- 新增离线升级包上传能力，升级包上传后保存到系统目录 `/data/smartx-storage-forecast/upgrades/{task_id}`。
- 系统升级页新增“可升级版本”区域，可选中某个升级包后执行预检查、开始升级、取消选择或删除未开始升级的包。
- 新增升级历史页，展示目标版本、状态、上传时间、完成时间和备份路径。
- 新增 `upgrade-runner` 服务，负责执行升级任务，避免 `web-api` 升级自身时中断任务。
- 升级前会自动生成数据迁移备份包，路径形如 `/data/smartx-storage-forecast/backups/upgrade-<version>-before-<time>.tar.gz`。
- 支持手动回滚到升级前镜像配置。

### 优化与修复

- 设置页移除数据迁移和服务管理相关内容，只保留 Tower 配置。
- 服务管理页进入后会收起集群侧栏，使平台运维页面居中展示。
- 优化服务管理页切换动画和滚动行为，避免切换数据迁移、系统升级、升级历史时页面显示不全。
- 优化上传控件样式，用统一上传面板替代浏览器原生文件选择控件。
- 优化预检查结果样式，成功项使用绿色勾，失败项使用红色 X。
- 统一系统升级操作按钮尺寸和对齐方式。

### 接口变更

新增鉴权接口：

```http
POST /api/admin/upgrade/upload
POST /api/admin/upgrade/precheck/{task_id}
POST /api/admin/upgrade/start/{task_id}
GET  /api/admin/upgrade/status/{task_id}
POST /api/admin/upgrade/rollback/{task_id}
DELETE /api/admin/upgrade/package/{task_id}
GET  /api/admin/upgrade/history
GET  /api/admin/upgrade/version
POST /api/admin/system/restart
GET  /api/admin/migration/export
POST /api/admin/migration/import
```

### 升级包格式

第一版离线升级包使用 `.tar.gz` 格式，包含：

```text
manifest.json
images/web-api.tar
images/frontend.tar
images/collector-worker.tar
scripts/migrate.sh      # 可选
release-notes.md        # 可选
```

`manifest.json` 需要包含版本、最低兼容版本、镜像列表、sha256、是否需要数据库迁移和重启服务列表。

### 数据保护策略

- 不覆盖 `.env`。
- 不替换业务数据卷和 Prometheus 数据卷。
- 不执行 `docker compose down -v`。
- 禁止修改核心 volume 挂载：`smartx-data:/data` 和 `prometheus-data:/prometheus`。
- 已开始升级的包不允许从页面删除，避免破坏回滚记录。

### 部署说明

升级到 v0.3.0 后需要重新构建并启动后端、前端和 upgrade-runner：

```bash
docker compose build web-api frontend collector-worker
docker compose up -d web-api frontend collector-worker upgrade-runner
```

## v0.2

发布日期：2026-05-25

### 更新摘要

v0.2 聚焦完善存储预测报表能力，新增 Word 和 Excel 导出，导出范围与页面当前选择保持一致，并修复月增长数据在部分环境下为空的问题。同时调整账号与页面交互，让平台密码修改入口回到管理员头像菜单。

### 新增功能

- 报表页新增统一 `导出` 按钮，点击后先选择历史时间区间，再自动下载 Word 和 Excel 两个文件。
- 导出范围跟随当前报表选择：全部集群、单个 Tower 或单个集群。
- 支持 7 天、14 天、30 天、90 天、180 天和 365 天历史窗口。
- Word 导出包含导出范围、生成时间、预测窗口、集群数量、集群预测汇总，以及每个集群的月增长 Top 100 VM 总结。
- Word 中每个集群分别提供按增长量排序和按增长率排序的 Top 100 表。
- Excel 导出包含 `汇总`、`VM_TOP100_汇总` 和每个集群独立 sheet。
- Excel VM 明细包含 Tower、集群、VM、当前容量、上期容量、月增长量和增长率。

### 优化与修复

- 修复报表容量增长速率可能为空的问题：当 Prometheus `offset` 查询缺少对应历史点时，会回退使用所选窗口内最早样本计算增长。
- 导出文件名按范围生成：全部导出使用 `storage-forecast-all-YYYYMMDD`，Tower 导出使用 Tower 名称加随机后缀，集群导出使用集群名称。
- 增长量/增长率切换按钮增加居中样式，避免紧凑宽度下文字偏移。
- 移除页面顶部的 `CHINATOWER` 范围栏，报表和虚拟机页面继续按当前集群树选择联动。
- 平台密码修改入口从设置页移动到右上角管理员头像菜单。头像菜单提供 `设置密码` 和 `登出`。

### 接口变更

新增鉴权接口：

```http
GET /api/reports/export/word?tower_id=&cluster_id=&period_days=30
GET /api/reports/export/excel?tower_id=&cluster_id=&period_days=30
```

### 依赖变更

后端新增文档导出依赖：

- `python-docx==1.1.2`
- `openpyxl==3.1.5`

## v0.1

发布日期：2026-05-23

### 更新摘要

v0.1 是项目第一版可用能力，提供 SmartX/CloudTower 容量采集、容量概览、虚拟机趋势、集群预测报表和基础平台管理能力。

### 新增功能

- 支持配置 CloudTower/Tower 连接信息，并通过连接测试发现集群。
- 支持多 Tower、多集群容量概览。
- 支持按全部、Tower、单集群范围查看容量数据。
- 支持每日定时采集和手动触发采集。
- 支持 Tower 级采集状态展示。
- 支持虚拟机列表、搜索和容量排序。
- 支持虚拟机存储趋势图，提供 7 天、14 天、30 天、90 天、180 天和 365 天时间范围。
- 支持当前虚拟机卷明细和所有虚拟卷明细展示。
- 支持日增长最快 VM 和月增长最快 VM 榜单。
- 支持按增长量和增长率切换排序。
- 支持集群容量预测报表，展示预测窗口、容量增长速率和容量风险。
- 支持平台登录、JWT 鉴权和管理员密码管理。

### 基础架构

- 后端使用 FastAPI。
- 前端使用 React、TypeScript 和 ECharts。
- 运行时数据存储在 SQLite 和 Prometheus 中。
- 使用 Docker Compose 部署 `web-api`、`collector-worker`、`frontend` 和 `prometheus`。
