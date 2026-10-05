export type PageKey = "dashboard" | "vms" | "reports" | "settings" | "service";

export interface LoginResponse {
  access_token: string;
  token_type: string;
  username: string;
}

export interface Cluster {
  cluster_id: string;
  name: string;
  enabled: boolean;
}

export interface Tower {
  id: number;
  name: string;
  base_url: string;
  username?: string;
  verify_tls: boolean;
  enabled: boolean;
  collection_hour: number;
  collection_minute: number;
  collection_interval_minutes?: number | null;
  collection_mode?: "interval" | "daily" | string | null;
  collection_retry_enabled: boolean;
  collection_retry_interval_minutes: number;
  collection_retry_max_attempts: number;
  last_error?: string | null;
  last_collection?: { status: string; finished_at?: string | null } | null;
  clusters: Cluster[];
}

export interface MetricItem {
  metric: Record<string, string>;
  value: number;
  tower_id?: string | number | null;
  cluster_id?: string | null;
  cluster?: string | null;
  vm_id?: string | null;
  vm_name?: string | null;
  current_bytes?: number | null;
  used_bytes?: number | null;
  growth_amount?: number | null;
  previous_value?: number | null;
  growth_ratio?: number | null;
  period_days?: number | null;
  sample_span_days?: number | null;
  forecast?: ForecastResult;
  provisioned?: number | null;
  total_bytes?: number | null;
  allocated_bytes?: number | null;
  used_ratio?: number | null;
  guest_used?: number | null;
  guest_used_ratio?: number | null;
}

export interface DashboardSummary {
  scope?: {
    type: "all" | "tower" | "cluster";
    label: string;
    tower_id?: number | null;
    cluster_id?: string | null;
    cluster_enabled?: boolean | null;
  };
  kpis: {
    tower_count: number;
    cluster_count: number;
    vm_count: number;
    used_bytes: number;
    total_bytes: number;
    allocated_bytes?: number;
    used_ratio: number;
    allocated_ratio?: number;
  };
  capacity_risk?: {
    level: "normal" | "warning" | "danger" | "high";
    title: string;
    evaluated_at?: string | null;
    thresholds?: { warning_ratio?: number | null; danger_ratio?: number | null } | null;
    message?: string;
    description: string;
    cluster_count: number;
    warning_count: number;
    danger_count: number;
    risk_clusters?: Array<{
      tower_id?: string | number | null;
      cluster_id?: string | null;
      cluster?: string | null;
      used_bytes?: number | null;
      total_bytes?: number | null;
      used_ratio?: number | null;
      forecast_90d?: number | null;
      exhaustion_days?: number | null;
      exhaustion_days_30d?: number | null;
      spike_detected?: boolean | null;
      risk_level?: "high" | "warning" | "danger" | "normal" | string | null;
    }>;
    top_clusters: Array<{
      tower_id?: string | null;
      tower?: string | null;
      cluster_id?: string | null;
      cluster?: string | null;
      used_bytes?: number | null;
      total_bytes?: number | null;
      used_ratio?: number | null;
      top_growth_vms?: Array<{
        tower_id?: number | string | null;
        cluster_id?: string | null;
        vm_id?: string | null;
        vm_name?: string | null;
        current_bytes?: number | null;
        growth_amount?: number | null;
        growth_ratio?: number | null;
      }>;
    }>;
  };
  latest_run?: {
    id: number;
    started_at: string;
    finished_at?: string;
    status: string;
    message?: string;
  };
  collection?: {
    status?: string | null;
    message?: string | null;
    last_success_at?: string | null;
    threshold_minutes?: number | null;
    data_freshness?: "fresh" | "stale" | "unknown" | string | null;
  } | null;
  top_vms: MetricItem[];
  day_fastest_growing_vms?: MetricItem[];
  day_new_vms?: MetricItem[];
  clusters: MetricItem[];
  towers: Tower[];
  tower_runs?: Array<{
    tower_id: number;
    tower_name: string;
    status: string;
    message?: string | null;
  }>;
}

export type DashboardScope =
  | { type: "all" }
  | { type: "tower"; towerId: number }
  | { type: "cluster"; towerId: number; clusterId: string };

export interface VmTrend {
  vm_id: string;
  metric: string;
  points: [number, number][];
  tower_id?: number;
  cluster_id?: string;
  vm_name?: string;
  latest_success_at?: string | null;
  latest_collection_status?: string;
  has_collection_gap?: boolean;
  gap_dates?: string[];
  data_freshness?: "fresh" | "stale" | "partial" | string;
}

export interface VmDetail {
  tower_id: number;
  cluster_id: string;
  vm_id: string;
  vm_name: string;
  used_bytes: number;
  updated_at?: string | null;
}

export interface VmVolume {
  [key: string]: unknown;
  id?: string;
  volume_id?: string;
  name?: string;
  used_size?: number;
  used_size_bytes?: number;
  used_bytes?: number;
  provisioned_size?: number;
  provisioned_size_bytes?: number;
  size_bytes?: number;
  path?: string;
  elf_storage_policy?: string;
  storage_policy?: string;
  elf_storage_policy_replica_num?: number;
  replica_num?: number;
  elf_storage_policy_ec_k?: number;
  ec_k?: number;
  elf_storage_policy_ec_m?: number;
  ec_m?: number;
  thin_provision?: boolean | null;
}

export interface VmVolumeRow extends VmVolume {
  tower_id: number;
  cluster_id: string;
  cluster_name?: string;
  vm_id: string;
  vm_name?: string;
}

export interface VmVolumePage {
  volumes: VmVolumeRow[];
  total: number;
  page: number;
  page_size: number;
}

export interface VmUsageSummaryItem {
  tower_id: number;
  cluster_id: string;
  vm_id: string;
  used_bytes: number;
  provisioned_bytes: number;
}

export interface LocalStorageUsage {
  path: string;
  total_bytes: number;
  used_bytes: number;
  free_bytes: number;
  used_ratio: number;
  free_ratio: number;
  total_label: string;
  used_label: string;
  free_label: string;
}

export interface ForecastPayload {
  clusters: Array<{
    labels: Record<string, string>;
    forecast: ForecastResult;
    points?: [number, number][];
    total?: number | null;
    warning?: number | null;
    allocated?: number | null;
  }>;
  fastest_growing_vms: GrowthVmReport[];
  day_fastest_growing_vms?: GrowthVmReport[];
  month_fastest_growing_vms?: GrowthVmReport[];
  day_new_vms?: GrowthVmReport[];
  month_new_vms?: GrowthVmReport[];
  cluster_growth_rate_per_day?: number | null;
  cluster_growth_rate?: {
    per_day?: number | null;
    per_month?: number | null;
    per_quarter?: number | null;
    day_sample_sufficient?: boolean;
    month_sample_sufficient?: boolean;
    quarter_sample_sufficient?: boolean;
    day_window_days?: number;
    month_window_days?: number;
    quarter_window_days?: number;
  };
  window_days: number;
  chart_days?: number;
  growth_rate_window_days?: number;
  forecast_days?: number;
  period_window?: {
    days?: number;
    start_at?: string;
    end_at?: string;
  };
  data_window?: {
    start_at?: string;
    end_at?: string;
  };
  data_quality?: DataQuality;
}

export interface DataQuality {
  status: "ok" | "warning" | "critical" | "unknown" | string;
  actual_data_window?: {
    start_at?: string;
    end_at?: string;
    days?: number;
  };
  requested_window?: {
    days?: number;
    start_at?: string;
    end_at?: string;
  };
  sample_sufficient?: boolean;
  missing_collection_dates?: string[];
  incomplete_clusters?: Array<{
    tower_id?: number | string | null;
    tower?: string | null;
    cluster_id?: string | null;
    cluster?: string | null;
    reason?: string | null;
  }>;
  sqlite_vm_count?: number;
  prometheus_vm_series_count?: number;
  sqlite_cluster_count?: number;
  prometheus_cluster_series_count?: number;
  vm_count_difference?: number;
  vm_count_difference_ratio?: number;
  latest_collection_status?: string | null;
  latest_success_at?: string | null;
  latest_prometheus_sample_at?: string | null;
  messages?: string[];
}

export interface GrowthVmReport {
  labels: Record<string, string>;
  vm_id?: string;
  vm_name?: string;
  forecast: ForecastResult;
  growth_amount?: number | null;
  previous_value?: number | null;
  growth_ratio?: number | null;
  period_days?: number | null;
  first_seen_at?: string | null;
  age_days?: number | null;
  sample_span_days?: number | null;
}

export interface ForecastResult {
  status: string;
  slope_per_day: number;
  current: number;
  forecast_30d?: number | null;
  forecast_60d?: number | null;
  forecast_90d?: number | null;
  forecast_180d?: number | null;
  exhaustion_days?: number | null;
  exhaustion_days_30d?: number | null;
  spike_detected?: boolean | null;
  band_half_width_now?: number | null;
  band_half_width_per_day?: number | null;
}


export interface UpgradeTask {
  task_id: string;
  status: string;
  uploaded_at?: string;
  started_at?: string;
  finished_at?: string;
  updated_at?: string;
  rollback_started_at?: string;
  rollback_finished_at?: string;
  package_filename?: string;
  package_sha256?: string;
  uploaded_sha256?: string;
  backup_path?: string;
  kind?: string;
  component?: string;
  components?: string[];
  target_version?: string;
  release_notes?: string;
  database_migration?: boolean;
  restart_services?: string[];
  precheck_ok?: boolean;
  manifest?: Record<string, unknown>;
  task_schema_version?: number;
  recovery_status?: string;
  recovery_reason?: string;
  recovery_command?: string | null;
  /**
   * 升级包是否还在（2026-10-04）。删包改为「只删包、保留记录」后，
   * 任务仍留在历史里且 `started_at` 仍在——若界面仍显示「删除」按钮，
   * 点了会没有反应。故据此隐藏按钮。
   */
  has_package?: boolean;
  /** US-29：人工回滚已下线，保留取值仅为历史任务/老客户端兼容，UI 不再暴露该操作。 */
  available_recovery_actions?: Array<"continue" | "rollback" | "fail">;
  /** US-27：任务被标记失败后环境是否需要收尾（重跑一次升级由 post-cleanup 清理残留）。 */
  cleanup_required?: boolean;
  residual_paths?: string[];
  /**
   * B3：预检查失败时的**下一步指引**（结构化字段）。
   * 只在 `ok=false` 时出现；由包携带（manifest.source_compatibility.remediation），
   * 前端只做展示，不自己拼版本号。
   */
  checks: Array<{ name: string; ok: boolean; message: string; detail?: unknown; remediation?: string }>;
  steps: Array<{ key: string; title: string; status: string; started_at?: string; finished_at?: string; message?: string }>;
  logs: string[];
}

/** 场景 B：可回滚性判定。blockers 是结构化数组——拒绝必须带出路（B3 同构）。 */
export interface UpgradeRollbackAvailability {
  available: boolean;
  blockers: string[];
  target_version?: string;
  current_version?: string;
  images?: string[];
  anchor_source?: string;
  anchor_task_id?: string;
  captured_at?: string;
  scope?: string;
  note?: string;
}

/** 场景 C：整备回滚可用性（含数据丢失窗口与确认要求）。 */
export interface UpgradeFullRollbackAvailability {
  available: boolean;
  blockers: string[];
  target_version?: string;
  current_version?: string;
  backup?: { present?: boolean; path?: string; sha256_ok?: boolean; data_loss_window?: string; reason?: string };
  scope?: string;
  data_loss_window?: string;
  requires_confirmation?: boolean;
  note?: string;
}

export interface UpgradeVerification {
  app_version: string;
  runner_version: string;
  prometheus_version?: string;
  compose_project: string;
  compose_file: string;
  service_status_error?: string | null;
  package?: {
    task_id?: string;
    version?: string;
    filename?: string;
    sha256?: string;
    image_sha256?: Record<string, string>;
    uploaded_at?: string;
    finished_at?: string;
  } | null;
  services: Array<{
    service: string;
    container: string;
    status: string;
    running: boolean;
    image: string;
    image_id?: string;
    app_version?: string | null;
    started_at?: string | null;
    error?: string | null;
  }>;
}

export interface UpgradePostCleanupStatus {
  parent_task_id: string;
  status: string;
  task_id?: string;
  task?: UpgradeTask | null;
}

export interface ComponentInfo {
  type: "runner" | "observability" | string;
  display_name: string;
  service: string;
  version: string;
  executor: string;
  upgradeable: boolean;
  status_message?: string | null;
  protocol_version?: number | null;
  capabilities?: string[];
  heartbeat_at?: string | null;
  compatible?: boolean;
}


export interface SpaceCleanupScanItem {
  key: string;
  label: string;
  description: string;
  path: string;
  count: number;
  size: number;
  size_label: string;
}

export interface SpaceCleanupScanResult {
  ok: boolean;
  items: SpaceCleanupScanItem[];
  total_count: number;
  total_size: number;
  total_size_label: string;
  message: string;
}

export interface SpaceCleanupResult {
  ok: boolean;
  deleted_count: number;
  kept_count?: number;
  space_reclaimed: number;
  space_reclaimed_label: string;
  logs: string[];
  message: string;
}

export interface MigrationExportTask {
  task_id: string;
  status: "pending" | "running" | "succeeded" | "failed";
  progress: number;
  processed_bytes: number;
  total_bytes: number;
  detail?: string;
  logs?: string[];
  steps?: AppTaskStep[];
  filename?: string;
  saved_path?: string;
  download_url?: string;
  created_at?: string;
  updated_at?: string;
  finished_at?: string;
}

export interface MigrationImportTask {
  task_id: string;
  status: "pending" | "running" | "succeeded" | "failed";
  progress: number;
  detail?: string;
  logs?: string[];
  steps?: AppTaskStep[];
  backup_path?: string;
  saved_path?: string;
  summary?: {
    sqlite?: Record<string, unknown>;
    prometheus?: Record<string, unknown>;
    health?: {
      complete?: boolean;
      message?: string;
      checks?: Record<string, boolean>;
    };
  };
  links?: AppTaskLink[];
  created_at?: string;
  updated_at?: string;
  finished_at?: string;
}

export interface MigrationHealth {
  checks: Record<string, boolean>;
  message: string;
  complete?: boolean;
  sqlite?: {
    exists?: boolean;
    size_bytes?: number;
    tables?: Record<string, number>;
    latest_vm_volumes_payload_bytes?: number;
    latest_vm_volume_items?: number;
  };
  prometheus?: {
    exists?: boolean;
    block_count?: number;
    blocks?: string[];
    runtime_entries_skipped?: string[];
  };
}

export interface SqliteVacuumScan {
  ok: boolean;
  path: string;
  size: number;
  size_label: string;
  page_count: number;
  freelist_count: number;
  page_size: number;
  estimated_reclaimable: number;
  estimated_reclaimable_label: string;
  runtime_cache?: {
    metric_snapshots?: { keep?: number; delete_count: number };
    collection_runs?: { retention_days?: number; delete_count: number };
    tasks?: { retention_days?: number; delete_count: number };
  };
  message: string;
}

export interface SqliteVacuumResult {
  ok: boolean;
  backup_path: string;
  before_size: number;
  after_size: number;
  before_size_label?: string;
  after_size_label?: string;
  space_reclaimed: number;
  space_reclaimed_label: string;
  runtime_cache?: {
    metric_snapshots_deleted: number;
    collection_runs_deleted: number;
    tasks_deleted: number;
  };
  message: string;
  logs?: string[];
}

export interface SqliteBackupItem {
  filename: string;
  path: string;
  size: number;
  size_label: string;
  modified_at?: string;
}

export interface SqliteBackupScanResult {
  ok: boolean;
  items: SqliteBackupItem[];
  total_count: number;
  total_size: number;
  total_size_label: string;
  message: string;
}

export interface SqliteBackupCleanupResult {
  ok: boolean;
  deleted_count: number;
  space_reclaimed: number;
  space_reclaimed_label: string;
  logs: string[];
  message: string;
}

export type AppTaskStatus = "pending" | "running" | "succeeded" | "failed" | "cancelled";
export type AppTaskKind = "upload" | "download" | "import" | "export" | "upgrade";
export type AppTaskSeverity = "info" | "warning" | "critical";

export interface AppTaskLink {
  label: string;
  filename?: string;
  url: string;
  path?: string;
  exists?: boolean;
  expired?: boolean;
}

export interface ReportBundleExport {
  task_id: string;
  status: "success" | "failed" | string;
  files: AppTaskLink[];
  links: AppTaskLink[];
  message: string;
}

export interface AppTaskStep {
  key: string;
  title: string;
  status: string;
  message?: string;
  started_at?: string;
  finished_at?: string;
}

export interface AppTask {
  id: string;
  kind: AppTaskKind;
  title: string;
  detail?: string;
  status: AppTaskStatus;
  progress: number;
  severity?: AppTaskSeverity;
  seenAt?: string | null;
  acknowledgedAt?: string | null;
  unhandled?: boolean;
  clearable?: boolean;
  links?: AppTaskLink[];
  logs?: string[];
  steps?: AppTaskStep[];
  createdAt: number;
  updatedAt: number;
}

export interface ServerTask {
  id: string;
  type?: string;
  kind?: AppTaskKind;
  status: "pending" | "running" | "success" | "failed" | "cancelled";
  title: string;
  message?: string;
  detail?: string;
  progress: number;
  severity?: AppTaskSeverity;
  seen_at?: string | null;
  acknowledged_at?: string | null;
  unhandled?: boolean;
  clearable?: boolean;
  links?: AppTaskLink[];
  logs?: string[];
  steps?: AppTaskStep[];
  created_at?: string;
  updated_at?: string;
  finished_at?: string | null;
}
