# v0.5.5 集中升级架构收口设计

- 日期：2026-10-21
- 状态：**推荐方案，待用户评审；未实施，不代表发布承诺**
- 目标：在一个平台版本批次内完成升级执行器的生命周期隔离、可恢复性、版本能力契约和迁移执行边界，避免把同一架构整改拆成多个平台版本。
- 关联：Phase 85、pending #102；初始 #90 方案见 [2026-10-14 迁移执行者解耦设计](2026-10-14-migration-executor-decoupling-design.md)，本方案评审通过后替代其实施口径。

## 1. 决策摘要

推荐把 v0.5.5 定为一次**集中架构版本**：同一台主机、同一 Docker daemon 上，把 `upgrade-runner` 从平台 Compose project 拆到自己的 Compose project；同时完成 runner 独立启动/自换/救援、能力和镜像身份校验、数据库迁移单一来源与执行者归一。这里的“独立 project”不是新主机、新业务微服务或 Kubernetes，只是 runner 有独立的 Compose 生命周期。

保持现有职责：web-api 接收包、鉴权、预检查、创建任务和展示结果；runner 是唯一升级执行者，负责平台服务切换、受控 schema migration、健康检查和回滚。平台升级计划不能操作 runner；runner 组件升级由 runner 自换。平台 Compose 不再声明 runner 服务。

0.5.4 候选的已完成验收作为冻结基线保留，不为塞入结构改动而重开 0.5.4。0.5.5 作为一个交付批次可以包含平台包和 runner 组件包，并在该批次中按依赖先升级 runner、再升级平台；这是一个平台版本，不代表把 runner 更新强行并进正在执行它的平台包。

## 2. 为什么选择独立 Compose project

当前 runner 已是独立容器，常规平台升级也通过服务清单排除 runner；因此仅仅“换一个 project 名”不能解决 runner 动作能力不足、镜像内容与版本号不一致、runner 缺失后的救援问题。

但 runner 仍被平台 Compose 文件和平台 Compose 生命周期管理。历史上旧 web-api 的 bootstrap 曾在同一 project 内停掉刚启动的新 runner；handoff 重入、runner 退出后无法恢复、运行时 Compose 与交付 Compose 漂移也都暴露出生命周期耦合。把 runner project 分开，可从结构上阻止平台级 `up/stop/down` 误操作 runner，并让平台服务整体重建时升级执行器仍在场。

采用独立 project 的前提是同时拆开两种身份：

- `platform_compose_project`：runner 操作平台服务时使用。
- `runner_compose_project`：runner 自换、启动和恢复自身时使用。

不得再让同一个 `SMARTX_COMPOSE_PROJECT_NAME` 同时表示这两个目标。平台网络要成为两份 Compose 配置共同使用的稳定 external network；runner 不依赖跨 project 的 `depends_on`，可用性通过重试和健康探测确认。runner 自身的 Compose 文件与状态文件放在平台项目文件同步不会覆盖的位置。

## 3. 目标运行形态

```text
平台 Compose project: smartx-hci-capacity-insight
  web-api / collector-worker / frontend / prometheus

runner Compose project: smartx-upgrade-runner
  upgrade-runner
  ├─ Docker socket：执行受控容器操作
  ├─ upgrades / backups：读写升级任务和备份
  ├─ platform project files：按需读取，不由平台文件同步覆盖 runner 配置
  └─ stable external network：检查目标平台健康状态
```

runner 仍与平台共享必要的数据目录和宿主机 Docker daemon，但拥有单独的 Compose 文件、project 标签、网络连接声明、启动/停止入口和健康状态。平台服务列表、平台包镜像清单、平台 `compose.apply` 与平台回滚都不得包含 runner。

## 4. 升级与迁移契约

1. **单一执行者**：新平台包仍由当前 runner 执行。平台服务停止/重建时，runner 保持运行并独立写入 task 文件；web-api 只投影任务状态。
2. **稳定通用动作**：优先使用已发布并经能力门禁确认的通用动作（如受限脚本沙箱），平台包携带受校验的迁移计划/脚本。普通 schema 变更不新增 runner 专用动作；确需新执行能力时，只发布一次兼容的 runner 组件版本，并由能力契约拒绝不支持的组合。
3. **schema 单一来源**：`migrations/registry.json` 是版本化 schema 变更的唯一声明源。打包时由 registry 生成受校验的迁移载荷；删除与它重复的 `_ensure_column` 版本副本。新库初始化和旧版历史补齐需明确分层，不能继续双份维护同一变更。
4. **单次、有序执行**：runner 在备份后、目标平台服务启动前执行 migration；执行前让可能写该 SQLite 的平台服务进入受控停写窗口，执行期间使用数据库锁/事务和 migration ledger。失败时不得启动新平台；旧平台恢复必须能读取 expand-only 后的 schema。
5. **启动职责**：web-api 与 collector-worker 的通用 `initialize()` 不得各自竞争执行同一批版本迁移。服务启动只验证要求的 schema 已存在；需要修复时明确报错并让升级任务/救援流程处理。
6. **兼容和回滚**：迁移仅允许 expand-only；有破坏性的 schema 变更拆成兼容窗口内的 expand/contract 两次发布。平台失败回滚旧镜像时，旧代码必须能在新 schema 上运行。

## 5. runner 身份、自换与救援

- runner 组件包、镜像归档和运行容器必须核对版本、构建标识和 SHA256/digest；仅有 `RUNNER_VERSION` 不足以证明内容一致。同一版本号、不同镜像内容必须在构建门禁或预检查阶段拒绝。
- `required_capabilities` 对应实际 runner 镜像的能力清单，不从平台源码推断。平台包声明能力与版本下限；runner 能力不满足时，升级前明确拒绝并给出组件升级路径。
- runner 自换采用新旧实例短暂并行的交接：新 runner 启动后先通过版本、能力、挂载、网络、心跳和任务租约检查，再取得唯一执行租约；全部满足后才停止旧实例。任何检查失败都保留旧 runner。
- handoff 必须幂等。进程重启后不能再次无限调度 handoff，也不能让单飞守卫永久锁死。
- 交付包提供**不依赖 web-api**的 runner 恢复入口（本机 CLI/恢复脚本），从本地已校验组件包重建独立 runner project。默认只检查并打印动作；显式 apply 才改变现场。它用于 runner 缺失、停止或心跳失效时恢复执行器，不替代正常产品升级入口。
- 心跳、容器 healthcheck、升级预检查和恢复 CLI 使用同一套版本感知健康判据；交付 Compose、运行时 Compose 生成器和组件升级写回保持一致。

## 6. 一次性迁移与失败保护

迁移从现有同 project 状态切到独立 runner project 时，由现有 runner 执行桥接：准备 runner 专用 Compose 配置和 external network → 启动目标 runner → 验证目标 runner 身份/心跳/挂载/网络 → 原子转移执行租约 → 停止旧 runner。只有新 runner 已确认能接管后才允许移除旧实例。

若目标 runner 未通过任一验证，旧 runner 保持原样，平台服务不开始升级。若迁移完成后平台升级失败，回滚只切回平台镜像；runner 保持独立 project 和可用状态。若 runner 自身升级失败，按旧镜像和旧 runner Compose 配置回切。升级记录保留两个 project 名、runner 两端身份与切换阶段，禁止仅凭“容器 Up”判成功。

## 7. v0.5.5 交付范围与边界

**必须同批完成**：独立 runner project；安装/升级/回滚/组件自换/runner 恢复入口全链路；两个 Compose project 的网络和路径契约；能力与镜像内容身份门禁；registry 单一来源迁移；handoff 幂等；缺失 runner、旧 runner、坏网络、坏挂载和升级中断的失败保护；客户操作说明。

**不纳入本次**：Kubernetes、拆分业务微服务、整机 A/B 双槽、无证据的大型 reconcile 控制器。它们不解决本次 runner 生命周期问题，且会扩大客户现场的升级前置条件。

平台版本仍为 0.5.5；runner 需按版本治理提升组件版本，但具体版本号由实现方案和交付物决定。不得为了少一个包而把 runner 镜像塞入正在执行的平台升级包。

## 8. 验收与测试计划

本任务触及 runner、Compose、安装/升级脚本和数据库迁移，按 `docs/test-architecture.md` 的 P3 定稿套餐执行；`.3` 只开发/构建，全部 L0–L6 证据来自 `.14`/`.12`。最终候选必须从本批真实平台包和 runner 包 SHA 取证。

不可缺少的验收格：

1. 全新安装后，平台容器和 runner 分属两个 Compose project；五个容器均健康，平台 Compose 变更不改 runner 容器 ID。
2. 从当前 v0.5.4 候选配对的 runner 升级到新 runner，再升 v0.5.5；覆盖 Web 与 CLI 入口、连续重启和最终 8 项验收。
3. 平台 project 全部服务 stop/up/down 的隔离验证：runner 保持运行，平台恢复后 runner 可继续执行健康检查。测试不得使用手工覆盖 Compose 模拟产品路径。
4. 迁移执行前后、每次服务重建后和最终状态，SQLite 完整性、外键检查和业务数据指纹全 PASS；Prometheus 历史数据与 Tower 凭据配对不变。
5. 负向测试：目标 runner 启动失败、心跳缺失、能力不符、digest 不符、网络/挂载错误、重复 handoff、断电/进程重启、旧 runner 不支持迁移。每种情形都必须保持旧执行器可用或进入明确可执行的恢复路径。
6. runner 缺失/停止时，通过离线恢复入口在无 web-api 的情况下恢复；恢复后重走升级预检查并完成一次真实任务。
7. L5 场景 B/C 回滚通过；平台回滚不降级 runner，runner 回滚不触碰平台业务数据。
8. L6 站点验收和证据归档完成；每个链路格记录包 SHA、镜像 digest、runner 能力探针、任务 ID 和数据比较结果。

若 `.12`/`.14` 任一关键验收格失败，不能以“其他场景通过”宣布 0.5.5 架构完成；修复后重打候选并按测试架构重新执行受影响的下游层，发布动作仍需用户明确指令。

## 9. 回滚

- **开发回滚**：各子项独立提交；runner 外置迁移可通过保留的旧 Compose 配置和镜像回退，平台代码回滚使用 `git revert`，不删除业务目录或数据。
- **现场迁移回滚**：只在目标 runner 尚未接管任务租约时回退到旧 runner；接管后必须先收敛唯一租约，再切回旧实例。旧/新 runner 不得并发执行任务。
- **schema 回滚**：不逆向删除 expand-only 列/表；恢复旧平台镜像并保留已扩展 schema。若完整备份恢复被触发，必须遵循 `docs/backup-recovery.md` 的 SQLite、配套 `.env` 与 Prometheus 成对核验。

## 10. 实施前必须解决的设计矛盾

初始 #90 验收写的是「v0.5.4 + runner v0.3.1 直升 v0.5.5」。这与当前 v0.5.4 批次规则（平台迁移要求先安装本批 runner 组件）不一致，不能直接作为测试基线。实施计划必须从 `docs/upgrade-chain.md` 和最终发布 ledger 读取真实的 v0.5.4/runner 配对及 SHA；若要支持 v0.5.3/runner v0.3.1 直达，也要单独列为兼容格并实测，不能用版本号推断能力。

