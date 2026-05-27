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
  last_error?: string | null;
  clusters: Cluster[];
}

export interface MetricItem {
  metric: Record<string, string>;
  value: number;
  growth_amount?: number | null;
  previous_value?: number | null;
  growth_ratio?: number | null;
  period_days?: number | null;
  forecast?: ForecastResult;
  provisioned?: number | null;
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
  };
  kpis: {
    tower_count: number;
    cluster_count: number;
    vm_count: number;
    used_bytes: number;
    total_bytes: number;
    used_ratio: number;
  };
  latest_run?: {
    id: number;
    started_at: string;
    finished_at?: string;
    status: string;
    message?: string;
  };
  top_vms: MetricItem[];
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
}

export interface VmVolume {
  [key: string]: unknown;
  id?: string;
  name?: string;
  used_size?: number;
  used_size_bytes?: number;
  provisioned_size?: number;
  provisioned_size_bytes?: number;
  path?: string;
  elf_storage_policy?: string;
  elf_storage_policy_replica_num?: number;
  elf_storage_policy_ec_k?: number;
  elf_storage_policy_ec_m?: number;
}

export interface VmVolumeSet {
  tower_id: number;
  cluster_id: string;
  vm_id: string;
  volumes: VmVolume[];
}

export interface ForecastPayload {
  clusters: Array<{
    labels: Record<string, string>;
    forecast: ForecastResult;
    points?: [number, number][];
    total?: number | null;
    warning?: number | null;
  }>;
  fastest_growing_vms: GrowthVmReport[];
  day_fastest_growing_vms?: GrowthVmReport[];
  month_fastest_growing_vms?: GrowthVmReport[];
  cluster_growth_rate_per_day?: number | null;
  cluster_growth_rate?: {
    per_day?: number | null;
    per_month?: number | null;
    per_quarter?: number | null;
  };
  window_days: number;
  forecast_days?: number;
}

export interface GrowthVmReport {
    labels: Record<string, string>;
    forecast: ForecastResult;
    growth_amount?: number | null;
    previous_value?: number | null;
    growth_ratio?: number | null;
    period_days?: number | null;
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
  backup_path?: string;
  kind?: string;
  component?: string;
  target_version?: string;
  release_notes?: string;
  database_migration?: boolean;
  restart_services?: string[];
  precheck_ok?: boolean;
  manifest?: Record<string, unknown>;
  checks: Array<{ name: string; ok: boolean; message: string; detail?: unknown }>;
  steps: Array<{ key: string; title: string; status: string; started_at?: string; finished_at?: string; message?: string }>;
  logs: string[];
}


export type AppTaskStatus = "running" | "succeeded" | "failed";
export type AppTaskKind = "upload" | "download" | "import" | "export" | "upgrade";

export interface AppTask {
  id: string;
  kind: AppTaskKind;
  title: string;
  detail?: string;
  status: AppTaskStatus;
  progress: number;
  createdAt: number;
  updatedAt: number;
}
