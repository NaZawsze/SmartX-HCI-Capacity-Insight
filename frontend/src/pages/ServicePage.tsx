import { Check, Download, FileArchive, History, Info, ListChecks, Power, RefreshCw, RotateCcw, Server, Upload, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api } from "../services/api";
import type { UpgradeTask } from "../types";

type ServiceSection = "migration" | "restart" | "upgrade" | "history";

const runningUpgradeStatuses = new Set(["pending", "running", "rollback_pending", "rollback_running"]);
const serviceItems = [
  { name: "web-api", description: "提供页面 API、报表导出、数据迁移和升级接口。" },
  { name: "collector-worker", description: "负责定时采集 Tower、集群和虚拟机容量数据。" },
  { name: "prometheus", description: "保存历史指标和趋势样本。" }
];

export function ServicePage() {
  const [section, setSection] = useState<ServiceSection>("upgrade");
  const [appVersion, setAppVersion] = useState("-");
  const [upgradeFile, setUpgradeFile] = useState<File | null>(null);
  const [upgradeTask, setUpgradeTask] = useState<UpgradeTask | null>(null);
  const [upgradeHistory, setUpgradeHistory] = useState<UpgradeTask[]>([]);
  const [upgradeBusy, setUpgradeBusy] = useState(false);
  const [upgradeMessage, setUpgradeMessage] = useState("");
  const [precheckExpanded, setPrecheckExpanded] = useState(true);
  const [stepsExpanded, setStepsExpanded] = useState(true);
  const [logsExpanded, setLogsExpanded] = useState(false);
  const [restartBusy, setRestartBusy] = useState(false);
  const [restartMessage, setRestartMessage] = useState("");
  const [migrationMessage, setMigrationMessage] = useState("");
  const [migrationBusy, setMigrationBusy] = useState(false);
  const [migrationFile, setMigrationFile] = useState<File | null>(null);
  const [migrationMode, setMigrationMode] = useState<"merge" | "overwrite">("merge");
  const [migrationConfirmed, setMigrationConfirmed] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const migrationFileInputRef = useRef<HTMLInputElement | null>(null);
  const contentPanelRef = useRef<HTMLElement | null>(null);

  async function reloadUpgradeHistory() {
    setUpgradeHistory(await api.upgradeHistory());
  }

  useEffect(() => {
    api.upgradeVersion().then((result) => setAppVersion(result.version)).catch(() => undefined);
    reloadUpgradeHistory().catch(() => undefined);
    resetServiceScroll();
  }, []);

  useEffect(() => {
    if (!upgradeTask || !runningUpgradeStatuses.has(upgradeTask.status)) return undefined;
    const timer = window.setInterval(() => {
      api.upgradeStatus(upgradeTask.task_id)
        .then((next) => {
          setUpgradeTask(next);
          if (!runningUpgradeStatuses.has(next.status)) {
            reloadUpgradeHistory().catch(() => undefined);
          }
        })
        .catch((exc) => setUpgradeMessage(exc instanceof Error ? exc.message : "刷新升级状态失败"));
    }, 2500);
    return () => window.clearInterval(timer);
  }, [upgradeTask]);

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
    try {
      const { blob, filename } = await api.exportMigration();
      saveBlob(blob, filename);
      setMigrationMessage("迁移包已生成");
    } catch (exc) {
      setMigrationMessage(exc instanceof Error ? exc.message : "导出失败");
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
    try {
      const result = await api.importMigration(migrationFile, migrationMode, migrationConfirmed);
      setMigrationMessage(result.message);
      setMigrationFile(null);
      if (migrationFileInputRef.current) migrationFileInputRef.current.value = "";
      setMigrationMode("merge");
      setMigrationConfirmed(false);
    } catch (exc) {
      setMigrationMessage(exc instanceof Error ? exc.message : "导入失败");
    } finally {
      setMigrationBusy(false);
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

  async function uploadUpgrade(file?: File | null) {
    const selectedFile = file ?? upgradeFile;
    setUpgradeMessage("");
    if (!selectedFile) {
      setUpgradeMessage("请选择升级包文件");
      return;
    }
    setUpgradeBusy(true);
    try {
      const task = await api.uploadUpgradePackage(selectedFile);
      setUpgradeTask(task);
      setUpgradeFile(selectedFile);
      setPrecheckExpanded(false);
      setLogsExpanded(false);
      setUpgradeMessage("升级包已上传并保存到系统目录，请选中后执行预检查。");
      await reloadUpgradeHistory();
    } catch (exc) {
      setUpgradeMessage(exc instanceof Error ? exc.message : "上传升级包失败");
    } finally {
      setUpgradeBusy(false);
    }
  }

  async function precheckUpgrade() {
    if (!upgradeTask) return;
    setUpgradeMessage("");
    setUpgradeBusy(true);
    try {
      const task = await api.precheckUpgrade(upgradeTask.task_id);
      setUpgradeTask(task);
      setPrecheckExpanded(true);
      setUpgradeMessage(task.precheck_ok ? "预检查通过，可以开始升级。" : "预检查未通过，请查看检查项。");
      await reloadUpgradeHistory();
    } catch (exc) {
      setUpgradeMessage(exc instanceof Error ? exc.message : "预检查失败");
    } finally {
      setUpgradeBusy(false);
    }
  }

  async function startUpgrade() {
    if (!upgradeTask) return;
    setUpgradeMessage("");
    setUpgradeBusy(true);
    try {
      const task = await api.startUpgrade(upgradeTask.task_id);
      setUpgradeTask(task);
      setStepsExpanded(true);
      setLogsExpanded(true);
      setUpgradeMessage("升级任务已提交，日志会自动刷新。");
    } catch (exc) {
      setUpgradeMessage(exc instanceof Error ? exc.message : "开始升级失败");
    } finally {
      setUpgradeBusy(false);
    }
  }

  async function rollbackUpgrade() {
    if (!upgradeTask) return;
    setUpgradeMessage("");
    setUpgradeBusy(true);
    try {
      const task = await api.rollbackUpgrade(upgradeTask.task_id);
      setUpgradeTask(task);
      setStepsExpanded(true);
      setLogsExpanded(true);
      setUpgradeMessage("回滚任务已提交，日志会自动刷新。");
    } catch (exc) {
      setUpgradeMessage(exc instanceof Error ? exc.message : "提交回滚失败");
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

  function loadHistoryItem(task: UpgradeTask) {
    selectUpgradePackage(task);
    selectSection("upgrade");
  }

  function selectSection(nextSection: ServiceSection) {
    setSection(nextSection);
    resetServiceScroll();
  }

  function resetServiceScroll() {
    window.requestAnimationFrame(() => {
      window.scrollTo({ top: 0 });
      document.querySelector<HTMLElement>(".workspace")?.scrollTo({ top: 0 });
      contentPanelRef.current?.scrollTo({ top: 0 });
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
        </div>
        <div className="service-subnav-group">
          <span>平台升级</span>
          <button className={section === "upgrade" ? "active" : ""} type="button" onClick={() => selectSection("upgrade")}>
            <Upload size={17} />
            系统升级
          </button>
          <button className={section === "history" ? "active" : ""} type="button" onClick={() => selectSection("history")}>
            <History size={17} />
            升级历史
          </button>
        </div>
      </aside>

      <main ref={contentPanelRef} className="service-content-panel">
        {section === "migration" && renderMigration()}
        {section === "restart" && renderRestart()}
        {section === "upgrade" && renderUpgrade()}
        {section === "history" && renderHistory()}
      </main>
    </div>
  );

  function renderMigration() {
    return (
      <>
        <PageHeader eyebrow="系统运维" title="数据迁移" action={(
          <button className="primary-button" type="button" onClick={exportMigration} disabled={migrationBusy}>
            <Download size={16} />
            导出迁移包
          </button>
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

  function renderUpgrade() {
    const isRunning = Boolean(upgradeTask && runningUpgradeStatuses.has(upgradeTask.status));
    const availablePackages = upgradeHistory.filter((task) => !task.started_at);
    return (
      <>
        <PageHeader
          eyebrow="平台升级"
          title="系统升级"
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
              <button className="primary-button" type="button" onClick={() => fileInputRef.current?.click()} disabled={upgradeBusy || isRunning}>
                <FileArchive size={16} />
                上传升级包
              </button>
            </>
          )}
        />
        <div className="service-upgrade-status-grid">
          <InfoRow label="当前版本" value={appVersion} />
          <InfoRow label="目标版本" value={upgradeTask?.target_version ?? "-"} />
          <InfoRow label="已选升级包" value={upgradeTask?.package_filename ?? "未选择"} />
        </div>
        <div className="service-notice">
          <Info size={16} />
          升级包会保存到系统升级目录；选中一个升级包后可执行预检查、升级、取消选择或删除。
        </div>
        {upgradeMessage && <div className="inline-message">{upgradeMessage}</div>}
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
                    <strong>{task.target_version || "未知版本"}</strong>
                    <small>{task.package_filename || "-"} · {formatTime(task.uploaded_at)} · {upgradeStatusText(task.status)}</small>
                  </span>
                </button>
              ))}
            </div>
          ) : (
            <EmptyUpgrade disabled={upgradeBusy || isRunning} onUpload={() => fileInputRef.current?.click()} />
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
            {renderUpgradeTask(upgradeTask)}
          </>
        )}
      </>
    );
  }

  function renderUpgradeTask(task: UpgradeTask) {
    return (
      <div className="service-upgrade-detail">
        <div className="service-info-table">
          <InfoRow label="升级包" value={task.package_filename ?? upgradeFile?.name ?? "-"} />
          <InfoRow label="影响服务" value={task.restart_services?.join("、") || "-"} />
          <InfoRow label="数据库迁移" value={task.database_migration ? "需要" : "不需要"} />
          <InfoRow label="备份文件" value={task.backup_path || "升级开始后生成"} />
        </div>
        {task.release_notes && <pre className="upgrade-release-notes">{task.release_notes}</pre>}
        {!!task.checks.length && (
          <CollapsibleSection title="预检查" expanded={precheckExpanded} onToggle={() => setPrecheckExpanded((expanded) => !expanded)}>
            <div className="upgrade-checks">
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
          </CollapsibleSection>
        )}
        {!!task.steps.length && (
          <CollapsibleSection title="执行步骤" expanded={stepsExpanded} onToggle={() => setStepsExpanded((expanded) => !expanded)}>
            <div className="upgrade-steps">
              {task.steps.map((step) => (
                <div className={`upgrade-step ${step.status}`} key={step.key}>
                  <span>{step.title}</span>
                  <strong>{stepStatusText(step.status)}</strong>
                  {step.message && <small>{step.message}</small>}
                </div>
              ))}
            </div>
          </CollapsibleSection>
        )}
        {!!task.logs.length && (
          <CollapsibleSection title="升级日志" expanded={logsExpanded} onToggle={() => setLogsExpanded((expanded) => !expanded)}>
            <pre className="upgrade-log">{task.logs.join("\n")}</pre>
          </CollapsibleSection>
        )}
      </div>
    );
  }

  function renderHistory() {
    return (
      <>
        <PageHeader eyebrow="平台升级" title="升级历史" action={<button className="secondary-button" type="button" onClick={reloadUpgradeHistory}>刷新</button>} />
        <div className="service-history-table">
          <div className="service-history-head">
            <span>目标版本</span>
            <span>状态</span>
            <span>上传时间</span>
            <span>完成时间</span>
            <span>备份路径</span>
          </div>
          {upgradeHistory.map((item) => (
            <button className="service-history-row" type="button" key={item.task_id} onClick={() => loadHistoryItem(item)}>
              <span>{item.target_version || "-"}</span>
              <span>{upgradeStatusText(item.status)}</span>
              <span>{formatTime(item.uploaded_at)}</span>
              <span>{formatTime(item.finished_at || item.rollback_finished_at)}</span>
              <span>{item.backup_path || "-"}</span>
            </button>
          ))}
          {!upgradeHistory.length && <div className="empty-state">暂无升级历史</div>}
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

function EmptyUpgrade({ disabled, onUpload }: { disabled: boolean; onUpload: () => void }) {
  return (
    <UploadPanel
      title="暂无升级包"
      description="上传离线 .tar.gz 升级包后，可在这里执行预检查、升级和回滚。"
      actionText="上传升级包"
      disabled={disabled}
      onClick={onUpload}
    />
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
    pending: "等待",
    running: "执行中",
    succeeded: "完成",
    failed: "失败"
  };
  return labels[status] ?? status;
}

function formatTime(value?: string): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", { hour12: false });
}
