import type {
  DashboardScope,
  DashboardSummary,
  ComponentInfo,
  ForecastPayload,
  LocalStorageUsage,
  LoginResponse,
  MetricItem,
  MigrationExportTask,
  MigrationImportTask,
  MigrationHealth,
  ReportBundleExport,
  ServerTask,
  SqliteBackupCleanupResult,
  SqliteBackupScanResult,
  SqliteVacuumResult,
  SqliteVacuumScan,
  SpaceCleanupResult,
  SpaceCleanupScanResult,
  Tower,
  UpgradePostCleanupStatus,
  UpgradeTask,
  UpgradeVerification,
  VmDetail,
  VmTrend,
  VmUsageSummaryItem,
  VmVolume,
  VmVolumePage
} from "../types";

const API_BASE = import.meta.env.VITE_API_BASE || "";
const TOKEN_KEY = "smartx-storage-token";
export const AUTH_CHANGED_EVENT = "smartx-auth-changed";

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string | null): void {
  if (token) {
    localStorage.setItem(TOKEN_KEY, token);
  } else {
    localStorage.removeItem(TOKEN_KEY);
  }
  window.dispatchEvent(new Event(AUTH_CHANGED_EVENT));
}

const DEFAULT_REQUEST_TIMEOUT_MS = 30_000;

async function request<T>(path: string, options: RequestInit & { timeoutMs?: number } = {}): Promise<T> {
  const token = getToken();
  const headers = new Headers(options.headers);
  headers.set("Content-Type", "application/json");
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), options.timeoutMs ?? DEFAULT_REQUEST_TIMEOUT_MS);
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, { ...options, headers, signal: controller.signal });
  } catch (exc) {
    window.clearTimeout(timer);
    if (exc instanceof DOMException && exc.name === "AbortError") {
      throw new Error("请求超时");
    }
    throw new Error(exc instanceof Error ? exc.message : "网络请求失败");
  }
  window.clearTimeout(timer);
  if (!response.ok) {
    const payload = await response.json().catch(() => ({ detail: response.statusText }));
    if (response.status === 401) {
      setToken(null);
      throw new Error(payload.detail || "登录已过期，请重新登录。");
    }
    throw new Error(payload.detail || response.statusText);
  }
  return response.json() as Promise<T>;
}

export type TransferPhase = "uploading" | "processing" | "done";

export interface TransferProgress {
  progress: number;
  loaded?: number;
  total?: number;
  speedBytesPerSecond?: number;
  phase?: TransferPhase;
}

type ProgressCallback = (progress: number | TransferProgress) => void;

export interface DownloadResult {
  blob: Blob;
  filename: string;
  savedPath?: string;
  downloadUrl?: string;
}

async function download(path: string, onProgress?: ProgressCallback, init?: { method?: string; jsonBody?: unknown }): Promise<DownloadResult> {
  const token = getToken();
  const headers = new Headers();
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  const hasBody = init?.jsonBody !== undefined;
  if (hasBody) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(`${API_BASE}${path}`, {
    headers,
    method: init?.method ?? "GET",
    body: hasBody ? JSON.stringify(init?.jsonBody) : undefined
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({ detail: response.statusText }));
    if (response.status === 401) {
      setToken(null);
      throw new Error(payload.detail || "登录已过期，请重新登录。");
    }
    throw new Error(payload.detail || response.statusText);
  }
  const filename = filenameFromDisposition(response.headers.get("Content-Disposition"));
  const savedPath = response.headers.get("X-SmartX-Export-Path") || undefined;
  const downloadUrl = response.headers.get("X-SmartX-Export-Url") || undefined;
  const total = Number(response.headers.get("Content-Length") || 0);
  if (!response.body || !total) {
    onProgress?.(90);
    return { blob: await response.blob(), filename, savedPath, downloadUrl };
  }
  const reader = response.body.getReader();
  const chunks: Uint8Array[] = [];
  let received = 0;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    if (value) {
      chunks.push(value);
      received += value.length;
      onProgress?.(Math.min(95, Math.round((received / total) * 100)));
    }
  }
  return { blob: new Blob(chunks.map((chunk) => chunk.slice()) as BlobPart[]), filename, savedPath, downloadUrl };
}

async function upload<T>(path: string, formData: FormData, onProgress?: ProgressCallback): Promise<T> {
  if (!onProgress) {
    const token = getToken();
    const headers = new Headers();
    if (token) {
      headers.set("Authorization", `Bearer ${token}`);
    }
    const response = await fetch(`${API_BASE}${path}`, { method: "POST", headers, body: formData });
    if (!response.ok) {
      const payload = await response.json().catch(() => ({ detail: response.statusText }));
      if (response.status === 401) {
        setToken(null);
        throw new Error(payload.detail || "登录已过期，请重新登录。");
      }
      throw new Error(payload.detail || response.statusText);
    }
    return response.json() as Promise<T>;
  }

  return new Promise<T>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_BASE}${path}`);
    const token = getToken();
    if (token) {
      xhr.setRequestHeader("Authorization", `Bearer ${token}`);
    }
    const startedAt = Date.now();
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) {
        const elapsedSeconds = Math.max((Date.now() - startedAt) / 1000, 0.1);
        onProgress({
          progress: Math.min(95, Math.round((event.loaded / event.total) * 100)),
          loaded: event.loaded,
          total: event.total,
          speedBytesPerSecond: event.loaded / elapsedSeconds,
          phase: "uploading"
        });
      }
    };
    xhr.upload.onload = () => {
      onProgress({
        progress: 96,
        phase: "processing"
      });
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        onProgress({ progress: 100, phase: "done" });
        resolve(JSON.parse(xhr.responseText) as T);
        return;
      }
      let detail = xhr.statusText;
      try {
        detail = JSON.parse(xhr.responseText).detail || detail;
      } catch {
        // ignore invalid JSON error responses
      }
      if (xhr.status === 401) setToken(null);
      reject(new Error(detail || "请求失败"));
    };
    xhr.onerror = () => reject(new Error("网络请求失败"));
    xhr.send(formData);
  });
}

function scopedParams(scope?: DashboardScope, periodDays?: number): URLSearchParams {
  const params = new URLSearchParams();
  if (scope?.type === "tower" || scope?.type === "cluster") {
    params.set("tower_id", String(scope.towerId));
  }
  if (scope?.type === "cluster") {
    params.set("cluster_id", scope.clusterId);
  }
  if (periodDays) {
    params.set("period_days", String(periodDays));
  }
  return params;
}

function scopedQuery(scope?: DashboardScope, periodDays?: number): string {
  const params = scopedParams(scope, periodDays);
  const query = params.toString();
  return query ? `?${query}` : "";
}

function normalizeVmTrend(payload: unknown, metric: string): VmTrend {
  const raw = payload && typeof payload === "object" ? (payload as Record<string, unknown>) : {};
  const points = Array.isArray(raw.points)
    ? raw.points
        .map((point): [number, number] | null => {
          if (Array.isArray(point)) return [numberish(point[0]), numberish(point[1])];
          if (point && typeof point === "object") {
            const record = point as Record<string, unknown>;
            return [numberish(record.timestamp), numberish(record.used_bytes ?? record.value)];
          }
          return null;
        })
        .filter((point): point is [number, number] => Boolean(point))
    : [];
  return {
    vm_id: String(raw.vm_id || ""),
    metric,
    points,
    tower_id: optionalNumber(raw.tower_id) ?? undefined,
    cluster_id: raw.cluster_id == null ? undefined : String(raw.cluster_id),
    vm_name: raw.vm_name == null ? undefined : String(raw.vm_name),
    latest_success_at: raw.latest_success_at == null ? null : String(raw.latest_success_at),
    latest_collection_status: raw.latest_collection_status == null ? "unknown" : String(raw.latest_collection_status),
    has_collection_gap: Boolean(raw.has_collection_gap),
    gap_dates: Array.isArray(raw.gap_dates) ? raw.gap_dates.map((item) => String(item)) : [],
    data_freshness: raw.data_freshness == null ? "fresh" : String(raw.data_freshness)
  };
}

function numberish(value: unknown): number {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return 0;
}

function optionalNumber(value: unknown): number | null {
  if (value == null) return null;
  const parsed = numberish(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function filenameFromDisposition(disposition: string | null): string {
  if (!disposition) return "";
  const encoded = disposition.match(/filename\*=UTF-8''([^;]+)/i)?.[1];
  if (encoded) return decodeURIComponent(encoded);
  const plain = disposition.match(/filename="?([^";]+)"?/i)?.[1];
  return plain ? decodeURIComponent(plain) : "";
}

export const api = {
  async login(username: string, password: string): Promise<LoginResponse> {
    return request<LoginResponse>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password })
    });
  },
  async changePassword(payload: { current_password: string; new_password: string; confirm_password: string }): Promise<{ ok: boolean }> {
    return request<{ ok: boolean }>("/api/me/password", {
      method: "PUT",
      body: JSON.stringify(payload)
    });
  },
  async summary(scope?: DashboardScope): Promise<DashboardSummary> {
    const params = scopedParams(scope);
    const query = params.toString();
    return request<DashboardSummary>(`/api/dashboard/summary${query ? `?${query}` : ""}`);
  },
  async towers(): Promise<Tower[]> {
    return request<Tower[]>("/api/towers");
  },
  async testTowerParams(payload: { base_url: string; username?: string; password?: string; api_token?: string; verify_tls: boolean }): Promise<{ ok: boolean; message: string; clusters: Array<{ cluster_id: string; name: string; enabled: boolean }> }> {
    return request("/api/towers/test", { method: "POST", body: JSON.stringify(payload) });
  },
  async createTower(payload: Record<string, unknown>): Promise<Tower> {
    return request<Tower>("/api/towers", { method: "POST", body: JSON.stringify(payload) });
  },
  async updateTower(id: number, payload: Record<string, unknown>): Promise<Tower> {
    return request<Tower>(`/api/towers/${id}`, { method: "PUT", body: JSON.stringify(payload) });
  },
  async deleteTower(id: number): Promise<{ ok: boolean }> {
    return request<{ ok: boolean }>(`/api/towers/${id}`, { method: "DELETE" });
  },
  async testTower(id: number): Promise<{ ok: boolean; message: string }> {
    return request<{ ok: boolean; message: string }>(`/api/towers/${id}/test`, { method: "POST" });
  },
  async updateCluster(towerId: number, clusterId: string, payload: { enabled?: boolean; name?: string }): Promise<{ cluster_id: string; name: string; enabled: boolean }> {
    return request<{ cluster_id: string; name: string; enabled: boolean }>(`/api/towers/${towerId}/clusters/${encodeURIComponent(clusterId)}`, {
      method: "PUT",
      body: JSON.stringify(payload)
    });
  },
  async runCollection(taskId?: string): Promise<{ run_id: number; status: string; message: string; task_id?: string }> {
    return request<{ run_id: number; status: string; message: string; task_id?: string }>("/api/collection/run", {
      method: "POST",
      body: taskId ? JSON.stringify({ task_id: taskId }) : undefined
    });
  },
  async vms(scope?: DashboardScope): Promise<MetricItem[]> {
    const params = scopedParams(scope);
    const query = params.toString();
    return request<MetricItem[]>(`/api/vms${query ? `?${query}` : ""}`);
  },
  async vmVolumesPage(scope?: DashboardScope, options?: { page?: number; pageSize?: number; sort?: string; order?: string }): Promise<VmVolumePage> {
    const params = scopedParams(scope);
    if (options?.page) params.set("page", String(options.page));
    if (options?.pageSize) params.set("page_size", String(options.pageSize));
    if (options?.sort) params.set("sort", options.sort);
    if (options?.order) params.set("order", options.order);
    const query = params.toString();
    return request<VmVolumePage>(`/api/vm-volumes${query ? `?${query}` : ""}`);
  },
  async vmVolumesUsageSummary(scope?: DashboardScope): Promise<VmUsageSummaryItem[]> {
    const params = scopedParams(scope);
    const query = params.toString();
    const payload = await request<{ usages: VmUsageSummaryItem[] }>(`/api/vm-volumes/usage-summary${query ? `?${query}` : ""}`);
    return payload.usages || [];
  },
  async vmTrend(vmId: string, metric = "used", days = 30, scope?: DashboardScope): Promise<VmTrend> {
    const params = scopedParams(scope);
    params.set("metric", metric);
    params.set("days", String(days));
    const payload = await request<unknown>(`/api/vms/${encodeURIComponent(vmId)}/trend?${params.toString()}`);
    return normalizeVmTrend(payload, metric);
  },
  async vmDetail(vmId: string, scope?: DashboardScope): Promise<VmDetail> {
    const params = scopedParams(scope);
    const query = params.toString();
    return request<VmDetail>(`/api/vms/${encodeURIComponent(vmId)}${query ? `?${query}` : ""}`);
  },
  async vmVolumes(vmId: string, scope?: DashboardScope): Promise<{ vm_id: string; volumes: VmVolume[] }> {
    const params = scopedParams(scope);
    const query = params.toString();
    const payload = await request<VmVolume[] | { vm_id: string; volumes: VmVolume[] }>(`/api/vms/${encodeURIComponent(vmId)}/volumes${query ? `?${query}` : ""}`);
    return Array.isArray(payload) ? { vm_id: vmId, volumes: payload } : payload;
  },
  async report(scope?: DashboardScope, periodDays?: number, chartDays?: number): Promise<ForecastPayload> {
    const params = scopedParams(scope, periodDays);
    if (chartDays) {
      params.set("chart_days", String(chartDays));
    }
    const query = params.toString();
    return request<ForecastPayload>(`/api/reports/latest${query ? `?${query}` : ""}`);
  },
  async exportReport(format: "word" | "excel", scope?: DashboardScope, periodDays?: number, onProgress?: ProgressCallback): Promise<DownloadResult> {
    return download(`/api/reports/export/${format}${scopedQuery(scope, periodDays)}`, onProgress);
  },
  async exportReportBundle(scope?: DashboardScope, periodDays?: number, taskId?: string): Promise<ReportBundleExport> {
    const params = scopedParams(scope, periodDays);
    if (taskId) {
      params.set("task_id", taskId);
    }
    const query = params.toString();
    return request<ReportBundleExport>(`/api/reports/export/bundle${query ? `?${query}` : ""}`, { method: "POST" });
  },
  async tasks(): Promise<ServerTask[]> {
    return request<ServerTask[]>("/api/tasks");
  },
  async clearFinishedTasks(): Promise<{ deleted: number }> {
    return request<{ deleted: number }>("/api/tasks/finished", { method: "DELETE" });
  },
  async markTasksSeen(taskIds: string[]): Promise<{ updated: number }> {
    return request<{ updated: number }>("/api/tasks/seen", { method: "POST", body: JSON.stringify({ task_ids: taskIds }) });
  },
  async acknowledgeTask(taskId: string): Promise<ServerTask> {
    return request<ServerTask>(`/api/tasks/${taskId}/ack`, { method: "POST" });
  },
  async clearClearableTasks(): Promise<{ deleted: number }> {
    return request<{ deleted: number }>("/api/tasks/clearable", { method: "DELETE" });
  },
  async deleteTask(taskId: string): Promise<{ ok: boolean; task_id: string }> {
    return request<{ ok: boolean; task_id: string }>(`/api/tasks/${taskId}`, { method: "DELETE" });
  },
  async exportMigration(onProgress?: ProgressCallback): Promise<DownloadResult> {
    return download("/api/admin/migration/export", onProgress);
  },
  async exportConfigMigration(onProgress?: ProgressCallback): Promise<DownloadResult> {
    return download("/api/admin/migration/config/export", onProgress);
  },
  async startMigrationExport(): Promise<MigrationExportTask> {
    return request<MigrationExportTask>("/api/admin/migration/export/start", { method: "POST" });
  },
  async migrationExportStatus(taskId: string): Promise<MigrationExportTask> {
    return request<MigrationExportTask>(`/api/admin/migration/export/status/${taskId}`);
  },
  async startMigrationImport(file: File, mode: "merge" | "overwrite", confirmed: boolean, onProgress?: ProgressCallback): Promise<MigrationImportTask> {
    const formData = new FormData();
    formData.set("file", file);
    formData.set("mode", mode);
    formData.set("confirmed", String(confirmed));
    return upload<MigrationImportTask>("/api/admin/migration/import/start", formData, onProgress);
  },
  async migrationImportStatus(taskId: string): Promise<MigrationImportTask> {
    return request<MigrationImportTask>(`/api/admin/migration/import/status/${taskId}`);
  },
  async migrationHealth(): Promise<MigrationHealth> {
    return request<MigrationHealth>("/api/admin/migration/health");
  },
  async downloadSavedExport(url: string, onProgress?: ProgressCallback): Promise<DownloadResult> {
    return download(url, onProgress);
  },
  async importMigration(file: File, mode: "merge" | "overwrite", confirmed: boolean, onProgress?: ProgressCallback): Promise<{ ok: boolean; restored: string[]; message: string; backup_path?: string; task_id?: string; saved_path?: string; summary?: { health?: { message?: string; checks?: Record<string, boolean> } } }> {
    const formData = new FormData();
    formData.set("file", file);
    formData.set("mode", mode);
    formData.set("confirmed", String(confirmed));
    return upload<{ ok: boolean; restored: string[]; message: string; backup_path?: string; task_id?: string; saved_path?: string; summary?: { health?: { message?: string; checks?: Record<string, boolean> } } }>("/api/admin/migration/import", formData, onProgress);
  },
  async restartSystemServices(): Promise<{ ok: boolean; services: string[]; message: string }> {
    return request<{ ok: boolean; services: string[]; message: string }>("/api/admin/system/restart", { method: "POST" });
  },
  async scanUnusedImages(): Promise<{ ok: boolean; images: Array<{ id: string; short_id: string; repo_tags: string[]; display_name: string; size: number; size_label: string; reclaimable_size?: number; reclaimable_size_label?: string; created_at?: number | string; category?: "dangling" | "unused" }>; protected_images?: Array<{ id: string; short_id: string; repo_tags: string[]; display_name: string; size: number; size_label: string }>; protected_count?: number; protected_size_label?: string; image_count: number; space_reclaimable: number; space_reclaimable_label: string; message: string }> {
    return request<{ ok: boolean; images: Array<{ id: string; short_id: string; repo_tags: string[]; display_name: string; size: number; size_label: string; reclaimable_size?: number; reclaimable_size_label?: string; created_at?: number | string; category?: "dangling" | "unused" }>; protected_images?: Array<{ id: string; short_id: string; repo_tags: string[]; display_name: string; size: number; size_label: string }>; protected_count?: number; protected_size_label?: string; image_count: number; space_reclaimable: number; space_reclaimable_label: string; message: string }>("/api/admin/system/cleanup-images/scan");
  },
  async cleanupUnusedImages(imageIds?: string[]): Promise<{ ok: boolean; deleted_count: number; space_reclaimed: number; space_reclaimed_label?: string; space_reclaimable_before?: number; space_reclaimable_before_label?: string; errors?: string[]; logs?: string[]; message: string }> {
    const ids = (imageIds || []).filter((id) => id.trim());
    return request<{ ok: boolean; deleted_count: number; space_reclaimed: number; space_reclaimed_label?: string; space_reclaimable_before?: number; space_reclaimable_before_label?: string; errors?: string[]; logs?: string[]; message: string }>("/api/admin/system/cleanup-images", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ image_ids: ids }) });
  },
  async downloadEnvFile(password: string): Promise<DownloadResult> {
    return download("/api/admin/migration/env-file", undefined, { method: "POST", jsonBody: { password } });
  },
  async scanSpaceCleanup(): Promise<SpaceCleanupScanResult> {
    return request<SpaceCleanupScanResult>("/api/admin/system/cleanup-artifacts/scan");
  },
  async cleanupSpaceArtifacts(keepRecentUpgrades = 0): Promise<SpaceCleanupResult> {
    return request<SpaceCleanupResult>("/api/admin/system/cleanup-artifacts", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ keep_recent_upgrades: Math.max(0, Math.min(100, Math.floor(keepRecentUpgrades) || 0)) }) });
  },
  async localStorageUsage(): Promise<LocalStorageUsage> {
    return request<LocalStorageUsage>("/api/admin/system/local-storage");
  },
  async scanSqliteVacuum(): Promise<SqliteVacuumScan> {
    return request<SqliteVacuumScan>("/api/admin/system/sqlite-vacuum/scan");
  },
  async vacuumSqlite(): Promise<SqliteVacuumResult> {
    return request<SqliteVacuumResult>("/api/admin/system/sqlite-vacuum", { method: "POST" });
  },
  async scanSqliteBackups(): Promise<SqliteBackupScanResult> {
    return request<SqliteBackupScanResult>("/api/admin/system/sqlite-backups/scan");
  },
  async deleteSqliteBackups(filenames: string[]): Promise<SqliteBackupCleanupResult> {
    return request<SqliteBackupCleanupResult>("/api/admin/system/sqlite-backups/delete", { method: "POST", body: JSON.stringify({ filenames }) });
  },
  async upgradeVersion(): Promise<{ version: string }> {
    return request<{ version: string }>("/api/admin/upgrade/version");
  },
  async componentUpgradeVersion(): Promise<{ component: string; version: string }> {
    return request<{ component: string; version: string }>("/api/admin/component-upgrade/version");
  },
  async componentUpgradeComponents(): Promise<{ components: ComponentInfo[] }> {
    return request<{ components: ComponentInfo[] }>("/api/admin/component-upgrade/components");
  },
  async uploadUpgradePackage(file: File, onProgress?: ProgressCallback): Promise<UpgradeTask> {
    const formData = new FormData();
    formData.set("file", file);
    return upload<UpgradeTask>("/api/admin/upgrade/upload", formData, onProgress);
  },
  async precheckUpgrade(taskId: string): Promise<UpgradeTask> {
    return request<UpgradeTask>(`/api/admin/upgrade/precheck/${taskId}`, { method: "POST" });
  },
  async startUpgrade(taskId: string): Promise<UpgradeTask> {
    return request<UpgradeTask>(`/api/admin/upgrade/start/${taskId}`, { method: "POST" });
  },
  async rollbackUpgrade(taskId: string): Promise<UpgradeTask> {
    return request<UpgradeTask>(`/api/admin/upgrade/rollback/${taskId}`, { method: "POST" });
  },
  async continueUpgradeRecovery(taskId: string): Promise<UpgradeTask> {
    return request<UpgradeTask>(`/api/admin/upgrade/recovery/${taskId}/continue`, { method: "POST" });
  },
  async rollbackUpgradeRecovery(taskId: string): Promise<UpgradeTask> {
    return request<UpgradeTask>(`/api/admin/upgrade/recovery/${taskId}/rollback`, { method: "POST" });
  },
  async failUpgradeRecovery(taskId: string): Promise<UpgradeTask> {
    return request<UpgradeTask>(`/api/admin/upgrade/recovery/${taskId}/fail`, { method: "POST" });
  },
  async cancelUpgrade(taskId: string): Promise<UpgradeTask> {
    return request<UpgradeTask>(`/api/admin/upgrade/cancel/${taskId}`, { method: "POST" });
  },
  async deleteUpgradePackage(taskId: string): Promise<{ ok: boolean; task_id: string }> {
    return request<{ ok: boolean; task_id: string }>(`/api/admin/upgrade/package/${taskId}`, { method: "DELETE" });
  },
  async upgradeStatus(taskId: string): Promise<UpgradeTask> {
    return request<UpgradeTask>(`/api/admin/upgrade/status/${taskId}`);
  },
  async upgradeHistory(): Promise<UpgradeTask[]> {
    return request<UpgradeTask[]>("/api/admin/upgrade/history");
  },
  async upgradeVerification(): Promise<UpgradeVerification> {
    return request<UpgradeVerification>("/api/admin/upgrade/verification");
  },
  async upgradePostCleanupStatus(taskId: string): Promise<UpgradePostCleanupStatus> {
    return request<UpgradePostCleanupStatus>(`/api/admin/upgrade/post-cleanup/${taskId}`);
  },
  async retryUpgradePostCleanup(taskId: string): Promise<UpgradeTask> {
    return request<UpgradeTask>(`/api/admin/upgrade/post-cleanup/${taskId}/retry`, { method: "POST" });
  },
  async uploadComponentUpgradePackage(file: File, onProgress?: ProgressCallback): Promise<UpgradeTask> {
    const formData = new FormData();
    formData.set("file", file);
    return upload<UpgradeTask>("/api/admin/component-upgrade/upload", formData, onProgress);
  },
  async precheckComponentUpgrade(taskId: string): Promise<UpgradeTask> {
    return request<UpgradeTask>(`/api/admin/component-upgrade/precheck/${taskId}`, { method: "POST" });
  },
  async startComponentUpgrade(taskId: string): Promise<UpgradeTask> {
    return request<UpgradeTask>(`/api/admin/component-upgrade/start/${taskId}`, { method: "POST" });
  },
  async cancelComponentUpgrade(taskId: string): Promise<UpgradeTask> {
    return request<UpgradeTask>(`/api/admin/component-upgrade/cancel/${taskId}`, { method: "POST" });
  },
  async deleteComponentUpgradePackage(taskId: string): Promise<{ ok: boolean; task_id: string }> {
    return request<{ ok: boolean; task_id: string }>(`/api/admin/component-upgrade/package/${taskId}`, { method: "DELETE" });
  },
  async componentUpgradeStatus(taskId: string): Promise<UpgradeTask> {
    return request<UpgradeTask>(`/api/admin/component-upgrade/status/${taskId}`);
  },
  async componentUpgradeHistory(component?: string): Promise<UpgradeTask[]> {
    const query = component ? `?component=${encodeURIComponent(component)}` : "";
    return request<UpgradeTask[]>(`/api/admin/component-upgrade/history${query}`);
  }
};

export function formatBytes(value: number | undefined | null): string {
  if (value == null || value === 0) return "0 B";
  const sign = value < 0 ? "-" : "";
  const absolute = Math.abs(value);
  const units = ["B", "KiB", "MiB", "GiB", "TiB", "PiB"];
  const index = Math.min(Math.floor(Math.log(absolute) / Math.log(1024)), units.length - 1);
  return `${sign}${(absolute / 1024 ** index).toFixed(index < 3 ? 0 : 2)} ${units[index]}`;
}
