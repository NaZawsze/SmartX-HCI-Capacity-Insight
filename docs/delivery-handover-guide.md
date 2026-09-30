# 交付手册：从打包到客户安装升级

> 面向**交付负责人**（我们的人）：怎么打出交付物、怎么交给客户、客户拿到后怎么用。
> 客户自己看的是 `offline-delivery/README.md`（包内文档），**不需要**读本文件。

## 1. 全景：三个角色、三类文件

先把最容易混的三件事分开：

| 谁 | 在哪干活 | 用什么 |
| --- | --- | --- |
| **我们（交付方）** | 打包机 | `ops/package.sh` → 产出 `ops/packages/latest/` |
| **我们（运维/开发）** | 开发机/测试机 | `ops/install.sh`、`ops/upgrade.sh`（需要先有交付物料） |
| **客户** | 客户机器 | **交付目录里的** `install/install.sh`、`upgrade/upgrade.sh` |

**最重要的一条**：`ops/` 里的脚本**不进交付目录**。客户拿到的永远是
`offline-delivery/` 里的 `install/install.sh` 与 `upgrade/upgrade.sh`。
两者源码相同（前者薄封装转发），但**客户不需要仓库**。

## 2. 第一步：打包（在打包机上）

### 2.1 前置

```bash
git clone https://github.com/NaZawsze/SmartX-HCI-Capacity-Insight.git
cd SmartX-HCI-Capacity-Insight
bash ops/check-deps.sh        # 体检：缺什么给什么装法
```

`check-deps.sh` 需要：Linux、Docker + Compose V2、Python 3.11+、git、约 20 GB 可用磁盘。
**另外必须有一个已发布的 runner 基线镜像**（默认 `…-upgrade-runner:v0.3.1`）——
它是发布产物、不在仓库里。缺了脚本会明确告诉你三条补法，不会静默失败。

### 2.2 执行

```bash
bash ops/package.sh                  # 默认打 main（发布线）
bash ops/package.sh --branch dev2    # 打开发线
```

`package.sh` 会：同步代码 → 体检 → 版本一致性预检 → 构建平台包与 runner 组件包 →
跑三道门禁（identity / runner 交付一致性 / 敏感文件扫描）→ 归档。

**任何一道门禁 FAIL 即中止，不出包。** 这是有意的——宁可不出，也不出坏包。

### 2.3 产物在哪

```
ops/packages/
├── latest/                          ← 交付用这个
│   ├── smartx-capacity-insight-upgrade-v0.5.3.tar.gz     平台包 235M
│   ├── smartx-upgrade-runner-v0.3.2.tar.gz               runner 组件包 78M
│   ├── offline-delivery/             ← **真正给客户的目录**（1.4G）
│   │   ├── README.md                客户文档（客户看这份）
│   │   ├── install/                 首次安装物料
│   │   │   ├── install.sh
│   │   │   ├── images/              5 个镜像 tar + SHA256SUMS
│   │   │   ├── project/             部署文件（compose 已落已发布 runner 基线）
│   │   │   ├── pre_install.sh
│   │   │   └── .env.template
│   │   └── upgrade/                 离线升级物料
│   │       ├── upgrade.sh
│   │       └── packages/            升级包 + SHA256SUMS
│   └── SHA256SUMS
└── archive/YYYYMMDD-HHMMSS/         历史归档，保留最近 5 份
```

`latest/` 是**副本不是软链**（软链在拷贝目录/换机器时会断）。

**注意区分**：
- `offline-delivery/` = 给客户的，**自包含**（带镜像与部署文件）
- 两个 `*.tar.gz` 放在 `latest/` 顶层，是给我们自己留的原始包，方便二次分发或排障

### 2.4 打给客户前的自检（必做）

```bash
cd ops/packages/latest/offline-delivery

# 1) 镜像完整性
cd install/images && sha256sum -c SHA256SUMS && cd ../..

# 2) compose 的 runner tag 必须是「已发布基线」，不是源码开发线版本
grep -A6 'upgrade-runner:' install/project/docker-compose*.yml | grep image:
#   期望：upgrade-runner:v0.3.1（已发布基线），**不是** v0.3.2（开发线）

# 3) 禁含文件（不应有 .env / 业务库）
find . -name ".env" -o -name "*.db" -o -name "*.sqlite*"
#   期望：无输出
```

## 3. 第二步：交付给客户

### 3.1 交付什么

**只给 `offline-delivery/` 这一个目录**（或它的压缩包）。它自包含，客户不需要网络、不需要仓库。

```bash
cd ops/packages/latest
tar -czf smartx-capacity-insight-offline-20260930.tar.gz offline-delivery/
sha256sum smartx-capacity-insight-offline-20260930.tar.gz > smartx-capacity-insight-offline-20260930.tar.gz.sha256
```

**同时把这个 SHA256 值单独发给客户**（微信/邮件正文，不要只发文件），
客户用它核对传输完整性。

### 3.2 交付时必须一并说明的三件事

1. **包的来源与版本**：`v0.5.3`，以及对应的 runner 组件包版本（`v0.3.2`）。
2. **SHA256 校验值**（见上）。
3. **客户从 `offline-delivery/README.md` 开始看**——那份是写给客户的，本文件不用给。

### 3.3 不要给客户的东西

- ❌ 整个仓库（含 `backend/`、`frontend/` 源码）——客户不需要
- ❌ `ops/` 目录——那是我们的内部入口
- ❌ `.env`、`smartx.db`、任何真实数据

## 4. 第三步：客户怎么用（转述，细节看包内 README）

给客户的一句话版本：

> 解压后进 `offline-delivery/` 目录，先读 `README.md`。
> 首次安装跑 `sudo bash install/install.sh`；
> 以后升级跑 `sudo bash upgrade/upgrade.sh`。

### 4.1 客户首次安装

```bash
tar -xzf smartx-capacity-insight-offline-20260930.tar.gz
cd offline-delivery

# 校验（可选但建议）
cd install/images && sha256sum -c SHA256SUMS && cd ../..

sudo bash install/install.sh
```

装完：
- 访问 `http://<客户机器IP>:8080`，用 `admin` / `password` 登录，**立即改口令**
- 自检：`curl -s http://127.0.0.1:8000/api/system/health` 应 `ok=true` 且三项 checks 全 true

### 4.2 客户后续升级

```bash
cd offline-delivery

# 平台升级（升级包已在 upgrade/packages/ 里，脚本自动选）
sudo bash upgrade/upgrade.sh --yes

# 平台升级成功之后，连带升级 runner 组件
sudo bash upgrade/upgrade.sh --yes --with-runner packages/smartx-upgrade-runner-v0.3.2.tar.gz
```

**升级顺序铁律：先平台，后 runner。** 顺序颠倒（旧平台的 web-api 会停掉刚启动的新 runner）会导致升级中断。
`--with-runner` 会**先等升级后清理（post-cleanup）收敛**再升 runner，不会被单飞守卫拒绝。

### 4.3 客户侧常见问题

| 现象 | 原因与处理 |
| --- | --- |
| 升级报「另有升级任务正在执行」 | 单飞守卫：同时只能有一个升级任务。等前一个收敛，或对卡死的任务用「标记失败」 |
| 升级报 `database is locked` / 503 | runner 刚升级完还在释放 SQLite 写锁，等约 10 秒重试 |
| prometheus 反复重启、日志 `permission denied` | `chown 65534:65534 /data/smartx-storage-forecast/prometheus` |
| 容器 `Exited(137)` | **先看 `OOMKilled`**：为 `false` 说明是被人为 SIGKILL（通常是用错 compose 变体重建），不是内存不足 |
| 找不到 `install/images` | 交付包不完整，重新取包 |

更细的排查见 `docs/troubleshooting.md`。

## 5. 我们自己要在开发机上装/升级

开发机或测试机上没有交付物料时：

```bash
bash ops/package.sh          # 先打包出交付物料
sudo bash ops/install.sh     # 再装（会自动定位 ops/packages/latest/offline-delivery/）
sudo bash ops/upgrade.sh --yes
```

`ops/install.sh` 找不到交付物料时会明确提示先打包，**不会**去改仓库里的
`delivery/install/install.sh`（那个目录只有脚本本体、没有镜像，直接跑必然失败）。

### ⚠ 在运行着实例的机器上做测试

**必须用独立 compose project 名**隔离，否则会重建现有实例：

```bash
docker compose -f docker-compose.offline.yml -p smartx-opstest up -d
```

同一个 project 名下混用不同 compose 变体（`docker-compose.yml` 与 `docker-compose.offline.yml`
定义不同、config-hash 不同），Docker 会判定「配置变了」并 **recreate** 现有容器 → 旧容器被 SIGKILL
（`exit 137`）。**测试目录用完即删。**

## 6. 相关文档

| 文档 | 给谁 | 内容 |
| --- | --- | --- |
| `offline-delivery/README.md` | **客户** | 包内文档：安装、升级、自检、卸载、FAQ |
| 本文件 | 交付负责人 | 打包 → 交付 → 客户使用的全链路 |
| `../ops/README.md` | 开发者 | 三个运维脚本的用法与参数 |
| [release-build-guide.md](release-build-guide.md) | 开发者 | 发版构建流程 |
| [troubleshooting.md](troubleshooting.md) | 运维 | 故障排查手册 |
