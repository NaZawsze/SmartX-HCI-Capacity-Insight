# OVA 交付说明

本文档说明 OVA 虚拟机模板与平台升级包、数据迁移包之间的边界。

## 制品边界

OVA 是全新部署或演示环境交付用的虚拟机模板，不是服务管理页上传的升级包。服务管理页只接受升级中心定义的 `.tar.gz` 平台包、组件包、观测包或组合包。

推荐交付物：

```text
smartx-capacity-insight-v0.5.1.ova
smartx-capacity-insight-v0.5.1.ova.sha256
```

如果同一版本还需要支持已有 v2 环境在线升级，另行提供平台升级包：

```text
smartx-capacity-insight-upgrade-v0.5.1.tar.gz
smartx-capacity-insight-upgrade-v0.5.1.tar.gz.sha256
```

Runner 组件包只在 Runner 能力变化或安全修复时单独交付，版本使用 `RUNNER_VERSION`，例如：

```text
smartx-upgrade-runner-v0.3.0.tar.gz
smartx-upgrade-runner-v0.3.0.tar.gz.sha256
```

## OVA 安全要求

交付 OVA 前必须确认：

- 不包含现场 `.env`、真实 `SMARTX_SECRET_KEY`、真实 `SMARTX_CREDENTIAL_KEY`。
- 不包含 SQLite 业务库、Prometheus 历史数据、备份、导出文件或升级留档。
- 不包含 Tower/CloudTower 地址、账号、密码、API token 或客户 VM 名称等现场数据。
- 默认账号密码只能用于首次登录，文档必须要求首次登录后修改。
- OVA 文件名必须带平台版本，例如 `smartx-capacity-insight-v0.5.1.ova`。

## 校验文件

每个交付文件都应提供 SHA256：

```bash
sha256sum smartx-capacity-insight-v0.5.1.ova > smartx-capacity-insight-v0.5.1.ova.sha256
sha256sum smartx-capacity-insight-upgrade-v0.5.1.tar.gz > smartx-capacity-insight-upgrade-v0.5.1.tar.gz.sha256
```

用户下载后校验：

```bash
sha256sum -c smartx-capacity-insight-v0.5.1.ova.sha256
sha256sum -c smartx-capacity-insight-upgrade-v0.5.1.tar.gz.sha256
```

## 版本检查

交付前检查：

- OVA 文件名、升级包 manifest 版本和文档版本使用同一个正式平台版本。
- Runner 组件包使用 `RUNNER_VERSION`，不跟随平台版本。
- OVA 说明写清它用于全新部署；平台升级包说明写清它用于 v2 同架构在线升级。
- 所有交付文件都有 SHA256。
