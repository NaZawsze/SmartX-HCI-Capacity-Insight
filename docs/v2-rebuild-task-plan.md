# feature/upgrade-v2 受控重建任务文档

更新时间：2026-06-05

## 1. 重建决策

本文件记录 `feature/upgrade-v2` 的受控重建任务。v2 采用全新重写方式，但不是盲目删除重做，而是以 v1 功能、现有问题台账、现场验证经验和待办文档作为需求来源，重新构建更清晰的模块边界、任务状态和升级体系。

已确认决策：

- 重建方式：全新重写。
- UI 范围：保留 v1 信息架构，导航和主要操作位置尽量不变。
- 数据兼容：必须支持 v1 现场数据迁入。
- 升级兼容：不兼容旧升级路径，v2 升级中心重新规划。
- 容器数量：默认保持 5 个容器：`frontend`、`web-api`、`collector-worker`、`prometheus`、`upgrade-runner`。
- 分支边界：只在 `feature/upgrade-v2` 上重建，不影响 `dev/main`。
- 测试边界：v2 构建、部署和现场验证可以使用 `10.20.11.3`，远端仓库必须切换到 `feature/upgrade-v2` 分支。
- 前端边界：前端风格必须和 v1 保持一致，保留现有蓝白业务风格、导航结构、主要操作位置和客户交付感。
- 安全边界：不提交 `.env`、SQLite、Prometheus 数据、Tower 凭据、升级包、迁移包、备份包。

## 2. 总目标

v2 要把当前平台从“功能可用”升级为“现场可交付、可迁移、可升级、可排障”的稳定版本。

核心目标：

- 保留 v1 的业务能力：Tower 配置、集群采集、VM 趋势、容量预测、报表导出、数据迁移、服务管理、升级中心。
- 重建后端模块边界，避免报表、迁移、升级、采集互相缠绕。
- 重建统一后台任务模型，让上传、备份、导出、导入、升级、清理都有进度、日志、结果和失败原因。
- 明确 SQLite、Prometheus、`/data` 文件系统各自职责。
- 兼容 v1 数据迁入，尤其是 Prometheus 历史指标和旧 VM 卷 payload。
- 重新设计平台升级、组件升级、Prometheus 升级，不再沿用旧升级链路的历史包袱。

## 3. 受控重建原则

- 文档先行：先写清 v2 架构、数据兼容、升级包结构和任务模型，再改代码。
- 阶段可运行：每个阶段结束都要能构建、能测试、能说明状态。
- 保留需求源：`docs/functional-modules.md`、`docs/upgrade-issues.md`、`task_plan.md`、`findings.md` 作为 v2 需求输入。
- 代码可重建：后端 app 和前端 src 可以按 v2 结构重写。
- 部署资产谨慎保留：compose、Dockerfile、pre_install、GitHub Actions 可重构，但不能丢失离线部署能力。
- 数据不冒险：任何导入、升级、清理操作都必须先有扫描、预检查或备份。
- 不新增微服务：优先在代码内部拆模块，不把现场部署复杂度推高。

## 4. 模块任务

### 4.1 基础平台与配置

功能范围：

- 平台版本读取。
- runner 版本读取。
- 时区配置。
- `/data` 运行目录配置。
- Prometheus URL 配置。
- Docker project 与 compose 路径配置。
- 健康检查。

任务：

- [x] 设计 v2 配置模型，明确环境变量、版本文件、默认值的读取优先级。
- [x] 固定平台版本来自镜像内 `VERSION`。
- [x] 固定 runner 版本来自 `RUNNER_VERSION`。
- [x] 定义所有运行目录：
  - `/data/smartx-capacity-insight-data/app`
  - `/data/smartx-capacity-insight-data/prometheus`
  - `/data/upgrades`
  - `/data/backups`
  - `/data/exports`
  - `/data/exports/reports`
  - `/data/exports/migrations`
  - `/data/exports/imports`
  - `/data/exports/migration-tasks`
  - `/data/compose-runtime`
- [x] 设计健康检查接口，至少覆盖 web-api、Prometheus、数据库、数据目录权限。
- [x] 更新 `pre_install.sh`，确保目录和权限可以重复初始化。

验收标准：

- 全新服务器执行 `pre_install.sh` 后目录完整。
- Prometheus 数据目录权限正确，不出现 `queries.active permission denied`。
- web-api 可以返回平台版本、runner 版本、运行路径和健康状态。

### 4.2 用户、认证与权限

功能范围：

- 登录。
- token 鉴权。
- 当前用户。
- 修改密码。
- 登出。
- 管理接口鉴权。

任务：

- [x] 重建用户表和初始化逻辑。
- [x] 重建登录接口。
- [x] 重建 token 签发和校验。
- [x] 重建 `/api/me`。
- [x] 重建修改密码接口。
- [x] 前端保留 admin 头像菜单：设置密码、登出。
- [x] 所有管理接口必须鉴权第一版。

验收标准：

- 默认账号可登录。
- 修改密码后旧密码失效。
- 未登录访问管理接口返回 401。
- token 过期后前端状态能正确回到登录页。

### 4.3 Tower 与集群配置

功能范围：

- Tower 新增、编辑、删除。
- Tower 连接测试。
- Tower 凭据加密。
- 集群同步。
- 集群启用/禁用。
- scope 切换。

任务：

- [x] 重建 Tower 数据结构，凭据字段加密保存。
- [x] 重建 Tower CRUD 接口。
- [x] 重建 Tower 连接测试接口。
- [x] 连接测试成功后同步集群。
- [x] 重建集群启用/禁用接口。
- [x] 统一 scope 参数：全部、Tower、单集群第一版。
- [x] 前端设置页只保留 Tower 和集群配置，不放服务管理内容。

验收标准：

- Tower 凭据不会明文写入日志、迁移包、升级包。
- 选择 Tower 后 Dashboard、VM、报表都按 Tower 过滤。
- 选择集群后所有列表和报表只显示该集群数据。

### 4.4 CloudTower 客户端与采集

功能范围：

- Tower 登录。
- 获取集群。
- 获取集群容量。
- 获取 VM。
- 获取 VM 卷。
- 手动采集。
- 定时采集。
- 采集记录。

任务：

- [x] 重建 CloudTower API 客户端。
- [x] 定义 CloudTower 原始响应到 v2 领域模型的转换层。
- [x] 重建手动采集入口。
- [x] 重建 collector-worker 定时采集。
- [x] 采集时只处理已启用集群。
- [x] 采集状态写入 SQLite。
- [x] 采集失败记录错误摘要，避免泄露凭据。
- [x] 采集成功后写入 Prometheus 指标。
- [x] 采集成功后更新 VM 最新名称和最新卷信息。

验收标准：

- 手动采集可以触发并展示状态。
- collector-worker 可以按配置时间采集。
- 采集后 Dashboard、VM、报表能看到最新数据。

### 4.5 Prometheus 历史指标

功能范围：

- 历史容量指标存储。
- Prometheus 查询。
- query_range。
- 历史 block 迁移。
- Prometheus 权限检查。

任务：

- [x] 明确 v2 指标名称和 label 口径。
- [x] VM 指标必须包含 `tower_id`、`cluster_id`、`vm_id`。
- [x] 集群指标必须包含 `tower_id`、`cluster_id`。
- [x] 重建 Prometheus 查询服务。
- [x] 所有趋势查询必须带完整身份条件。
- [x] 增加 Prometheus 健康检查和权限检查。
- [x] 增加历史指标导入后校验第一版。

验收标准：

- `smartx_vm_storage_used_bytes` 可查询。
- VM 趋势、日增长、月增长、集群预测都能从 Prometheus 得到数据。
- 导入迁移包后 Prometheus 历史数据仍可查询。

### 4.6 SQLite 业务库

功能范围：

- 用户。
- Tower。
- 集群。
- VM 最新元数据。
- 最新卷结构化数据。
- 采集记录。
- 任务记录。
- 升级历史。
- 导出历史。

任务：

- [x] 重建 v2 schema。
- [x] 避免继续保存完整 Tower VM 卷原始 payload。
- [x] 建立结构化 VM 卷表，只保存页面、报表、导出和分析需要的字段。
- [x] 记录 VM 最新名称，历史趋势仍按 UUID。
- [x] 记录后台任务状态。
- [x] 记录导出文件和下载路径第一版。
- [x] 记录升级历史和回滚信息第一版。
- [x] 提供 schema 初始化和迁移机制第一版。

验收标准：

- 新部署可自动初始化数据库。
- v1 迁移包导入后能抽取旧 payload 中必要字段。
- SQLite 体积不再因完整 VM 卷原始 JSON 快速膨胀。

后续增强：

- 任务中心通知状态继续保存在 SQLite `tasks` 表，新增 `severity`、`seen_at`、`acknowledged_at` 等字段用于未处理角标和确认状态。
- 不立即拆分 SQLite 双 DB；`config.db + runtime.db` 作为低优先级架构治理项保留。
- 新机器配置迁移只依赖 `towers/clusters`，其他运行态表不作为配置迁移必需项。

### 4.7 Dashboard 首页

功能范围：

- 容量风险。
- Tower 数量。
- 集群数量。
- VM 数量。
- 容量使用率。
- SmartX ZBS 卡片。
- 采集状态。
- 日增长最快 VM。
- 本日新建 VM。
- 集群容量列表。
- 风险提示。

任务：

- [x] 重建 Dashboard 汇总接口。
- [x] 任一集群使用率 `>= 80%` 判定高风险。
- [x] 任一集群使用率 `75%-80%` 判定需关注。
- [x] 无风险时显示 `当前所有集群暂无明显容量风险`。
- [x] 容量风险卡片放在首页最前面。
- [x] Tower 和集群卡片保持独立，布局不影响其他卡片。
- [x] 日增长最快 VM 支持增长量/增长率切换。
- [x] 本日新建 VM 做成独立卡片，放在日增长下方。
- [x] VM 项点击跳转虚拟机页面并定位。

验收标准：

- 某个集群高风险时首页立即显示风险。
- 总容量正常但单集群超 80% 时仍触发风险。
- 本日新建 VM 卡片不是嵌入日增长卡片内部。

### 4.8 虚拟机页面

功能范围：

- VM 列表。
- VM 趋势。
- VM 详情。
- VM 卷详情。
- 存储策略解析。
- scope 联动。

任务：

- [x] 重建 VM 列表接口。
- [x] 重建 VM 趋势接口。
- [x] 趋势查询支持 7/14/30/90/180/365 天。
- [x] 趋势查询按 `tower_id + cluster_id + vm_id` 过滤。
- [x] 重建 VM 卷详情接口。
- [x] 前端支持从 Dashboard 跳转到指定 VM。
- [x] VM 改名后展示最新名称。
- [x] 前端支持从报表跳转到指定 VM。

验收标准：

- VM 改名后历史趋势不断裂。
- 不同 Tower/集群中相同 `vm_id` 不会混合。
- 卷信息能展示容量、已用、策略、副本/EC 信息。

### 4.9 报表与存储预测

功能范围：

- 集群预测。
- 90 天预测。
- 7 天平均增长速率。
- 趋势窗口。
- 日增长榜。
- 月增长榜。
- 本日/本月新建 VM。
- Word 导出。
- Excel 导出。
- 导出留存和下载。

任务：

- [x] 重建 `latest_report` 领域逻辑。
- [x] 集群预测默认使用 90 天。
- [x] 容量增长速率使用最近 7 天平均。
- [x] 页面提示 `7 天平均`。
- [x] 支持 7/30/90/365/720 天图表窗口。
- [x] 月增长 VM 必须样本跨度满 30 天。
- [x] 刚部署不足 30 天时月增长榜为空。
- [x] 本日新建 VM 和本月新建 VM 都做成独立卡片。
- [x] Word/Excel 导出复用页面同一数据口径第一版。
- [x] 导出表格标注统计窗口起止日期。
- [x] 导出中的“上期容量”统一改为“期初容量”。
- [x] 高风险 VM 底纹标红：增长率超过 20% 且增长量大于 100G。
- [x] Word 增加目录，目录项为每个集群。
- [x] Word 页脚包含 Tower、集群、时间。
- [x] 导出文件保存到 `/data/exports/reports`。
- [x] 任务中心提供报表下载链接。

验收标准：

- Word/Excel 均能打开。
- 文件名包含 scope、日期时间、统计天数。
- 月增长榜不包含样本不足 30 天的 VM。
- 报表首页显示当前软件版本。
- 报表图表坐标轴不会把线条挤在顶部或柱状图贴边。

### 4.10 数据迁移与灾备

功能范围：

- 数据迁出。
- 数据迁入。
- 导入前备份。
- merge/overwrite。
- Prometheus 历史指标迁移。
- v1 数据兼容。
- 导入后健康验证。

任务：

- [x] 重建迁移包 manifest 第一版。
- [x] 迁移包必须包含 SQLite 必要业务数据。
- [x] 迁移包必须包含 Prometheus 历史 block。
- [x] 迁移包必须包含校验信息第一版。
- [x] 数据迁出任务显示精确进度、小日志、当前文件第一版。
- [x] 数据迁出文件保存到 `/data/exports/migrations`。
- [x] 数据迁入包保存到 `/data/exports/imports`。
- [x] 导入前自动备份当前系统到 `/data/backups`。
- [x] 备份失败阻止导入第一版。
- [x] 默认 merge 模式补全缺失数据，不覆盖现有数据第一版。
- [x] overwrite 模式必须显式选择。
- [x] 支持 v1 迁移包导入第一版。
- [x] 从 v1 旧 VM 卷 payload 中抽取必要字段写入 v2 结构第一版。
- [x] 导入后提供 Prometheus 历史指标回归检查第一版。
- [x] 任务中心提供迁出包下载链接和导入结果摘要第一版。

验收标准：

- 只导入 SQLite 不允许被误认为完整迁移。
- 完整迁移后趋势图、日增长、月增长、集群预测报表都有数据。
- 导入前备份文件真实存在。
- v1 迁移包可导入 v2。

已落地增强：

- [x] 新增“配置迁移包”：只导出 `towers` 和 `clusters`，manifest 标记 `migration_scope=config`。
- [x] 保留“完整迁移包”：包含 SQLite 必要数据和 Prometheus 历史指标。
- [x] 配置迁移包导入前仍先备份当前 `smartx.db`，导入时只 merge `towers/clusters`。
- [x] 配置迁移不迁移平台管理员账号、任务历史、VM/卷缓存、采集记录或当前指标快照。
- Tower 凭据如因加密 key 不一致无法解密，需要在目标系统重新录入密码或 token。

### 4.11 统一后台任务中心

功能范围：

- 上传任务。
- 报表导出任务。
- 数据迁出任务。
- 数据迁入任务。
- 升级任务。
- 清理任务。
- 下载链接。
- 日志和进度。

任务：

- [x] 设计统一任务状态：pending、running、success、failed、cancelled。
- [x] 设计统一任务步骤：名称、状态、进度、日志、开始时间、结束时间第一版。
- [x] 任务状态持久化到 SQLite，确保 web-api 重启后可恢复。
- [x] 前端右上角任务入口展示后台任务第一版。
- [x] 点击空白处可收起任务菜单。
- [x] 任务完成后保留结果和下载链接第一版。
- [x] 失败任务展示失败步骤和错误摘要。

验收标准：

- 上传大文件不会停在 95% 无提示。
- 备份、导出、导入、升级都能看到进度。
- 页面刷新后仍能看到正在执行或已完成任务。

已落地增强：

- [x] 任务中心分为 `info`、`warning`、`critical` 三类通知。
- [x] 角标统计未处理通知，不统计运行中任务数量。
- [x] 信息类完成任务在打开任务中心并点击空白关闭后标记已读。
- [x] 告警和严重告警必须点击“确认”或 X 删除后才清除角标。
- [x] 一键清空只清理已读信息任务和已确认告警任务。
- [x] 失败/取消任务右侧展示“确认”和 X 两个操作，确认按钮位于 X 左侧。

### 4.12 升级中心 v2

功能范围：

- 统一升级包上传。
- manifest 自动识别组件。
- 平台升级。
- runner 组件升级。
- Prometheus 组件升级。
- 项目文件同步。
- 预检查。
- 备份。
- 回滚。
- 历史记录。

任务：

- [x] 设计 v2 升级包 manifest 第一版。
- [x] manifest 自动识别平台三件套、runner、Prometheus/observability 第一版。
- [x] 平台升级只升级 `web-api`、`collector-worker`、`frontend` 第一版。
- [x] runner 升级作为组件升级，不跟随平台版本第一版。
- [x] Prometheus 升级作为 observability 组件第一版。
- [x] 预检查显示步骤化进度。
- [x] 预检查校验 manifest、镜像 archive、sha256、项目文件、敏感路径第一版。
- [x] 升级前强制备份数据第一版。
- [x] 同步项目文件前备份旧项目文件第一版。
- [x] 平台和 Prometheus 升级任务由 upgrade-runner 执行第一版。
- [x] runner 组件升级由 web-api 直接执行第一版，避免 upgrade-runner 重启自己导致任务断链。
- [x] 回滚恢复镜像 override、项目文件和运行配置第一版。
- [x] 升级历史记录版本、组件、状态、备份路径、日志路径第一版。
- [x] 页面合并平台状态和升级后核验，不重复展示。

验收标准：

- 上传一个包后能自动识别升级类型。
- 未在 manifest 中声明的组件不会被动到。
- Prometheus 升级前必须检查历史数据目录权限。
- 平台升级不会误升级 runner。
- runner 组件升级不会依赖旧只读 `/opt` 写入路径，也不会由 runner 自己执行重启自身。

### 4.13 服务管理与空间清理

功能范围：

- 数据迁移。
- 服务重启。
- 平台升级。
- 组件升级。
- 升级历史。
- 镜像清理。
- 运行文件清理。

任务：

- [x] 服务管理作为独立主导航页面。
- [x] 左侧二级菜单包含数据迁移、服务重启、升级中心、空间清理。
- [x] 设置页不再包含服务管理内容。
- [x] 服务重启支持 web-api、collector-worker、Prometheus 第一版。
- [x] 空间清理先扫描再清理第一版。
- [x] 扫描升级包、数据迁出、报表导出、导入留档。
- [x] 扫描并清理未使用 Docker 镜像第一版。
- [x] 显示每项大小和预计可释放空间第一版。
- [x] 清理按钮使用危险色，扫描按钮使用主色。
- [x] 清理结果展示释放空间和日志第一版。

验收标准：

- 清理旧镜像不再显示错误的 0B。
- 清理运行文件不会清理 `/data/backups` 默认备份。
- 清理前能看到将被删除的文件列表。

### 4.14 前端 UI 与组件

功能范围：

- AppLayout。
- 登录页。
- Dashboard。
- VM 页面。
- 报表页。
- 设置页。
- 服务管理页。
- 通用组件。

任务：

- [x] 保留 v1 主导航信息架构第一版。
- [x] 重建统一布局和全局 scope第一版。
- [x] 重建卡片、状态、表格、上传、进度、任务下拉组件第一版。
- [x] Dashboard 首屏突出容量风险第一版。
- [x] VM 页面支持趋势和详情。
- [x] 报表页支持统计窗口、新建 VM 卡片和导出。
- [x] 设置页只处理 Tower 和账号相关能力。
- [x] 服务管理页处理迁移、重启、升级、清理。
- [x] 移动端不遮挡、不错位第一版。
- [x] 下拉菜单点击空白处自动收起。
- [x] 隐藏滚动条但滚动时可用。

验收标准：

- 用户不需要重新学习主要导航。
- 重点页面没有卡片错位。
- 上传、预检查、备份、清理都有页面内进度，不使用浏览器原生丑弹窗。

### 4.15 部署、构建与发版

功能范围：

- Dockerfile。
- compose。
- pre_install。
- GitHub Actions。
- 升级包打包脚本。
- runner 组件包打包脚本。
- 文档和 changelog。

任务：

- [x] 平台镜像使用平台版本 tag。
- [x] runner 镜像使用 runner 版本 tag。
- [x] 平台 GitHub Actions 只构建平台三件套。
- [x] runner GitHub Actions 只构建 runner。
- [x] compose 使用明确版本，不默认 `latest`。
- [x] release/offline compose 不包含 build。
- [x] 升级包不包含 `.env`、数据库、Prometheus 数据、凭据。
- [x] 打包脚本自动校验版本一致性。
- [x] 每次发版更新 changelog 第一版。
- [x] README 写清升级包目录结构。

验收标准：

- 离线环境不会因为 compose build 拉 DockerHub 基础镜像。
- DockerHub 不再出现 runner 被平台 tag 污染。
- 升级包 manifest、compose、镜像 tag、版本显示一致。

## 5. 数据职责

SQLite 负责：

- 用户和密码哈希。
- Tower 和加密凭据。
- 集群元数据和启用状态。
- VM 最新元数据和最新名称。
- VM 最新卷结构化数据。
- 采集运行记录。
- 后台任务状态。
- 导出历史。
- 升级历史。

Prometheus 负责：

- 集群容量历史。
- VM 容量历史。
- 趋势图查询。
- 日增长、月增长计算。
- 集群预测和报表历史数据。

`/data` 文件系统负责：

- Prometheus 历史 block。
- SQLite 文件。
- 升级包。
- 升级前备份。
- 迁出包。
- 迁入包。
- 报表导出文件。
- 任务日志。
- compose runtime override。

## 6. v1 数据兼容要求

v2 不兼容 v1 旧升级路径，但必须兼容 v1 数据迁入。

必须支持：

- 导入 v1 迁移包。
- 读取 v1 SQLite 中 Tower、集群、VM、采集记录。
- 读取 v1 Prometheus 历史 block。
- [x] 从 v1 `latest_vm_volumes.payload_json` 中抽取必要卷字段第一版。
- 丢弃不需要的 Tower 原始字段。
- 导入后 VM 趋势、日增长、月增长、集群预测报表可用。

不要求支持：

- 通过旧 web-api/旧 runner 原地升级到 v2。
- 兼容旧升级包格式执行 v2 升级。
- 保留 v1 中所有原始 Tower payload 字段。

## 7. 实施阶段

### Phase V2-0 - 需求冻结与文档

状态：完成

- [x] 输出 `docs/architecture-v2.md`。
- [x] 输出 `docs/architecture.md`，作为项目架构总览入口。
- [x] 输出 `docs/v1-data-compatibility.md`。
- [x] 输出 `docs/v2-upgrade-center-design.md`。
- [x] 输出 `docs/v2-api-contracts.md`。
- [x] 输出 `docs/v2-frontend-design.md`。
- [x] 输出 `docs/v2-implementation-sequence.md`。
- [x] 更新 `docs/functional-modules.md`，标注 v2 模块边界。
- [x] 更新 `docs/upgrade-issues.md`，把旧升级问题映射到 v2 设计规避点。

### Phase V2-1 - 项目骨架

状态：完成

- [x] 重建后端模块目录。
- [x] 重建前端页面和组件目录。
- [x] 定义统一类型、任务状态、错误模型。
- [x] 保证空壳后端和前端能构建。

### Phase V2-2 - 基础平台与认证

状态：完成

- [x] 配置、版本、路径、数据库初始化。
- [x] 用户、登录、鉴权、改密。
- [x] 健康检查。
- [x] 远端 Docker 环境验证 API 鉴权链路和前端构建。

### Phase V2-3 - Tower、采集与 Prometheus

状态：完成第一版

- [x] Tower 管理。
- [x] 集群同步和启用。
- [x] 手动采集基础链路。
- [x] collector-worker 定时采集基础。
- [x] Prometheus 指标文本基础格式。
- [x] Prometheus 查询和健康检查基础。
- [x] Prometheus scrape 基础闭环。
- [x] 采集记录列表和详情 API。

### Phase V2-4 - Dashboard 与 VM 页面

状态：完成第一版

- [x] Dashboard 容量风险驾驶舱后端基础。
- [x] Dashboard 容量风险 API 返回风险标题、说明、风险集群数量和 top clusters。
- [x] 日增长和本日新建 VM 后端基础。
- [x] VM 列表和趋势后端基础。
- [x] VM 详情和卷信息后端基础。
- [x] Dashboard/VM 前端页面接入。

### Phase V2-5 - 报表与导出

状态：完成第一版

- [x] 90 天预测。
- [x] 7 天平均增长速率。
- [x] 月增长 30 天样本过滤。
- [x] 本月新建 VM 后端基础。
- [x] 报表页接入 v2 `latest_report` 合同。
- [x] 报表页支持从月增长、本日/本月新建 VM 跳转虚拟机页面。
- [x] Word/Excel 导出和留存第一版。
- [x] 导出文件保存到 `/data/exports/reports`。
- [x] 导出响应提供任务中心可用下载链接。
- [x] Word/Excel 首页增加容量风险摘要。

### Phase V2-6 - 数据迁移灾备

状态：完成第一版

- [x] v2 迁出第一版。
- [x] v2 迁入第一版。
- [x] 导入前备份。
- [x] v1 数据兼容迁入第一版。
- [x] 导入后健康验证第一版。

### Phase V2-7 - 升级中心 v2

状态：完成第一版

- [x] 统一 manifest 第一版。
- [x] 平台升级第一版。
- [x] runner 组件升级第一版。
- [x] Prometheus 组件升级第一版。
- [x] 项目文件同步第一版。
- [x] 回滚和历史记录第一版。

### Phase V2-8 - 服务管理与空间清理

状态：完成第一版

- [x] 数据迁移页面第一版。
- [x] 服务重启第一版。
- [x] 空间扫描和清理第一版。
- [x] SQLite 空间整理扫描和 VACUUM 第一版。
- [x] 任务中心基础联动。

### Phase V2-9 - 部署、打包与现场验证

状态：完成第一版

- [x] compose 和 Dockerfile。
- [x] GitHub Actions。
- [x] pre_install。
- [x] 升级包和组件包打包第一版。
- [x] 在 `10.20.11.3` 切换到 `feature/upgrade-v2` 后完成 v2 第一版构建和运行验证。

## 8. 测试计划

后端测试：

- [x] 认证和改密。
- [x] Tower CRUD 和连接测试。
- [x] 采集响应解析。
- [x] Prometheus 查询。
- [x] Dashboard 风险判断。
- [x] VM 改名展示。
- [x] 月增长 30 天样本过滤。
- [x] 报表导出数据口径。
- [x] 数据迁入前备份。
- [x] v1 迁移包兼容。
- [x] 升级 manifest 预检查。
- [x] 空间清理扫描和删除。

前端测试：

- [x] 登录和 token 过期第一版。
- [x] scope 切换第一版。
- [x] Dashboard 风险卡片。
- [x] 本日/本月新建 VM 独立卡片。
- [x] VM 趋势和跳转定位。
- [x] 报表导出任务。
- [x] 数据迁移任务。
- [x] 升级预检查和执行进度。
- [x] 空间清理扫描和确认。

集成测试：

- [x] 新部署采集后 Dashboard、VM、报表都有数据。
- [x] v1/v2 迁移包导入后趋势图、日增长、预测报表都有数据；月增长按 30 天样本规则验证。
- [x] Prometheus 权限错误能被预检查发现第一版。
- [x] 平台升级不影响 Prometheus 数据第一版。
- [x] Prometheus 组件升级后历史指标仍可查询。

现场验证：

- [x] 在 `10.20.11.3` 部署 v2，并确认远端分支为 `feature/upgrade-v2`。
- [x] 执行 `pre_install.sh`。
- [x] 启动 compose。
- [x] 添加 Tower 并采集。
- [x] 导出 Word/Excel。
- [x] 迁出数据并导入隔离验证环境。
- [x] 执行平台升级包。
- [x] 执行 runner 组件包。
- [x] 执行 Prometheus 组件升级包。
- [x] 验证任务中心、空间清理、服务重启第一版。

## 9. 风险与约束

- v2 全新重写会带来较大回归成本，因此每个阶段必须可验证。
- v1 数据兼容是硬要求，不能只兼容 SQLite，必须兼容 Prometheus 历史指标。
- 升级路径不兼容旧版本，但必须提供清晰迁移指引。
- 不新增微服务，避免离线部署和现场排障复杂度上升。
- Prometheus 是趋势和增长数据核心，不能把历史指标简化为可选项。
- runner 自升级必须重新设计，不能依赖旧 web-api 写只读路径。

## 10. 当前下一步

- [x] 确认本任务文档内容。
- [x] 创建 v2 架构文档。
- [x] 创建 v1 数据兼容文档。
- [x] 创建 v2 升级中心设计文档。
- [x] 创建 v2 API 契约文档。
- [x] 创建 v2 前端设计文档。
- [x] 创建 v2 实施顺序文档。
- [x] 再开始代码层面的受控重建。

## 11. v2 细化设计文档清单

Phase V2-0 先细写设计文档，再进入代码重建。该阶段目标是把模块职责、数据结构、API、迁移兼容、升级状态机、前端页面和验收标准提前锁定，避免后续实现时边写边猜。

### 11.1 `docs/architecture-v2.md`

定位：v2 总体架构文档。

需要写清：

- 系统目标：现场可交付、可迁移、可升级、可排障。
- 容器职责：`frontend`、`web-api`、`collector-worker`、`prometheus`、`upgrade-runner`。
- 后端模块边界：`auth`、`inventory`、`collection`、`metrics`、`forecast`、`reports`、`migration`、`upgrade`、`tasks`、`system`。
- 前端信息架构：Dashboard、VM、Reports、Settings、Service Management。
- 数据职责：SQLite、Prometheus、`/data` 文件系统分别保存什么。
- 关键规则：VM 身份、VM 最新名称、Tower 原始 payload 处理、不新增微服务容器。

### 11.2 `docs/v1-data-compatibility.md`

定位：v1 现场数据迁入 v2 的兼容方案。

需要写清：

- v2 不兼容旧升级路径，但必须兼容 v1 数据迁入。
- v1 数据来源：SQLite、Prometheus 历史 block、v1 迁移包 manifest、旧 `latest_vm_volumes.payload_json`。
- 导入前强制备份，备份失败阻止导入。
- 默认 merge，不覆盖现有 Tower/集群/VM；overwrite 必须显式选择。
- 旧 VM 卷 payload 只抽取页面、报表、导出所需字段，其他 Tower 原始字段丢弃。
- Prometheus 历史 block 必须导入，不导入 `wal` 运行时目录。
- 导入后健康验证：SQLite 记录、Prometheus series、`query_range`、VM 趋势、日增长、月增长、集群预测报表。

### 11.3 `docs/v2-upgrade-center-design.md`

定位：v2 升级中心设计文档。

需要写清：

- 统一升级入口：上传一个 `.tar.gz` 包，由 `manifest.json` 自动识别升级内容。
- 支持组件：platform、runner、observability。
- 升级包结构：`manifest.json`、`images/*.tar`、`project/**`、`scripts/migrate.sh`、`release-notes.md`。
- manifest 字段：包类型、目标组件、版本、镜像、sha256、重启服务、项目文件、迁移要求、兼容版本。
- 状态机：uploaded、parsed、prechecked、backup_running、images_loaded、project_synced、migration_running、services_restarting、health_checking、success、failed、rollback_ready。
- 预检查：镜像名/tag/sha256、Docker、compose、网络、volume、项目文件敏感路径、磁盘空间、Prometheus 权限。
- 回滚：恢复 compose override、项目文件备份、运行配置；数据备份保留给人工恢复。
- runner 自升级：不写只读 `/opt`，使用 `/data/compose-runtime`，任务状态跨重启恢复。
- Prometheus 升级：强制备份数据目录，检查 `65534:65534` 权限，升级后检查 `/-/ready`、`query`、`query_range`。

### 11.4 `docs/v2-api-contracts.md`

定位：v2 API 和前后端数据契约。

需要写清：

- 认证 API：login、me、change password。
- Tower/cluster API：Tower CRUD、连接测试、同步集群、启用集群。
- collection API：手动采集、采集状态。
- dashboard API：summary、risk status、day growth、day new VMs。
- VM API：list、trend、volumes。
- report API：latest report、export report task、export download。
- migration API：export task、import upload、import start、import status、health check。
- upgrade API：upload package、package list、precheck、start、status、rollback、history。
- task API：list tasks、task detail、task logs、download artifact。
- 每个 API 都需要标注参数、响应关键字段、错误状态、鉴权要求和对应前端页面。

### 11.5 `docs/v2-frontend-design.md`

定位：v2 前端页面和组件文档。

需要写清：

- 保留 v1 主导航。
- 页面职责：Dashboard、VM、Reports、Settings、Service Management。
- 通用组件：Scope selector、Task center、Upload panel、Step progress、Data table、Risk card、Trend chart。
- 交互规则：下拉点击空白处收起，上传显示速度和服务器处理阶段，预检查和升级步骤使用统一状态图标。
- 本日/本月新建 VM 是独立卡片，不嵌入增长榜。
- 响应式规则：移动端不遮挡，卡片不挤压，表格可横向滚动。

### 11.6 `docs/v2-implementation-sequence.md`

定位：v2 代码重建阶段执行顺序。

需要写清：

- Phase V2-0：文档冻结。
- Phase V2-1：项目骨架。
- Phase V2-2：基础平台和认证。
- Phase V2-3：Tower、采集、Prometheus。
- Phase V2-4：Dashboard 和 VM。
- Phase V2-5：报表。
- Phase V2-6：数据迁移。
- Phase V2-7：升级中心。
- Phase V2-8：服务管理。
- Phase V2-9：部署和现场验证。
- 每个阶段都需要写明目标、交付物、验收命令、不允许混入的工作、是否可以提交。
