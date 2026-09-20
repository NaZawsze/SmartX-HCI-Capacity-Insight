import { Check, Info, RefreshCw, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../../services/api";
import type { AppTask, LocalStorageUsage, SpaceCleanupScanItem, SqliteBackupScanResult, SqliteVacuumScan } from "../../types";
import { LocalStorageUsageCard, PageHeader, formatTime, taskId } from "./shared";

interface CleanupSectionProps {
  active: boolean;
  addTask: (task: Omit<AppTask, "createdAt" | "updatedAt">) => void;
  updateTask: (id: string, patch: Partial<Omit<AppTask, "id" | "createdAt">>) => void;
}

export function CleanupSection({ active, addTask, updateTask }: CleanupSectionProps) {
  const [spaceCleanupBusy, setSpaceCleanupBusy] = useState(false);
  const [spaceCleanupScanBusy, setSpaceCleanupScanBusy] = useState(false);
  const [spaceCleanupMessage, setSpaceCleanupMessage] = useState("");
  const [spaceCleanupItems, setSpaceCleanupItems] = useState<SpaceCleanupScanItem[]>([]);
  const [spaceCleanupTotal, setSpaceCleanupTotal] = useState("0 B");
  const [spaceCleanupLogs, setSpaceCleanupLogs] = useState<string[]>([]);
  const [spaceCleanupKeepCount, setSpaceCleanupKeepCount] = useState(0);
  const [localStorage, setLocalStorage] = useState<LocalStorageUsage | null>(null);
  const [localStorageMessage, setLocalStorageMessage] = useState("");
  const [sqliteVacuumScan, setSqliteVacuumScan] = useState<SqliteVacuumScan | null>(null);
  const [sqliteVacuumBusy, setSqliteVacuumBusy] = useState(false);
  const [sqliteVacuumMessage, setSqliteVacuumMessage] = useState("");
  const [sqliteVacuumLogs, setSqliteVacuumLogs] = useState<string[]>([]);
  const [sqliteBackupScan, setSqliteBackupScan] = useState<SqliteBackupScanResult | null>(null);
  const [sqliteBackupBusy, setSqliteBackupBusy] = useState(false);
  const [sqliteBackupMessage, setSqliteBackupMessage] = useState("");
  const [sqliteBackupLogs, setSqliteBackupLogs] = useState<string[]>([]);
  const [selectedSqliteBackups, setSelectedSqliteBackups] = useState<Set<string>>(new Set());

  useEffect(() => {
    if (!active) return;
    refreshLocalStorageUsage().catch(() => undefined);
  }, [active]);

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
    setSqliteVacuumLogs(["开始扫描 SQLite 数据库和运行态缓存..."]);
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
      const result = await api.cleanupSpaceArtifacts(spaceCleanupKeepCount);
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
    addTask({ id, kind: "upgrade", title: "SQLite 清理并整理", detail: "正在备份、清理运行态缓存并整理业务库", status: "running", progress: 35, logs: ["开始 SQLite 清理并整理"] });
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
      updateTask(id, { status: "failed", progress: 100, detail: message, logs: ["SQLite 清理并整理失败", message] });
    } finally {
      setSqliteVacuumBusy(false);
    }
  }

  async function scanSqliteBackups() {
    setSqliteBackupBusy(true);
    setSqliteBackupMessage("");
    setSqliteBackupLogs(["开始扫描 SQLite 数据库备份..."]);
    try {
      const result = await api.scanSqliteBackups();
      setSqliteBackupScan(result);
      setSelectedSqliteBackups(new Set());
      setSqliteBackupLogs([result.message]);
      setSqliteBackupMessage(result.message);
      await refreshLocalStorageUsage();
    } catch (exc) {
      const message = exc instanceof Error ? exc.message : "SQLite 备份扫描失败";
      setSqliteBackupLogs((current) => [...current, message]);
      setSqliteBackupMessage(message);
    } finally {
      setSqliteBackupBusy(false);
    }
  }

  function toggleSqliteBackup(filename: string) {
    setSelectedSqliteBackups((current) => {
      const next = new Set(current);
      if (next.has(filename)) next.delete(filename);
      else next.add(filename);
      return next;
    });
  }

  function toggleAllSqliteBackups() {
    const items = sqliteBackupScan?.items || [];
    if (!items.length) return;
    setSelectedSqliteBackups((current) => {
      if (current.size === items.length) return new Set();
      return new Set(items.map((item) => item.filename));
    });
  }

  async function deleteSelectedSqliteBackups() {
    const filenames = Array.from(selectedSqliteBackups);
    if (!filenames.length) {
      setSqliteBackupMessage("请先选择需要删除的 SQLite 备份。");
      return;
    }
    setSqliteBackupBusy(true);
    setSqliteBackupMessage("");
    const id = taskId("sqlite-backup-cleanup");
    addTask({ id, kind: "upgrade", title: "SQLite 备份清理", detail: `正在删除 ${filenames.length} 个 SQLite 备份`, status: "running", progress: 35, logs: ["开始 SQLite 备份清理"] });
    try {
      const result = await api.deleteSqliteBackups(filenames);
      setSqliteBackupLogs(result.logs || [result.message]);
      setSqliteBackupMessage(result.message);
      updateTask(id, { status: "succeeded", progress: 100, detail: result.message, logs: result.logs });
      const scan = await api.scanSqliteBackups();
      setSqliteBackupScan(scan);
      setSelectedSqliteBackups(new Set());
      await refreshLocalStorageUsage();
    } catch (exc) {
      const message = exc instanceof Error ? exc.message : "SQLite 备份清理失败";
      setSqliteBackupLogs((current) => [...current, message]);
      setSqliteBackupMessage(message);
      updateTask(id, { status: "failed", progress: 100, detail: message, logs: ["SQLite 备份清理失败", message] });
    } finally {
      setSqliteBackupBusy(false);
    }
  }

  if (!active) return null;

  const totalCount = spaceCleanupItems.reduce((total, item) => total + item.count, 0);
  const sqliteBackupItems = sqliteBackupScan?.items || [];
  const allSqliteBackupsSelected = sqliteBackupItems.length > 0 && selectedSqliteBackups.size === sqliteBackupItems.length;
  return (
    <>
      <PageHeader eyebrow="系统运维" title="空间清理" />
      <div className="service-operation-card">
        <LocalStorageUsageCard usage={localStorage} message={localStorageMessage} />
        <div className="cleanup-module">
          <div className="service-operation-head">
            <div className="cleanup-module-title">
              <strong>运行产物清理</strong>
              <span>扫描升级包、数据迁移导出和报表导出留档；不会删除业务库、Prometheus 历史指标或升级前自动备份。</span>
            </div>
            <div className="cleanup-control-stack">
              <div className="cleanup-summary compact">
                <strong>{totalCount} 项</strong>
                <span>预计可释放 {spaceCleanupTotal}</span>
              </div>
              <div className="cleanup-inline-actions">
                <button className="primary-button service-header-button" type="button" onClick={scanSpaceCleanup} disabled={spaceCleanupBusy || spaceCleanupScanBusy}>
                  <RefreshCw size={16} />
                  {spaceCleanupScanBusy ? "扫描中" : "扫描"}
                </button>
                <label className="cleanup-keep-control">
                  <span>保留最近</span>
                  <input
                    type="number"
                    min={0}
                    max={100}
                    value={spaceCleanupKeepCount}
                    onChange={(event) => setSpaceCleanupKeepCount(Math.max(0, Math.min(100, Number(event.target.value) || 0)))}
                  />
                  <span>个升级任务</span>
                </label>
                <button className="secondary-button danger-button service-header-button" type="button" onClick={cleanupSpaceArtifacts} disabled={spaceCleanupBusy || spaceCleanupScanBusy || totalCount === 0}>
                  <Trash2 size={16} />
                  {spaceCleanupBusy ? "清理中" : "一键清理"}
                </button>
              </div>
            </div>
          </div>
          <div className="cleanup-warning">
            <Info size={16} />
            一键清理会删除已上传升级包、数据迁移导出包和报表导出文件；需要保留的文件请先下载到本地。「保留最近 N 个升级任务」只作用于升级包目录（按时间保留最近 N 项，0 = 全部清理）；存在正在执行的升级任务时会拒绝清理。
          </div>
          <div className="cleanup-result-panel cleanup-image-list space-cleanup-list auto-scrollbar">
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
            <div className="cleanup-module-title">
              <strong>SQLite 清理并整理</strong>
              <span>清理运行态缓存，备份业务库后执行 VACUUM 释放数据库空闲页。</span>
            </div>
            <div className="cleanup-control-stack">
              <div className="cleanup-summary compact">
                <strong>{sqliteVacuumScan?.size_label || "待扫描"}</strong>
                <span>预计释放 {sqliteVacuumScan?.estimated_reclaimable_label || "0 B"}</span>
              </div>
              <div className="cleanup-inline-actions">
                <button className="primary-button service-header-button" type="button" onClick={scanSqliteVacuum} disabled={sqliteVacuumBusy || spaceCleanupScanBusy}>
                  <RefreshCw size={16} />
                  扫描 SQLite
                </button>
                <button className="secondary-button danger-button service-header-button" type="button" onClick={vacuumSqlite} disabled={sqliteVacuumBusy || spaceCleanupScanBusy || !sqliteVacuumScan}>
                  <RefreshCw size={16} />
                  {sqliteVacuumBusy ? "清理中" : "清理并整理 SQLite"}
                </button>
              </div>
            </div>
          </div>
          <div className="cleanup-result-panel cleanup-image-list auto-scrollbar">
            <div className="cleanup-image-row">
              <div>
                <strong>{sqliteVacuumScan?.path || "smartx.db"}</strong>
                <small>{sqliteVacuumScan ? `空闲页 ${sqliteVacuumScan.freelist_count} / 总页 ${sqliteVacuumScan.page_count}` : "点击扫描后显示 SQLite 文件大小和可整理空间。"}</small>
              </div>
              <span>{sqliteVacuumScan ? `预计释放 ${sqliteVacuumScan.estimated_reclaimable_label}` : "待扫描"}</span>
            </div>
            {sqliteVacuumScan ? (
              <>
                <div className="cleanup-image-row">
                  <div>
                    <strong>指标快照</strong>
                    <small>保留最新 1 条 metric_snapshots</small>
                  </div>
                  <span>指标快照：{sqliteVacuumScan.runtime_cache?.metric_snapshots?.delete_count ?? 0} 条可清理</span>
                </div>
                <div className="cleanup-image-row">
                  <div>
                    <strong>采集记录</strong>
                    <small>collection_runs 保留最近 7 天</small>
                  </div>
                  <span>采集记录：{sqliteVacuumScan.runtime_cache?.collection_runs?.delete_count ?? 0} 条可清理</span>
                </div>
                <div className="cleanup-image-row">
                  <div>
                    <strong>任务记录</strong>
                    <small>tasks 保留最近 30 天，未确认告警继续保留</small>
                  </div>
                  <span>任务记录：{sqliteVacuumScan.runtime_cache?.tasks?.delete_count ?? 0} 条可清理</span>
                </div>
              </>
            ) : null}
          </div>
          <pre className="cleanup-log auto-scrollbar">{sqliteVacuumLogs.length ? sqliteVacuumLogs.join("\n") : "等待扫描..."}</pre>
          {sqliteVacuumMessage && <div className="inline-message">{sqliteVacuumMessage}</div>}
        </div>
        <div className="cleanup-module sqlite-backup-panel">
          <div className="service-operation-head">
            <div className="cleanup-module-title">
              <strong>SQLite 备份清理</strong>
              <span>扫描 /data/backups 中的 SQLite 数据库备份，只删除本框中勾选的 .db / .sqlite 备份文件。</span>
            </div>
            <div className="cleanup-control-stack">
              <div className="cleanup-summary compact">
                <strong>{sqliteBackupScan ? `${sqliteBackupScan.total_count} 个备份` : "待扫描"}</strong>
                <span>可释放 {sqliteBackupScan?.total_size_label || "0 B"}</span>
              </div>
              <div className="cleanup-inline-actions sqlite-backup-actions">
                <button className="primary-button service-header-button" type="button" onClick={scanSqliteBackups} disabled={sqliteBackupBusy}>
                  <RefreshCw size={16} />
                  {sqliteBackupBusy ? "处理中" : "扫描备份"}
                </button>
                <button className="secondary-button service-header-button" type="button" onClick={toggleAllSqliteBackups} disabled={sqliteBackupBusy || sqliteBackupItems.length === 0}>
                  <Check size={16} />
                  {allSqliteBackupsSelected ? "取消全选" : "全选"}
                </button>
                <button className="secondary-button danger-button service-header-button" type="button" onClick={deleteSelectedSqliteBackups} disabled={sqliteBackupBusy || selectedSqliteBackups.size === 0}>
                  <Trash2 size={16} />
                  {sqliteBackupBusy ? "删除中" : "删除选中"}
                </button>
              </div>
            </div>
          </div>
          <div className="cleanup-warning">
            <Info size={16} />
            这里只清理 SQLite 清理并整理、旧表迁移等动作产生的数据库备份；升级前备份、导入前备份和 Prometheus 备份不会出现在列表里。
          </div>
          <div className="cleanup-result-panel cleanup-image-list sqlite-backup-list auto-scrollbar">
            {sqliteBackupItems.length ? (
              sqliteBackupItems.map((item) => (
                <label className="cleanup-image-row sqlite-backup-row" key={item.filename}>
                  <input type="checkbox" checked={selectedSqliteBackups.has(item.filename)} onChange={() => toggleSqliteBackup(item.filename)} disabled={sqliteBackupBusy} />
                  <div>
                    <strong>{item.filename}</strong>
                    <small>{item.path}{item.modified_at ? ` · ${formatTime(item.modified_at)}` : ""}</small>
                  </div>
                  <span>{item.size_label}</span>
                </label>
              ))
            ) : (
              <div className="cleanup-image-empty">点击“扫描备份”查看可删除的 SQLite 备份。</div>
            )}
          </div>
          <pre className="cleanup-log auto-scrollbar">{sqliteBackupLogs.length ? sqliteBackupLogs.join("\n") : "等待扫描..."}</pre>
          {sqliteBackupMessage && <div className="inline-message">{sqliteBackupMessage}</div>}
        </div>
      </div>
    </>
  );
}
