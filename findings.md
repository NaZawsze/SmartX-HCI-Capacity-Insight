# SmartX HCI Capacity Insight - 项目发现与接手笔记

## 项目概览

SmartX HCI Capacity Insight 是一个面向 SmartX/HCI 容量趋势、虚拟机增长和存储预测的离线部署平台。

主要能力：

- Tower/集群配置与采集。
- 容量趋势、日增长、月增长、虚拟机 Top 列表。
- 集群预测报表和 Word/Excel 导出。
- 数据迁移导入导出。
- 服务管理、服务重启。
- 离线升级中心和组件升级。

## 服务与职责

- `frontend`：Nginx 托管的前端页面，默认对外端口 `8080`。
- `web-api`：FastAPI 后端，负责接口、鉴权、报表、数据迁移、升级控制。
- `collector-worker`：采集任务 worker，负责周期采集并写入指标。
- `prometheus`：保存历史时序指标，是趋势图、日增长、月增长、预测报表的重要数据来源。
- `upgrade-runner`：执行系统升级任务，避免 `web-api` 自己升级自己时任务中断。

## 数据路径

当前推荐持久化路径放在 `/data` 下：

- 应用业务库：`/data/smartx-capacity-insight-data/app`
- Prometheus 指标：`/data/smartx-capacity-insight-data/prometheus`
- 业务库文件：`/data/smartx-capacity-insight-data/app/smartx.db`
- 升级包和任务：容器内 `/data/upgrades`
- 升级前备份：容器内 `/data/backups`

## Docker 网络

为避免和用户环境常见网段冲突，`10.20.11.3` Docker 地址池已调整：

```json
{
  "bip": "10.249.0.1/24",
  "default-address-pools": [
    {
      "base": "10.249.0.0/16",
      "size": 24
    }
  ]
}
```

项目网络期望使用 `10.249.249.0/24`。

## Prometheus 权限坑

如果实际部署后趋势图、日增长、月增长、报表为空，先检查 Prometheus 是否在反复重启。

典型日志：

```text
Error opening query log file file=/prometheus/queries.active err="open /prometheus/queries.active: permission denied"
panic: Unable to create mmap-ed active query log
```

根因通常是宿主机 Prometheus 数据目录权限不对。`prom/prometheus` 容器通常需要 `65534:65534` 写权限。

已新增并提交 `pre_install.sh`，部署前应执行：

```bash
./pre_install.sh
```

它会创建并修复：

- `/data/smartx-capacity-insight-data/app`
- `/data/smartx-capacity-insight-data/prometheus`

## SELinux 与防火墙

部分部署机 SELinux 会影响 bind mount 写入。用户曾要求在测试机永久关闭 SELinux。

防火墙原则：

- 对外只需要开放 `8080/tcp`。
- 其他服务端口除调试场景外不建议对外暴露。

## 数据迁移注意事项

数据迁移不能只迁移 SQLite 业务库，否则新环境会出现：

- 趋势图为空。
- 日增长/月增长为空。
- 集群预测报表为空。

原因是这些能力依赖 Prometheus 历史指标。完整迁移需要同时包含：

- 业务库 `smartx.db`
- Prometheus 历史数据块

导入策略应尽量补全缺失数据，不覆盖现有系统已有数据。业务库导入应避免按整库覆盖；对于已存在集群，需要谨慎处理 cluster/tower 映射，避免导入后过滤条件不匹配导致历史指标查不到。

## 升级中心注意事项

第一版系统升级设计为离线 `.tar.gz` 升级包：

- `manifest.json`
- `images/*.tar`
- 可选 `scripts/migrate.sh`
- 可选 `release-notes.md`

系统升级由 `upgrade-runner` 执行。`upgrade-runner` 不能可靠地在线升级自己，因为它在升级过程中承担执行者角色。

后续已引入“组件升级”概念：

- 平台升级：升级业务服务。
- 组件升级：用于升级 `upgrade-runner` 等基础组件。

一般原则：

- 不执行 `docker compose down -v`。
- 不覆盖 `.env`。
- 不完整替换 `docker-compose.yml`。
- 不替换或清空核心数据目录。

## 离线部署注意事项

源码包内普通 `docker-compose.yml` 可能包含 `build`，在无外网环境会尝试拉取基础镜像并失败。

离线环境应使用 release/offline compose，并确保目标镜像已存在本机，例如：

```bash
docker compose -f docker-compose.offline.yml --project-name smartx-capacity-insight up -d
```

如果镜像只有 `latest` 标签，而 compose 指向 `v0.x.x` 标签，会触发拉取。需要统一镜像标签或先 `docker tag`。

## 报表与增长率口径

报表页容量增长速率当前需求：

- 按最近 7 天平均增长速率计算。
- 卡片提示显示 `7 天平均`。
- 趋势图窗口可以切换 `7 / 30 / 90 / 365 / 720` 天。
- 图表横坐标需要根据窗口大小调整显示间隔。

## Git 规则

- 默认开发分支：`dev`。
- 默认提交到 `dev`。
- 只有用户明确要求时，才同步 `dev` 到 `main` 并打 tag。
- 推送 `main` 和 tag 前，要再次确认用户要求的 tag 名，例如 `v0.3.3U1`、`v0.3.2`。

## 安全规则

- 不把 SSH 密码、平台密码、token 写入仓库文档。
- 不在文档中保存真实凭据。
- 不执行破坏性命令，例如 `git reset --hard`、删除 volumes、删除数据目录，除非用户明确要求。
