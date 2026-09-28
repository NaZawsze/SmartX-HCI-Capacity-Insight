# 设计：离线交付一键安装 + 一键升级（49-56）

状态：设计（2026-09-28）。**未实施。** 立项见 `task_plan.md` 第 56 项。
用户已定口径：**Q1 升级脚本走 API**；**Q2 安装镜像/包与升级镜像/包分开放**（具体形态由工程决定）；**Q4 初始管理员口令一律 `password`**。

## 1. 背景与缺口

| 现状 | 核实结果 |
| --- | --- |
| `pre_install.sh`（45 行） | **只建目录 + 设权限**，不加载镜像、不启动服务——是 OVA 部署钩子，不是"一键安装" |
| `docker-compose.offline.yml` | 已有 `pull_policy: never` → **离线交付是既定场景**，但无配套脚本 |
| 升级路径 | **只有 Web 升级中心上传 tar.gz**（需网络 + 手工操作）→ **离线/内网客户无路可走** |
| `docs/ova-delivery.md` | 有制品边界/安全/校验清单，**不含一键脚本与镜像目录规范** |

**本项同时是 `docs/upgrade-architecture-options.md` 方案 D（执行者与被升级对象解耦）的落地雏形**：脚本在平台之外执行，升级仍由 runner 走产品链路。

## 2. 口径

### 2.1 核心决策：安装交付「运行物料」，升级交付「版本单元」

| | 交付物 | 理由 |
| --- | --- | --- |
| **安装** | `images/*.tar`（镜像归档） | 首次安装没有"包"的概念，不需要 manifest；OVA 传输保真；可 SHA256 校验；客户机器镜像缓存可能已丢失，必须随交付物提供 |
| **升级** | `packages/*.tar.gz`（升级包 / 组件包） | **走 API（Q1=a），包就是 API 的输入单元**；包是版本身份载体（manifest + SHA256 + 能力声明）；松散镜像重组会丢失 manifest 与版本可审计性 |

### 2.2 升级脚本必须走升级中心 API（Q1=a）

**禁止**在脚本里 `docker load` + `compose up` 直接改环境。原因（不是流程洁癖，是产品正确性）：

| 直接改环境会绕过 | 后果 |
| --- | --- |
| 单飞守卫（US-23） | 并发升级，第二个任务在错误状态上执行 |
| post-cleanup | **旧环境不清理，残留累积（US-27 现场已复现）** |
| 任务历史 | 无留痕，现场无法取证 |
| 失败逃生门（US-25） | 卡死任务无产品化出路，**环境被永久锁死** |

API 是**本机 web-api**（`127.0.0.1:8000`），离线场景照样可用，因此走 API 不牺牲离线性。

### 2.3 `.env` 生成口径（回答 Q3：不是"都为空"）

| 类别 | 键 | 口径 |
| --- | --- | --- |
| **密钥** | `SMARTX_SECRET_KEY`、`SMARTX_CREDENTIAL_KEY` | **脚本生成 32+ 字节随机值**。绝不留空、绝不沿用模板占位符（`replace-with-…` 留着 = 密钥公开） |
| **路径/地址** | `SMARTX_DB_PATH`、`SMARTX_PROMETHEUS_URL`、`SMARTX_*_PATH` | 填固定正确默认值，不为空 |
| **账号** | `SMARTX_ADMIN_USER=admin`、`SMARTX_ADMIN_PASSWORD=password` | **按用户口径固定**；脚本与 README 明确提示首次登录后修改 |
| 业务阈值 | 采集周期、容量告警比例、升级产物清理 | 沿用 `.env.example` 默认值 |
| 可空 | `SMARTX_CORS_ORIGINS` | 内网可按需收紧 |

### 2.4 交付物版本纪律（与既有治理一致，不新增例外）

- 安装交付物内 **compose 必须落已发布 runner 基线 `v0.3.1`**（源码 compose 的 `v0.3.2` 属开发线，见 `docs/version-governance.md`）；
- 镜像 tag 与 `VERSION` / `RUNNER_VERSION` 一致，可审计；
- 升级包必须是 **Release 资产或 `.3` 门禁通过的候选包**，附 `.sha256`。

## 3. 交付目录规范

```text
smartx-capacity-insight-v0.5.3-offline/
├── README.md                       # 中文使用说明（总入口：安装/升级/故障排查）
├── install/                        # 首次部署物料
│   ├── install.sh                  # 一键安装入口
│   ├── images/
│   │   ├── web-api.tar
│   │   ├── collector-worker.tar
│   │   ├── frontend.tar
│   │   ├── upgrade-runner.tar
│   │   ├── prometheus.tar
│   │   └── SHA256SUMS              # 镜像校验
│   ├── project/                    # 平台部署文件（compose + 配置 + 校验后的 .env.example）
│   └── .env.template               # 生成 .env 的模板（含占位符，由脚本替换）
└── upgrade/                        # 离线升级物料
    ├── upgrade.sh                  # 一键升级入口
    └── packages/
        ├── smartx-capacity-insight-upgrade-v0.5.3.tar.gz
        ├── smartx-upgrade-runner-v0.3.2.tar.gz   # 可选：仅当需升级 runner 时
        └── SHA256SUMS
```

**分开放的硬约束**：`install/` 与 `upgrade/` **互不依赖**——客户可只拿 `install/`（全新装），也可只拿 `upgrade/`（已有现场升级）。升级脚本**不要求**客户有镜像目录。

## 4. `install.sh` 设计

**入口**：`bash install/install.sh [选项]`

| 选项 | 默认 | 说明 |
| --- | --- | --- |
| `--install-root` | `/data/smartx-storage-forecast` | 数据根目录 |
| `--admin-user` | `admin` | 管理员用户名 |
| `--admin-password` | `password` | 管理员口令（按用户口径固定默认） |
| `--tower-url` / `--tower-user` / `--tower-password` | 空 | 可选，写入 `.env` 便于首次配置 |
| `--yes` | — | 非交互（批量/涉密场景） |
| `--force-env` | — | 已存在 `.env` 时是否重新生成（**默认不覆盖**） |

**流程**（失败即停，不留半成品）：

1. **前置检查**：root 权限、`docker` / `docker compose` 可用、磁盘可用空间（≥ 镜像总和 ×3 + 10 GiB）、内存、端口 8000/8080/9090 未占用；
2. **幂等检查**：目标 `project/.env` 已存在 → 提示"已安装"并退出（除非 `--force-env`）；
3. **校验镜像**：`sha256sum -c images/SHA256SUMS`；
4. **加载镜像**：`docker load -i images/*.tar`，逐个确认 tag 与期望一致；
5. **生成 `.env`**：模板 + 随机密钥 + 固定默认值，`chmod 600`；
6. **准备目录**：复用 `pre_install.sh` 的目录/权限逻辑（含 prometheus uid/gid）；
7. **放置 project 文件**；
8. **启动**：`docker compose -f docker-compose.offline.yml -p smartx-hci-capacity-insight up -d`；
9. **健康检查**：轮询 `/api/system/health`（带超时，建议 180s），失败则打印诊断（容器状态 + 最近日志）并给出下一步；
10. **收尾输出**：访问 URL、版本、**首次登录后请立即修改管理员口令**的提示。

**失败处理**：任一步失败 → 打印已完成到哪一步 + 补救命令；**不自动删除已加载的镜像**（无害），但**不启动半套服务**。

## 5. `upgrade.sh` 设计

**入口**：`bash upgrade/upgrade.sh --package <path> [选项]`

| 选项 | 默认 | 说明 |
| --- | --- | --- |
| `--package` | 自动选 `packages/` 里唯一的平台包 | 要升级的包路径 |
| `--base-url` | `http://127.0.0.1:8000` | 平台 API（默认本机 = 离线） |
| `--admin-user` / `--admin-password` | `admin` / `password` | 从 `.env` 读取优先 |
| `--yes` | — | 非交互 |

**流程**（全程走产品链路）：

1. **前置检查**：root、平台可达且 `/api/system/health` 返回 `ok=true`、读出当前版本与 runner 版本；
2. **校验包**：`sha256sum -c` → 再跑**身份门禁**（版本/镜像 tag/SHA 一致）；
3. **登录**：`POST /api/auth/login` 取 token；
4. **上传**：`POST /api/admin/upgrade/upload`；
5. **预检查**：`POST /api/admin/upgrade/precheck/{tid}`，**逐项打印结果**；任一项 false → **停止并打印失败项**（不强行开始）；
6. **开始**：`POST /api/admin/upgrade/start/{tid}`；若返回 400（如"正在执行或需要恢复"）→ 打印提示并退出；
7. **轮询**：`GET .../status/{tid}`，打印进度；终态判定与 `chain_step2.sh` 一致；
8. **结果**：
   - 成功 → 打印新版本、runner 版本、post-cleanup 状态、**建议执行的 8 项自检要点**；
   - 失败 → **按状态给指引**（可重试 / 需逃生门 `recovery/fail` / 需查日志），**绝不自行改环境**；
9. **可选 `--with-runner <组件包>`**：升级完成后按需再做 runner 组件升级（**默认不做**——顺序铁律：先平台后 runner）。

**安全约束（脚本级）**：脚本**只调 API**，不执行任何 `docker load` / `compose up` / 文件删除。

## 6. 安全边界

- 交付物**不含** `.env`、SQLite、Prometheus 数据、备份、Tower 凭据、token（沿用 `docs/ova-delivery.md` 制品边界，并纳入 `scripts/verify_release_docs_safe.py` 扫描）；
- `.env` 由脚本在目标机生成，`0600 root:root`；
- 随机密钥不打印到日志之外的任何文件，不写进交付物；
- 脚本以 root 运行但**只操作自己的交付目录与平台标准路径**，不做清理宿主其它内容（对齐 `.12` 演练纪律：宿主不做无关变更）。

## 7. 测试计划

| # | 场景 | 通过标准 |
| --- | --- | --- |
| 1 | **干净 VM 全新安装** | `install.sh` 一次跑通；`/api/system/health` 全绿；五容器起；UI 200；随机密钥已写入且非占位符 |
| 2 | **安装幂等** | 已安装再跑一次 → 提示已安装并退出，**不覆盖 `.env`、不重建容器** |
| 3 | **镜像损坏** | 篡改 `images/*.tar` → SHA 校验失败并中止，**不启动服务** |
| 4 | **离线升级** | 断网/屏蔽 DockerHub，`upgrade.sh` 跑通；8 项验收全过；DB 计数不变 |
| 5 | **升级预检查失败** | 构造不匹配包 → 脚本停在预检查并打印失败项，**不调用 start** |
| 6 | **重复升级** | 已有任务执行中 → 脚本拿到 400 并给出提示，**不排队** |
| 7 | **文档对照** | 说明书每条命令在干净 VM 上实跑通过 |

**执行环境**：`.3` 做脚本静态与流程演练；**至少一次在干净 VM 形态实测**（无历史数据的全新安装 + 离线升级），因为这正是本需求的交付场景，不能只在有历史的机器上验。

## 8. 回滚

| 场景 | 回滚方式 |
| --- | --- |
| 安装失败 | 全新安装无回滚概念。卸载 = 停服务 + 删除数据目录，**说明书明确写出并警告数据不可恢复** |
| 升级失败 | **失败自动回滚保留**（US-29 决定）；自动回滚未发生时用逃生门（US-25）+ 再跑一次升级让 post-cleanup 收尾（US-27 正在加强） |
| 脚本自身有 bug | 脚本不改动平台代码，可直接替换重跑；已升级的平台不受影响 |

## 9. 边界（本次不做）

- **不做**自动回滚架构（US-29 已决定放弃人工回滚；本项沿用失败自动回滚）
- **不做**安装期的 Tower 连通性验证（配置在 Web 界面完成，脚本只写 `.env`）
- **不做**多机/集群部署（单节点 on-prem 场景）
- **不做**无人值守自动升级（离线客户也由人发起，保留人工确认环节）
- 交付物 compose 落 `v0.3.1` 基线，**不落**源码 compose 的 `v0.3.2`

## 10. 关联

- 立项：`task_plan.md` 第 56 项
- 制品边界与安全：`docs/ova-delivery.md`；交付文档：`docs/deployment.md`、`docs/upgrade-chain.md`
- 版本治理：`docs/version-governance.md`（交付物 compose 落已发布基线）
- 架构定位：`docs/upgrade-architecture-options.md` §3 长期方向（方案 D）
- 升级链路既有约束：`docs/upgrade-strategy-issues.md` US-23/25/26/27/29
