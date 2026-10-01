import { Download, Info, RefreshCw, ShieldAlert, Upload } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api } from "../../services/api";
import type { AppTask, MigrationHealth } from "../../types";
import { InfoRow, PageHeader, UploadPanel, migrationExportTaskPatch, migrationImportTaskPatch, saveBlob, sleep, taskId, transferProgressValue, uploadProgressTaskPatch, type ServiceSection } from "./shared";

interface MigrationSectionProps {
  active: boolean;
  onNavigate?: (section: ServiceSection) => void;
  addTask: (task: Omit<AppTask, "createdAt" | "updatedAt">) => void;
  updateTask: (id: string, patch: Partial<Omit<AppTask, "id" | "createdAt">>) => void;
}

type EnvStatusState = "idle" | "checking" | "ready" | "error";

export function MigrationSection({ active, onNavigate, addTask, updateTask }: MigrationSectionProps) {
  const [exportMessage, setExportMessage] = useState("");
  const [exportKeyPrompt, setExportKeyPrompt] = useState(false);
  const [importMessage, setImportMessage] = useState("");
  const [migrationBusy, setMigrationBusy] = useState(false);
  const [migrationFile, setMigrationFile] = useState<File | null>(null);
  const [migrationMode, setMigrationMode] = useState<"merge" | "overwrite">("merge");
  const [migrationConfirmed, setMigrationConfirmed] = useState(false);
  const [envStatus, setEnvStatus] = useState<MigrationHealth | null>(null);
  const [envStatusState, setEnvStatusState] = useState<EnvStatusState>("idle");
  const [envStatusError, setEnvStatusError] = useState("");
  const [keyDialogOpen, setKeyDialogOpen] = useState(false);
  const [keyPassword, setKeyPassword] = useState("");
  const [keyError, setKeyError] = useState("");
  const [keyBusy, setKeyBusy] = useState(false);
  const migrationFileInputRef = useRef<HTMLInputElement | null>(null);
  const envStatusCheckedRef = useRef(false);

  useEffect(() => {
    if (!active || envStatusCheckedRef.current) return;
    envStatusCheckedRef.current = true;
    void checkMigrationHealth();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active]);

  async function exportMigration() {
    setExportMessage("");
    setExportKeyPrompt(false);
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
        setExportMessage(message);
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
        logs: ["迁移包已生成", "恢复还需单独下载恢复密钥（需验证平台密码）", task.saved_path ? `服务器留档：${task.saved_path}` : "已完成浏览器下载"],
        links: [{ label: "下载", filename: task.filename, url: task.download_url, path: task.saved_path }]
      });
      setExportKeyPrompt(true);
    } catch (exc) {
      const message = exc instanceof Error ? exc.message : "导出失败";
      updateTask(id, { status: "failed", progress: 100, detail: message, logs: ["导出失败", message] });
      setExportMessage(message);
    } finally {
      setMigrationBusy(false);
    }
  }

  async function exportDataMigration() {
    setExportMessage("");
    setExportKeyPrompt(false);
    setMigrationBusy(true);
    const id = taskId("data-migration-export");
    addTask({ id, kind: "export", title: "仅导出存储监测数据", detail: "正在创建导出任务", status: "running", progress: 1, logs: ["正在创建后台导出任务"] });
    try {
      let task = await api.startMigrationDataExport();
      updateTask(id, migrationExportTaskPatch(task));
      while (task.status === "pending" || task.status === "running") {
        await sleep(1000);
        task = await api.migrationExportStatus(task.task_id);
        updateTask(id, migrationExportTaskPatch(task));
      }
      if (task.status !== "succeeded" || !task.download_url) {
        const message = task.detail || "导出失败";
        updateTask(id, { status: "failed", progress: 100, detail: message, logs: task.logs || [message] });
        setExportMessage(message);
        return;
      }
      const result = await api.downloadSavedExport(task.download_url, (progress) => {
        const value = transferProgressValue(progress);
        updateTask(id, { progress: Math.max(98, value), detail: "监测数据包已生成，正在下载", logs: ["监测数据包已生成", "正在下载到浏览器"] });
      });
      saveBlob(result.blob, result.filename || task.filename || "smartx-data-migration.tar.gz");
      updateTask(id, {
        status: "succeeded",
        progress: 100,
        detail: task.filename || "监测数据包已生成",
        logs: ["监测数据包已生成", "不含 Tower 配置，无需恢复密钥", task.saved_path ? `服务器留档：${task.saved_path}` : "已完成浏览器下载"],
        links: [{ label: "下载", filename: task.filename, url: task.download_url, path: task.saved_path }]
      });
      setExportMessage("监测数据包已导出（不含 Tower 配置，无需恢复密钥）。导入时用「合并数据」，不会改动本机 Tower 配置。");
    } catch (exc) {
      let message = exc instanceof Error ? exc.message : "导出失败";
      if (message === "Not Found") {
        // #66：新前端 + 旧后端（混合部署/升级窗口）时 404 原样透出，用户看不懂
        message = "后端暂未提供该导出接口（平台版本较旧），请先升级平台后再使用";
      }
      updateTask(id, { status: "failed", progress: 100, detail: message, logs: ["导出失败", message] });
      setExportMessage(message);
    } finally {
      setMigrationBusy(false);
    }
  }

  async function exportConfigMigration() {
    setExportMessage("");
    setExportKeyPrompt(false);
    setMigrationBusy(true);
    const id = taskId("config-migration-export");
    addTask({ id, kind: "export", title: "仅导出 Tower 配置", detail: "正在导出 Tower 和集群配置", status: "running", progress: 30, logs: ["此导出不包含历史数据"] });
    try {
      const result = await api.exportConfigMigration((progress) => {
        const value = transferProgressValue(progress);
        updateTask(id, { progress: Math.max(30, Math.min(95, value)), detail: "正在下载配置文件" });
      });
      saveBlob(result.blob, result.filename || "smartx-config-migration.tar.gz");
      updateTask(id, {
        status: "succeeded",
        progress: 100,
        detail: result.filename || "Tower 配置已导出",
        logs: ["Tower 配置已导出", result.savedPath ? `服务器留档：${result.savedPath}` : "已完成浏览器下载"],
        links: result.downloadUrl ? [{ label: "下载", filename: result.filename, url: result.downloadUrl, path: result.savedPath }] : undefined
      });
      setExportMessage("Tower 配置已导出（不含历史数据）。配置包里的 Tower 密码同样是加密的，恢复时需要恢复密钥。");
    } catch (exc) {
      const message = exc instanceof Error ? exc.message : "Tower 配置导出失败";
      updateTask(id, { status: "failed", progress: 100, detail: message, logs: ["Tower 配置导出失败", message] });
      setExportMessage(message);
    } finally {
      setMigrationBusy(false);
    }
  }

  async function importMigration() {
    setImportMessage("");
    if (!migrationFile) {
      setImportMessage("请选择迁移包文件");
      return;
    }
    if (migrationMode === "overwrite" && !migrationConfirmed) {
      setImportMessage("整库替换会清空当前数据，请先勾选确认");
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
      setImportMessage(["数据迁移导入完成", backupLog, healthLog].filter(Boolean).join(" "));
      setMigrationFile(null);
      if (migrationFileInputRef.current) migrationFileInputRef.current.value = "";
      setMigrationMode("merge");
      setMigrationConfirmed(false);
    } catch (exc) {
      const message = exc instanceof Error ? exc.message : "导入失败";
      updateTask(id, { status: "failed", progress: 100, detail: message, logs: ["导入失败", message] });
      setImportMessage(message);
    } finally {
      setMigrationBusy(false);
    }
  }

  async function downloadEnvFile() {
    if (!keyPassword) {
      setKeyError("请输入平台登录密码");
      return;
    }
    setKeyBusy(true);
    setKeyError("");
    try {
      const result = await api.downloadEnvFile(keyPassword);
      saveBlob(result.blob, result.filename || "project.env");
      setKeyDialogOpen(false);
      setExportKeyPrompt(false);
      setKeyPassword("");
      setExportMessage("已下载恢复密钥。恢复迁移包时请与其一同使用；若没有密钥，也可导入后在 Tower 设置中重新输入密码。");
    } catch (exc) {
      setKeyError(exc instanceof Error ? exc.message : "下载恢复密钥失败");
    } finally {
      setKeyBusy(false);
    }
  }

  async function checkMigrationHealth() {
    setEnvStatusState("checking");
    setEnvStatusError("");
    try {
      const result = await api.migrationHealth();
      setEnvStatus(result);
      setEnvStatusState("ready");
    } catch (exc) {
      const message = exc instanceof Error ? exc.message : "环境状态检查失败";
      setEnvStatusError(message);
      setEnvStatusState("error");
    }
  }

  if (!active) return null;

  const tableCount = envStatus ? Object.keys(envStatus.sqlite?.tables || {}).length : 0;
  const blockCount = envStatus?.prometheus?.block_count ?? 0;
  const complete = envStatus?.complete ?? false;

  return (
    <>
      <PageHeader eyebrow="系统运维" title="数据迁移" action={(
        <div className="service-header-actions service-migration-actions">
          <button className="secondary-button service-header-button" type="button" onClick={exportDataMigration} disabled={migrationBusy}>
            <Download size={15} />
            仅导出存储监测数据
          </button>
          <button className="secondary-button service-header-button" type="button" onClick={exportConfigMigration} disabled={migrationBusy}>
            <Download size={15} />
            仅导出 Tower 配置
          </button>
          <button className="primary-button service-header-button" type="button" onClick={exportMigration} disabled={migrationBusy}>
            <Download size={16} />
            导出迁移包
          </button>
        </div>
      )} />
      <div className="service-operation-card service-migration-card">
        <div className="service-operation-head">
          <div>
            <strong>导出迁移包</strong>
            <span>包含 Tower 配置、库内监测数据与全部历史指标的完整备份，用于备份或搬到另一台服务器。导出后还需单独下载“恢复密钥”，两者一起保存才能完整恢复。</span>
          </div>
        </div>
        <p className="migration-export-hint">“仅导出存储监测数据”只导监测数据与历史指标、不带 Tower 配置，导入时不动本机配置、无需恢复密钥；“仅导出 Tower 配置”只导配置、不带历史数据，适合让新环境快速接入同一批 Tower。除监测数据包外，其余导出都需再单独下载恢复密钥。</p>
        {exportMessage && <div className="inline-message">{exportMessage}</div>}
      </div>
      <div className="service-operation-card service-migration-card">
        <div className="service-operation-head">
          <div>
            <strong>迁移包导入</strong>
            <span>选择本系统导出的迁移包装回数据。先选导入方式，再开始导入。</span>
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
            description={migrationFile ? "已选择迁移包，可选择导入方式后开始导入。" : "选择本系统导出的 .tar.gz / .tgz 迁移包文件。"}
            actionText={migrationFile ? "重新选择" : "选择文件"}
            disabled={migrationBusy}
            onClick={() => migrationFileInputRef.current?.click()}
          />
          <div className="migration-mode-cards" role="radiogroup" aria-label="导入方式">
            <button
              className={migrationMode === "merge" ? "migration-mode-card active" : "migration-mode-card"}
              type="button"
              role="radio"
              aria-checked={migrationMode === "merge"}
              onClick={() => setMigrationMode("merge")}
              disabled={migrationBusy}
            >
              <strong>合并数据</strong>
              <span>只补缺的，现有的 Tower、集群和历史数据保持不动。最安全，默认选择。</span>
            </button>
            <button
              className={migrationMode === "overwrite" ? "migration-mode-card danger active" : "migration-mode-card danger"}
              type="button"
              role="radio"
              aria-checked={migrationMode === "overwrite"}
              onClick={() => setMigrationMode("overwrite")}
              disabled={migrationBusy}
            >
              <strong>整库替换</strong>
              <span>清空并替换现有业务数据和历史指标。操作前会自动生成导入前备份。</span>
            </button>
          </div>
          {migrationMode === "overwrite" && (
            <p className="migration-mode-hint migration-mode-hint-danger">
              整库替换会清空当前系统的业务数据和历史指标，且不可撤销（只能用导入前备份回退）。
            </p>
          )}
          {migrationMode === "overwrite" && (
            <label className="checkbox-line migration-confirm">
              <input type="checkbox" checked={migrationConfirmed} onChange={(event) => setMigrationConfirmed(event.target.checked)} disabled={migrationBusy} />
              我确认清空并替换当前系统数据
            </label>
          )}
          <button className={migrationMode === "overwrite" ? "secondary-button danger-button service-header-button" : "secondary-button service-header-button"} type="button" onClick={importMigration} disabled={migrationBusy || !migrationFile || (migrationMode === "overwrite" && !migrationConfirmed)}>
            <Upload size={15} />
            导入迁移包
          </button>
        </div>
        <div className="service-notice">
          <Info size={16} />
          <span>导入完成后，需要执行“服务重启”，新数据才会完全生效。</span>
          {onNavigate && (
            <button className="secondary-button service-restart-link" type="button" onClick={() => onNavigate("restart")}>
              去服务重启
            </button>
          )}
        </div>
        {importMessage && <div className="inline-message">{importMessage}</div>}
      </div>
      <div className="service-operation-card service-migration-card">
        <div className="service-operation-head">
          <div>
            <strong>环境状态</strong>
            <span>当前环境数据完整性的只读体检：业务库、历史指标是否齐全。只查看、不修改任何内容。</span>
          </div>
          <button className="secondary-button service-header-button" type="button" onClick={checkMigrationHealth} disabled={envStatusState === "checking"}>
            <RefreshCw size={16} className={envStatusState === "checking" ? "spin-icon" : undefined} />
            {envStatusState === "checking" ? "检查中" : "重新检查"}
          </button>
        </div>
        <div className="service-upgrade-status-grid service-upgrade-status-grid-wide">
          <InfoRow
            label="业务库"
            tone={envStatusState === "ready" ? (envStatus?.sqlite?.exists ? "ok" : "bad") : undefined}
            value={
              envStatusState === "checking"
                ? "检查中…"
                : envStatusState === "error"
                  ? "检查失败"
                  : envStatus?.sqlite?.exists
                    ? `正常 · ${tableCount} 张表`
                    : "未找到业务库文件"
            }
          />
          <InfoRow
            label="历史指标"
            tone={envStatusState === "ready" ? (blockCount > 0 ? "ok" : "bad") : undefined}
            value={envStatusState === "checking" ? "检查中…" : envStatusState === "error" ? "检查失败" : `${blockCount} 个数据块`}
          />
          <InfoRow
            label="完整性"
            tone={envStatusState === "ready" ? (complete ? "ok" : "bad") : undefined}
            value={
              envStatusState === "checking"
                ? "检查中…"
                : envStatusState === "error"
                  ? envStatusError || "检查失败"
                  : complete
                    ? "业务库和历史指标齐全"
                    : envStatus?.message || "不完整"
            }
          />
        </div>
      </div>
      <div className="service-operation-card service-migration-guide">
        <div className="service-operation-head">
          <div>
            <strong>使用说明</strong>
            <span>迁移包、恢复密钥与导入操作的说明，按需参考。</span>
          </div>
        </div>
        <ul>
          <li><strong>导出迁移包</strong>：完整备份——Tower 配置、库内监测数据和全部历史指标一起打包，用于备份或搬到另一台服务器。导出完成后需再单独下载“恢复密钥”（需验证平台密码），请与迁移包一起保存。</li>
          <li><strong>仅导出 Tower 配置</strong>：只导配置、不带历史数据，适合让新环境快速接入同一批 Tower。</li>
          <li><strong>仅导出存储监测数据</strong>：把 VM、卷、采集记录和全部历史指标打包，不含 Tower 配置，无需恢复密钥。导入时用「合并数据」，不会改动目标机的 Tower 配置和账号。</li>
          <li><strong>恢复密钥</strong>：迁移包里的 Tower 密码是加密保存的，恢复时必须配上导出时的密钥才能解开；没带密钥也可以在导入后到 Tower 设置里重新输入密码。</li>
          <li><strong>导入</strong>：选择文件 → 选导入方式 → 导入 → 服务重启。“合并数据”只补缺的、最安全；“整库替换”会清空现有数据，请确认后再用。</li>
          <li><strong>环境状态</strong>：进入页面自动检查一次，也可随时“重新检查”；只查看、不修改任何内容。</li>
        </ul>
        <div className="migration-guide-key-row">
          <ShieldAlert size={16} />
          <span>恢复密钥是打开迁移包里 Tower 密码的钥匙：拿到它就能解开全部 Tower 凭据。请妥善保管，不要放在公开位置或通过聊天工具、邮箱等不安全渠道传输。</span>
          <button className="secondary-button" type="button" onClick={() => setKeyDialogOpen(true)} disabled={migrationBusy}>
            <Download size={15} />
            下载恢复密钥
          </button>
        </div>
      </div>
      {exportKeyPrompt && (
        <div className="modal-backdrop" role="presentation" onClick={() => { if (!keyBusy) setExportKeyPrompt(false); }}>
          <div className="migration-key-prompt" role="dialog" aria-modal="true" aria-labelledby="migration-key-prompt-title" onClick={(event) => event.stopPropagation()}>
            <div className="migration-key-prompt-icon"><ShieldAlert size={20} /></div>
            <strong id="migration-key-prompt-title">迁移包已下载，还需下载恢复密钥</strong>
            <p>迁移包里只含加密数据，恢复时还需要“恢复密钥”才能解开 Tower 密码。密钥不打进迁移包里，需要单独下载并和迁移包一起保存。</p>
            <div className="migration-key-prompt-actions">
              <button className="secondary-button" type="button" onClick={() => setExportKeyPrompt(false)} disabled={keyBusy}>取消</button>
              <button className="primary-button" type="button" onClick={() => setKeyDialogOpen(true)} disabled={keyBusy}>
                <Download size={15} />
                下载恢复密钥
              </button>
            </div>
          </div>
        </div>
      )}
      {keyDialogOpen && (
        <div className="modal-backdrop" role="presentation" onClick={() => { if (!keyBusy) setKeyDialogOpen(false); }}>
          <div className="migration-key-dialog" role="dialog" aria-modal="true" aria-labelledby="migration-key-dialog-title" onClick={(event) => event.stopPropagation()}>
            <strong id="migration-key-dialog-title">下载恢复密钥</strong>
            <p>恢复密钥等同于本系统全部 Tower 密码的钥匙：任何拿到它的人都能解开迁移包中的 Tower 凭据并登录对应集群。</p>
            <p>请只保存在受控的存储位置，不要通过聊天工具、邮箱等不安全渠道传输；如果怀疑泄露，请立即在 Tower 设置中重置相关密码。</p>
            <form className="migration-key-form" onSubmit={(event) => { event.preventDefault(); downloadEnvFile(); }}>
              <input
                type="password"
                className="migration-key-password"
                placeholder="请输入平台登录密码确认身份"
                value={keyPassword}
                autoComplete="current-password"
                disabled={keyBusy}
                onChange={(event) => { setKeyPassword(event.target.value); setKeyError(""); }}
              />
              {keyError && <span className="migration-key-error" role="alert">{keyError}</span>}
              <div className="migration-key-dialog-actions">
                <button className="secondary-button" type="button" onClick={() => setKeyDialogOpen(false)} disabled={keyBusy}>取消</button>
                <button className="primary-button" type="submit" disabled={keyBusy}>确认下载</button>
              </div>
            </form>
          </div>
        </div>
      )}
    </>
  );
}
