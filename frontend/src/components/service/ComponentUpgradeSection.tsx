import { FileArchive, Info, ListChecks, Upload, X } from "lucide-react";
import { useEffect, useRef, useState, type Dispatch, type MutableRefObject, type SetStateAction } from "react";
import { api } from "../../services/api";
import type { AppTask, ComponentInfo, UpgradeTask } from "../../types";
import {
  EmptyUpgrade,
  InfoRow,
  PageHeader,
  UpgradeTaskDetail,
  activeUpgradeDetail,
  componentPrecheckStepDefaults,
  componentServiceFromTask,
  defaultComponentInfos,
  formatTime,
  formatVersionForDisplay,
  restartWindowMessage,
  runningUpgradeStatuses,
  taskBelongsToComponent,
  taskId,
  upgradeProgress,
  upgradeStatusText,
  upgradeTaskStatus,
  uploadProgressTaskPatch,
  type RestartWindowState
} from "./shared";

interface ComponentUpgradeSectionProps {
  active: boolean;
  addTask: (task: Omit<AppTask, "createdAt" | "updatedAt">) => void;
  updateTask: (id: string, patch: Partial<Omit<AppTask, "id" | "createdAt">>) => void;
  runnerVersion: string;
  componentInfos: ComponentInfo[];
  selectedComponentService: string;
  setRunnerVersion: (v: string) => void;
  setComponentInfos: Dispatch<SetStateAction<ComponentInfo[]>>;
  setSelectedComponentService: (v: string) => void;
  componentHistory: UpgradeTask[];
  setComponentHistory: Dispatch<SetStateAction<UpgradeTask[]>>;
  reloadComponentHistory: () => Promise<void>;
  reloadComponentInfos: () => Promise<void>;
  upgradeRunTaskRef: MutableRefObject<Record<string, string>>;
  historySelection: UpgradeTask | null;
  onConsumeHistorySelection: () => void;
}

export function ComponentUpgradeSection({
  active,
  addTask,
  updateTask,
  runnerVersion,
  componentInfos,
  selectedComponentService,
  setRunnerVersion,
  setComponentInfos,
  setSelectedComponentService,
  componentHistory,
  setComponentHistory,
  reloadComponentHistory,
  reloadComponentInfos,
  upgradeRunTaskRef,
  historySelection,
  onConsumeHistorySelection
}: ComponentUpgradeSectionProps) {
  const [componentFile, setComponentFile] = useState<File | null>(null);
  const [componentTask, setComponentTask] = useState<UpgradeTask | null>(null);
  const [componentBusy, setComponentBusy] = useState(false);
  const [componentMessage, setComponentMessage] = useState("");
  const [componentPrecheckExpanded, setComponentPrecheckExpanded] = useState(true);
  const [componentPrecheckRunning, setComponentPrecheckRunning] = useState(false);
  const [componentPrecheckProgressIndex, setComponentPrecheckProgressIndex] = useState(-1);
  const [componentStepsExpanded, setComponentStepsExpanded] = useState(true);
  const [componentLogsExpanded, setComponentLogsExpanded] = useState(false);
  const componentFileInputRef = useRef<HTMLInputElement | null>(null);
  const componentRestartWindowRef = useRef<RestartWindowState | null>(null);

  async function refreshComponentUpgradeState(taskId?: string, knownTask?: UpgradeTask) {
    const statusRequest = taskId && !knownTask ? api.componentUpgradeStatus(taskId) : Promise.resolve(knownTask);
    const [statusResult, historyResult, componentsResult, versionResult] = await Promise.allSettled([
      statusRequest,
      api.componentUpgradeHistory(),
      api.componentUpgradeComponents(),
      api.componentUpgradeVersion()
    ]);
    let latestTask: UpgradeTask | undefined;
    if (statusResult.status === "fulfilled" && statusResult.value) {
      latestTask = statusResult.value;
      setComponentTask(latestTask);
      if (latestTask.steps.length) setComponentStepsExpanded(true);
      if (latestTask.logs.length) setComponentLogsExpanded(true);
    }
    if (historyResult.status === "fulfilled") setComponentHistory(historyResult.value);
    if (componentsResult.status === "fulfilled" && componentsResult.value.components.length) {
      setComponentInfos(componentsResult.value.components);
      const selectedExists = componentsResult.value.components.some((component) => component.service === selectedComponentService);
      if (!selectedExists) setSelectedComponentService(componentsResult.value.components[0].service);
    }
    if (versionResult.status === "fulfilled") setRunnerVersion(versionResult.value.version);
    return latestTask;
  }

  useEffect(() => {
    api.componentUpgradeVersion().then((result) => setRunnerVersion(result.version)).catch(() => undefined);
    reloadComponentInfos().catch(() => undefined);
    reloadComponentHistory().catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!componentTask || !runningUpgradeStatuses.has(componentTask.status)) return undefined;
    const timer = window.setInterval(() => {
      api.componentUpgradeStatus(componentTask.task_id)
        .then((next) => {
          if (componentRestartWindowRef.current) {
            componentRestartWindowRef.current = null;
            setComponentMessage("");
          }
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
            refreshComponentUpgradeState(next.task_id, next).catch(() => undefined);
          }
        })
        .catch((exc) => setComponentMessage(restartWindowMessage(exc, componentRestartWindowRef, "升级中心组件正在重启，正在重新连接...", "刷新组件升级状态失败")));
    }, 2500);
    return () => window.clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [componentTask, updateTask]);

  useEffect(() => {
    if (!historySelection || historySelection.kind !== "component") return;
    selectComponentPackage(historySelection);
    onConsumeHistorySelection();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [historySelection]);

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
      const latestTask = await refreshComponentUpgradeState(task.task_id);
      if (latestTask) {
        updateTask(id, { status: upgradeTaskStatus(latestTask), progress: upgradeProgress(latestTask), detail: activeUpgradeDetail(latestTask) });
        if (!runningUpgradeStatuses.has(latestTask.status)) delete upgradeRunTaskRef.current[latestTask.task_id];
      }
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
    const service = componentServiceFromTask(task);
    if (service) setSelectedComponentService(service);
    setComponentPrecheckExpanded(Boolean(task.checks.length));
    setComponentStepsExpanded(Boolean(task.steps.length));
    setComponentLogsExpanded(false);
    setComponentMessage("");
  }

  async function handleComponentRecovery(action: "continue" | "rollback" | "fail") {
    if (!componentTask) return;
    setComponentBusy(true);
    setComponentMessage("");
    try {
      const result = action === "continue"
        ? await api.continueUpgradeRecovery(componentTask.task_id)
        : action === "rollback"
          ? await api.rollbackUpgradeRecovery(componentTask.task_id)
          : await api.failUpgradeRecovery(componentTask.task_id);
      const next = action === "fail" ? result : { ...result, status: "running" };
      setComponentTask(next);
      if (action !== "fail") {
        upgradeRunTaskRef.current[result.task_id] = result.task_id;
        setComponentMessage(action === "continue" ? "已请求 upgrade-runner 继续执行。" : "已请求 upgrade-runner 执行回滚。");
      } else {
        setComponentMessage("组件升级任务已标记为失败。");
      }
      await reloadComponentHistory();
    } catch (exc) {
      setComponentMessage(exc instanceof Error ? exc.message : "提交恢复操作失败");
    } finally {
      setComponentBusy(false);
    }
  }

  if (!active) return null;

  const isRunning = Boolean(componentTask && runningUpgradeStatuses.has(componentTask.status));
  const selectedComponent = componentInfos.find((component) => component.service === selectedComponentService) ?? componentInfos[0] ?? defaultComponentInfos[0];
  const selectedTask = taskBelongsToComponent(componentTask, selectedComponent.service) ? componentTask : null;
  const availablePackages = componentHistory.filter(
    (task) =>
      (!componentServiceFromTask(task) || taskBelongsToComponent(task, selectedComponent.service)) &&
      (!task.started_at || task.task_id === selectedTask?.task_id || runningUpgradeStatuses.has(task.status))
  );
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
              if (componentTask && !taskBelongsToComponent(componentTask, component.service)) setComponentTask(null);
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
        {selectedComponent.service === "upgrade-runner" && <InfoRow label="执行协议" value={selectedComponent.protocol_version ? `v${selectedComponent.protocol_version}` : "未上报"} />}
        {selectedComponent.service === "upgrade-runner" && <InfoRow label="能力状态" value={selectedComponent.compatible ? "兼容" : "未就绪"} />}
        {selectedComponent.service === "upgrade-runner" && <InfoRow label="最后心跳" value={formatTime(selectedComponent.heartbeat_at || undefined)} />}
        <InfoRow label="执行者" value={selectedComponent.executor || "-"} />
        <InfoRow label="目标版本" value={formatVersionForDisplay(selectedTask?.target_version)} />
        <InfoRow label="已选升级包" value={selectedTask?.package_filename ?? "未选择"} />
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
                  {task.started_at && (
                    <small className="upgrade-package-progress">
                      <i style={{ width: `${upgradeProgress(task)}%` }} />
                    </small>
                  )}
                </span>
              </button>
            ))}
          </div>
        ) : (
          <EmptyUpgrade message={`点击右上角“上传组件包”后，可在这里执行${selectedComponent.display_name}预检查和组件升级。`} />
        )}
      </section>
      {selectedTask && (
        <>
          <div className="service-upgrade-actions">
            <button className="secondary-button" type="button" onClick={precheckComponentUpgrade} disabled={componentBusy || isRunning}>
              <ListChecks size={16} />
              预检查
            </button>
            <button className="primary-button" type="button" onClick={startComponentUpgrade} disabled={componentBusy || !selectedTask.precheck_ok || isRunning}>
              <Upload size={16} />
              开始升级
            </button>
            <button className="secondary-button" type="button" onClick={cancelSelectedComponentPackage} disabled={componentBusy || isRunning}>
              <X size={16} />
              取消选择
            </button>
            <button className="secondary-button danger-button" type="button" onClick={deleteSelectedComponentPackage} disabled={componentBusy || isRunning}>
              <X size={16} />
              删除
            </button>
          </div>
          <UpgradeTaskDetail
            task={selectedTask}
            file={componentFile}
            componentMode={true}
            precheckExpanded={componentPrecheckExpanded}
            precheckRunning={componentPrecheckRunning}
            precheckProgressIndex={componentPrecheckProgressIndex}
            stepsExpanded={componentStepsExpanded}
            logsExpanded={componentLogsExpanded}
            onPrecheckToggle={() => setComponentPrecheckExpanded((expanded) => !expanded)}
            onStepsToggle={() => setComponentStepsExpanded((expanded) => !expanded)}
            onLogsToggle={() => setComponentLogsExpanded((expanded) => !expanded)}
            upgradeBusy={componentBusy}
            onRecovery={handleComponentRecovery}
          />
        </>
      )}
    </>
  );
}
