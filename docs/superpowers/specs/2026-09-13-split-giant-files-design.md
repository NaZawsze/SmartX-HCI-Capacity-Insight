# 拆分巨型文件设计（Phase 49-13）

更新时间：2026-09-13
状态：✅ 已完成（2026-09-13，四个文件独立提交部署，全量回归零新增；见 progress.md）
关联：task_plan.md Phase 49 第 13 项；docs/pending-tasks.md P3

## 1. 原则

- **纯结构重构**：不改任何行为、不改对外接口、不改路由路径与 payload。
- 兼容优先：包拆分后保留原 import 路径（`__init__.py` 再导出），调用方零改动。
- 一个文件一个提交 + 一次 .3 部署验证；任意一步可独立 revert。
- 验证门槛：改动前后 OpenAPI 路由清单一致（api 拆分用脚本对比 `/openapi.json` 的 path+method 集合）；后端全量测试；前端目标测试 + 构建；.3 健康检查。

## 2. `backend/app/v2/api.py`（1112 行，69 条路由）→ 包

目标结构：

~~~text
app/v2/api/
├── __init__.py        # router = APIRouter(); include 各域子 router（对外路径不变）
├── deps.py            # 现有 get_*_service 依赖与公共 Annotated 别名
├── auth.py            # /api/auth/login、/api/me（3 条）
├── towers.py          # /api/towers*（7 条 + test/clusters/sync）
├── dashboard.py       # /api/dashboard/summary（1 条）
├── vms.py             # /api/vms*、/api/vm-volumes（5 条）
├── reports.py         # /api/reports*（4 条）
├── collection.py      # /api/collection*（3 条）
├── tasks.py           # /api/tasks*（5 条）
├── system.py          # /api/system/*（1 条）
└── admin.py           # /api/admin/*（43 条；内部再按 upgrade/migration/system 分节注释）
~~~

- `admin.py` 首批不继续拆（43 条在同一响应模型批次里还会动），只搬家 + 分节注释；响应模型批次落地时再细化。
- 验收：拆分前后 `/openapi.json` 的 `(method, path)` 集合 diff 为空；`from app.v2.api import router` 与 `from app.v2.api import xxx` 兼容（`__init__` 再导出）。

## 3. `backend/app/v2/reports/export.py`（3720 行）→ 包

现状函数分布：`_customer_*`（Word 客户版模板）、`_xlsx_*/_write_xlsx_template_*/_setup_*`（Excel 模板）、43 个 `_*` 公共助手（字节数/百分比标签、颜色、集群命名、数据质量状态等）、3 个 `build_report_*` 公共入口。

目标结构：

~~~text
app/v2/reports/export/
├── __init__.py        # 再导出 build_report_word / build_report_excel 等公共入口
├── common.py          # 公共助手（标签格式化、颜色常量、集群名、数据质量文案）
├── word.py            # Word 客户版（_customer_*、封面/摘要/矩阵/建议）
├── excel.py           # Excel 客户版（_xlsx_*、_write_xlsx_template_*、_setup_*）
└── legacy.py          # 其余未归类函数（逐步消化）
~~~

- `common.py` 的助手在 word/excel 间以 `from .common import` 引用，禁止循环导入（公共助手不得 import word/excel）。
- 验收：`grep "from app.v2.reports.export import"` 全部调用方零改动；Word/Excel 导出各真实跑一次（.3 导出产物人工抽查 + 既有 export 测试回归）。

## 4. `backend/app/v2/upgrade/service.py`（1791 行，UpgradeService 55 方法）→ Mixin 拆分

选择 Mixin 方案（而非拆服务类）：UpgradeService 的状态字段（database/settings/tasks/prometheus）被全部方法共享，Mixin 拆分零行为风险且 import 路径稳定。

~~~text
app/v2/upgrade/service/
├── __init__.py        # class UpgradeService(... mixins 组合)（原类名/构造签名不变）
├── intake.py          # upload_package_bytes / delete_package / history / version / component_version
├── precheck.py        # precheck
├── execution.py       # start / status / cancel / runner 提交与状态同步
├── cleanup.py         # create/retry/status post_upgrade_cleanup 三方法
├── verification.py    # verification / latest_package / 包身份校验
└── fs.py              # _safe_extract / _remove_path / _backup_existing_project_path 等模块级助手
~~~

- 验收：`UpgradeService` 构造签名与公开方法集合不变（脚本对比 `dir()`）；既有 upgrade 测试回归。

## 5. `frontend/src/pages/ServicePage.tsx`（2305 行）→ 域组件

页面四大域：升级中心（上传/预检查/任务/恢复控制）、服务状态（组件状态/重启）、空间清理（扫描/清理/SQLite 备份清理）、数据迁移（导出/导入/配置迁移）。

~~~text
frontend/src/components/service/
├── UpgradeCenterSection.tsx
├── ServiceStatusSection.tsx
├── CleanupSection.tsx
├── MigrationSection.tsx
└── shared.tsx            # 页内公共小组件
ServicePage.tsx 收敛为：状态编排 + 四个 Section 的组装（目标 ≤400 行）。
~~~

- 拆分前先在文件内标注段落边界（现有代码按域注释分块）；props 走显式接口，不引入全局状态。
- 验收：现有 ServicePage 测试迁移后全绿；tsc 通过；页面功能人工抽查（上传/重启/清理/迁移各一次）。

## 6. 实施顺序与节奏

1. api.py（最小行为风险，为响应模型批次铺路）
2. ServicePage.tsx（前端独立，随时可做）
3. export.py（导出产物需人工抽查，安排在无发布压力时）
4. upgrade/service.py（Mixin 拆分，放最后）

每个文件：独立提交（`refactor: split xxx`）→ .3 构建部署 → 该文件对应验收 → 标记。四个全部完成后本项关闭。

## 7. 不做范围

- 不借此机会改任何函数逻辑、命名、payload 字段。
- admin.py 的二次拆分、export legacy 的消化归入后续维护，不在本项验收内。


## 附录 A：函数映射清单（实施时以此为准，边界冲突以 import 闭包校验裁决）

> 生成方式：`grep -nE "^def |^    def " <file>`。行号为 2026-09-13 快照。

### A.1 export.py（190 函数）

**excel.py（36 个）**：`build_report_xlsx`、`_load_customer_xlsx_template`、`_get_or_create_sheet`、`_get_or_create_sheet_after`、`_clone_cluster_template_sheet`、`_remove_sheets`、`_clear_xlsx_sheet`、`_clear_xlsx_tables`、`_reset_xlsx_sheet_rows`、`_set_xlsx_cell`、`_write_xlsx_template_cover`、`_write_xlsx_template_summary`、`_write_xlsx_template_capacity_trend`、`_write_xlsx_data_quality_sheet`、`_write_xlsx_template_vm_top100`、`_write_xlsx_template_growth_detail`、`_write_scope_detail_sheet`、`_write_cluster_summary_sheet`、`_style_customer_xlsx_table`、`_merge_title_row`、`_apply_vm_top100_layout`、`_xlsx_vm_display_row`、`_vm_risk_label`、`_xlsx_bytes_label`、`_xlsx_signed_bytes_label`、`_parse_xlsx_bytes_label`、`_parse_percent_label`、`_style_sheet`、`_autosize`、`_write_directory_sheet`、`_write_vm_top_sheet`、`_write_simple_vm_sheet`、`_write_cluster_vm_sheet`、`_apply_cluster_sheet_layout`、`_normalize_xlsx_fonts`、`_vm_xlsx_row`、`_style_vm_rows`

**word.py（约 95 个）**：`build_report_docx`、`_setup_document`、`_add_cover`、`_add_callout`、`_add_paragraph_table`、`_add_cluster_directory`、`_add_cluster_table`、`_add_vm_table`、`_add_new_vm_table`、`_setup_footer`、`_footer_label`、`_overview_sentence`、`_add_single_cluster_summary`、`_add_single_cluster_charts`、`_docx_bytes`、`_shade_cell`、`_set_cell_text_color`、`_risk_text_color`、`_risk_word_color`、`_repeat_table_header`、`_prevent_row_split`、全部 `_customer_*`（约 50 个：_customer_setup_document 至 _customer_emphasis_segments）、全部 `_v1_*`（约 50 个：_v1_setup_document 至 _v1_vm_window_label）

**common.py（其余约 55 个）**：`report_period_profile`、`_export_context`、`_persist_report`、`_period_window_label`、`_requested_report_window_label`、`_effective_report_window`、`_vm_sample_window_label`、`_parse_report_datetime`、`_report_timezone`、`_capacity_risk_summary`、`_risk_summary_sentence`、`_cluster_name`、`_cluster_full_name`、`_tower_scope_label`、`_cluster_scope_label`、`_cluster_used_ratio`、`_risk_level`、`_overall_risk_status`、`_customer_growth_vms`、`_report_vm_count`、`_report_cluster_vm_counts`、`_cluster_vm_count`、`_report_vm_keys`、`_customer_key_findings`、`_customer_risk_matrix_rows`、`_customer_operation_advice`、`_vm_display_name`、`_vm_full_name`、`_vm_scope_name`、`_vm_current_bytes`、`_largest_vm`、`_exhaustion_days`、`_cluster_period_growth`、`_cluster_points`、`_merged_cluster_points`、`_vms_by_cluster`、`_cluster_key`、`_top_vms`、`_merge_growth_candidates`、`_float_or_none`、`_first_cluster_name`、`_is_alert_vm`、`_add_figure`、`_add_cluster_growth_chart`、`_line_chart_image`、`_horizontal_bar_chart_image`、`_figure_bytes`、`_configure_chart_fonts`、`_chart_color`、`_chart_y_limits`、`_truncate_label`、`_chart_bar_value`、`_bytes_to_tib`、`_bytes_to_gb`、`_local_now`、`_slug`、`_bytes_label`、`_signed_bytes_label`、`_days_label`、`_percent_label`

裁决规则：

- 同时被 word/excel 引用的 → common；仅一方引用 → 归该方（哪怕前缀像公共）。
- **已知陷阱**：文件内存在重复定义（`_percent_label` 定义了两次，后者生效）——拆分时必须消解，保留一个进 common。
- 搬移后 `python -m pyflakes`（或 import 冒烟）驱动的缺失补齐循环，直至零 NameError。

### A.2 upgrade/service.py（145 方法/函数）

| 目标模块 | 内容 |
| --- | --- |
| `fs.py`（模块级助手） | `_safe_extract`、`_remove_path`、`_backup_existing_project_path`、`_validate_members`、`_sha256_file`、`_now` |
| `intake.py` | `upload_package_bytes`、`delete_package`、`history`、`version`、`component_version`、`component_catalog`、`_read_manifest`、`_component_types`、`_component_types_from_task`、`_check_package_checksums`、`_task_package_sha256`、`_is_real_platform_package_task` |
| `precheck.py` | `precheck`、`_check_manifest`、`_check_protocol`、`_check_source_compatibility`、`_check_images`、`_check_images_with_executor`、`_local_image_requirements`、`_packaged_compose_service_image`、`_check_project_files`、`_platform_images`、`_platform_services`、`_observability_images`、`_observability_services`、`_runner_images`、`_runner_services`、`_runner_only`、`_runner_bootstrap`、`_runner_bootstrap_target_root`、`_runner_compose_project_name`、`_runtime_network_name`、`_upgrade_images`、`_upgrade_services`、`_task_images`、`_task_services`、`_check_prometheus_permissions`、`_version_from_env`、`_version_from_image`、`_version_from_service_status`、`_service_from_docker_ps_item` |
| `execution.py` | `start`、`status`、`cancel`、`execute_task`、`rollback`、`recovery_continue/rollback/fail`、`_set_recovery_command`、`_recover_runner_only_success_after_save_conflict`、`_resume_runner_upgrade`、`_normalize_completed_runner_task`、`_maybe_schedule_post_upgrade_cleanup`、`_runner_state`、`_active_runner_state`、`_active_runner_state_from_docker`、`_active_runner_version`、`_check_runner_protocol`、`_runner_state_is_fresh` |
| `cleanup.py` | `create_post_upgrade_cleanup_task`、`retry_post_upgrade_cleanup`、`post_upgrade_cleanup_status` |
| `verification.py` | `verification`、`_runtime_services`、`_runtime_services_from_docker_ps`、`_current_compose_project`、`_inspect_service_by_name`、`_inspect_container` |
| `taskfile.py` | `_save_task_file`、`_read_task_file`、`_step`、`_replace_step`、`_add_json`、`_add_directory`、`_public_status`、`_completed_runner_task_view`、`_public_task`、`_read_task_or_pending_record`、`_parse_datetime`、`_first_task_timestamp`、`_history_task_sort_key`、`_successful_package_sort_key` |
| `paths.py` | `_create_upgrade_backup`、`_sync_project_files`、`_write_upgrade_override`、`_write_runner_override`、`_write_task_override`、`_write_override`、`_host_data_path`、`_host_upgrades_path`、`_host_backups_path`、`_host_exports_path`、`_host_compose_runtime_path`、`_host_prometheus_path`、`_host_project_path`、`_host_path`、`_container_mount_source` |
| `__init__.py` | `UpgradeCommandExecutor` + `class UpgradeService(IntakeMixin, PrecheckMixin, ExecutionMixin, CleanupMixin, VerificationMixin, TaskFileMixin, PathsMixin)`（构造签名不变） |

### A.3 api.py 路由 → 域模块

| 模块 | 路由（method path） | 同时搬移的模型/依赖 |
| --- | --- | --- |
| auth.py | POST /api/auth/login；GET /api/me；POST /api/me/password | LoginRequest/TokenResponse/UserResponse/PasswordChangeRequest |
| towers.py | GET/POST /api/towers；PUT/DELETE /api/towers/{id}；POST sync/test/test-params；PUT clusters/{cid} | TowerPayload/ClusterPayload/ClusterUpdatePayload/TowerResponse/ClusterResponse/TowerTestPayload/TowerTestResponse/TowerCollectionStatus/tower_response/cluster_response/cluster_input_from_any/tower_last_collection |
| dashboard.py | GET /api/dashboard/summary | — |
| vms.py | GET /api/vms、/api/vms/{id}、/api/vms/{id}/trend、/api/vm-volumes、/api/vm-volumes/all | VmTrendResponse |
| reports.py | GET /api/reports/latest 等 3 GET；POST export word/excel/bundle；GET download_saved_export | — |
| collection.py | POST /api/collection/run；GET /api/collection/runs；GET /api/collection/runs/{id} | CollectionRunResponse/CollectionRunRequest |
| tasks.py | GET /api/tasks；POST seen/ack；DELETE /api/tasks/{id}、/api/tasks/finished、sqlite-backup | TaskSeenRequest/SqliteBackupDeleteRequest |
| system.py | GET /api/system/health | — |
| admin.py | 43 条 /api/admin/*（升级/迁移/清理/系统） | 其余全部模型 |
| deps.py | get_*_service 全部 + require_user + get_v2_settings/database | — |

### A.4 ServicePage.tsx 分区边界

以现有 JSX 注释与 Card title 为界：`升级中心`（上传/包列表/预检查/任务/恢复控制）、`服务状态`（组件状态/重启/版本）、`空间清理`（扫描/清理/SQLite 备份清理）、`数据迁移`（导出/导入/配置迁移）。拆分前先用 grep 统计各域 useState/handler 数量确定边界；共享的 api 调用放各自 Section 内。
