import { FileArchive, Info, ListChecks, RefreshCw, RotateCcw, Upload, X } from "lucide-react";
import { useEffect, useRef, useState, type Dispatch, type MutableRefObject, type SetStateAction } from "react";
import { api } from "../../services/api";
import type { AppTask, ComponentInfo, UpgradePostCleanupStatus, UpgradeTask, UpgradeVerification } from "../../types";
import {
  CleanupDialog,
  EmptyUpgrade,
  InfoRow,
  PageHeader,
  UpgradeRuntimeVerification,
  UpgradeTaskDetail,
  activeUpgradeDetail,
  formatBytes,
  formatTime,
  formatVersionForDisplay,
  postCleanupStatusText,
  restartWindowMessage,
  runnerRequirementLabel,
  runningUpgradeStatuses,
  shortSha,
  taskId,
  upgradeProgress,
  upgradeStatusText,
  upgradeTaskStatus,
  uploadProgressTaskPatch,
  platformPrecheckStepDefaults,
  type CleanupScanImage,
  type RestartWindowState
} from "./shared";

interface PlatformUpgradeSectionProps {
  active: boolean;
  addTask: (task: Omit<AppTask, "createdAt" | "updatedAt">) => void;
  updateTask: (id: string, patch: Partial<Omit<AppTask, "id" | "createdAt">>) => void;
  appVersion: string;
  runnerVersion: string;
  componentInfos: ComponentInfo[];
  setAppVersion: (v: string) => void;
  setRunnerVersion: (v: string) => void;
  setComponentInfos: Dispatch<SetStateAction<ComponentInfo[]>>;
  upgradeHistory: UpgradeTask[];
  reloadUpgradeHistory: () => Promise<void>;
  upgradeRunTaskRef: MutableRefObject<Record<string, string>>;
  historySelection: UpgradeTask | null;
  onConsumeHistorySelection: () => void;
}

export function PlatformUpgradeSection({
  active,
  addTask,
  updateTask,
  appVersion,
  runnerVersion,
  componentInfos,
  setAppVersion,
  setRunnerVersion,
  setComponentInfos,
  upgradeHistory,
  reloadUpgradeHistory,
  upgradeRunTaskRef,
  historySelection,
  onConsumeHistorySelection
}: PlatformUpgradeSectionProps) {
  const [upgradeFile, setUpgradeFile] = useState<File | null>(null);
  const [upgradeTask, setUpgradeTask] = useState<UpgradeTask | null>(null);
  const [upgradeVerification, setUpgradeVerification] = useState<UpgradeVerification | null>(null);
  const [postCleanupStatus, setPostCleanupStatus] = useState<UpgradePostCleanupStatus | null>(null);
  const [postCleanupBusy, setPostCleanupBusy] = useState(false);
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
  const [cleanupProtectedImages, setCleanupProtectedImages] = useState<CleanupScanImage[]>([]);
  const [cleanupSelectedIds, setCleanupSelectedIds] = useState<Set<string>>(new Set());
  const [cleanupReclaimable, setCleanupReclaimable] = useState("0 B");
  const [cleanupActualReclaimed, setCleanupActualReclaimed] = useState("");
  const [precheckExpanded, setPrecheckExpanded] = useState(true);
  const [precheckRunning, setPrecheckRunning] = useState(false);
  const [precheckProgressIndex, setPrecheckProgressIndex] = useState(-1);
  const [stepsExpanded, setStepsExpanded] = useState(true);
  const [logsExpanded, setLogsExpanded] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const upgradeRestartWindowRef = useRef<RestartWindowState | null>(null);
  const verificationRestartWindowRef = useRef<RestartWindowState | null>(null);
  const postCleanupRestartWindowRef = useRef<RestartWindowState | null>(null);

  async function reloadUpgradeVerification() {
    setVerificationBusy(true);
    try {
      const result = await api.upgradeVerification();
      if (verificationRestartWindowRef.current) {
        verificationRestartWindowRef.current = null;
        setUpgradeMessage("");
      }
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
      if (result.package?.task_id) {
        api
          .upgradePostCleanupStatus(result.package.task_id)
          .then((status) => {
            postCleanupRestartWindowRef.current = null;
            setPostCleanupStatus(status);
          })
          .catch((exc) => {
            setUpgradeMessage(restartWindowMessage(exc, postCleanupRestartWindowRef, "服务正在重启，正在重新连接...", "刷新升级后清理状态失败"));
            setPostCleanupStatus(null);
          });
      } else {
        setPostCleanupStatus(null);
      }
    } catch (exc) {
      setUpgradeMessage(restartWindowMessage(exc, verificationRestartWindowRef, "服务正在重启，正在重新连接...", "刷新核验失败"));
      throw exc;
    } finally {
      setVerificationBusy(false);
    }
  }

  async function retryPostUpgradeCleanup() {
    const parentTaskId = postCleanupStatus?.parent_task_id || upgradeVerification?.package?.task_id;
    if (!parentTaskId) return;
    setPostCleanupBusy(true);
    setUpgradeMessage("");
    try {
      const task = await api.retryUpgradePostCleanup(parentTaskId);
      setPostCleanupStatus({ parent_task_id: parentTaskId, status: task.status, task_id: task.task_id, task });
      addTask({
        id: task.task_id,
        kind: "upgrade",
        title: "升级后清理",
        detail: upgradeStatusText(task.status),
        status: upgradeTaskStatus(task),
        progress: upgradeProgress(task)
      });
      setUpgradeMessage("升级后清理任务已提交。");
    } catch (exc) {
      setUpgradeMessage(exc instanceof Error ? exc.message : "提交升级后清理失败");
    } finally {
      setPostCleanupBusy(false);
    }
  }

  useEffect(() => {
    api.upgradeVersion().then((result) => setAppVersion(result.version)).catch(() => undefined);
    reloadUpgradeHistory().catch(() => undefined);
    reloadUpgradeVerification().catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!upgradeTask || !runningUpgradeStatuses.has(upgradeTask.status)) return undefined;
    const timer = window.setInterval(() => {
      api.upgradeStatus(upgradeTask.task_id)
        .then((next) => {
          if (upgradeRestartWindowRef.current) {
            upgradeRestartWindowRef.current = null;
            setUpgradeMessage("");
          }
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
            api
              .upgradePostCleanupStatus(next.task_id)
              .then((status) => {
                postCleanupRestartWindowRef.current = null;
                setPostCleanupStatus(status);
              })
              .catch((exc) => setUpgradeMessage(restartWindowMessage(exc, postCleanupRestartWindowRef, "服务正在重启，正在重新连接...", "刷新升级后清理状态失败")));
          }
        })
        .catch((exc) => setUpgradeMessage(restartWindowMessage(exc, upgradeRestartWindowRef, "服务正在重启，正在重新连接...", "刷新升级状态失败")));
    }, 2500);
    return () => window.clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [upgradeTask, updateTask]);

  useEffect(() => {
    if (!historySelection || historySelection.kind === "component") return;
    selectUpgradePackage(historySelection);
    onConsumeHistorySelection();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [historySelection]);

  async function scanCleanupImages() {
    setCleanupMessage("");
    setCleanupLogs(["开始扫描未使用 Docker 镜像..."]);
    setCleanupProgress(20);
    setCleanupScanBusy(true);
    try {
      const result = await api.scanUnusedImages();
      setCleanupImagesList(result.images);
      setCleanupProtectedImages(result.protected_images || []);
      setCleanupSelectedIds(new Set(result.images.map((image) => image.id)));
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

  function toggleCleanupImage(imageId: string) {
    setCleanupSelectedIds((current) => {
      const next = new Set(current);
      if (next.has(imageId)) next.delete(imageId);
      else next.add(imageId);
      return next;
    });
  }

  function toggleAllCleanupImages() {
    if (!cleanupImagesList.length) return;
    setCleanupSelectedIds((current) => {
      if (current.size === cleanupImagesList.length) return new Set();
      return new Set(cleanupImagesList.map((image) => image.id));
    });
  }

  async function cleanupImages() {
    const selectedCount = cleanupSelectedIds.size;
    setCleanupMessage("");
    setCleanupLogs((current) => [
      ...current,
      `准备清理 ${selectedCount} 个选中镜像，预计释放 ${cleanupReclaimable}。`,
      "正在执行镜像清理..."
    ]);
    setCleanupProgress(70);
    setCleanupBusy(true);
    const id = taskId("cleanup-images");
    addTask({ id, kind: "upgrade", title: "清理未使用镜像", detail: `正在清理 ${selectedCount} 个选中的未使用 Docker 镜像`, status: "running", progress: 60 });
    try {
      const result = await api.cleanupUnusedImages(Array.from(cleanupSelectedIds));
      setCleanupProgress(100);
      updateTask(id, { status: result.ok ? "succeeded" : "failed", progress: 100, detail: result.message, logs: result.logs });
      setCleanupLogs((current) => [...current, ...(result.logs || []), result.message, ...(result.errors || []), "清理完成。"]);
      setCleanupMessage(result.message);
      setCleanupActualReclaimed(result.space_reclaimed_label ?? formatBytes(result.space_reclaimed));
      setCleanupReclaimable(result.space_reclaimable_before_label ?? cleanupReclaimable);
      setCleanupImagesList([]);
      setCleanupProtectedImages([]);
      setCleanupSelectedIds(new Set());
    } catch (exc) {
      const message = exc instanceof Error ? exc.message : "清理未使用镜像失败";
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

  async function handleUpgradeRecovery(action: "continue" | "rollback" | "fail") {
    if (!upgradeTask) return;
    setUpgradeBusy(true);
    setUpgradeMessage("");
    try {
      const result = action === "continue"
        ? await api.continueUpgradeRecovery(upgradeTask.task_id)
        : action === "rollback"
          ? await api.rollbackUpgradeRecovery(upgradeTask.task_id)
          : await api.failUpgradeRecovery(upgradeTask.task_id);
      const next = action === "fail" ? result : { ...result, status: "running" };
      setUpgradeTask(next);
      if (action !== "fail") {
        upgradeRunTaskRef.current[result.task_id] = result.task_id;
        setUpgradeMessage(action === "continue" ? "已请求 upgrade-runner 继续执行。" : "已请求 upgrade-runner 执行回滚。");
      } else {
        setUpgradeMessage("升级任务已标记为失败。");
      }
      await reloadUpgradeHistory();
    } catch (exc) {
      setUpgradeMessage(exc instanceof Error ? exc.message : "提交恢复操作失败");
    } finally {
      setUpgradeBusy(false);
    }
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

  if (!active) return null;

  const isRunning = Boolean(upgradeTask && runningUpgradeStatuses.has(upgradeTask.status));
  const needsRecovery = upgradeTask?.status === "recovery_required";
  const availablePackages = upgradeHistory.filter((task) => !task.started_at);
  const packageInfo = upgradeVerification?.package;
  const selectedPackageSha = upgradeTask?.package_sha256 || upgradeTask?.uploaded_sha256;
  const runnerInfo = componentInfos.find((component) => component.service === "upgrade-runner");
  const runnerCompatible = runnerInfo?.compatible;
  const runnerRequirement = upgradeTask ? runnerRequirementLabel(upgradeTask, runnerInfo) : "";
  const runnerRequirementWarn = runnerRequirement.startsWith("缺少") || runnerRequirement.startsWith("需要");
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
          <InfoRow
            label="Runner 当前状态"
            value={runnerCompatible === undefined ? "-" : runnerCompatible ? "满足平台要求" : "不满足平台要求，请检查 Runner 心跳或升级 Runner"}
            tone={runnerCompatible === undefined ? undefined : runnerCompatible ? "ok" : "warn"}
          />
          <InfoRow
            label="升级包 Runner 要求"
            value={upgradeTask ? runnerRequirement : "未选择升级包"}
            tone={runnerRequirementWarn ? "warn" : undefined}
          />
          <InfoRow label="观测组件版本" value={formatVersionForDisplay(upgradeVerification?.prometheus_version)} />
          <InfoRow label="Compose 项目" value={upgradeVerification?.compose_project ?? "-"} />
          <InfoRow label="最近成功包" value={packageInfo ? `${formatVersionForDisplay(packageInfo.version)} · ${packageInfo.filename || "-"}` : "暂无成功升级记录"} />
          <InfoRow label="已选升级包 SHA256" value={selectedPackageSha ? shortSha(selectedPackageSha) : "-"} />
          <InfoRow label="最近成功包 SHA256" value={packageInfo?.sha256 ? shortSha(packageInfo.sha256) : "-"} />
          <InfoRow label="旧环境清理" value={postCleanupStatusText(postCleanupStatus)} />
        </div>
        {postCleanupStatus && ["failed", "warning"].includes(postCleanupStatus.status) && (
          <div className="service-upgrade-actions service-upgrade-actions-inline">
            <button className="secondary-button" type="button" onClick={retryPostUpgradeCleanup} disabled={postCleanupBusy}>
              <RefreshCw size={16} />
              {postCleanupBusy ? "提交中" : "重试清理"}
            </button>
          </div>
        )}
        <UpgradeRuntimeVerification verification={upgradeVerification} />
      </section>
      <div className="service-notice">
        <Info size={16} />
        升级包会保存到系统升级目录；选中一个升级包后可执行预检查、升级、取消选择或删除。
      </div>
      {cleanupMessage && <div className="inline-message">{cleanupMessage}</div>}
      {upgradeMessage && <div className="inline-message">{upgradeMessage}</div>}
      {cleanupDialogOpen && (
        <CleanupDialog
          busy={cleanupBusy}
          scanBusy={cleanupScanBusy}
          progress={cleanupProgress}
          logs={cleanupLogs}
          images={cleanupImagesList}
          protectedImages={cleanupProtectedImages}
          selectedIds={cleanupSelectedIds}
          onToggle={toggleCleanupImage}
          onToggleAll={toggleAllCleanupImages}
          reclaimable={cleanupReclaimable}
          actualReclaimed={cleanupActualReclaimed}
          onClose={() => setCleanupDialogOpen(false)}
          onScan={scanCleanupImages}
          onCleanup={cleanupImages}
        />
      )}
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
            <button className="secondary-button" type="button" onClick={precheckUpgrade} disabled={upgradeBusy || isRunning || needsRecovery}>
              <ListChecks size={16} />
              预检查
            </button>
            <button className="primary-button" type="button" onClick={startUpgrade} disabled={upgradeBusy || !upgradeTask.precheck_ok || isRunning || needsRecovery}>
              <Upload size={16} />
              开始升级
            </button>
            <button className="secondary-button" type="button" onClick={cancelSelectedUpgradePackage} disabled={upgradeBusy || isRunning || needsRecovery}>
              <X size={16} />
              取消选择
            </button>
            <button className="secondary-button danger-button" type="button" onClick={deleteSelectedUpgradePackage} disabled={upgradeBusy || isRunning || needsRecovery}>
              <X size={16} />
              删除
            </button>
            <button className="secondary-button danger-button" type="button" onClick={rollbackUpgrade} disabled={upgradeBusy || isRunning || needsRecovery || !upgradeTask.started_at}>
              <RotateCcw size={16} />
              手动回滚
            </button>
          </div>
          <UpgradeTaskDetail
            task={upgradeTask}
            file={upgradeFile}
            componentMode={false}
            precheckExpanded={precheckExpanded}
            precheckRunning={precheckRunning}
            precheckProgressIndex={precheckProgressIndex}
            stepsExpanded={stepsExpanded}
            logsExpanded={logsExpanded}
            onPrecheckToggle={() => setPrecheckExpanded((expanded) => !expanded)}
            onStepsToggle={() => setStepsExpanded((expanded) => !expanded)}
            onLogsToggle={() => setLogsExpanded((expanded) => !expanded)}
            upgradeBusy={upgradeBusy}
            onRecovery={handleUpgradeRecovery}
          />
        </>
      )}
    </>
  );
}
