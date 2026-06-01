import type {
  DashboardScope,
  DashboardSummary,
  ForecastPayload,
  LoginResponse,
  MetricItem,
  Tower,
  UpgradeTask,
  VmTrend,
  VmVolume,
  VmVolumeSet
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

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = getToken();
  const headers = new Headers(options.headers);
  headers.set("Content-Type", "application/json");
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  const response = await fetch(`${API_BASE}${path}`, { ...options, headers });
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

type ProgressCallback = (progress: number) => void;

async function download(path: string, onProgress?: ProgressCallback): Promise<{ blob: Blob; filename: string }> {
  const token = getToken();
  const headers = new Headers();
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  const response = await fetch(`${API_BASE}${path}`, { headers });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({ detail: response.statusText }));
    if (response.status === 401) {
      setToken(null);
      throw new Error(payload.detail || "登录已过期，请重新登录。");
    }
    throw new Error(payload.detail || response.statusText);
  }
  const filename = filenameFromDisposition(response.headers.get("Content-Disposition"));
  const total = Number(response.headers.get("Content-Length") || 0);
  if (!response.body || !total) {
    onProgress?.(90);
    return { blob: await response.blob(), filename };
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
  return { blob: new Blob(chunks.map((chunk) => chunk.slice()) as BlobPart[]), filename };
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
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) {
        onProgress(Math.min(95, Math.round((event.loaded / event.total) * 100)));
      }
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        onProgress(100);
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
  async runCollection(): Promise<{ run_id: number; status: string; message: string }> {
    return request<{ run_id: number; status: string; message: string }>("/api/collection/run", { method: "POST" });
  },
  async vms(scope?: DashboardScope): Promise<MetricItem[]> {
    const params = scopedParams(scope);
    const query = params.toString();
    return request<MetricItem[]>(`/api/vms${query ? `?${query}` : ""}`);
  },
  async vmVolumesAll(scope?: DashboardScope): Promise<VmVolumeSet[]> {
    const params = scopedParams(scope);
    const query = params.toString();
    return request<VmVolumeSet[]>(`/api/vm-volumes${query ? `?${query}` : ""}`);
  },
  async vmTrend(vmId: string, metric = "used", days = 30, scope?: DashboardScope): Promise<VmTrend> {
    const params = scopedParams(scope);
    params.set("metric", metric);
    params.set("days", String(days));
    return request<VmTrend>(`/api/vms/${encodeURIComponent(vmId)}/trend?${params.toString()}`);
  },
  async vmVolumes(vmId: string, scope?: DashboardScope): Promise<{ vm_id: string; volumes: VmVolume[] }> {
    const params = scopedParams(scope);
    const query = params.toString();
    return request<{ vm_id: string; volumes: VmVolume[] }>(`/api/vms/${encodeURIComponent(vmId)}/volumes${query ? `?${query}` : ""}`);
  },
  async report(scope?: DashboardScope, periodDays?: number, chartDays?: number): Promise<ForecastPayload> {
    const params = scopedParams(scope, periodDays);
    if (chartDays) {
      params.set("chart_days", String(chartDays));
    }
    const query = params.toString();
    return request<ForecastPayload>(`/api/reports/latest${query ? `?${query}` : ""}`);
  },
  async exportReport(format: "word" | "excel", scope?: DashboardScope, periodDays?: number, onProgress?: ProgressCallback): Promise<{ blob: Blob; filename: string }> {
    return download(`/api/reports/export/${format}${scopedQuery(scope, periodDays)}`, onProgress);
  },
  async exportMigration(onProgress?: ProgressCallback): Promise<{ blob: Blob; filename: string }> {
    return download("/api/admin/migration/export", onProgress);
  },
  async importMigration(file: File, mode: "merge" | "overwrite", confirmed: boolean, onProgress?: ProgressCallback): Promise<{ ok: boolean; restored: string[]; message: string }> {
    const formData = new FormData();
    formData.set("file", file);
    formData.set("mode", mode);
    formData.set("confirmed", String(confirmed));
    return upload<{ ok: boolean; restored: string[]; message: string }>("/api/admin/migration/import", formData, onProgress);
  },
  async restartSystemServices(): Promise<{ ok: boolean; services: string[]; message: string }> {
    return request<{ ok: boolean; services: string[]; message: string }>("/api/admin/system/restart", { method: "POST" });
  },
  async upgradeVersion(): Promise<{ version: string }> {
    return request<{ version: string }>("/api/admin/upgrade/version");
  },
  async componentUpgradeVersion(): Promise<{ component: string; version: string }> {
    return request<{ component: string; version: string }>("/api/admin/component-upgrade/version");
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
  async deleteUpgradePackage(taskId: string): Promise<{ ok: boolean; task_id: string }> {
    return request<{ ok: boolean; task_id: string }>(`/api/admin/upgrade/package/${taskId}`, { method: "DELETE" });
  },
  async upgradeStatus(taskId: string): Promise<UpgradeTask> {
    return request<UpgradeTask>(`/api/admin/upgrade/status/${taskId}`);
  },
  async upgradeHistory(): Promise<UpgradeTask[]> {
    return request<UpgradeTask[]>("/api/admin/upgrade/history");
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
  async deleteComponentUpgradePackage(taskId: string): Promise<{ ok: boolean; task_id: string }> {
    return request<{ ok: boolean; task_id: string }>(`/api/admin/component-upgrade/package/${taskId}`, { method: "DELETE" });
  },
  async componentUpgradeStatus(taskId: string): Promise<UpgradeTask> {
    return request<UpgradeTask>(`/api/admin/component-upgrade/status/${taskId}`);
  },
  async componentUpgradeHistory(): Promise<UpgradeTask[]> {
    return request<UpgradeTask[]>("/api/admin/component-upgrade/history");
  }
};

export function formatBytes(value: number | undefined | null): string {
  if (!value || value <= 0) return "0 B";
  const units = ["B", "KiB", "MiB", "GiB", "TiB", "PiB"];
  const index = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1);
  return `${(value / 1024 ** index).toFixed(index < 3 ? 0 : 2)} ${units[index]}`;
}
