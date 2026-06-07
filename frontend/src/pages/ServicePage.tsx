import { Check, Circle, Download, FileArchive, History, Info, ListChecks, LoaderCircle, Power, RefreshCw, RotateCcw, Server, Trash2, Upload, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api } from "../services/api";
import type { TransferProgress } from "../services/api";
import type { AppTask, ComponentInfo, LocalStorageUsage, MigrationExportTask, MigrationImportTask, SpaceCleanupScanItem, SqliteVacuumScan, UpgradeTask, UpgradeVerification } from "../types";

type ServiceSection = "migration" | "restart" | "space-cleanup" | "platform-upgrade" | "component-upgrade" | "history";
type CleanupScanImage = { id: string; short_id: string; repo_tags: string[]; display_name: string; size: number; size_label: string; reclaimable_size?: number; reclaimable_size_label?: string; created_at?: number };
type UpgradeCheck = UpgradeTask["checks"][number];
type PrecheckStepDefinition = { key: string; title: string; checks: string[] };
type DisplayStep = { key: string; title: string; status: string; message?: string };

const runningUpgradeStatuses = new Set(["pending", "running", "rollback_pending", "rollback_running"]);
const serviceItems = [
  { name: "web-api", description: "提供页面 API、报表导出、数据迁移和升级接口。" },
  { name: "collector-worker", description: "负责定时采集 Tower、集群和虚拟机容量数据。" },
  { name: "prometheus", description: "保存历史指标和趋势样本。" }
];
const upgradeStepDefaults = [
  { key: "backup", title: "生成升级前数据备份" },
  { key: "load_images", title: "加载升级镜像" },
  { key: "write_override", title: "写入服务镜像覆盖配置" },
  { key: "migration", title: "执行数据库迁移脚本" },
  { key: "restart", title: "重启升级服务" },
  { key: "healthcheck", title: "执行服务健康检查" }
];
const rollbackStepDefaults = [
  { key: "rollback_config", title: "恢复升级前镜像配置" },
  { key: "rollback_restart", title: "重启回滚服务" },
  { key: "rollback_healthcheck", title: "执行回滚健康检查" }
];
const componentStepDefaults = [
  { key: "load_images", title: "加载组件镜像" },
  { key: "write_override", title: "写入组件镜像覆盖配置" },
  { key: "restart", title: "重启升级中心组件" },
  { key: "healthcheck", title: "检查组件运行状态" }
];
const platformPrecheckStepDefaults = [
  { key: "manifest", title: "校验升级包结构", checks: ["manifest"] },
  { key: "version", title: "校验版本兼容性", checks: ["version", "services"] },
  { key: "images", title: "校验镜像名、Tag 与 SHA256", checks: ["sha256", "image-names"] },
  { key: "docker", title: "检查 Docker 与升级执行器", checks: ["docker", "upgrade-runner"] },
  { key: "compose", title: "检查 compose、数据卷与网络", checks: ["volumes", "network", "compose-tag"] },
  { key: "project", title: "检查项目文件与敏感路径", checks: ["project-files"] },
  { key: "resources", title: "检查磁盘空间与迁移脚本", checks: ["disk", "migration"] },
  { key: "summary", title: "生成预检查结果", checks: [] }
] satisfies PrecheckStepDefinition[];
const componentPrecheckStepDefaults = [
  { key: "manifest", title: "校验组件包结构", checks: ["manifest"] },
  { key: "version", title: "校验组件版本兼容性", checks: ["version", "platform-upgrade"] },
  { key: "images", title: "校验组件镜像与 SHA256", checks: ["sha256"] },
  { key: "environment", title: "检查 Docker、CLI 与磁盘空间", checks: ["docker", "docker-cli", "disk"] },
  { key: "summary", title: "生成组件预检查结果", checks: [] }
] satisfies PrecheckStepDefinition[];
const defaultComponentInfos: ComponentInfo[] = [
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

interface ServicePageProps {
  addTask: (task: Omit<AppTask, "createdAt" | "updatedAt">) => void;
  updateTask: (id: string, patch: Partial<Omit<AppTask, "id" | "createdAt">>) => void;
}

export function ServicePage({ addTask, updateTask }: ServicePageProps) {
  const [section, setSection] = useState<ServiceSection>("platform-upgrade");
  const [appVersion, setAppVersion] = useState("-");
  const [runnerVersion, setRunnerVersion] = useState("v0.1.0");
  const [upgradeFile, setUpgradeFile] = useState<File | null>(null);
  const [upgradeTask, setUpgradeTask] = useState<UpgradeTask | null>(null);
  const [upgradeHistory, setUpgradeHistory] = useState<UpgradeTask[]>([]);
  const [upgradeVerification, setUpgradeVerification] = useState<UpgradeVerification | null>(null);
  const [verificationBusy, setVerificationBusy] = useState(false);
  const [upgradeBusy, setUpgradeBusy] = useState(false);
  const [upgradeMessage, setUpgradeMessage] = useState("");
  const [cleanupBusy, setCleanupBusy] = useState(false);
  const [cleanupScanBusy, setCleanupScanBusy] = useState(false);
  const [cleanupMessage, setCleanupMessage] = useState("");
  const [cleanupDialogOpen, setCleanupDialogOpen] = useState(false);
  const [cleanupProgress, setCleanupProgress] = useState(0);
  const [cleanupLogs, setCleanupLogs] = useState<string[]>([]);
  const [cleanupImagesList, setCleanupImagesList] = useState<CleanupScanImage[]>([]);
  const [cleanupReclaimable, setCleanupReclaimable] = useState("0 B");
  const [cleanupActualReclaimed, setCleanupActualReclaimed] = useState("");
  const [componentFile, setComponentFile] = useState<File | null>(null);
  const [componentTask, setComponentTask] = useState<UpgradeTask | null>(null);
  const [componentHistory, setComponentHistory] = useState<UpgradeTask[]>([]);
  const [componentInfos, setComponentInfos] = useState<ComponentInfo[]>(defaultComponentInfos);
  const [selectedComponentService, setSelectedComponentService] = useState("upgrade-runner");
  const [componentBusy, setComponentBusy] = useState(false);
  const [componentMessage, setComponentMessage] = useState("");
  const [precheckExpanded, setPrecheckExpanded] = useState(true);
  const [precheckRunning, setPrecheckRunning] = useState(false);
  const [precheckProgressIndex, setPrecheckProgressIndex] = useState(-1);
  const [stepsExpanded, setStepsExpanded] = useState(true);
  const [logsExpanded, setLogsExpanded] = useState(false);
  const [componentPrecheckExpanded, setComponentPrecheckExpanded] = useState(true);
  const [componentPrecheckRunning, setComponentPrecheckRunning] = useState(false);
  const [componentPrecheckProgressIndex, setComponentPrecheckProgressIndex] = useState(-1);
  const [componentStepsExpanded, setComponentStepsExpanded] = useState(true);
  const [componentLogsExpanded, setComponentLogsExpanded] = useState(false);
  const [restartBusy, setRestartBusy] = useState(false);
  const [restartMessage, setRestartMessage] = useState("");
  const [spaceCleanupBusy, setSpaceCleanupBusy] = useState(false);
  const [spaceCleanupScanBusy, setSpaceCleanupScanBusy] = useState(false);
  const [spaceCleanupMessage, setSpaceCleanupMessage] = useState("");
  const [spaceCleanupItems, setSpaceCleanupItems] = useState<SpaceCleanupScanItem[]>([]);
  const [spaceCleanupTotal, setSpaceCleanupTotal] = useState("0 B");
  const [spaceCleanupLogs, setSpaceCleanupLogs] = useState<string[]>([]);
  const [localStorage, setLocalStorage] = useState<LocalStorageUsage | null>(null);
  const [localStorageMessage, setLocalStorageMessage] = useState("");
  const [sqliteVacuumScan, setSqliteVacuumScan] = useState<SqliteVacuumScan | null>(null);
  const [sqliteVacuumBusy, setSqliteVacuumBusy] = useState(false);
  const [sqliteVacuumMessage, setSqliteVacuumMessage] = useState("");
  const [sqliteVacuumLogs, setSqliteVacuumLogs] = useState<string[]>([]);
  const [migrationMessage, setMigrationMessage] = useState("");
  const [migrationBusy, setMigrationBusy] = useState(false);
  const [migrationFile, setMigrationFile] = useState<File | null>(null);
  const [migrationMode, setMigrationMode] = useState<"merge" | "overwrite">("merge");
  const [migrationConfirmed, setMigrationConfirmed] = useState(false);
  const [migrationHealthMessage, setMigrationHealthMessage] = useState("");
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const componentFileInputRef = useRef<HTMLInputElement | null>(null);
  const migrationFileInputRef = useRef<HTMLInputElement | null>(null);
  const contentPanelRef = useRef<HTMLElement | null>(null);
  const upgradeRunTaskRef = useRef<Record<string, string>>({});

  async function reloadUpgradeHistory() {
    setUpgradeHistory(await api.upgradeHistory());
  }

  async function reloadUpgradeVerification() {
    setVerificationBusy(true);
    try {
      const result = await api.upgradeVerification();
      setUpgradeVerification(result);
      setAppVersion(result.app_version || "-");
      setRunnerVersion(result.runner_version || "v0.1.0");
      setComponentInfos((current) =>
        current.map((component) => {
          if (component.service === "upgrade-runner") return { ...component, version: result.runner_version || component.version };
          if (component.service === "prometheus") return { ...component, version: result.prometheus_version || component.version };
          return component;
        })
      );
    } finally {
      setVerificationBusy(false);
    }
  }

  async function reloadComponentHistory() {
    setComponentHistory(await api.componentUpgradeHistory());
  }

  async function reloadComponentInfos() {
    const result = await api.componentUpgradeComponents();
    if (result.components.length) {
      setComponentInfos(result.components);
      const selectedExists = result.components.some((component) => component.service === selectedComponentService);
      if (!selectedExists) setSelectedComponentService(result.components[0].service);
    }
  }

  useEffect(() => {
    api.upgradeVersion().then((result) => setAppVersion(result.version)).catch(() => undefined);
    api.componentUpgradeVersion().then((result) => setRunnerVersion(result.version)).catch(() => undefined);
    reloadComponentInfos().catch(() => undefined);
    reloadUpgradeHistory().catch(() => undefined);
    reloadUpgradeVerification().catch(() => undefined);
    reloadComponentHistory().catch(() => undefined);
    resetServiceScroll();
  }, []);

  useEffect(() => {
    if (!upgradeTask || !runningUpgradeStatuses.has(upgradeTask.status)) return undefined;
    const timer = window.setInterval(() => {
      api.upgradeStatus(upgradeTask.task_id)
        .then((next) => {
          setUpgradeTask(next);
          const appTaskId = upgradeRunTaskRef.current[next.task_id];
          if (appTaskId) {
            const done = !runningUpgradeStatuses.has(next.status);
            updateTask(appTaskId, {
              status: upgradeTaskStatus(next),
              progress: upgradeProgress(next),
              detail: activeUpgradeDetail(next)
            });
            if (done) delete upgradeRunTaskRef.current[next.task_id];
          }
          if (!runningUpgradeStatuses.has(next.status)) {
            reloadUpgradeHistory().catch(() => undefined);
            reloadUpgradeVerification().catch(() => undefined);
          }
        })
        .catch((exc) => setUpgradeMessage(exc instanceof Error ? exc.message : "刷新升级状态失败"));
    }, 2500);
    return () => window.clearInterval(timer);
  }, [upgradeTask, updateTask]);

  useEffect(() => {
    if (!componentTask || !runningUpgradeStatuses.has(componentTask.status)) return undefined;
    const timer = window.setInterval(() => {
      api.componentUpgradeStatus(componentTask.task_id)
        .then((next) => {
          setComponentTask(next);
          const appTaskId = upgradeRunTaskRef.current[next.task_id];
          if (appTaskId) {
            const done = !runningUpgradeStatuses.has(next.status);
            updateTask(appTaskId, {
              status: upgradeTaskStatus(next),
              progress: upgradeProgress(next),
              detail: activeUpgradeDetail(next)
            });
            if (done) delete upgradeRunTaskRef.current[next.task_id];
          }
          if (!runningUpgradeStatuses.has(next.status)) {
            reloadComponentHistory().catch(() => undefined);
            reloadComponentInfos().catch(() => undefined);
            api.componentUpgradeVersion().then((result) => setRunnerVersion(result.version)).catch(() => undefined);
          }
        })
        .catch((exc) => setComponentMessage(exc instanceof Error ? exc.message : "刷新组件升级状态失败"));
    }, 2500);
    return () => window.clearInterval(timer);
  }, [componentTask, updateTask]);

  useEffect(() => {
    if (section !== "space-cleanup") return;
    refreshLocalStorageUsage().catch(() => undefined);
  }, [section]);

  function taskId(prefix: string) {
    return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  }

  function saveBlob(blob: Blob, filename: string) {
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename || "smartx-storage-migration.tar.gz";
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  }

  async function exportMigration() {
    setMigrationMessage("");
    setMigrationBusy(true);
    const id = taskId("migration-export");
    addTask({ id, kind: "export", title: "导出迁移包", detail: "正在创建导出任务", status: "running", progress: 1, logs: ["正在创建后台导出任务"] });
    try {
      let task = await api.startMigrationExport();
      updateTask(id, migrationExportTaskPatch(task));
      while (task.status === "pending" || task.status === "running") {
        await sleep(1000);
        task = await api.migrationExportStatus(task.task_id);
        updateTask(id, migrationExportTaskPatch(task));
      }
      if (task.status !== "succeeded" || !task.download_url) {
        const message = task.detail || "导出失败";
        updateTask(id, { status: "failed", progress: 100, detail: message, logs: task.logs || [message] });
        setMigrationMessage(message);
        return;
      }
      const result = await api.downloadSavedExport(task.download_url, (progress) => {
        const value = transferProgressValue(progress);
        updateTask(id, { progress: Math.max(98, value), detail: "迁移包已生成，正在下载", logs: ["迁移包已生成", "正在下载到浏览器"] });
      });
      saveBlob(result.blob, result.filename || task.filename || "smartx-storage-migration.tar.gz");
      updateTask(id, {
        status: "succeeded",
        progress: 100,
        detail: task.filename || "迁移包已生成",
        logs: ["迁移包已生成", task.saved_path ? `服务器留档：${task.saved_path}` : "已完成浏览器下载"],
        links: [{ label: "下载", filename: task.filename, url: task.download_url, path: task.saved_path }]
      });
      setMigrationMessage("迁移包已生成");
    } catch (exc) {
      const message = exc instanceof Error ? exc.message : "导出失败";
      updateTask(id, { status: "failed", progress: 100, detail: message, logs: ["导出失败", message] });
      setMigrationMessage(message);
    } finally {
      setMigrationBusy(false);
    }
  }

  async function importMigration() {
    setMigrationMessage("");
    if (!migrationFile) {
      setMigrationMessage("请选择迁移包文件");
      return;
    }
    if (migrationMode === "overwrite" && !migrationConfirmed) {
      setMigrationMessage("覆盖导入会清空当前数据，请先勾选确认");
      return;
    }
    setMigrationBusy(true);
    const id = taskId("migration-import");
    addTask({ id, kind: "import", title: "导入迁移包", detail: migrationFile.name, status: "running", progress: 0 });
    try {
      let task = await api.startMigrationImport(migrationFile, migrationMode, migrationConfirmed, (progress) => updateTask(id, uploadProgressTaskPatch(progress)));
      const backendTaskId = task.task_id || id;
      updateTask(id, migrationImportTaskPatch(task));
      while (task.status === "pending" || task.status === "running") {
        await sleep(1000);
        task = await api.migrationImportStatus(backendTaskId);
        updateTask(id, migrationImportTaskPatch(task));
      }
      if (task.status === "failed") {
        throw new Error(task.detail || "导入失败");
      }
      const backupLog = task.backup_path ? `导入前备份：${task.backup_path}` : "";
      const healthLog = task.summary?.health?.message || "";
      updateTask(id, { ...migrationImportTaskPatch(task), status: "succeeded", progress: 100, detail: healthLog || "数据迁移导入完成" });
      setMigrationMessage(["数据迁移导入完成", backupLog, healthLog].filter(Boolean).join(" "));
      setMigrationFile(null);
      if (migrationFileInputRef.current) migrationFileInputRef.current.value = "";
      setMigrationMode("merge");
      setMigrationConfirmed(false);
    } catch (exc) {
      const message = exc instanceof Error ? exc.message : "导入失败";
      updateTask(id, { status: "failed", progress: 100, detail: message, logs: ["导入失败", message] });
      setMigrationMessage(message);
    } finally {
      setMigrationBusy(false);
    }
  }

  async function checkMigrationHealth() {
    setMigrationMessage("");
    setMigrationHealthMessage("");
    const id = taskId("migration-health");
    addTask({ id, kind: "import", title: "迁移健康检查", detail: "正在检查业务库和历史指标", status: "running", progress: 20 });
    try {
      const result = await api.migrationHealth();
      const failed = Object.entries(result.checks || {}).filter(([, ok]) => !ok).map(([name]) => name);
      const logs = [
        result.message,
        `SQLite 表数量：${Object.keys(result.sqlite?.tables || {}).length}`,
        `Prometheus block：${result.prometheus?.block_count ?? 0}`,
        failed.length ? `未通过项：${failed.join(", ")}` : "所有检查项均通过"
      ];
      updateTask(id, { status: failed.length ? "failed" : "succeeded", progress: 100, detail: result.message, logs });
      setMigrationHealthMessage(result.message);
    } catch (exc) {
      const message = exc instanceof Error ? exc.message : "迁移健康检查失败";
      updateTask(id, { status: "failed", progress: 100, detail: message, logs: ["迁移健康检查失败", message] });
      setMigrationHealthMessage(message);
    }
  }

  async function scanSpaceCleanup() {
    setSpaceCleanupMessage("");
    setSpaceCleanupScanBusy(true);
    setSpaceCleanupLogs(["开始扫描升级包、数据迁移导出和报表导出..."]);
    try {
      await refreshLocalStorageUsage();
      const result = await api.scanSpaceCleanup();
      setSpaceCleanupItems(result.items);
      setSpaceCleanupTotal(result.total_size_label);
      setSpaceCleanupLogs((current) => [...current, result.message]);
      setSpaceCleanupMessage(result.message);
    } catch (exc) {
      const message = exc instanceof Error ? exc.message : "空间扫描失败";
      setSpaceCleanupLogs((current) => [...current, message]);
      setSpaceCleanupMessage(message);
    } finally {
      setSpaceCleanupScanBusy(false);
    }
  }

  async function scanSqliteVacuum() {
    setSqliteVacuumMessage("");
    setSqliteVacuumLogs(["开始扫描 SQLite 数据库..."]);
    try {
      const result = await api.scanSqliteVacuum();
      setSqliteVacuumScan(result);
      setSqliteVacuumLogs([result.message]);
      setSqliteVacuumMessage(result.message);
      await refreshLocalStorageUsage();
    } catch (exc) {
      const message = exc instanceof Error ? exc.message : "SQLite 扫描失败";
      setSqliteVacuumLogs((current) => [...current, message]);
      setSqliteVacuumMessage(message);
    }
  }

  async function refreshLocalStorageUsage() {
    try {
      setLocalStorage(await api.localStorageUsage());
      setLocalStorageMessage("");
    } catch (exc) {
      setLocalStorageMessage(exc instanceof Error ? exc.message : "本机空间刷新失败");
    }
  }

  async function cleanupSpaceArtifacts() {
    setSpaceCleanupMessage("");
    setSpaceCleanupBusy(true);
    const id = taskId("space-cleanup");
    addTask({ id, kind: "upgrade", title: "空间清理", detail: "正在清理升级包和导出留档", status: "running", progress: 30, logs: ["开始清理服务器留档文件"] });
    try {
      const result = await api.cleanupSpaceArtifacts();
      setSpaceCleanupLogs((current) => [...current, ...(result.logs || []), result.message]);
      setSpaceCleanupMessage(result.message);
      setSpaceCleanupTotal(result.space_reclaimed_label);
      setSpaceCleanupItems([]);
      updateTask(id, { status: "succeeded", progress: 100, detail: result.message, logs: result.logs });
      await refreshLocalStorageUsage();
    } catch (exc) {
      const message = exc instanceof Error ? exc.message : "空间清理失败";
      setSpaceCleanupLogs((current) => [...current, message]);
      setSpaceCleanupMessage(message);
      updateTask(id, { status: "failed", progress: 100, detail: message, logs: ["空间清理失败", message] });
      await refreshLocalStorageUsage();
    } finally {
      setSpaceCleanupBusy(false);
    }
  }

  async function vacuumSqlite() {
    setSqliteVacuumBusy(true);
    setSqliteVacuumMessage("");
    const id = taskId("sqlite-vacuum");
    addTask({ id, kind: "upgrade", title: "SQLite 空间整理", detail: "正在备份并整理业务库", status: "running", progress: 35, logs: ["开始 SQLite 空间整理"] });
    try {
      const result = await api.vacuumSqlite();
      setSqliteVacuumLogs(result.logs || [result.message]);
      setSqliteVacuumMessage(result.backup_path ? `${result.message} 整理前备份：${result.backup_path}` : result.message);
      updateTask(id, {
        status: "succeeded",
        progress: 100,
        detail: result.message,
        logs: result.logs,
        links: result.backup_path ? [{ label: "整理前备份", filename: result.backup_path.split("/").pop(), url: "", path: result.backup_path }] : undefined
      });
      const scan = await api.scanSqliteVacuum();
      setSqliteVacuumScan(scan);
      await refreshLocalStorageUsage();
    } catch (exc) {
      const message = exc instanceof Error ? exc.message : "SQLite 空间整理失败";
      setSqliteVacuumLogs((current) => [...current, message]);
      setSqliteVacuumMessage(message);
      updateTask(id, { status: "failed", progress: 100, detail: message, logs: ["SQLite 空间整理失败", message] });
    } finally {
      setSqliteVacuumBusy(false);
    }
  }

  async function restartServices() {
    setRestartMessage("");
    setRestartBusy(true);
    try {
      const result = await api.restartSystemServices();
      setRestartMessage(result.message);
    } catch (exc) {
      setRestartMessage(exc instanceof Error ? exc.message : "重启失败");
    } finally {
      setRestartBusy(false);
    }
  }

  async function scanCleanupImages() {
    setCleanupMessage("");
    setCleanupLogs(["开始扫描未使用 Docker 镜像..."]);
    setCleanupProgress(20);
    setCleanupScanBusy(true);
    try {
      const result = await api.scanUnusedImages();
      setCleanupImagesList(result.images);
      setCleanupReclaimable(result.space_reclaimable_label);
      setCleanupActualReclaimed("");
      setCleanupProgress(45);
      setCleanupLogs((current) => [...current, result.message]);
      setCleanupMessage(result.message);
    } catch (exc) {
      const message = exc instanceof Error ? exc.message : "扫描未使用镜像失败";
      setCleanupLogs((current) => [...current, message]);
      setCleanupMessage(message);
    } finally {
      setCleanupScanBusy(false);
    }
  }

  async function cleanupImages() {
    setCleanupMessage("");
    setCleanupLogs((current) => [
      ...current,
      `准备清理 ${cleanupImagesList.length} 个未使用镜像，预计释放 ${cleanupReclaimable}。`,
      "正在执行镜像清理..."
    ]);
    setCleanupProgress(70);
    setCleanupBusy(true);
    const id = taskId("cleanup-images");
    addTask({ id, kind: "upgrade", title: "清理旧版本镜像", detail: "正在清理未使用 Docker 镜像", status: "running", progress: 60 });
    try {
      const result = await api.cleanupUnusedImages();
      setCleanupProgress(100);
      updateTask(id, { status: "succeeded", progress: 100, detail: result.message });
      setCleanupLogs((current) => [...current, result.message, ...(result.errors || []), "清理完成。"]);
      setCleanupMessage(result.message);
      setCleanupActualReclaimed(result.space_reclaimed_label ?? formatBytes(result.space_reclaimed));
      setCleanupReclaimable(result.space_reclaimable_before_label ?? cleanupReclaimable);
      setCleanupImagesList([]);
    } catch (exc) {
      const message = exc instanceof Error ? exc.message : "清理旧版本镜像失败";
      updateTask(id, { status: "failed", progress: 100, detail: message });
      setCleanupProgress(100);
      setCleanupLogs((current) => [...current, message]);
      setCleanupMessage(message);
    } finally {
      setCleanupBusy(false);
    }
  }

  async function uploadUpgrade(file?: File | null) {
    const selectedFile = file ?? upgradeFile;
    setUpgradeMessage("");
    if (!selectedFile) {
      setUpgradeMessage("请选择升级包文件");
      return;
    }
    setUpgradeBusy(true);
    const id = taskId("upgrade-upload");
    addTask({ id, kind: "upload", title: "上传升级包", detail: selectedFile.name, status: "running", progress: 0 });
    try {
      const task = await api.uploadUpgradePackage(selectedFile, (progress) => updateTask(id, uploadProgressTaskPatch(progress)));
      setUpgradeTask(task);
      setUpgradeFile(selectedFile);
      setPrecheckExpanded(false);
      setLogsExpanded(false);
      updateTask(id, { status: "succeeded", progress: 100, detail: task.target_version || "升级包已上传" });
      setUpgradeMessage("升级包已上传并保存到系统目录，请选中后执行预检查。");
      await reloadUpgradeHistory();
    } catch (exc) {
      const message = exc instanceof Error ? exc.message : "上传升级包失败";
      updateTask(id, { status: "failed", progress: 100, detail: message });
      setUpgradeMessage(message);
    } finally {
      setUpgradeBusy(false);
    }
  }

  async function precheckUpgrade() {
    if (!upgradeTask) return;
    setUpgradeMessage("");
    setUpgradeBusy(true);
    setPrecheckRunning(true);
    setPrecheckExpanded(true);
    setPrecheckProgressIndex(0);
    let progressTimer: number | undefined;
    const id = taskId("upgrade-precheck");
    addTask({ id, kind: "upgrade", title: "升级预检查", detail: upgradeTask.package_filename || upgradeTask.target_version || "升级包", status: "running", progress: 10 });
    try {
      progressTimer = window.setInterval(() => {
        setPrecheckProgressIndex((current) => Math.min(platformPrecheckStepDefaults.length - 1, current + 1));
      }, 450);
      const task = await api.precheckUpgrade(upgradeTask.task_id);
      setPrecheckProgressIndex(platformPrecheckStepDefaults.length);
      setUpgradeTask(task);
      setPrecheckExpanded(true);
      const message = task.precheck_ok ? "预检查通过，可以开始升级。" : "预检查未通过，请查看检查项。";
      updateTask(id, { status: task.precheck_ok ? "succeeded" : "failed", progress: 100, detail: message });
      setUpgradeMessage(message);
      await reloadUpgradeHistory();
    } catch (exc) {
      const message = exc instanceof Error ? exc.message : "预检查失败";
      setPrecheckProgressIndex(platformPrecheckStepDefaults.length);
      updateTask(id, { status: "failed", progress: 100, detail: message });
      setUpgradeMessage(message);
    } finally {
      if (progressTimer) window.clearInterval(progressTimer);
      setPrecheckRunning(false);
      setUpgradeBusy(false);
    }
  }

  async function startUpgrade() {
    if (!upgradeTask) return;
    setUpgradeMessage("");
    setUpgradeBusy(true);
    const id = upgradeTask.task_id;
    addTask({ id, kind: "upgrade", title: "执行系统升级", detail: upgradeTask.target_version || "升级任务", status: "running", progress: 10 });
    try {
      const task = await api.startUpgrade(upgradeTask.task_id);
      setUpgradeTask(task);
      setStepsExpanded(true);
      setLogsExpanded(true);
      upgradeRunTaskRef.current[task.task_id] = id;
      updateTask(id, { progress: upgradeProgress(task), detail: upgradeStatusText(task.status) });
      setUpgradeMessage("升级任务已提交，日志会自动刷新。");
    } catch (exc) {
      const message = exc instanceof Error ? exc.message : "开始升级失败";
      updateTask(id, { status: "failed", progress: 100, detail: message });
      setUpgradeMessage(message);
    } finally {
      setUpgradeBusy(false);
    }
  }

  async function rollbackUpgrade() {
    if (!upgradeTask) return;
    setUpgradeMessage("");
    setUpgradeBusy(true);
    const id = taskId("upgrade-rollback");
    addTask({ id, kind: "upgrade", title: "手动回滚", detail: upgradeTask.target_version || "升级任务", status: "running", progress: 10 });
    try {
      const task = await api.rollbackUpgrade(upgradeTask.task_id);
      setUpgradeTask(task);
      setStepsExpanded(true);
      setLogsExpanded(true);
      upgradeRunTaskRef.current[task.task_id] = id;
      updateTask(id, { progress: upgradeProgress(task), detail: upgradeStatusText(task.status) });
      setUpgradeMessage("回滚任务已提交，日志会自动刷新。");
    } catch (exc) {
      const message = exc instanceof Error ? exc.message : "提交回滚失败";
      updateTask(id, { status: "failed", progress: 100, detail: message });
      setUpgradeMessage(message);
    } finally {
      setUpgradeBusy(false);
    }
  }

  async function uploadComponentUpgrade(file?: File | null) {
    const selectedFile = file ?? componentFile;
    setComponentMessage("");
    if (!selectedFile) {
      setComponentMessage("请选择组件升级包文件");
      return;
    }
    setComponentBusy(true);
    const id = taskId("component-upload");
    addTask({ id, kind: "upload", title: "上传组件升级包", detail: selectedFile.name, status: "running", progress: 0 });
    try {
      const task = await api.uploadComponentUpgradePackage(selectedFile, (progress) => updateTask(id, uploadProgressTaskPatch(progress)));
      setComponentTask(task);
      setComponentFile(selectedFile);
      if (task.component) setSelectedComponentService(task.component);
      setComponentPrecheckExpanded(false);
      setComponentLogsExpanded(false);
      updateTask(id, { status: "succeeded", progress: 100, detail: task.target_version || "组件升级包已上传" });
      setComponentMessage("组件升级包已上传并保存到系统目录，请选中后执行预检查。");
      await reloadComponentHistory();
    } catch (exc) {
      const message = exc instanceof Error ? exc.message : "上传组件升级包失败";
      updateTask(id, { status: "failed", progress: 100, detail: message });
      setComponentMessage(message);
    } finally {
      setComponentBusy(false);
    }
  }

  async function precheckComponentUpgrade() {
    if (!componentTask) return;
    setComponentMessage("");
    setComponentBusy(true);
    setComponentPrecheckRunning(true);
    setComponentPrecheckExpanded(true);
    setComponentPrecheckProgressIndex(0);
    let progressTimer: number | undefined;
    const id = taskId("component-precheck");
    addTask({ id, kind: "upgrade", title: "组件升级预检查", detail: componentTask.package_filename || componentTask.target_version || "组件升级包", status: "running", progress: 10 });
    try {
      progressTimer = window.setInterval(() => {
        setComponentPrecheckProgressIndex((current) => Math.min(componentPrecheckStepDefaults.length - 1, current + 1));
      }, 450);
      const task = await api.precheckComponentUpgrade(componentTask.task_id);
      setComponentPrecheckProgressIndex(componentPrecheckStepDefaults.length);
      setComponentTask(task);
      setComponentPrecheckExpanded(true);
      const message = task.precheck_ok ? "组件预检查通过，可以开始升级。" : "组件预检查未通过，请查看检查项。";
      updateTask(id, { status: task.precheck_ok ? "succeeded" : "failed", progress: 100, detail: message });
      setComponentMessage(message);
      await reloadComponentHistory();
    } catch (exc) {
      const message = exc instanceof Error ? exc.message : "组件预检查失败";
      setComponentPrecheckProgressIndex(componentPrecheckStepDefaults.length);
      updateTask(id, { status: "failed", progress: 100, detail: message });
      setComponentMessage(message);
    } finally {
      if (progressTimer) window.clearInterval(progressTimer);
      setComponentPrecheckRunning(false);
      setComponentBusy(false);
    }
  }

  async function startComponentUpgrade() {
    if (!componentTask) return;
    setComponentMessage("");
    setComponentBusy(true);
    const id = componentTask.task_id;
    addTask({ id, kind: "upgrade", title: "执行组件升级", detail: componentTask.target_version || componentTask.component || "组件升级", status: "running", progress: 10 });
    try {
      const task = await api.startComponentUpgrade(componentTask.task_id);
      setComponentTask(task);
      setComponentStepsExpanded(true);
      setComponentLogsExpanded(true);
      upgradeRunTaskRef.current[task.task_id] = id;
      updateTask(id, { status: upgradeTaskStatus(task), progress: upgradeProgress(task), detail: upgradeStatusText(task.status) });
      setComponentMessage("组件升级已执行，日志会自动刷新。");
      await reloadComponentHistory();
      api.componentUpgradeVersion().then((result) => setRunnerVersion(result.version)).catch(() => undefined);
    } catch (exc) {
      const message = exc instanceof Error ? exc.message : "开始组件升级失败";
      updateTask(id, { status: "failed", progress: 100, detail: message });
      setComponentMessage(message);
    } finally {
      setComponentBusy(false);
    }
  }

  async function deleteSelectedComponentPackage() {
    if (!componentTask) return;
    if (componentTask.started_at || runningUpgradeStatuses.has(componentTask.status)) {
      setComponentMessage("组件升级已开始或正在执行，不能删除该升级包记录。");
      return;
    }
    setComponentMessage("");
    setComponentBusy(true);
    try {
      await api.deleteComponentUpgradePackage(componentTask.task_id);
      setComponentTask(null);
      setComponentFile(null);
      setComponentPrecheckExpanded(false);
      setComponentStepsExpanded(true);
      setComponentLogsExpanded(false);
      setComponentMessage("组件升级包已删除。");
      await reloadComponentHistory();
    } catch (exc) {
      setComponentMessage(exc instanceof Error ? exc.message : "删除组件升级包失败");
    } finally {
      setComponentBusy(false);
    }
  }

  function cancelSelectedComponentPackage() {
    setComponentTask(null);
    setComponentFile(null);
    setComponentPrecheckExpanded(false);
    setComponentStepsExpanded(true);
    setComponentLogsExpanded(false);
    setComponentMessage("");
  }

  function selectComponentPackage(task: UpgradeTask) {
    setComponentTask(task);
    setComponentFile(null);
    if (task.component) setSelectedComponentService(task.component);
    setComponentPrecheckExpanded(Boolean(task.checks.length));
    setComponentStepsExpanded(Boolean(task.steps.length));
    setComponentLogsExpanded(false);
    setComponentMessage("");
  }

  async function deleteSelectedUpgradePackage() {
    if (!upgradeTask) return;
    if (upgradeTask.started_at || runningUpgradeStatuses.has(upgradeTask.status)) {
      setUpgradeMessage("升级已开始或正在执行，不能删除该升级包记录。");
      return;
    }
    setUpgradeMessage("");
    setUpgradeBusy(true);
    try {
      await api.deleteUpgradePackage(upgradeTask.task_id);
      setUpgradeTask(null);
      setUpgradeFile(null);
      setPrecheckExpanded(false);
      setStepsExpanded(true);
      setLogsExpanded(false);
      setUpgradeMessage("升级包已删除。");
      await reloadUpgradeHistory();
    } catch (exc) {
      setUpgradeMessage(exc instanceof Error ? exc.message : "删除升级包失败");
    } finally {
      setUpgradeBusy(false);
    }
  }

  function cancelSelectedUpgradePackage() {
    setUpgradeTask(null);
    setUpgradeFile(null);
    setPrecheckExpanded(false);
    setStepsExpanded(true);
    setLogsExpanded(false);
    setUpgradeMessage("");
  }

  function selectUpgradePackage(task: UpgradeTask) {
    setUpgradeTask(task);
    setUpgradeFile(null);
    setPrecheckExpanded(Boolean(task.checks.length));
    setStepsExpanded(Boolean(task.steps.length));
    setLogsExpanded(false);
    setUpgradeMessage("");
  }

  function loadHistoryItem(task: UpgradeTask) {
    selectUpgradePackage(task);
    selectSection(task.kind === "component" ? "component-upgrade" : "platform-upgrade");
  }

  function selectSection(nextSection: ServiceSection) {
    setSection(nextSection);
    resetServiceScroll();
  }

  function resetServiceScroll() {
    window.requestAnimationFrame(() => {
      window.scrollTo({ top: 0 });
      scrollElementToTop(document.querySelector<HTMLElement>(".workspace"));
      scrollElementToTop(contentPanelRef.current);
    });
  }

  return (
    <div className="service-page-shell">
      <aside className="service-subnav">
        <div className="service-subnav-group">
          <span>系统运维</span>
          <button className={section === "migration" ? "active" : ""} type="button" onClick={() => selectSection("migration")}>
            <Download size={17} />
            数据迁移
          </button>
          <button className={section === "restart" ? "active" : ""} type="button" onClick={() => selectSection("restart")}>
            <Power size={17} />
            服务重启
          </button>
          <button className={section === "space-cleanup" ? "active" : ""} type="button" onClick={() => selectSection("space-cleanup")}>
            <Trash2 size={17} />
            空间清理
          </button>
        </div>
        <div className="service-subnav-group">
          <span>升级中心</span>
          <button className={section === "platform-upgrade" ? "active" : ""} type="button" onClick={() => selectSection("platform-upgrade")}>
            <Upload size={17} />
            平台升级
          </button>
          <button className={section === "component-upgrade" ? "active" : ""} type="button" onClick={() => selectSection("component-upgrade")}>
            <Server size={17} />
            组件升级
          </button>
          <button className={section === "history" ? "active" : ""} type="button" onClick={() => selectSection("history")}>
            <History size={17} />
            升级历史
          </button>
        </div>
      </aside>

      <main ref={contentPanelRef} className="service-content-panel auto-scrollbar">
        {section === "migration" && renderMigration()}
        {section === "restart" && renderRestart()}
        {section === "space-cleanup" && renderSpaceCleanup()}
        {section === "platform-upgrade" && renderUpgrade()}
        {section === "component-upgrade" && renderComponentUpgrade()}
        {section === "history" && renderHistory()}
      </main>
    </div>
  );

  function renderMigration() {
    return (
      <>
        <PageHeader eyebrow="系统运维" title="数据迁移" action={(
          <div className="service-header-actions">
            <button className="secondary-button" type="button" onClick={checkMigrationHealth} disabled={migrationBusy}>
              <Info size={16} />
              健康检查
            </button>
            <button className="primary-button" type="button" onClick={exportMigration} disabled={migrationBusy}>
              <Download size={16} />
              导出迁移包
            </button>
          </div>
        )} />
        <div className="service-operation-card service-migration-card">
          <div className="service-operation-head">
            <div>
              <strong>迁移包导入</strong>
              <span>默认补全缺失数据；覆盖导入会替换当前业务库和历史指标数据。</span>
            </div>
          </div>
          <div className="migration-import service-migration-import">
            <input
              ref={migrationFileInputRef}
              className="visually-hidden"
              type="file"
              accept=".gz,.tgz,.tar.gz,application/gzip"
              onChange={(event) => setMigrationFile(event.target.files?.[0] ?? null)}
              disabled={migrationBusy}
            />
            <UploadPanel
              title={migrationFile ? migrationFile.name : "选择迁移包"}
              description={migrationFile ? "已选择迁移包，可选择导入方式后开始导入。" : "支持 .tar.gz / .tgz 数据迁移包，默认补全缺失数据。"}
              actionText={migrationFile ? "重新选择" : "选择文件"}
              disabled={migrationBusy}
              onClick={() => migrationFileInputRef.current?.click()}
            />
            <div className="migration-mode-group" role="radiogroup" aria-label="导入方式">
              <button className={migrationMode === "merge" ? "active" : ""} type="button" onClick={() => setMigrationMode("merge")} disabled={migrationBusy}>
                补全缺失数据
              </button>
              <button className={migrationMode === "overwrite" ? "active" : ""} type="button" onClick={() => setMigrationMode("overwrite")} disabled={migrationBusy}>
                覆盖导入
              </button>
            </div>
            {migrationMode === "overwrite" && (
              <label className="checkbox-line migration-confirm">
                <input type="checkbox" checked={migrationConfirmed} onChange={(event) => setMigrationConfirmed(event.target.checked)} disabled={migrationBusy} />
                我确认覆盖当前系统数据
              </label>
            )}
            <button className={migrationMode === "overwrite" ? "secondary-button danger-button" : "secondary-button"} type="button" onClick={importMigration} disabled={migrationBusy || !migrationFile || (migrationMode === "overwrite" && !migrationConfirmed)}>
              <Upload size={15} />
              导入迁移包
            </button>
          </div>
          <div className="service-notice">
            <Info size={16} />
            导入后请在本页执行“服务重启”，使 web-api、collector-worker 和 Prometheus 完全加载补全后的数据。
          </div>
          {migrationHealthMessage && <div className="inline-message">{migrationHealthMessage}</div>}
          {migrationMessage && <div className="inline-message">{migrationMessage}</div>}
        </div>
      </>
    );
  }

  function renderRestart() {
    return (
      <>
        <PageHeader eyebrow="系统运维" title="服务重启" />
        <div className="service-operation-card">
          <div className="service-operation-head">
            <div>
              <strong>数据服务</strong>
              <span>导入迁移包后可手动重启，使业务库和历史指标完全生效。</span>
            </div>
            <button className="primary-button" type="button" onClick={restartServices} disabled={restartBusy}>
              <RefreshCw size={16} />
              {restartBusy ? "正在提交" : "重启数据服务"}
            </button>
          </div>
          <div className="service-runtime-list">
            {serviceItems.map((item) => (
              <div className="service-runtime-item" key={item.name}>
                <Server size={18} />
                <div>
                  <strong>{item.name}</strong>
                  <span>{item.description}</span>
                </div>
              </div>
            ))}
          </div>
          {restartMessage && <div className="inline-message">{restartMessage}</div>}
        </div>
      </>
    );
  }

  function renderSpaceCleanup() {
    const totalCount = spaceCleanupItems.reduce((total, item) => total + item.count, 0);
    return (
      <>
        <PageHeader eyebrow="系统运维" title="空间清理" />
        <div className="service-operation-card">
          <LocalStorageUsageCard usage={localStorage} message={localStorageMessage} />
          <div className="cleanup-module">
            <div className="service-operation-head">
              <div>
                <strong>运行产物清理</strong>
                <span>扫描升级包、数据迁移导出和报表导出留档；不会删除业务库、Prometheus 历史指标或升级前自动备份。</span>
              </div>
              <div className="cleanup-module-actions">
                <div className="cleanup-summary compact">
                  <strong>{totalCount} 项</strong>
                  <span>预计可释放 {spaceCleanupTotal}</span>
                </div>
                <button className="primary-button service-header-button" type="button" onClick={scanSpaceCleanup} disabled={spaceCleanupBusy || spaceCleanupScanBusy}>
                  <RefreshCw size={16} />
                  {spaceCleanupScanBusy ? "扫描中" : "扫描"}
                </button>
                <button className="secondary-button danger-button service-header-button" type="button" onClick={cleanupSpaceArtifacts} disabled={spaceCleanupBusy || spaceCleanupScanBusy || totalCount === 0}>
                  <Trash2 size={16} />
                  {spaceCleanupBusy ? "清理中" : "一键清理"}
                </button>
              </div>
            </div>
            <div className="cleanup-warning">
              <Info size={16} />
              一键清理会删除已上传升级包、数据迁移导出包和报表导出文件；需要保留的文件请先下载到本地。
            </div>
            <div className="cleanup-image-list space-cleanup-list auto-scrollbar">
              {spaceCleanupItems.length ? (
                spaceCleanupItems.map((item) => (
                  <div className="cleanup-image-row" key={item.key}>
                    <div>
                      <strong>{item.label}</strong>
                      <small>{item.description} · {item.path}</small>
                    </div>
                    <span>{item.count} 项 · {item.size_label}</span>
                  </div>
                ))
              ) : (
                <div className="cleanup-image-empty">点击“扫描”查看可清理文件。</div>
              )}
            </div>
            <pre className="cleanup-log auto-scrollbar">{spaceCleanupLogs.length ? spaceCleanupLogs.join("\n") : "等待扫描..."}</pre>
            {spaceCleanupMessage && <div className="inline-message">{spaceCleanupMessage}</div>}
          </div>
          <div className="cleanup-module sqlite-vacuum-panel">
            <div className="service-operation-head">
              <div>
                <strong>SQLite 空间整理</strong>
                <span>删除旧虚拟卷 payload 后，可先备份业务库再执行 VACUUM 释放数据库空闲页。</span>
              </div>
              <div className="cleanup-module-actions">
                <div className="cleanup-summary compact">
                  <strong>{sqliteVacuumScan?.size_label || "待扫描"}</strong>
                  <span>预计释放 {sqliteVacuumScan?.estimated_reclaimable_label || "0 B"}</span>
                </div>
                <button className="primary-button service-header-button" type="button" onClick={scanSqliteVacuum} disabled={sqliteVacuumBusy || spaceCleanupScanBusy}>
                  <RefreshCw size={16} />
                  扫描 SQLite
                </button>
                <button className="secondary-button danger-button service-header-button" type="button" onClick={vacuumSqlite} disabled={sqliteVacuumBusy || spaceCleanupScanBusy || !sqliteVacuumScan}>
                  <RefreshCw size={16} />
                  {sqliteVacuumBusy ? "整理中" : "整理 SQLite"}
                </button>
              </div>
            </div>
            <div className="cleanup-image-row">
              <div>
                <strong>{sqliteVacuumScan?.path || "smartx.db"}</strong>
                <small>{sqliteVacuumScan ? `空闲页 ${sqliteVacuumScan.freelist_count} / 总页 ${sqliteVacuumScan.page_count}` : "点击扫描后显示 SQLite 文件大小和可整理空间。"}</small>
              </div>
            </div>
            {sqliteVacuumLogs.length > 0 && <pre className="cleanup-log auto-scrollbar">{sqliteVacuumLogs.join("\n")}</pre>}
            {sqliteVacuumMessage && <div className="inline-message">{sqliteVacuumMessage}</div>}
          </div>
        </div>
      </>
    );
  }

  function renderUpgrade() {
    const isRunning = Boolean(upgradeTask && runningUpgradeStatuses.has(upgradeTask.status));
    const availablePackages = upgradeHistory.filter((task) => !task.started_at);
    const packageInfo = upgradeVerification?.package;
    return (
      <>
        <PageHeader
          eyebrow="平台升级"
          title="平台升级"
          action={(
            <>
              <input
                ref={fileInputRef}
                className="visually-hidden"
                type="file"
                accept=".gz,.tgz,.tar.gz,application/gzip"
                onChange={(event) => {
                  const file = event.target.files?.[0] ?? null;
                  setUpgradeFile(file);
                  if (file) uploadUpgrade(file).catch(() => undefined);
                  event.currentTarget.value = "";
                }}
                disabled={upgradeBusy || isRunning}
              />
              <button className="primary-button service-header-button" type="button" onClick={() => fileInputRef.current?.click()} disabled={upgradeBusy || isRunning}>
                <FileArchive size={16} />
                上传升级包
              </button>
              <button className="secondary-button service-header-button" type="button" onClick={() => {
                setCleanupDialogOpen(true);
                setCleanupProgress(0);
                setCleanupLogs([]);
                setCleanupImagesList([]);
                setCleanupReclaimable("0 B");
                setCleanupActualReclaimed("");
              }} disabled={cleanupBusy || isRunning}>
                <RefreshCw size={16} />
                {cleanupBusy ? "清理中" : "清理旧版本"}
              </button>
            </>
          )}
        />
        <section className="upgrade-platform-status">
          <div className="upgrade-platform-status-head">
            <div>
              <strong>平台状态</strong>
              <span>版本、升级包和当前运行服务集中展示。</span>
            </div>
            <button className="secondary-button service-header-button" type="button" onClick={() => reloadUpgradeVerification().catch((exc) => setUpgradeMessage(exc instanceof Error ? exc.message : "刷新核验失败"))} disabled={verificationBusy}>
              <RefreshCw size={16} />
              {verificationBusy ? "刷新中" : "刷新状态"}
            </button>
          </div>
          <div className="service-upgrade-status-grid service-upgrade-status-grid-wide">
            <InfoRow label="当前版本" value={formatVersionForDisplay(upgradeVerification?.app_version ?? appVersion)} />
            <InfoRow label="目标版本" value={formatVersionForDisplay(upgradeTask?.target_version)} />
            <InfoRow label="已选升级包" value={upgradeTask?.package_filename ?? "未选择"} />
            <InfoRow label="升级中心组件版本" value={formatVersionForDisplay(upgradeVerification?.runner_version ?? runnerVersion)} />
            <InfoRow label="观测组件版本" value={formatVersionForDisplay(upgradeVerification?.prometheus_version)} />
            <InfoRow label="Compose 项目" value={upgradeVerification?.compose_project ?? "-"} />
            <InfoRow label="最近成功包" value={packageInfo ? `${formatVersionForDisplay(packageInfo.version)} · ${packageInfo.filename || "-"}` : "暂无成功升级记录"} />
            <InfoRow label="升级包 SHA256" value={packageInfo?.sha256 ? shortSha(packageInfo.sha256) : "-"} />
          </div>
          {renderUpgradeRuntimeVerification()}
        </section>
        <div className="service-notice">
          <Info size={16} />
          升级包会保存到系统升级目录；选中一个升级包后可执行预检查、升级、取消选择或删除。
        </div>
        {cleanupMessage && <div className="inline-message">{cleanupMessage}</div>}
        {upgradeMessage && <div className="inline-message">{upgradeMessage}</div>}
        {cleanupDialogOpen && renderCleanupDialog()}
        <section className="upgrade-package-section">
          <div className="service-operation-head">
            <div>
              <strong>可升级版本</strong>
              <span>上传后的离线升级包会保存在系统目录中，选中后再执行升级动作。</span>
            </div>
          </div>
          {availablePackages.length ? (
            <div className="upgrade-package-list">
              {availablePackages.map((task) => (
                <button className={upgradeTask?.task_id === task.task_id ? "upgrade-package-item active" : "upgrade-package-item"} type="button" key={task.task_id} onClick={() => selectUpgradePackage(task)}>
                  <FileArchive size={18} />
                  <span>
                    <strong>{formatVersionForDisplay(task.target_version, "未知版本")}</strong>
                    <small>{task.package_filename || "-"} · {formatTime(task.uploaded_at)} · {upgradeStatusText(task.status)}</small>
                  </span>
                </button>
              ))}
            </div>
          ) : (
            <EmptyUpgrade />
          )}
        </section>
        {upgradeTask && (
          <>
            <div className="service-upgrade-actions">
              <button className="secondary-button" type="button" onClick={precheckUpgrade} disabled={upgradeBusy || isRunning}>
                <ListChecks size={16} />
                预检查
              </button>
              <button className="primary-button" type="button" onClick={startUpgrade} disabled={upgradeBusy || !upgradeTask.precheck_ok || isRunning}>
                <Upload size={16} />
                开始升级
              </button>
              <button className="secondary-button" type="button" onClick={cancelSelectedUpgradePackage} disabled={upgradeBusy || isRunning}>
                <X size={16} />
                取消选择
              </button>
              <button className="secondary-button danger-button" type="button" onClick={deleteSelectedUpgradePackage} disabled={upgradeBusy || isRunning || Boolean(upgradeTask.started_at)}>
                <X size={16} />
                删除
              </button>
              <button className="secondary-button danger-button" type="button" onClick={rollbackUpgrade} disabled={upgradeBusy || isRunning || !upgradeTask.started_at}>
                <RotateCcw size={16} />
                手动回滚
              </button>
            </div>
            {renderUpgradeTask(upgradeTask, { precheckRunning, precheckProgressIndex })}
          </>
        )}
      </>
    );
  }

  function renderUpgradeRuntimeVerification() {
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
          {(upgradeVerification?.services ?? []).map((item) => (
            <div className="upgrade-runtime-row" key={item.service}>
              <span>{item.service}</span>
              <span className={item.running ? "runtime-ok" : "runtime-bad"}>{item.running ? "运行中" : item.status || "未运行"}</span>
              <span title={item.image}>{item.image}</span>
              <span>{formatVersionForDisplay(item.app_version)}</span>
              <span>{formatTime(item.started_at || undefined)}</span>
            </div>
          ))}
          {upgradeVerification && !upgradeVerification.services.length && <div className="empty-state">{upgradeVerification.service_status_error || "未读取到服务状态"}</div>}
          {!upgradeVerification && <div className="empty-state">点击“刷新核验”读取当前服务状态</div>}
        </div>
      </div>
    );
  }

  function renderCleanupDialog() {
    return (
      <div className="modal-backdrop" role="presentation" onClick={() => !cleanupBusy && setCleanupDialogOpen(false)}>
        <div className="cleanup-dialog" role="dialog" aria-modal="true" aria-labelledby="cleanup-dialog-title" onClick={(event) => event.stopPropagation()}>
          <div className="export-dialog-head">
            <div>
              <strong id="cleanup-dialog-title">清理旧版本镜像</strong>
              <span>清理未被任何容器使用的 Docker 镜像，当前运行中的镜像不会被删除。</span>
            </div>
          </div>
          <div className="cleanup-warning">
            <Info size={16} />
            该操作可能移除旧版本镜像，清理后如果需要回滚到旧镜像，可能需要重新上传或重新加载对应升级包。
          </div>
          <div className="cleanup-progress" aria-label={`${cleanupProgress}%`}>
            <span style={{ width: `${cleanupProgress}%` }} />
          </div>
          <div className="cleanup-steps">
            <CleanupStep active={cleanupScanBusy} done={cleanupProgress >= 45} label="扫描未使用镜像" />
            <CleanupStep active={cleanupBusy && cleanupProgress >= 70 && cleanupProgress < 100} done={cleanupProgress >= 100} label="执行镜像清理" />
            <CleanupStep active={false} done={cleanupProgress >= 100 && !cleanupBusy} label="输出清理结果" />
          </div>
          <div className="cleanup-summary">
            <strong>{cleanupImagesList.length} 个未使用镜像</strong>
            <span>候选逻辑大小 {cleanupReclaimable}</span>
            {cleanupActualReclaimed && <span>实际释放 {cleanupActualReclaimed}</span>}
          </div>
          <div className="cleanup-image-list auto-scrollbar">
            {cleanupImagesList.length ? (
              cleanupImagesList.map((image) => (
                <div className="cleanup-image-row" key={image.id}>
                  <div>
                    <strong>{image.display_name}</strong>
                    <small>{image.short_id}{image.created_at ? ` · ${formatUnixTime(image.created_at)}` : ""}</small>
                  </div>
                  <span>{image.reclaimable_size_label ?? image.size_label}</span>
                </div>
              ))
            ) : (
              <div className="cleanup-image-empty">{cleanupProgress >= 45 ? "没有可清理的未使用镜像。" : "请先扫描未使用镜像。"}</div>
            )}
          </div>
          <pre className="cleanup-log auto-scrollbar">{cleanupLogs.length ? cleanupLogs.join("\n") : "等待开始清理..."}</pre>
          <div className="export-dialog-actions">
            <button className="secondary-button cleanup-action-button" type="button" onClick={() => setCleanupDialogOpen(false)} disabled={cleanupBusy || cleanupScanBusy}>
              关闭
            </button>
            <button className="primary-button cleanup-action-button" type="button" onClick={scanCleanupImages} disabled={cleanupBusy || cleanupScanBusy}>
              <RefreshCw size={15} />
              {cleanupScanBusy ? "扫描中" : "扫描"}
            </button>
            <button className="secondary-button cleanup-action-button cleanup-danger-button" type="button" onClick={cleanupImages} disabled={cleanupBusy || cleanupScanBusy || cleanupImagesList.length === 0}>
              <RefreshCw size={15} />
              {cleanupBusy ? "清理中" : "开始清理"}
            </button>
          </div>
        </div>
      </div>
    );
  }

  function renderComponentUpgrade() {
    const isRunning = Boolean(componentTask && runningUpgradeStatuses.has(componentTask.status));
    const selectedComponent = componentInfos.find((component) => component.service === selectedComponentService) ?? componentInfos[0] ?? defaultComponentInfos[0];
    const availablePackages = componentHistory.filter((task) => !task.started_at && (!task.component || task.component === selectedComponent.service));
    return (
      <>
        <PageHeader
          eyebrow="升级中心"
          title="组件升级"
          action={(
            <>
              <input
                ref={componentFileInputRef}
                className="visually-hidden"
                type="file"
                accept=".gz,.tgz,.tar.gz,application/gzip"
                onChange={(event) => {
                  const file = event.target.files?.[0] ?? null;
                  setComponentFile(file);
                  if (file) uploadComponentUpgrade(file).catch(() => undefined);
                  event.currentTarget.value = "";
                }}
                disabled={componentBusy || isRunning}
              />
              <button className="primary-button" type="button" onClick={() => componentFileInputRef.current?.click()} disabled={componentBusy || isRunning}>
                <FileArchive size={16} />
                上传组件包
              </button>
            </>
          )}
        />
        <div className="component-upgrade-card-grid">
          {componentInfos.map((component) => (
            <button
              className={selectedComponent.service === component.service ? "component-upgrade-card active" : "component-upgrade-card"}
              type="button"
              key={component.service}
              aria-label={`${component.display_name} ${component.service} ${formatVersionForDisplay(component.version)}`}
              onClick={() => {
                setSelectedComponentService(component.service);
                if (componentTask?.component && componentTask.component !== component.service) setComponentTask(null);
              }}
            >
              <strong>{component.display_name}</strong>
              <span>{component.service}</span>
              <small>{formatVersionForDisplay(component.version)}</small>
            </button>
          ))}
        </div>
        <div className="service-upgrade-status-grid">
          <InfoRow label="组件名称" value={`${selectedComponent.display_name} / ${selectedComponent.service}`} />
          <InfoRow label="当前版本" value={formatVersionForDisplay(selectedComponent.version || (selectedComponent.service === "upgrade-runner" ? runnerVersion : "-"))} />
          <InfoRow label="执行者" value={selectedComponent.executor || "-"} />
          <InfoRow label="目标版本" value={formatVersionForDisplay(componentTask?.component === selectedComponent.service ? componentTask?.target_version : undefined)} />
          <InfoRow label="已选升级包" value={componentTask?.component === selectedComponent.service ? componentTask?.package_filename ?? "未选择" : "未选择"} />
        </div>
        <div className="service-notice">
          <Info size={16} />
          {selectedComponent.service === "prometheus"
            ? "升级 Prometheus 观测组件会保留历史指标，升级前会检查数据目录权限；平台升级任务执行中时不能升级组件。"
            : "升级中心组件只更新 upgrade-runner，不修改业务库、历史指标和平台数据卷；平台升级任务执行中时不能升级组件。"}
        </div>
        {componentMessage && <div className="inline-message">{componentMessage}</div>}
        <section className="upgrade-package-section">
          <div className="service-operation-head">
            <div>
              <strong>可升级组件包</strong>
              <span>上传后的组件包会保存在系统目录中，选中后再执行组件预检查和升级。</span>
            </div>
          </div>
          {availablePackages.length ? (
            <div className="upgrade-package-list">
              {availablePackages.map((task) => (
                <button className={componentTask?.task_id === task.task_id ? "upgrade-package-item active" : "upgrade-package-item"} type="button" key={task.task_id} onClick={() => selectComponentPackage(task)}>
                  <FileArchive size={18} />
                  <span>
                    <strong>{formatVersionForDisplay(task.target_version, "未知版本")}</strong>
                    <small>{task.package_filename || "-"} · {formatTime(task.uploaded_at)} · {upgradeStatusText(task.status)}</small>
                  </span>
                </button>
              ))}
            </div>
          ) : (
            <EmptyUpgrade message={`点击右上角“上传组件包”后，可在这里执行${selectedComponent.display_name}预检查和组件升级。`} />
          )}
        </section>
        {componentTask && componentTask.component === selectedComponent.service && (
          <>
            <div className="service-upgrade-actions">
              <button className="secondary-button" type="button" onClick={precheckComponentUpgrade} disabled={componentBusy || isRunning}>
                <ListChecks size={16} />
                预检查
              </button>
              <button className="primary-button" type="button" onClick={startComponentUpgrade} disabled={componentBusy || !componentTask.precheck_ok || isRunning}>
                <Upload size={16} />
                开始升级
              </button>
              <button className="secondary-button" type="button" onClick={cancelSelectedComponentPackage} disabled={componentBusy || isRunning}>
                <X size={16} />
                取消选择
              </button>
              <button className="secondary-button danger-button" type="button" onClick={deleteSelectedComponentPackage} disabled={componentBusy || isRunning || Boolean(componentTask.started_at)}>
                <X size={16} />
                删除
              </button>
            </div>
            {renderUpgradeTask(componentTask, {
              file: componentFile,
              componentMode: true,
              precheckExpanded: componentPrecheckExpanded,
              precheckRunning: componentPrecheckRunning,
              precheckProgressIndex: componentPrecheckProgressIndex,
              stepsExpanded: componentStepsExpanded,
              logsExpanded: componentLogsExpanded,
              onPrecheckToggle: () => setComponentPrecheckExpanded((expanded) => !expanded),
              onStepsToggle: () => setComponentStepsExpanded((expanded) => !expanded),
              onLogsToggle: () => setComponentLogsExpanded((expanded) => !expanded)
            })}
          </>
        )}
      </>
    );
  }

  function renderUpgradeTask(task: UpgradeTask, options?: { file?: File | null; precheckExpanded?: boolean; precheckRunning?: boolean; precheckProgressIndex?: number; stepsExpanded?: boolean; logsExpanded?: boolean; onPrecheckToggle?: () => void; onStepsToggle?: () => void; onLogsToggle?: () => void; componentMode?: boolean }) {
    const currentFile = options?.file ?? upgradeFile;
    const isComponent = Boolean(options?.componentMode);
    return (
      <div className="service-upgrade-detail">
        <div className="service-info-table">
          <InfoRow label="升级包" value={task.package_filename ?? currentFile?.name ?? "-"} />
          {isComponent && <InfoRow label="组件" value={task.component || "upgrade-runner"} />}
          <InfoRow label="影响服务" value={task.restart_services?.join("、") || "-"} />
          <InfoRow label="数据库迁移" value={isComponent ? "不涉及" : task.database_migration ? "需要" : "不需要"} />
          {!isComponent && <InfoRow label="备份文件" value={task.backup_path || "升级开始后生成"} />}
        </div>
        {task.release_notes && <pre className="upgrade-release-notes auto-scrollbar">{task.release_notes}</pre>}
        {(options?.precheckRunning || task.checks.length > 0 || task.precheck_ok !== undefined) && (
          <CollapsibleSection title="预检查" expanded={options?.precheckExpanded ?? precheckExpanded} onToggle={options?.onPrecheckToggle ?? (() => setPrecheckExpanded((expanded) => !expanded))}>
            <div className="upgrade-steps upgrade-precheck-steps">
              {displayPrecheckSteps(task, isComponent, Boolean(options?.precheckRunning), options?.precheckProgressIndex ?? -1).map((step) => (
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
        {!!displayUpgradeSteps(task).length && (
          <CollapsibleSection title="执行步骤" expanded={options?.stepsExpanded ?? stepsExpanded} onToggle={options?.onStepsToggle ?? (() => setStepsExpanded((expanded) => !expanded))}>
            <div className="upgrade-steps">
              {displayUpgradeSteps(task).map((step) => (
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
          <CollapsibleSection title="升级日志" expanded={options?.logsExpanded ?? logsExpanded} onToggle={options?.onLogsToggle ?? (() => setLogsExpanded((expanded) => !expanded))}>
            <pre className="upgrade-log auto-scrollbar">{task.logs.join("\n")}</pre>
          </CollapsibleSection>
        )}
      </div>
    );
  }

  function renderHistory() {
    const allHistory = [...upgradeHistory.map((item) => ({ ...item, kind: item.kind || "platform" })), ...componentHistory].sort((left, right) => new Date(right.updated_at || right.uploaded_at || 0).getTime() - new Date(left.updated_at || left.uploaded_at || 0).getTime());
    return (
      <>
        <PageHeader eyebrow="升级中心" title="升级历史" action={<button className="secondary-button" type="button" onClick={() => { reloadUpgradeHistory().catch(() => undefined); reloadComponentHistory().catch(() => undefined); }}>刷新</button>} />
        <div className="service-history-table">
          <div className="service-history-head">
            <span>目标版本</span>
            <span>状态</span>
            <span>上传时间</span>
            <span>完成时间</span>
            <span>备份路径</span>
          </div>
          {allHistory.map((item) => (
            <button className="service-history-row" type="button" key={item.task_id} onClick={() => loadHistoryItem(item)}>
              <span>{item.kind === "component" ? "组件升级" : "平台升级"} · {formatVersionForDisplay(item.target_version)}</span>
              <span>{upgradeStatusText(item.status)}</span>
              <span>{formatTime(item.uploaded_at)}</span>
              <span>{formatTime(item.finished_at || item.rollback_finished_at)}</span>
              <span>{item.backup_path || "-"}</span>
            </button>
          ))}
          {!allHistory.length && <div className="empty-state">暂无升级历史</div>}
        </div>
      </>
    );
  }
}

function PageHeader({ eyebrow, title, action }: { eyebrow: string; title: string; action?: React.ReactNode }) {
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

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="service-info-row">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function CollapsibleSection({ title, expanded, onToggle, children }: { title: string; expanded: boolean; onToggle: () => void; children: React.ReactNode }) {
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

function CleanupStep({ active, done, label }: { active: boolean; done: boolean; label: string }) {
  return (
    <div className={done ? "cleanup-step done" : active ? "cleanup-step active" : "cleanup-step"}>
      <span>{done ? <Check size={14} /> : active ? <LoaderCircle size={14} /> : <Circle size={14} />}</span>
      <strong>{label}</strong>
    </div>
  );
}

function LocalStorageUsageCard({ usage, message }: { usage: LocalStorageUsage | null; message: string }) {
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

function EmptyUpgrade({ message = "点击右上角“上传升级包”后，可在这里执行预检查、升级和回滚。" }: { message?: string }) {
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

function UploadPanel({ title, description, actionText, disabled, onClick }: { title: string; description: string; actionText: string; disabled?: boolean; onClick: () => void }) {
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

function scrollElementToTop(element: HTMLElement | null) {
  if (!element) return;
  if (typeof element.scrollTo === "function") {
    element.scrollTo({ top: 0 });
    return;
  }
  element.scrollTop = 0;
}

function upgradeStatusText(status: string): string {
  const labels: Record<string, string> = {
    uploaded: "已上传",
    prechecked: "预检查通过",
    pending: "等待执行",
    running: "升级中",
    succeeded: "升级成功",
    failed: "升级失败",
    rollback_pending: "等待回滚",
    rollback_running: "回滚中",
    rolled_back: "已回滚",
    rollback_failed: "回滚失败"
  };
  return labels[status] ?? status;
}

function stepStatusText(status: string): string {
  const labels: Record<string, string> = {
    pending: "未执行",
    running: "执行中",
    succeeded: "完成",
    failed: "失败"
  };
  return labels[status] ?? status;
}

function stepIcon(status: string) {
  if (status === "succeeded") return <Check size={14} />;
  if (status === "failed") return <X size={14} />;
  if (status === "running") return <LoaderCircle size={14} />;
  return <Circle size={14} />;
}

function displayUpgradeSteps(task: UpgradeTask) {
  const defaults = task.status.startsWith("rollback") || task.status === "rolled_back" ? rollbackStepDefaults : upgradeStepDefaults;
  const existing = new Map(task.steps.map((step) => [step.key, step]));
  const merged = defaults.map((item) => ({ ...item, status: "pending", ...existing.get(item.key) }));
  const known = new Set(defaults.map((item) => item.key));
  return [...merged, ...task.steps.filter((step) => !known.has(step.key))];
}

function displayPrecheckSteps(task: UpgradeTask, isComponent: boolean, running: boolean, progressIndex: number): DisplayStep[] {
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
    return defaults.map((item, index) => {
      const isLast = index === defaults.length - 1;
      if (!isLast) {
        const relatedChecks = item.checks.map((name) => checksByName.get(name)).filter((check): check is UpgradeCheck => Boolean(check));
        const relatedFailed = relatedChecks.filter((check) => !check.ok);
        return {
          key: item.key,
          title: item.title,
          status: relatedFailed.length ? "failed" : relatedChecks.length === item.checks.length ? "succeeded" : "pending",
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

function formatCheckMessages(checks: UpgradeCheck[]): string | undefined {
  if (!checks.length) return undefined;
  return checks.map((check) => {
    const detail = formatCheckDetail(check.detail);
    return detail ? `${check.message} ${detail}` : check.message;
  }).join(" ");
}

function formatCheckDetail(detail: unknown): string {
  if (!detail) return "";
  if (Array.isArray(detail)) {
    return detail.map((item) => String(item)).filter(Boolean).join("；");
  }
  if (typeof detail === "object") {
    return Object.entries(detail as Record<string, unknown>).map(([key, value]) => `${key}: ${String(value)}`).join("；");
  }
  return String(detail);
}

function migrationExportTaskPatch(task: MigrationExportTask): Partial<Omit<AppTask, "id" | "createdAt">> {
  return {
    status: task.status === "failed" ? "failed" : task.status === "succeeded" ? "succeeded" : "running",
    progress: Math.max(0, Math.min(100, task.progress || 0)),
    detail: task.detail || migrationExportStatusText(task.status),
    logs: task.logs,
    steps: task.steps,
    links: task.status === "succeeded" && task.download_url ? [{ label: "下载", filename: task.filename, url: task.download_url, path: task.saved_path }] : undefined
  };
}

function migrationExportStatusText(status: MigrationExportTask["status"]): string {
  const labels: Record<MigrationExportTask["status"], string> = {
    pending: "等待开始导出",
    running: "正在生成迁移包",
    succeeded: "迁移包已生成",
    failed: "导出失败"
  };
  return labels[status];
}

function migrationImportTaskPatch(task: MigrationImportTask): Partial<Omit<AppTask, "id" | "createdAt">> {
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

function migrationImportStatusText(status: MigrationImportTask["status"]): string {
  const labels: Record<MigrationImportTask["status"], string> = {
    pending: "等待开始导入",
    running: "正在导入迁移包",
    succeeded: "数据迁移导入完成",
    failed: "导入失败"
  };
  return labels[status];
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function formatTime(value?: string): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", { hour12: false });
}

function formatUnixTime(value?: number): string {
  if (!value) return "-";
  return formatTime(new Date(value * 1000).toISOString());
}

function formatBytes(value?: number): string {
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

function shortSha(value: string): string {
  return value.length > 16 ? `${value.slice(0, 12)}...${value.slice(-8)}` : value;
}

function uploadProgressTaskPatch(progress: number | TransferProgress): { progress: number; detail: string } {
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

function transferProgressValue(progress: number | TransferProgress): number {
  return typeof progress === "number" ? progress : progress.progress;
}

function formatTransferSpeed(value?: number): string {
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

function upgradeProgress(task: UpgradeTask): number {
  if (task.status === "succeeded" || task.status === "rolled_back") return 100;
  if (task.status === "failed" || task.status === "rollback_failed") return 100;
  const total = task.steps.length || 6;
  const finished = task.steps.filter((step) => step.status === "succeeded").length;
  const running = task.steps.some((step) => step.status === "running") ? 0.5 : 0;
  return Math.min(95, Math.max(10, Math.round(((finished + running) / total) * 100)));
}

function activeUpgradeDetail(task: UpgradeTask): string {
  const running = task.steps.find((step) => step.status === "running");
  if (running?.message) return running.message;
  if (running?.title) return running.title;
  const failed = task.steps.find((step) => step.status === "failed");
  if (failed?.message) return failed.message;
  return upgradeStatusText(task.status);
}


function upgradeTaskStatus(task: UpgradeTask): AppTask["status"] {
  if (task.status === "succeeded" || task.status === "rolled_back") return "succeeded";
  if (task.status === "failed" || task.status === "rollback_failed") return "failed";
  return "running";
}
