# SmartX HCI Capacity Insight 功能模块归类

本文用于把当前项目按功能域拆开，后续排查和优化时可以一个模块一个模块处理，避免前端、后端、采集、升级和部署问题混在一起。

升级模块的当前问题、根因和修复顺序单独记录在 `docs/upgrade-issues.md`。

## 1. 基础平台与部署

目标：保证系统能稳定部署、启动、升级后服务正常。

主要内容：
- Docker Compose 编排：`web-api`、`frontend`、`collector-worker`、`prometheus`、`upgrade-runner`
- 镜像构建：开发镜像、本地离线镜像、Release 镜像、升级包镜像
- 数据目录：`/data/smartx-capacity-insight-data/app`、`/data/smartx-capacity-insight-data/prometheus`
- 运行产物目录：`/data/upgrades`、`/data/backups`、`/data/exports`、`/data/compose-runtime`；其中报表、数据迁出、数据迁入留档分别在 `/data/exports/reports`、`/data/exports/migrations`、`/data/exports/imports`。
- 网络规划：Docker 网络段、端口暴露、Prometheus 内部访问
- 时区配置：宿主机 CST、容器内 CST、报表和升级日志时间
- 安装前置脚本：目录创建、权限、SELinux/防火墙/Prometheus 权限

相关文件：
- `docker-compose.yml`
- `docker-compose.offline.yml`
- `docker-compose.release.yml`
- `docker-compose.upgrade.yml`
- `pre_install.sh`
- `.github/workflows/docker-images.yml`
- `backend/Dockerfile`
- `backend/Dockerfile.worker`
- `backend/Dockerfile.upgrade`
- `frontend/Dockerfile`
- `prometheus/prometheus.yml`

常见问题：
- [已解决] 新机器启动时仍尝试从 Docker Hub 拉基础镜像：提供离线 compose 和本地镜像部署路径
- [已解决] Prometheus 数据目录权限导致容器循环重启：`pre_install.sh` 创建目录并修正权限
- [已解决] compose 文件写死旧版本：版本来源改为镜像内置 `VERSION`，compose 默认 tag 固定到明确版本
- [已解决] 容器时间和页面日志差 8 小时：按 CST/Asia/Shanghai 统一展示
- [已解决] Docker 默认网段和客户环境冲突：项目网络改为 `10.249.249.0/24`，Docker daemon 可配置 `10.249.0.0/16`
- [已解决] 升级包、备份、报表导出、数据迁出、数据迁入留档等运行产物不再落在 `app/` 目录下：独立到 `/data/upgrades`、`/data/backups`、`/data/exports`、`/data/compose-runtime`

## 2. 用户、认证与权限

目标：保证登录、改密、鉴权和会话行为清晰可靠。

主要内容：
- 登录和 token 签发
- `/api/me` 当前用户信息
- admin 头像下拉菜单：修改密码、登出
- 管理接口鉴权
- 密码修改位置和交互

相关文件：
- `backend/app/api/deps.py`
- `backend/app/core/security.py`
- `backend/app/services/users.py`
- `backend/app/api/routes.py`
- `frontend/src/App.tsx`
- `frontend/src/components/AppLayout.tsx`
- `frontend/src/pages/LoginPage.tsx`
- `frontend/src/services/api.ts`

常见问题：
- token 过期后页面状态不同步
- [已解决] 改密入口位置不符合用户习惯：移动到 admin 头像下拉菜单
- [已解决] 下拉菜单点击空白处不自动收起：账号菜单和任务菜单支持空白处收起
- [已解决] 登录页和标签页 logo 展示不一致：favicon 同步登录页图形风格

## 3. Tower 与集群配置

目标：管理 Tower 连接、集群启用状态和采集范围。

主要内容：
- Tower 新增、编辑、删除
- Tower 连接测试
- Tower 凭据加密存储
- 集群同步、启用、禁用
- 页面 scope 切换：全部、Tower、单集群

相关文件：
- `backend/app/services/towers.py`
- `backend/app/services/cloudtower.py`
- `backend/app/models.py`
- `backend/app/api/routes.py`
- `frontend/src/pages/SettingsPage.tsx`
- `frontend/src/App.tsx`
- `frontend/src/types.ts`

常见问题：
- [已解决] 页面选择 Tower 后数据没有按 Tower 过滤：列表、报表、虚拟机页面按当前 scope 切换
- 集群启用状态和采集结果不一致
- Tower 凭据不能被误提交或导出
- [已解决] 设置页职责过多，服务管理内容不应放在设置里：服务管理独立成主导航页面

## 4. 数据采集与历史指标

目标：从 Tower 采集容量数据，写入业务库和 Prometheus，供趋势、增长和预测使用。

主要内容：
- 手动采集
- 定时采集 worker
- Tower、集群、VM、卷信息采集
- Prometheus 指标写入和查询
- 采集状态展示
- 历史指标保留周期

相关文件：
- `backend/app/collector/collector.py`
- `backend/app/collector/worker.py`
- `backend/app/services/cloudtower.py`
- `backend/app/services/prometheus.py`
- `backend/app/services/dashboard.py`
- `backend/app/models.py`
- `prometheus/prometheus.yml`
- `frontend/src/pages/DashboardPage.tsx`

常见问题：
- 新部署导入业务库后日增长、月增长、趋势图为空
- [已解决] Prometheus 没有历史 block 或权限错误：迁移包支持 Prometheus 历史指标，安装前置脚本处理权限
- collector-worker 正常运行但没有写入指标
- 采集时间和页面显示时间不一致

## 5. 总览仪表盘

目标：提供客户第一眼能看懂的容量状态、风险、采集状态和增长摘要。

主要内容：
- 顶部指标卡：容量风险、Tower、集群、虚拟机、容量使用率
- SmartX ZBS 容量卡
- 采集状态
- 日增长最快 VM
- 集群容量列表
- 风险提示
- Scope 联动

相关文件：
- `frontend/src/pages/DashboardPage.tsx`
- `frontend/src/components/MetricCard.tsx`
- `frontend/src/components/StorageBar.tsx`
- `frontend/src/components/StatusPill.tsx`
- `frontend/src/styles/global.css`
- `backend/app/services/dashboard.py`

常见问题：
- [已解决] 顶部卡片宽度错位：容量风险、Tower、集群卡片按固定比例调整
- [已解决] 容量风险不够显眼：容量风险独立卡片前置展示
- [已解决] 容量风险按总容量汇总判断会掩盖单集群告警：改为任一集群使用率 >= 80% 即高风险，75%-80% 为需关注
- 日增长最快 VM 无数据
- [已解决] 报表页/增长区域在“日增长最快 VM”下新增“本日新建 VM”，并支持点击跳转到虚拟机页面
- [已解决] 增长量/增长率切换位置和居中问题：按钮居中并优化说明文字位置
- [已解决] Dashboard 单元测试中重复文本导致断言失败：测试改为容忍多处风险标题展示

## 6. 虚拟机容量页面

目标：按当前范围查看 VM 容量、卷信息和趋势。

主要内容：
- VM 列表
- VM 容量排序
- VM 详情和卷信息
- VM 身份口径：以 `tower_id + cluster_id + vm_id` 为准，`vm`/虚拟机名称只用于展示
- 存储策略、副本、EC 信息解析
- 单 VM 趋势图
- Scope 联动

相关文件：
- `frontend/src/pages/VmsPage.tsx`
- `frontend/src/components/TrendChart.tsx`
- `frontend/src/services/api.ts`
- `backend/app/services/dashboard.py`
- `backend/app/api/routes.py`

常见问题：
- 切换 Tower/集群后 VM 列表未刷新
- 趋势图没有数据
- VM 改名后历史趋势应连续；删除重建同名 VM 会因 `vm_id` 变化被视为新 VM
- [已解决] VM 改名后展示名称优先使用最新采集名称；历史数据继续按 `tower_id + cluster_id + vm_id` 绑定
- [已解决] VM 趋势查询需要同时带 `tower_id`、`cluster_id` 和 `vm_id`，避免跨 Tower/集群的极端重复 ID 混合
- 卷字段在不同 Tower API 版本下名称不一致
- 存储策略显示不完整或解析错误

## 7. 报表与存储预测

目标：给页面和客户文档提供容量预测、增长速率、风险判断和导出能力。

主要内容：
- 集群容量预测
- 7/30/90/365/720 天统计窗口
- 90 天预测窗口
- 容量增长速率，按 7 天平均增长速率提示
- 日增长、月增长 VM 榜单
- Word/Excel 导出
- 报表图表、目录、分页、页脚、字体和客户展示风格

相关文件：
- `backend/app/services/forecast.py`
- `backend/app/services/dashboard.py`
- `backend/app/services/report_export.py`
- `backend/app/api/routes.py`
- `frontend/src/pages/ReportsPage.tsx`
- `frontend/src/components/ClusterCapacityChart.tsx`
- `frontend/src/components/TrendChart.tsx`

常见问题：
- [已解决] 报表容量增长速率为空：按 7 天平均增长速率计算并显示提示
- [已解决] 导出的 Word/Excel 没数据：导出复用当前报表 scope 和月增长 TOP100 数据
- [已解决] 图表坐标轴不合理：报表图表按数据范围自动调整坐标轴
- [已解决] 生成时间慢 8 小时：导出文件名和文档时间按平台时区生成
- [已解决] 报表文件名范围、日期、天数不准确：文件名包含 scope、具体时间和统计天数
- [已解决] 增长率/增长量排序和高风险底纹标记不符合要求：导出表格支持排序，高风险 VM 标红
- [已解决] 月增长最快 VM 排除历史样本不足 30 天的 VM；刚部署没有满足 30 天样本时月增长榜为空
- [已解决] Word/Excel 导出的月增长 TOP VM 使用“样本满 30 天”过滤口径
- [已解决] Word/Excel 导出中的“上期容量”改为“期初容量”，并在说明或标题中标注统计窗口起止日期，例如 `2026年05月06日-2026年06月05日`
- [已解决] 报表页在“月增长最快 VM”下新增“本月新建 VM”，并支持点击跳转到虚拟机页面
- [已解决] 增长榜 TOP100 在增长量和增长率双排序合并后仍限制不超过 100 条

## 8. 数据迁移、导出与导入

目标：让测试服务器数据能迁移到另一套系统，支持补全缺失数据而不覆盖现有数据。

主要内容：
- 数据迁移包导出
- 业务库导入
- Prometheus 历史指标导入
- merge 模式：补全缺失数据
- overwrite 模式：覆盖当前数据
- 导入后提示重启数据服务

相关文件：
- `backend/app/services/data_migration.py`
- `backend/app/api/routes.py`
- `frontend/src/pages/ServicePage.tsx`
- `frontend/src/services/api.ts`

常见问题：
- [已解决] 只导出了业务库，没有历史指标：迁移包包含 Prometheus 历史指标目录
- [已解决] 导入后趋势、日增长、月增长为空：Prometheus 历史 block 支持补全导入，导入后重启数据服务生效
- [已解决] 重复导入时集群/Tower 是否覆盖不明确：默认 merge 模式按缺失数据补全，不覆盖当前已有 Tower/集群记录
- [已解决] 大文件上传触发 Request Entity Too Large：前端和服务端支持后台任务与上传进度展示
- [已解决] 导入后不重启服务导致页面仍显示旧数据：服务管理提供数据服务重启入口
- [已解决] 已取消“跳过历史指标换取迁移导出速度”的方向：Prometheus 历史指标必须保留，真正优化点是把运行产物搬离 `app/` 并增加精确进度
- [已解决] 数据迁移导入没有服务器留档目录：上传包、解压目录和 `task.json` 统一写入 `/data/exports/imports/<task_id>/`，并纳入空间清理扫描。
- [已解决] 数据迁移导入前先生成当前系统备份，备份成功后才继续导入；备份失败默认阻止导入，导入结果和任务中心显示备份路径。

## 9. 服务管理

目标：把与集群无关的运维能力集中到独立页面。

主要内容：
- 数据迁移
- 服务重启
- 平台升级
- 组件升级
- 升级历史
- 清理旧版本镜像
- 任务中心联动

相关文件：
- `frontend/src/pages/ServicePage.tsx`
- `frontend/src/components/AppLayout.tsx`
- `frontend/src/styles/global.css`
- `backend/app/services/system_control.py`
- `backend/app/services/upgrade.py`
- `backend/app/api/routes.py`

常见问题：
- 服务管理和集群选择无关，切换页面时左侧集群栏需要收起或居中
- 平台升级和升级后核验内容重复
- 预检查没有执行流程感
- [已解决] 清理镜像需要先扫描，清理时按扫描候选逐个删除未使用镜像
- 弹窗按钮大小、颜色和状态不统一

## 10. 在线升级与升级包

目标：支持通过 Web 上传离线升级包完成平台升级，并保护数据不被覆盖。

主要内容：
- 平台升级包上传
- manifest 校验
- sha256 校验
- 预检查
- 备份 `/data/backups/upgrade-版本-before-时间.tar.gz`
- `upgrade-runner` 执行升级
- `docker load`
- 写入 `docker-compose.upgrade.yml`
- 执行可选迁移脚本
- 重启服务和健康检查
- 手动回滚
- 升级历史和升级后核验

相关文件：
- `backend/app/services/upgrade.py`
- `backend/app/upgrade/runner.py`
- `scripts/build_upgrade_package.py`
- `docker-compose.upgrade.yml`
- `docs/upgrade-runner-lifecycle.md`
- `frontend/src/pages/ServicePage.tsx`

升级包结构：

```text
manifest.json
release-notes.md
images/web-api.tar
images/collector-worker.tar
images/frontend.tar
scripts/migrate.sh
```

常见问题：
- 旧 runner 无法升级自己
- 平台版本和 runner 版本生命周期不同
- compose 写死旧版本导致升级后页面仍显示旧版本
- 升级中重建 runner 会让 running 任务卡住
- 需要区分平台升级和组件升级
- [待处理] 基于历史升级问题重新设计全新的平台升级和组件升级模式，形成新的架构、状态机、包格式和回滚策略

## 11. 组件升级与 upgrade-runner 生命周期

目标：让升级中心自身作为独立组件管理，不和平台版本强绑定。

主要内容：
- 组件升级包上传
- 组件预检查
- 只允许升级 `upgrade-runner`
- runner 当前版本显示
- runner 手动升级流程
- 平台升级包一般不包含 runner

相关文件：
- `backend/app/services/upgrade.py`
- `backend/app/upgrade/runner.py`
- `backend/Dockerfile.upgrade`
- `docs/upgrade-runner-lifecycle.md`
- `frontend/src/pages/ServicePage.tsx`

常见问题：
- 平台升级包为什么不升级 runner
- runner 是否需要显示平台版本
- [待处理] runner 自升级需要重新设计，不应依赖旧 web-api 写只读路径，也不应在任务执行中重启自身导致状态断链
- runner 被重建时正在执行的升级任务如何恢复
- 以后需要升级 Prometheus 时是否属于平台升级包能力范围

## 12. 版本、发布与升级包生成

目标：保证版本来源统一，升级包可复现，发布流程清晰。

主要内容：
- 根目录 `VERSION`
- 镜像内置 `/app/VERSION`
- `SMARTX_APP_VERSION` 仅兜底
- Git tag
- dev/main 分支同步
- GitHub Actions 镜像构建
- 离线升级包生成
- 更新说明和 README

相关文件：
- `VERSION`
- `scripts/build_upgrade_package.py`
- `README.md`
- `README.zh-CN.md`
- `docs/releases/CHANGELOG.md`
- `.github/workflows/docker-images.yml`
- `docker-compose.release.yml`

常见问题：
- `v0.4.0`、`0.4.0`、`v0.4.0U1` 格式不统一
- 升级包和源码版本不一致
- tag、main、dev 指向不同提交
- GitHub Actions 没构建某个服务镜像

## 13. 前端 UI 与交互规范

目标：保证页面对客户展示统一、美观，操作反馈清晰。

主要内容：
- 主导航和二级导航
- 页面切换动画
- 任务中心
- 上传进度和速度
- 弹窗、按钮、状态图标
- 表格、卡片、滚动条
- 移动端适配
- 图标和标签页 logo

相关文件：
- `frontend/src/App.tsx`
- `frontend/src/components/AppLayout.tsx`
- `frontend/src/pages/*.tsx`
- `frontend/src/components/*.tsx`
- `frontend/src/styles/global.css`
- `frontend/public/favicon.svg`

常见问题：
- 按钮大小不一致
- 页面卡片嵌套卡片导致视觉复杂
- 弹窗和页面提示混用
- 选择文件控件不好看
- 下拉菜单点击空白处不收起
- 滚动条显示策略不统一

## 14. API 与数据模型

目标：统一接口入参、返回结构和前后端类型定义。

主要内容：
- FastAPI 路由
- Pydantic 请求/响应模型
- SQLite 表结构
- 前端 TypeScript 类型
- API client 封装
- 错误返回和 401 处理

相关文件：
- `backend/app/api/routes.py`
- `backend/app/models.py`
- `backend/app/db.py`
- `frontend/src/types.ts`
- `frontend/src/services/api.ts`
- `docs/api.md`

常见问题：
- 后端字段存在但前端类型没更新
- API 返回 UTC 时间，前端显示本地时间
- 错误信息没有透传到页面
- 大文件上传和普通 JSON 请求处理方式不同

## 建议排查顺序

后续逐个模块解决问题时，建议按下面顺序推进：

1. 基础平台与部署
2. 版本、发布与升级包生成
3. 在线升级与升级包
4. 服务管理
5. 数据迁移、导出与导入
6. 数据采集与历史指标
7. 报表与存储预测
8. 总览仪表盘
9. 虚拟机容量页面
10. Tower 与集群配置
11. 用户、认证与权限
12. 前端 UI 与交互规范
13. API 与数据模型
14. 组件升级与 upgrade-runner 生命周期

这个顺序的原因是：部署、版本和升级决定系统是否能稳定交付；数据迁移和采集决定页面是否有数据；报表和仪表盘建立在数据正确的基础上；最后再统一 UI、权限和接口细节。

## 每个模块的处理模板

处理任一模块时，建议固定按下面格式记录：

```text
模块：
目标：
当前问题：
影响范围：
涉及文件：
复现步骤：
根因判断：
修改方案：
验证命令：
是否需要升级包：
是否需要提交 dev：
是否需要同步 main/tag：
```

## 当前已知遗留点

- 远端 `dev` 当前仍有未提交的服务管理 UI 和 compose 时区改动。
- 前端全量测试存在既有失败：`._DashboardPage.test.tsx` AppleDouble 文件被 Vitest 扫描，Dashboard 测试里 `50.00%` 文本重复。
- 项目目录存在若干 macOS `._*` 文件和历史 `.bak.*` 文件，后续应单独清理和确认 `.gitignore`。
- 升级任务如果执行中重建 `upgrade-runner`，可能停留在 running 状态，需要补充任务恢复或超时失败机制。
- 后续若需要升级 Prometheus，需要明确是平台升级包支持 Prometheus 镜像，还是单独作为组件/基础服务升级。
