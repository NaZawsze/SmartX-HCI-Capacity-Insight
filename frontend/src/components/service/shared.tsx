import { Check, Circle, FileArchive, Info, LoaderCircle, RefreshCw, Upload, X } from "lucide-react";
import type { ReactNode } from "react";
import type { TransferProgress } from "../../services/api";
import type { AppTask, ComponentInfo, LocalStorageUsage, MigrationExportTask, MigrationImportTask, UpgradePostCleanupStatus, UpgradeTask, UpgradeVerification } from "../../types";

export type ServiceSection = "migration" | "restart" | "space-cleanup" | "platform-upgrade" | "component-upgrade" | "history";
export type CleanupScanImage = { id: string; short_id: string; repo_tags: string[]; display_name: string; size: number; size_label: string; reclaimable_size?: number; reclaimable_size_label?: string; created_at?: number | string; category?: "dangling" | "unused" };
export type UpgradeCheck = UpgradeTask["checks"][number];
export type PrecheckStepDefinition = { key: string; title: string; checks: string[] };
export type DisplayStep = { key: string; title: string; status: string; message?: string };
export type RestartWindowState = { startedAt: number; lastError: string };

export const runningUpgradeStatuses = new Set(["pending", "running", "rollback_pending", "rollback_running"]);
export const restartWindowTimeoutMs = 5 * 60 * 1000;
export const serviceItems = [
  { name: "web-api", description: "提供页面 API、报表导出、数据迁移和升级接口。" },
  { name: "collector-worker", description: "负责定时采集 Tower、集群和虚拟机容量数据。" },
  { name: "prometheus", description: "保存历史指标和趋势样本。" }
];
export const upgradeStepDefaults = [
  { key: "backup", title: "生成升级前数据备份" },
  { key: "load_images", title: "加载升级镜像" },
  { key: "write_override", title: "写入服务镜像覆盖配置" },
  { key: "migration", title: "执行数据库迁移脚本" },
  { key: "restart", title: "重启升级服务" },
  { key: "healthcheck", title: "执行服务健康检查" }
];
export const rollbackStepDefaults = [
  { key: "rollback_config", title: "恢复升级前镜像配置" },
  { key: "rollback_restart", title: "重启回滚服务" },
  { key: "rollback_healthcheck", title: "执行回滚健康检查" }
];
export const componentStepDefaults = [
  { key: "load_images", title: "加载组件镜像" },
  { key: "write_override", title: "写入组件镜像覆盖配置" },
  { key: "restart", title: "重启升级中心组件" },
  { key: "healthcheck", title: "检查组件运行状态" }
];
export const platformPrecheckStepDefaults = [
  { key: "manifest", title: "校验升级包结构", checks: ["manifest"] },
  { key: "paths", title: "检查项目文件与敏感路径", checks: ["paths", "project_files"] },
  { key: "runner_protocol", title: "校验版本兼容性与升级执行器", checks: ["source_compatibility", "runner_protocol"] },
  { key: "images", title: "校验镜像名、Tag 与 SHA256", checks: ["checksums", "images"] },
  { key: "observability", title: "检查观测组件数据权限", checks: ["prometheus_permissions"] },
  { key: "summary", title: "生成预检查结果", checks: [] }
] satisfies PrecheckStepDefinition[];
export const componentPrecheckStepDefaults = [
  { key: "manifest", title: "校验组件包结构", checks: ["manifest"] },
  { key: "paths", title: "检查组件包路径安全", checks: ["paths"] },
  { key: "runner_protocol", title: "校验组件版本兼容性与执行器", checks: ["runner_protocol"] },
  { key: "images", title: "校验组件镜像与 SHA256", checks: ["checksums", "images"] },
  { key: "observability", title: "检查观测组件数据权限", checks: ["prometheus_permissions"] },
  { key: "summary", title: "生成组件预检查结果", checks: [] }
] satisfies PrecheckStepDefinition[];
export const defaultComponentInfos: ComponentInfo[] = [
  {
    type: "runner",
    display_name: "升级中心组件",
    service: "upgrade-runner",
    version: "v0.3.0",
    executor: "web-api",
    upgradeable: true,
    status_message: "由 web-api 执行自升级，不修改业务库和历史指标。"
  },
  {
    type: "observability",
    display_name: "观测组件",
    service: "prometheus",
    version: "-",
    executor: "upgrade-runner",
    upgradeable: true,
    status_message: "由 upgrade-runner 执行升级，保留 Prometheus 历史指标。"
  }
];

export function taskBelongsToComponent(task: UpgradeTask | null | undefined, service: string): boolean {
  if (!task) return false;
  if (task.component === service) return true;
  const components = task.components ?? [];
  if (service === "upgrade-runner") return components.includes("runner");
  if (service === "prometheus") return components.includes("observability");
  return false;
}

export function componentServiceFromTask(task: UpgradeTask): string | undefined {
  if (task.component) return task.component;
  const components = task.components ?? [];
  if (components.includes("runner")) return "upgrade-runner";
  if (components.includes("observability")) return "prometheus";
  return undefined;
}

export function errorMessage(exc: unknown, fallback: string): string {
  return exc instanceof Error && exc.message ? exc.message : fallback;
}

export function isRecoverableRestartError(exc: unknown): boolean {
  const message = errorMessage(exc, "").toLowerCase();
  if (!message) return false;
  return (
    message.includes("internal server error") ||
    message.includes("failed to fetch") ||
    message.includes("networkerror") ||
    message.includes("connection reset") ||
    message.includes("connection refused") ||
    /\b50[0-4]\b/.test(message)
  );
}

export function restartWindowMessage(
  exc: unknown,
  stateRef: { current: RestartWindowState | null },
  reconnectingMessage: string,
  fallbackError: string
): string {
  const message = errorMessage(exc, fallbackError) || "Internal Server Error";
  if (!isRecoverableRestartError(exc)) {
    stateRef.current = null;
    return message;
  }
  const now = Date.now();
  if (!stateRef.current) {
    stateRef.current = { startedAt: now, lastError: message };
  } else {
    stateRef.current.lastError = message;
  }
  if (now - stateRef.current.startedAt >= restartWindowTimeoutMs) {
    const finalMessage = stateRef.current.lastError || message || "Internal Server Error";
    stateRef.current = null;
    return finalMessage;
  }
  return reconnectingMessage;
}

export function taskId(prefix: string) {
  return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export function saveBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename || "smartx-storage-migration.tar.gz";
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

export function formatUnknownCount(value: unknown): string {
  if (typeof value === "number" && Number.isFinite(value)) return String(value);
  if (typeof value === "string" && value.trim()) return value;
  return "-";
}

export function scrollElementToTop(element: HTMLElement | null) {
  if (!element) return;
  if (typeof element.scrollTo === "function") {
    element.scrollTo({ top: 0 });
    return;
  }
  element.scrollTop = 0;
}

export function upgradeStatusText(status: string): string {
  const labels: Record<string, string> = {
    uploaded: "已上传",
    prechecked: "预检查通过",
    pending: "等待执行",
    running: "升级中",
    success: "升级成功",
    succeeded: "升级成功",
    failed: "升级失败",
    rollback_pending: "等待回滚",
    rollback_running: "回滚中",
    rolled_back: "已回滚",
    rollback_failed: "回滚失败",
    recovery_required: "需要恢复处理"
  };
  return labels[status] ?? status;
}

export function postCleanupStatusText(status?: UpgradePostCleanupStatus | null): string {
  if (!status) return "-";
  const labels: Record<string, string> = {
    not_required: "不需要",
    pending: "等待清理",
    running: "清理中",
    success: "清理完成",
    succeeded: "清理完成",
    warning: "清理有告警",
    failed: "清理失败",
    cancelled: "已取消"
  };
  return labels[status.status] ?? status.status;
}

export function stepStatusText(status: string): string {
  const labels: Record<string, string> = {
    pending: "未执行",
    running: "执行中",
    succeeded: "完成",
    failed: "失败"
  };
  return labels[status] ?? status;
}

export function stepIcon(status: string) {
  if (status === "succeeded") return <Check size={14} />;
  if (status === "failed") return <X size={14} />;
  if (status === "running") return <LoaderCircle size={14} />;
  return <Circle size={14} />;
}

export function displayUpgradeSteps(task: UpgradeTask, isComponent = false) {
  if (task.steps.length > 0) return task.steps;
  if (isComponent) return [];
  const defaults = task.status.startsWith("rollback") || task.status === "rolled_back" ? rollbackStepDefaults : upgradeStepDefaults;
  const existing = new Map(task.steps.map((step) => [step.key, step]));
  const merged = defaults.map((item) => ({ ...item, status: "pending", ...existing.get(item.key) }));
  const known = new Set(defaults.map((item) => item.key));
  return [...merged, ...task.steps.filter((step) => !known.has(step.key))];
}

export function displayPrecheckSteps(task: UpgradeTask, isComponent: boolean, running: boolean, progressIndex: number): DisplayStep[] {
  const defaults = isComponent ? componentPrecheckStepDefaults : platformPrecheckStepDefaults;
  if (running) {
    return defaults.map((item, index) => ({
      ...item,
      status: index < progressIndex ? "succeeded" : index === progressIndex ? "running" : "pending"
    }));
  }
  if (task.checks.length) {
    const checksByName = new Map(task.checks.map((check) => [check.name, check]));
    const failed = task.checks.some((check) => !check.ok);
    const applicableDefaults = defaults.filter((item, index) => index === defaults.length - 1 || item.checks.some((name) => checksByName.has(name)));
    return applicableDefaults.map((item, index) => {
      const isLast = index === applicableDefaults.length - 1;
      if (!isLast) {
        const relatedChecks = item.checks.map((name) => checksByName.get(name)).filter((check): check is UpgradeCheck => Boolean(check));
        const relatedFailed = relatedChecks.filter((check) => !check.ok);
        return {
          key: item.key,
          title: item.title,
          status: relatedFailed.length ? "failed" : relatedChecks.length > 0 ? "succeeded" : "pending",
          message: relatedFailed.length ? formatCheckMessages(relatedFailed) : formatCheckMessages(relatedChecks)
        };
      }
      return {
        key: item.key,
        title: item.title,
        status: failed && isLast ? "failed" : "succeeded",
        message: isLast ? (failed ? "预检查未通过" : "预检查通过") : undefined
      };
    });
  }
  return defaults.map((item) => ({ ...item, status: "pending" }));
}

export function formatCheckMessages(checks: UpgradeCheck[]): string | undefined {
  if (!checks.length) return undefined;
  return checks.map((check) => {
    const detail = formatCheckDetail(check.detail);
    return detail ? `${check.message} ${detail}` : check.message;
  }).join(" ");
}

export function formatCheckDetail(detail: unknown): string {
  if (!detail) return "";
  if (Array.isArray(detail)) {
    return detail.map((item) => String(item)).filter(Boolean).join("；");
  }
  if (typeof detail === "object") {
    return Object.entries(detail as Record<string, unknown>).map(([key, value]) => `${key}: ${String(value)}`).join("；");
  }
  return String(detail);
}

export function sourceCompatibilityLabel(task?: UpgradeTask | null): string {
  const check = task?.checks?.find((item) => item.name === "source_compatibility");
  const checkDetail = check?.detail && typeof check.detail === "object" ? (check.detail as Record<string, unknown>) : undefined;
  const manifest = task?.manifest && typeof task.manifest === "object" ? task.manifest : undefined;
  const sourceCompatibility = manifest?.source_compatibility && typeof manifest.source_compatibility === "object" ? (manifest.source_compatibility as Record<string, unknown>) : undefined;
  const versions = checkDetail?.supported_versions ?? sourceCompatibility?.supported_versions;
  if (Array.isArray(versions) && versions.length) {
    return versions.map((item) => String(item)).join("、");
  }
  const minVersion = String(checkDetail?.min_version ?? sourceCompatibility?.min_version ?? manifest?.min_version ?? "");
  const maxVersion = String(checkDetail?.max_version_inclusive ?? sourceCompatibility?.max_version_inclusive ?? task?.target_version ?? "");
  if (minVersion && maxVersion) return `${minVersion} 至 ${maxVersion}`;
  if (minVersion) return `${minVersion} 及以上`;
  return "-";
}

export function stringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.map((item) => String(item)).filter(Boolean);
}

export function runnerRequirementLabel(task?: UpgradeTask | null, runner?: ComponentInfo): string {
  if (!task) return "-";
  const protocolCheck = task.checks?.find((item) => item.name === "runner_protocol");
  const detail = protocolCheck?.detail && typeof protocolCheck.detail === "object" ? (protocolCheck.detail as Record<string, unknown>) : undefined;
  const manifest = task.manifest && typeof task.manifest === "object" ? task.manifest : undefined;
  const required = stringArray(detail?.required_capabilities ?? manifest?.required_capabilities);
  const current = stringArray(detail?.capabilities ?? runner?.capabilities);
  const missing = required.filter((item) => !current.includes(item));
  const needsProjectMigration = required.includes("compose.project_migrate.v1");
  if (missing.length) return `缺少 ${missing.join("、")}`;
  if (needsProjectMigration) return "需要 Runner v0.3.1+（项目/网络迁移能力）";
  if (required.length) return "当前 Runner 能力满足";
  return "-";
}

export function migrationExportTaskPatch(task: MigrationExportTask): Partial<Omit<AppTask, "id" | "createdAt">> {
  return {
    status: task.status === "failed" ? "failed" : task.status === "succeeded" ? "succeeded" : "running",
    progress: Math.max(0, Math.min(100, task.progress || 0)),
    detail: task.detail || migrationExportStatusText(task.status),
    logs: task.logs,
    steps: task.steps,
    links: task.status === "succeeded" && task.download_url ? [{ label: "下载", filename: task.filename, url: task.download_url, path: task.saved_path }] : undefined
  };
}

export function migrationExportStatusText(status: MigrationExportTask["status"]): string {
  const labels: Record<MigrationExportTask["status"], string> = {
    pending: "等待开始导出",
    running: "正在生成迁移包",
    succeeded: "迁移包已生成",
    failed: "导出失败"
  };
  return labels[status];
}

export function migrationImportTaskPatch(task: MigrationImportTask): Partial<Omit<AppTask, "id" | "createdAt">> {
  const backupLog = task.backup_path ? [`导入前备份：${task.backup_path}`] : [];
  return {
    status: task.status === "failed" ? "failed" : task.status === "succeeded" ? "succeeded" : "running",
    progress: Math.max(0, Math.min(100, task.progress || 0)),
    detail: task.detail || migrationImportStatusText(task.status),
    logs: [...(task.logs || []), ...backupLog],
    steps: task.steps,
    links: task.backup_path ? [{ label: "导入前备份", filename: task.backup_path.split("/").pop(), url: "", path: task.backup_path }] : task.links
  };
}

export function migrationImportStatusText(status: MigrationImportTask["status"]): string {
  const labels: Record<MigrationImportTask["status"], string> = {
    pending: "等待开始导入",
    running: "正在导入迁移包",
    succeeded: "数据迁移导入完成",
    failed: "导入失败"
  };
  return labels[status];
}

export function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

export function formatTime(value?: string): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", { hour12: false });
}

export function formatUnixTime(value?: number | string): string {
  if (!value) return "-";
  if (typeof value === "number") return formatTime(new Date(value * 1000).toISOString());
  return formatTime(value);
}

export function formatBytes(value?: number): string {
  let size = Number(value || 0);
  const units = ["B", "KiB", "MiB", "GiB", "TiB"];
  let index = 0;
  while (size >= 1024 && index < units.length - 1) {
    size /= 1024;
    index += 1;
  }
  return index < 2 ? `${size.toFixed(0)} ${units[index]}` : `${size.toFixed(2)} ${units[index]}`;
}

export function formatVersionForDisplay(value?: string | null, fallback = "-"): string {
  const normalized = String(value || "").trim();
  if (!normalized || normalized === "-") return fallback;
  return normalized.toLowerCase().startsWith("v") ? normalized : `v${normalized}`;
}

export function shortSha(value: string): string {
  return value.length > 16 ? `${value.slice(0, 12)}...${value.slice(-8)}` : value;
}

export function uploadProgressTaskPatch(progress: number | TransferProgress): { progress: number; detail: string } {
  if (typeof progress === "number") {
    return { progress, detail: `上传中 ${progress}%` };
  }
  if (progress.phase === "processing") {
    return {
      progress: Math.max(96, progress.progress),
      detail: "上传完成，正在保存、解压并校验文件..."
    };
  }
  if (progress.phase === "done") {
    return { progress: 100, detail: "文件处理完成" };
  }
  const speed = formatTransferSpeed(progress.speedBytesPerSecond);
  return {
    progress: progress.progress,
    detail: speed ? `上传中 ${progress.progress}% · ${speed}` : `上传中 ${progress.progress}%`
  };
}

export function transferProgressValue(progress: number | TransferProgress): number {
  return typeof progress === "number" ? progress : progress.progress;
}

export function formatTransferSpeed(value?: number): string {
  if (!value || !Number.isFinite(value)) return "";
  const units = ["B/s", "KB/s", "MB/s", "GB/s"];
  let size = value;
  let index = 0;
  while (size >= 1024 && index < units.length - 1) {
    size /= 1024;
    index += 1;
  }
  return `${size.toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}

export function upgradeProgress(task: UpgradeTask): number {
  if (task.status === "success" || task.status === "succeeded" || task.status === "rolled_back") return 100;
  if (task.status === "failed" || task.status === "rollback_failed") return 100;
  const total = task.steps.length || 6;
  const finished = task.steps.filter((step) => step.status === "succeeded").length;
  const running = task.steps.some((step) => step.status === "running") ? 0.5 : 0;
  return Math.min(95, Math.max(10, Math.round(((finished + running) / total) * 100)));
}

export function activeUpgradeDetail(task: UpgradeTask): string {
  const running = task.steps.find((step) => step.status === "running");
  if (running?.message) return running.message;
  if (running?.title) return running.title;
  const failed = task.steps.find((step) => step.status === "failed");
  if (failed?.message) return failed.message;
  return upgradeStatusText(task.status);
}

export function upgradeTaskStatus(task: UpgradeTask): AppTask["status"] {
  if (task.status === "success" || task.status === "succeeded" || task.status === "rolled_back") return "succeeded";
  if (task.status === "failed" || task.status === "rollback_failed") return "failed";
  return "running";
}

export function PageHeader({ eyebrow, title, action }: { eyebrow: string; title: string; action?: ReactNode }) {
  return (
    <div className="service-page-head">
      <div>
        <span>{eyebrow}</span>
        <h2>{title}</h2>
      </div>
      {action && <div className="service-page-action">{action}</div>}
    </div>
  );
}

export function InfoRow({ label, value, tone }: { label: string; value: ReactNode; tone?: "ok" | "warn" | "bad" }) {
  return (
    <div className="service-info-row">
      <span>{label}</span>
      <strong className={tone === "ok" ? "service-info-value-ok" : tone === "warn" ? "service-info-value-warn" : tone === "bad" ? "service-info-value-bad" : undefined}>{value}</strong>
    </div>
  );
}

export function CollapsibleSection({ title, expanded, onToggle, children }: { title: string; expanded: boolean; onToggle: () => void; children: ReactNode }) {
  return (
    <section className="upgrade-section">
      <button className="upgrade-section-toggle" type="button" onClick={onToggle} aria-expanded={expanded}>
        <span>{title}</span>
        <strong>{expanded ? "收起" : "展开"}</strong>
      </button>
      {expanded && children}
    </section>
  );
}

export function CleanupStep({ active, done, label }: { active: boolean; done: boolean; label: string }) {
  return (
    <div className={done ? "cleanup-step done" : active ? "cleanup-step active" : "cleanup-step"}>
      <span>{done ? <Check size={14} /> : active ? <LoaderCircle size={14} /> : <Circle size={14} />}</span>
      <strong>{label}</strong>
    </div>
  );
}

export function LocalStorageUsageCard({ usage, message }: { usage: LocalStorageUsage | null; message: string }) {
  const usedRatio = usage ? Math.max(0, Math.min(usage.used_ratio, 1)) : 0;
  const lowFree = usage ? usage.free_ratio < 0.2 : false;
  return (
    <div className="local-storage-card">
      <div className="local-storage-head">
        <div>
          <strong>本机空间使用量</strong>
          <span>{usage?.path || "/data"}</span>
        </div>
        <div>
          <strong>{usage ? `${(usedRatio * 100).toFixed(1)}%` : "-"}</strong>
          <span>{usage ? `剩余 ${usage.free_label}` : message || "正在刷新..."}</span>
        </div>
      </div>
      <div className={lowFree ? "local-storage-track danger" : "local-storage-track"} aria-label={`本机空间使用率 ${(usedRatio * 100).toFixed(1)}%`}>
        <span style={{ width: `${usedRatio * 100}%` }} />
      </div>
      <div className="local-storage-meta">
        <span>{usage ? `已用 ${usage.used_label} / 总量 ${usage.total_label}` : "等待空间数据"}</span>
        <span>{usage ? `剩余 ${usage.free_label}` : message}</span>
      </div>
    </div>
  );
}

export function EmptyUpgrade({ message = "点击右上角“上传升级包”后，可在这里执行预检查、升级和回滚。" }: { message?: string }) {
  return (
    <div className="service-upload-panel passive">
      <div className="service-upload-icon">
        <FileArchive size={30} />
      </div>
      <div className="service-upload-copy">
        <strong>暂无升级包</strong>
        <span>{message}</span>
      </div>
    </div>
  );
}

export function UploadPanel({ title, description, actionText, disabled, onClick }: { title: string; description: string; actionText: string; disabled?: boolean; onClick: () => void }) {
  return (
    <div className="service-upload-panel">
      <div className="service-upload-icon">
        <FileArchive size={30} />
      </div>
      <div className="service-upload-copy">
        <strong>{title}</strong>
        <span>{description}</span>
      </div>
      <button className="secondary-button service-upload-button" type="button" onClick={onClick} disabled={disabled}>
        <Upload size={15} />
        {actionText}
      </button>
    </div>
  );
}

export interface UpgradeTaskDetailProps {
  task: UpgradeTask;
  file: File | null;
  componentMode: boolean;
  precheckExpanded: boolean;
  precheckRunning: boolean;
  precheckProgressIndex: number;
  stepsExpanded: boolean;
  logsExpanded: boolean;
  onPrecheckToggle: () => void;
  onStepsToggle: () => void;
  onLogsToggle: () => void;
  upgradeBusy: boolean;
  onRecovery: (action: "continue" | "rollback" | "fail") => void;
}

export function UpgradeTaskDetail({
  task,
  file,
  componentMode,
  precheckExpanded,
  precheckRunning,
  precheckProgressIndex,
  stepsExpanded,
  logsExpanded,
  onPrecheckToggle,
  onStepsToggle,
  onLogsToggle,
  upgradeBusy,
  onRecovery
}: UpgradeTaskDetailProps) {
  const currentFile = file ?? null;
  const isComponent = Boolean(componentMode);
  return (
    <div className="service-upgrade-detail">
      {task.status === "recovery_required" && (
        <section className="upgrade-recovery-panel" aria-label="升级恢复处理">
          <div>
            <strong>需要恢复处理</strong>
            <p>{task.recovery_reason || "升级动作的执行结果无法自动确认，请选择恢复方式。"}</p>
          </div>
          <div className="upgrade-recovery-actions">
            {task.available_recovery_actions?.includes("continue") && <button className="primary-button" type="button" disabled={upgradeBusy} onClick={() => onRecovery("continue")}>继续执行</button>}
            {task.available_recovery_actions?.includes("fail") && <button className="secondary-button danger-button" type="button" disabled={upgradeBusy} onClick={() => onRecovery("fail")}>标记失败</button>}
          </div>
        </section>
      )}
      {task.cleanup_required && (
        <section className="upgrade-recovery-panel" aria-label="升级收尾提示">
          <div>
            <strong>需要收尾：环境可能处于半迁移状态</strong>
            <p>
              本次升级在执行中断时被标记失败，升级后清理没有执行。检测到残留路径：
              {(task.residual_paths || []).join("、") || "（请检查旧环境目录）"}。
              请重新上传同一个升级包并完整执行一次升级，由升级后清理收尾；在此之前不要开始新的升级任务。
            </p>
          </div>
        </section>
      )}
      <div className="service-info-table">
        <InfoRow label="升级包" value={task.package_filename ?? currentFile?.name ?? "-"} />
        {isComponent && <InfoRow label="组件" value={componentServiceFromTask(task) || "upgrade-runner"} />}
        <InfoRow label="影响服务" value={task.restart_services?.join("、") || "-"} />
        {!isComponent && <InfoRow label="兼容来源版本" value={sourceCompatibilityLabel(task)} />}
        <InfoRow label="数据库迁移" value={isComponent ? "不涉及" : task.database_migration ? "需要" : "不需要"} />
        {!isComponent && <InfoRow label="备份文件" value={task.backup_path || "升级开始后生成"} />}
      </div>
      {task.release_notes && <pre className="upgrade-release-notes auto-scrollbar">{task.release_notes}</pre>}
      {(precheckRunning || task.checks.length > 0 || task.precheck_ok !== undefined) && (
        <CollapsibleSection title="预检查" expanded={precheckExpanded} onToggle={onPrecheckToggle}>
          <div className="upgrade-steps upgrade-precheck-steps">
            {displayPrecheckSteps(task, isComponent, precheckRunning, precheckProgressIndex).map((step) => (
              <div className={`upgrade-step ${step.status}`} key={step.key}>
                <span className="upgrade-step-icon" aria-hidden="true">{stepIcon(step.status)}</span>
                <strong>{step.title}</strong>
                <span>{stepStatusText(step.status)}</span>
                {step.message && <small>{step.message}</small>}
              </div>
            ))}
          </div>
          {!!task.checks.length && (
            <div className="upgrade-checks upgrade-checks-after-steps">
              {task.checks.map((check) => (
                <div className={check.ok ? "upgrade-check ok" : "upgrade-check failed"} key={check.name}>
                  <span className="upgrade-check-icon" aria-hidden="true">
                    {check.ok ? <Check size={14} /> : <X size={14} />}
                  </span>
                  <strong>{check.name}</strong>
                  <span>{check.message}</span>
                </div>
              ))}
            </div>
          )}
        </CollapsibleSection>
      )}
      {!!displayUpgradeSteps(task, isComponent).length && (
        <CollapsibleSection title="执行步骤" expanded={stepsExpanded} onToggle={onStepsToggle}>
          <div className="upgrade-steps">
            {displayUpgradeSteps(task, isComponent).map((step) => (
              <div className={`upgrade-step ${step.status}`} key={step.key}>
                <span className="upgrade-step-icon" aria-hidden="true">{stepIcon(step.status)}</span>
                <strong>{step.title}</strong>
                <span>{stepStatusText(step.status)}</span>
                {step.message && <small>{step.message}</small>}
              </div>
            ))}
          </div>
        </CollapsibleSection>
      )}
      {!!task.logs.length && (
        <CollapsibleSection title="升级日志" expanded={logsExpanded} onToggle={onLogsToggle}>
          <pre className="upgrade-log auto-scrollbar">{task.logs.join("\n")}</pre>
        </CollapsibleSection>
      )}
    </div>
  );
}

export function UpgradeRuntimeVerification({ verification }: { verification: UpgradeVerification | null }) {
  return (
    <div className="upgrade-verification-inline">
      <div className="upgrade-runtime-table upgrade-runtime-table-flat">
        <div className="upgrade-runtime-head">
          <span>服务</span>
          <span>状态</span>
          <span>运行镜像</span>
          <span>版本</span>
          <span>启动时间</span>
        </div>
        {(verification?.services ?? []).map((item) => (
          <div className="upgrade-runtime-row" key={item.service}>
            <span>{item.service}</span>
            <span className={item.running ? "runtime-ok" : "runtime-bad"}>{item.running ? "运行中" : item.status || "未运行"}</span>
            <span className="upgrade-runtime-image" title={item.image}>{item.image}</span>
            <span>{formatVersionForDisplay(item.app_version)}</span>
            <span>{formatTime(item.started_at || undefined)}</span>
          </div>
        ))}
        {verification && !verification.services.length && <div className="empty-state">{verification.service_status_error || "未读取到服务状态"}</div>}
        {!verification && <div className="empty-state">点击“刷新核验”读取当前服务状态</div>}
      </div>
    </div>
  );
}

export interface CleanupDialogProps {
  busy: boolean;
  scanBusy: boolean;
  progress: number;
  logs: string[];
  images: CleanupScanImage[];
  protectedImages: CleanupScanImage[];
  selectedIds: Set<string>;
  onToggle: (id: string) => void;
  onToggleAll: () => void;
  reclaimable: string;
  actualReclaimed: string;
  onClose: () => void;
  onScan: () => void;
  onCleanup: () => void;
}

function cleanupCategoryLabel(image: CleanupScanImage): string {
  return image.category === "dangling" ? "悬空镜像" : "未使用镜像";
}

export function CleanupDialog({ busy, scanBusy, progress, logs, images, protectedImages, selectedIds, onToggle, onToggleAll, reclaimable, actualReclaimed, onClose, onScan, onCleanup }: CleanupDialogProps) {
  const allSelected = images.length > 0 && selectedIds.size === images.length;
  return (
    <div className="modal-backdrop" role="presentation" onClick={() => !busy && onClose()}>
      <div className="cleanup-dialog" role="dialog" aria-modal="true" aria-labelledby="cleanup-dialog-title" onClick={(event) => event.stopPropagation()}>
        <div className="export-dialog-head">
          <div>
            <strong id="cleanup-dialog-title">清理未使用镜像</strong>
            <span>清理未被任何容器使用的 Docker 镜像；平台/组件仓库镜像受回滚保护，不会出现在可清理列表。</span>
          </div>
        </div>
        <div className="cleanup-warning">
          <Info size={16} />
          只删除勾选的镜像；当前运行中的镜像不会被删除。删除前服务端会重新校验镜像状态，被容器引用或受保护的镜像会被跳过。
        </div>
        <div className="cleanup-progress" aria-label={`${progress}%`}>
          <span style={{ width: `${progress}%` }} />
        </div>
        <div className="cleanup-steps">
          <CleanupStep active={scanBusy} done={progress >= 45} label="扫描未使用镜像" />
          <CleanupStep active={busy && progress >= 70 && progress < 100} done={progress >= 100} label="执行镜像清理" />
          <CleanupStep active={false} done={progress >= 100 && !busy} label="输出清理结果" />
        </div>
        <div className="cleanup-summary">
          <strong>{images.length} 个可清理镜像</strong>
          <span>已选 {selectedIds.size} 个 · 候选逻辑大小 {reclaimable}</span>
          {actualReclaimed && <span>实际释放 {actualReclaimed}</span>}
        </div>
        <div className="cleanup-image-list auto-scrollbar">
          {images.length ? (
            <>
              <label className="cleanup-image-row cleanup-image-check-row cleanup-image-select-head">
                <input type="checkbox" checked={allSelected} onChange={onToggleAll} disabled={busy || scanBusy} />
                <div>
                  <strong>{allSelected ? "取消全选" : "全选可清理镜像"}</strong>
                  <small>悬空镜像与未被容器使用的非平台镜像</small>
                </div>
                <span>{images.length} 个</span>
              </label>
              {images.map((image) => (
                <label className="cleanup-image-row cleanup-image-check-row" key={image.id}>
                  <input type="checkbox" checked={selectedIds.has(image.id)} onChange={() => onToggle(image.id)} disabled={busy || scanBusy} />
                  <div>
                    <strong>{image.display_name}</strong>
                    <small>{cleanupCategoryLabel(image)} · {image.short_id}{image.created_at ? ` · ${formatUnixTime(image.created_at)}` : ""}</small>
                  </div>
                  <span>{image.reclaimable_size_label ?? image.size_label}</span>
                </label>
              ))}
            </>
          ) : (
            <div className="cleanup-image-empty">{progress >= 45 ? "没有可清理的未使用镜像。" : "请先扫描未使用镜像。"}</div>
          )}
          {protectedImages.length ? (
            <>
              <div className="cleanup-image-row cleanup-image-protected-head">
                <div>
                  <strong>{protectedImages.length} 个受回滚保护的镜像（不参与清理）</strong>
                  <small>平台/组件仓库的旧版本镜像，回滚时需要从本地加载，产品内不提供删除。</small>
                </div>
              </div>
              {protectedImages.map((image) => (
                <div className="cleanup-image-row" key={image.id}>
                  <div>
                    <strong>{image.display_name}</strong>
                    <small>回滚保护 · {image.short_id}</small>
                  </div>
                  <span>{image.size_label}</span>
                </div>
              ))}
            </>
          ) : null}
        </div>
        <pre className="cleanup-log auto-scrollbar">{logs.length ? logs.join("\n") : "等待开始清理..."}</pre>
        <div className="export-dialog-actions">
          <button className="secondary-button cleanup-action-button" type="button" onClick={onClose} disabled={busy || scanBusy}>
            关闭
          </button>
          <button className="primary-button cleanup-action-button" type="button" onClick={onScan} disabled={busy || scanBusy}>
            <RefreshCw size={15} />
            {scanBusy ? "扫描中" : "扫描"}
          </button>
          <button className="secondary-button cleanup-action-button cleanup-danger-button" type="button" onClick={onCleanup} disabled={busy || scanBusy || selectedIds.size === 0}>
            <RefreshCw size={15} />
            {busy ? "清理中" : "清理选中镜像"}
          </button>
        </div>
      </div>
    </div>
  );
}
