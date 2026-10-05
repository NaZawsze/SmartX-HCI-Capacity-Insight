# SmartX HCI Capacity Insight · 离线交付包

本包用于在**无外网**的环境完成首次安装与后续升级。

- 首次安装 → 使用 `install/`
- 版本升级 → 使用 `upgrade/`

> `install/` 与 `upgrade/` **互不依赖**：只做新装可以只拿 `install/`；只做升级可以只拿 `upgrade/`。

---

## 1. 前置条件

| 项目 | 要求 |
| --- | --- |
| 操作系统 | Linux（已验证 openEuler、Debian 13、CentOS/RHEL 8+ 系的常见发行版） |
| 权限 | **必须 root** |
| Docker | Engine 20.10+，且已安装 Compose V2 插件（`docker compose version` 有输出） |
| CPU / 内存 | 建议 4 核 / 8 GiB 以上 |
| 磁盘 | 交付包 3 倍 + 10 GiB 余量（安装脚本会自动检查并给出具体数字） |
| 空闲端口 | **8000**（API）、**8080**（Web 界面）、**9090**（Prometheus）必须空闲 |
| 网络 | **不需要外网**。镜像随包提供，不会去仓库拉取 |

安装脚本不修改宿主机上与本平台无关的内容。

---

## 2. 目录结构

```
smartx-capacity-insight-v0.5.4-offline/
├── README.md                     本文件
├── install/                      首次部署
│   ├── install.sh                一键安装入口
│   ├── compose-guard.sh          compose 变体守卫（防误用变体导致服务中断，见 §9.1）
│   ├── images/                   5 个镜像归档
│   │   ├── web-api.tar
│   │   ├── collector-worker.tar
│   │   ├── frontend.tar
│   │   ├── upgrade-runner.tar
│   │   ├── prometheus.tar
│   │   └── SHA256SUMS            镜像校验清单
│   ├── .env.template             .env 模板（密钥位由脚本生成随机值）
│   └── project/                  平台部署文件
│       ├── docker-compose.offline.yml
│       ├── prometheus/prometheus.yml
│       └── pre_install.sh
└── upgrade/                      离线升级
    ├── upgrade.sh                一键升级入口
    └── packages/
        ├── smartx-capacity-insight-upgrade-<版本>.tar.gz
        ├── SHA256SUMS
        └── *.sha256
    # packages/ 里有什么就用什么：本交付批次的交付范围（是否含 runner 组件包）
    # 以随包交付说明为准——不在本批次交付范围的组件包不会出现在这里
```

**请不要修改交付目录内的任何文件**——`install.sh` 与 `upgrade.sh` 每次运行前都会校验 SHA256。

---

## 3. 首次安装

### 3.1 最简用法

```bash
tar -xzf smartx-capacity-insight-v0.5.4-offline.tar.gz
cd smartx-capacity-insight-v0.5.4-offline
sudo bash install/install.sh
```

脚本会逐步打印进度，任一步失败会停下并给出补救命令。

不确定参数时随时查看完整帮助：

```bash
bash install/install.sh --help
bash upgrade/upgrade.sh --help
```

### 3.2 常用选项

```bash
sudo bash install/install.sh \
  --install-root /data/smartx-storage-forecast \
  --admin-user admin \
  --admin-password '你的初始口令' \
  --tower-url https://tower.example.com \
  --yes
```

| 选项 | 默认值 | 说明 |
| --- | --- | --- |
| `--install-root <路径>` | `/data/smartx-storage-forecast` | 数据根目录。**改这个值时 compose 里的绝对路径会自动改写**，请用不含 `&`、`|`、`\` 等特殊字符的路径 |
| `--admin-user` | `admin` | 管理员用户名 |
| `--admin-password` | `password` | 管理员初始口令 |
| `--tower-url` / `--tower-user` / `--tower-password` | 空 | 可选，写入 `.env` 便于首次配置（也可装完后在 Web 界面配） |
| `--health-timeout <秒>` | `180` | 健康检查等待上限 |
| `--yes` | — | 非交互，跳过启动前确认 |
| `--force-env` | — | 重新生成 `.env`（默认**不覆盖**已存在的） |
| `--force-compose-switch` | 拦截 | `.env` 记录的 compose 变体与本脚本不一致时默认**拒绝启动**（防 recreate 中断服务）；确认要换变体才加（会先完整停机，造成计划内中断） |

### 3.3 安装脚本做了什么

1. 前置检查（root / docker / 磁盘 / 端口）
2. 幂等检查：已安装则提示并退出，**不覆盖 `.env`、不重建容器**
3. 校验镜像 SHA256
4. `docker load` 加载镜像，并核对 compose 需要的 tag 是否齐备
5. 准备数据目录与权限
6. 放置 compose 与 Prometheus 配置
7. 生成 `.env`：`0600 root:root`，**两把密钥随机生成且互不相同**
8. `docker compose up -d`
9. 轮询健康检查
10. 输出访问地址与版本

**失败即停**：任何一步失败都不会启动半套服务，也不会删除已加载的镜像（镜像留着无害，重跑即可）。

### 3.4 安装完成后

- Web 界面：浏览器打开 `http://<本机IP>:8080`
- 管理员：安装时指定的账号（默认 `admin` / `password`）
- **请立即修改管理员口令**（见第 8 节）

---

## 4. 离线升级

```bash
cd smartx-capacity-insight-v0.5.4-offline
sudo bash upgrade/upgrade.sh
```

`packages/` 里只有一个平台升级包时会被自动选中；多个时用 `--package` 指定。

```bash
# 指定包
sudo bash upgrade/upgrade.sh --package upgrade/packages/<随包提供的平台升级包名>.tar.gz --yes

# 平台升级成功之后，若本批次交付了 runner 组件包（以随包交付说明为准），
# 连带升级 runner 组件
sudo bash upgrade/upgrade.sh --with-runner upgrade/packages/<随包提供的 runner 组件包名>.tar.gz --yes
```

> **在哪个目录执行都行。** `--package` / `--with-runner` 的相对路径按**脚本自身位置**
> 解析（不是按你当前所在的目录），所以在 `/root`、`/tmp` 等任意目录下执行上面两条命令
> 都能正确找到包；写绝对路径当然也可以。

### 4.1 升级脚本做了什么

1. 访问本机 `http://127.0.0.1:8000/api/system/health`，读出当前平台与 runner 版本
2. 校验包 SHA256
3. 登录取令牌
4. 上传升级包
5. **预检查并逐项打印结果**——任一项不通过就停下，**不会调用 start**
6. 确认后开始升级
7. 轮询任务直到终态
8. 输出结果与自检建议

### 4.2 重要：为什么升级必须走脚本，而不是自己 `docker load`

升级脚本**只调用升级中心 API，不直接改环境**。这是有意的：

| 自己改环境会绕过 | 后果 |
| --- | --- |
| 并发守卫 | 同时发起两个升级，第二个在错误状态上执行 |
| 升级后清理 | 旧目录残留，长期累积 |
| 任务历史 | 没有留痕，现场无法取证 |
| 失败恢复入口 | 卡住的任务没有产品化出路，环境被锁死 |

本机 API 不需要外网，所以走 API **不会牺牲离线性**。

### 4.3 升级顺序

**默认只升平台。** runner 组件升级请在平台升级**成功之后**单独发起（即上面的 `--with-runner`）。

顺序颠倒（旧平台的 web-api 会停掉刚启动的新 runner）可能导致升级中断、runner 心跳丢失。

### 4.4 升级脚本选项

| 选项 | 默认值 | 说明 |
| --- | --- | --- |
| `--package <包路径>` | 自动选 `packages/` 里唯一的平台包 | 要升级的包 |
| `--with-runner <组件包>` | 不做 | 平台升级成功后再升级 runner 组件 |
| `--base-url <地址>` | `http://127.0.0.1:8000` | 平台 API 地址（默认本机）。排障时可用它指向别处验证连通性 |
| `--admin-user` / `--admin-password` | 读 `.env`，回退 `admin` / `password` | 管理员凭据 |
| `--env-file <路径>` | `/data/smartx-storage-forecast/project/.env` | 读取凭据用的 `.env` 位置 |
| `--poll-timeout <秒>` | `1800` | 等待升级完成的超时 |
| `--allow-same-version` | 拦截 | 目标版本与当前版本相同时（同版本重装，恢复手段、服务会中断）默认**拦截**并给指引；确认要重装才加此参数 |
| `--yes` | — | 非交互，跳过确认 |

---

## 5. 8 项自检

升级完成后建议逐项确认（前 4 项脚本已自动检查）：

```bash
# 1) 健康检查：ok=true，directories/database/prometheus 三项均为 true
curl -s http://127.0.0.1:8000/api/system/health

# 2) 五个容器均为 Up
docker ps --format '{{.Names}}\t{{.Status}}' | grep smartx-hci-capacity-insight

# 3) Web 界面可登录
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8080

# 4) 升级中心无失败任务
curl -s http://127.0.0.1:8000/api/admin/upgrade/history -H "Authorization: Bearer <token>"

# 5) 旧环境目录已清理（以下应全部"不存在"）
ls -d /opt/smartx-storage-forecast /data/upgrades 2>&1

# 6) 数据库完整
docker exec <web-api 容器名> python -c "import sqlite3;print(sqlite3.connect('/data/smartx.db').execute('PRAGMA integrity_check').fetchone())"

# 7) 业务数据计数未变（升级不应改动数据）
docker exec <web-api 容器名> python -c "import sqlite3;c=sqlite3.connect('/data/smartx.db');print('towers=',c.execute('SELECT COUNT(*) FROM towers').fetchone()[0])"

# 8) 升级后自动采集可触发
# Web 界面 → 服务 → 任务 → 手动触发一次采集，确认成功
```

---

## 6. 常见失败与处理

### 6.1 安装

| 现象 | 原因与处理 |
| --- | --- |
| `必须以 root 运行` | 用 `sudo bash install/install.sh` |
| `未找到 docker` / `docker 守护进程未运行` | 先装 Docker 并 `systemctl start docker` |
| `磁盘空间不足` | 按提示的数字清理，或用 `--install-root` 换大容量挂载点 |
| `端口被占用` | 停掉占用 8000/8080/9090 的服务，或改 compose 的 `ports` 映射 |
| `镜像 SHA256 校验未通过` | 交付包传输损坏，**服务未启动**，重新传输即可 |
| `加载镜像失败` | 手工执行 `docker load -i install/images/<name>.tar` 看具体报错 |
| `镜像 tag 与 compose 声明不匹配` | 交付包不完整，确认 `images/` 下 5 个 tar 都在 |
| `服务未在超时内达到健康状态` | 脚本会打印容器状态与 web-api 日志；常见是磁盘不足、端口冲突、目录权限 |
| `已检测到安装` | 幂等保护。要重新生成 `.env` 用 `--force-env`；要重装请先看第 7 节卸载 |

### 6.2 升级

| 现象 | 原因与处理 |
| --- | --- |
| `平台不可达或健康检查失败` | 平台没在运行：`docker ps \| grep web-api` |
| `登录失败` | 管理员口令已在 Web 界面改过，用 `--admin-user` / `--admin-password` |
| `未找到升级包` | 把平台升级包放进 `upgrade/packages/`，或用 `--package` 指定 |
| `预检查未通过` | 按打印的失败项处理；**环境未被改动** |
| `已有升级任务在执行或等待恢复` | 并发守卫正常工作。到 Web 界面「服务 → 升级中心」先处理那个任务 |
| 终态 `failed` | 早期失败通常**未改动环境**（如镜像校验失败），修正后可直接重跑 |
| 终态 `recovery_required` | 需要人工确认。到 Web 界面选「继续执行」或「标记失败」 |
| 终态 `rolled_back` / `rollback_failed` | 平台已尝试自动回滚，查任务日志确认结果 |
| 升级成功但旧目录还在 | **再跑一次完整升级**，由升级后清理收尾 |

---

## 7. 卸载

> ⚠️ **以下操作不可恢复，业务数据会被永久删除。**

```bash
# 1) 停止并删除容器与网络
cd /data/smartx-storage-forecast/project
docker compose -f docker-compose.offline.yml -p smartx-hci-capacity-insight down

# 2) 删除数据目录（含 SQLite 业务库、Prometheus 历史、导出文件、备份）
rm -rf /data/smartx-storage-forecast
```

请在执行第 2 步前确认：是否需要先备份业务库与报表导出物。

---

## 8. 安全建议

1. **首次登录后立即修改管理员口令**。默认 `admin` / `password` 是公开的，任何能访问 8000 端口的人都能登录。
2. `.env` 含两把随机密钥（`SMARTX_SECRET_KEY`、`SMARTX_CREDENTIAL_KEY`），权限 `0600 root:root`：
   - 不要复制给他人
   - 不要提交到代码仓库
   - 迁移或恢复时必须与数据库**成对**迁移（凭据密钥丢失会导致已存凭据无法解密）
3. `8080`（Web 界面）与 `8000`（API）默认监听所有网卡。若只需内网访问，建议在防火墙上限制来源。
4. Prometheus 的 `9090` 仅供内部监控使用，**不建议**对外暴露。
5. 交付包本身不含任何现场数据（无 `.env`、无数据库、无 Tower 凭据），可安全存放与传递。

---

## 9. 常用运维命令

```bash
# 查看容器状态
docker compose -f /data/smartx-storage-forecast/project/docker-compose.offline.yml \
               -p smartx-hci-capacity-insight ps

# 跟踪 web-api 日志
docker compose -f /data/smartx-storage-forecast/project/docker-compose.offline.yml \
               -p smartx-hci-capacity-insight logs -f web-api

# 停止 / 启动
docker compose -f /data/smartx-storage-forecast/project/docker-compose.offline.yml \
               -p smartx-hci-capacity-insight stop
docker compose -f /data/smartx-storage-forecast/project/docker-compose.offline.yml \
               -p smartx-hci-capacity-insight start

# 健康检查
curl -s http://127.0.0.1:8000/api/system/health
```

---

## 9.0 数据迁移与恢复密钥（Web 界面 · 服务管理 → 数据迁移）

三个导出入口（按钮在页面右上角），语义各不相同：

| 入口 | 包内容 | 需要恢复密钥？ | 适用 |
| --- | --- | --- | --- |
| **导出迁移包** | Tower 配置 + 库内监测数据 + 全部历史指标（**完整备份**） | **需要** | 备份 / 整机搬迁 |
| **仅导出存储监测数据** | 只导监测业务数据与历史指标（不含 Tower 配置） | 不需要 | 把数据搬到已配好 Tower 的新环境 |
| **仅导出 Tower 配置** | 只导 Tower 与集群清单（不含历史数据） | 需要 | 让新环境快速接入同一批 Tower |

- **恢复密钥**：迁移包里的 Tower 密码是加密的，恢复时必须配上导出时**单独下载**的
  恢复密钥（`.env`，需验证平台密码）。**迁移包与密钥必须成对保存**，缺一则 Tower
  凭据无法解密（可在 Web 界面重新输入密码补救）。
- **导入**：数据迁移页上传包 → 选导入方式 → 导入 → 服务重启。「合并数据」只补缺的、
  最安全；「整库替换」会清空现有数据（数据类导入包不支持此模式，后端直接拒绝）。
- 导入完成后需执行「服务重启」新数据才完全生效。

## 9.1 compose 变体守卫（US-37）

平台部署目录里有 **4 份 compose 变体**（`docker-compose.yml` /
`docker-compose.offline.yml` / `.release.yml` / `.upgrade.yml`），
它们**共用同一个 project 名**，但服务定义不同。

**如果你用错变体执行 `docker compose up/down/restart`，Docker 会判定「配置变了」
并 recreate 容器，旧容器被 SIGKILL（`exit 137`）——服务会中断。**

平台为此做了防护：

- **安装时**会把实际生效的 compose 记入 `/data/smartx-storage-forecast/project/.env`
  的 `SMARTX_COMPOSE_FILE_ACTIVE`；
- **任何 compose 操作前**可以用守卫自查：

```bash
# 返回 0 = 你用的就是生效的那份，可以继续
# 返回 2 = 变体不一致，会 recreate 掉服务，按提示选一条路
bash /data/smartx-storage-forecast/project/compose-guard.sh check \
     /data/smartx-storage-forecast/project/.env \
     <你打算用的-compose文件名> \
     smartx-hci-capacity-insight

# 只看当前实例用的是哪份
bash /data/smartx-storage-forecast/project/compose-guard.sh show \
     /data/smartx-storage-forecast/project/.env
```

**日常运维请用平台升级中心的升级流程**，它已把「预检查 → 执行 → 收尾」串起来，
不需要手工敲 `docker compose`。确需手工操作时，**先过守卫**。

若守卫报「无法判定」，说明这是旧环境、没有标记：重跑一次 `install/install.sh` 即可补上
（它会从运行中容器的标签读取真实使用的变体，不会乱猜）。

## 10. 排障速查

| 症状 | 先看哪里 |
| --- | --- |
| 页面打不开 | `docker ps` 确认 5 个容器都 Up；`curl 127.0.0.1:8080` |
| 登录失败 | 确认用的是安装时设置的账号口令；看 web-api 日志 |
| 页面提示数据过期 | 到「服务 → 任务」手动触发一次采集；检查 CloudTower 连通性 |
| 升级相关任何问题 | Web 界面「服务 → 升级中心」看任务详情、步骤与日志 |
| 接口返回 503 且提示数据库忙 | upgrade-runner 刚完成组件升级，稍等几十秒重试即可 |
| 磁盘告警 | `du -sh /data/smartx-storage-forecast/*`；备份与升级包可清理 |
