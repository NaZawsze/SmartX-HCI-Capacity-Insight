import { Download, Info, ShieldAlert, Upload } from "lucide-react";
import { useRef, useState } from "react";
import { api } from "../../services/api";
import type { AppTask } from "../../types";
import { PageHeader, UploadPanel, migrationExportTaskPatch, migrationImportTaskPatch, saveBlob, sleep, taskId, transferProgressValue, uploadProgressTaskPatch } from "./shared";

interface MigrationSectionProps {
  active: boolean;
  addTask: (task: Omit<AppTask, "createdAt" | "updatedAt">) => void;
  updateTask: (id: string, patch: Partial<Omit<AppTask, "id" | "createdAt">>) => void;
}

export function MigrationSection({ active, addTask, updateTask }: MigrationSectionProps) {
  const [migrationMessage, setMigrationMessage] = useState("");
  const [migrationBusy, setMigrationBusy] = useState(false);
  const [migrationFile, setMigrationFile] = useState<File | null>(null);
  const [migrationMode, setMigrationMode] = useState<"merge" | "overwrite">("merge");
  const [migrationConfirmed, setMigrationConfirmed] = useState(false);
  const [migrationHealthMessage, setMigrationHealthMessage] = useState("");
  const [keyDialogOpen, setKeyDialogOpen] = useState(false);
  const [keyPassword, setKeyPassword] = useState("");
  const [keyError, setKeyError] = useState("");
  const [keyBusy, setKeyBusy] = useState(false);
  const migrationFileInputRef = useRef<HTMLInputElement | null>(null);

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
      setMigrationMessage("迁移包已生成。恢复密钥已同步生成，可在任务中心下载，两份文件请一起保存。");
    } catch (exc) {
      const message = exc instanceof Error ? exc.message : "导出失败";
      updateTask(id, { status: "failed", progress: 100, detail: message, logs: ["导出失败", message] });
      setMigrationMessage(message);
    } finally {
      setMigrationBusy(false);
    }
  }

  async function exportConfigMigration() {
    setMigrationMessage("");
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
      setMigrationMessage("Tower 配置已导出（不含历史数据）");
    } catch (exc) {
      const message = exc instanceof Error ? exc.message : "Tower 配置导出失败";
      updateTask(id, { status: "failed", progress: 100, detail: message, logs: ["Tower 配置导出失败", message] });
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
      setMigrationMessage("整库替换会清空当前数据，请先勾选确认");
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

  async function downloadEnvFile() {
    setMigrationMessage("");
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
      setKeyPassword("");
      setMigrationMessage("已下载恢复密钥。恢复迁移包时请与其一同使用；若没有密钥，也可导入后在 Tower 设置中重新输入密码。");
    } catch (exc) {
      setKeyError(exc instanceof Error ? exc.message : "下载恢复密钥失败");
    } finally {
      setKeyBusy(false);
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

  if (!active) return null;

  return (
    <>
      <PageHeader eyebrow="系统运维" title="数据迁移" action={(
        <div className="service-header-actions service-migration-actions">
          <button className="secondary-button service-header-button" type="button" onClick={checkMigrationHealth} disabled={migrationBusy}>
            <Info size={16} />
            健康检查
          </button>
          <button className="secondary-button service-header-button" type="button" onClick={exportConfigMigration} disabled={migrationBusy}>
            <Download size={16} />
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
            <strong>迁移包导入</strong>
            <span>选择本系统导出的迁移包装回数据。默认“合并数据”，只补缺的、不动现有内容；如需整体替换请选“整库替换”，会清空现有数据。</span>
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
          <div className="migration-mode-group" role="radiogroup" aria-label="导入方式">
            <button className={migrationMode === "merge" ? "active" : ""} type="button" onClick={() => setMigrationMode("merge")} disabled={migrationBusy}>
              合并数据
            </button>
            <button className={migrationMode === "overwrite" ? "active" : ""} type="button" onClick={() => setMigrationMode("overwrite")} disabled={migrationBusy}>
              整库替换
            </button>
          </div>
          <p className="migration-mode-hint">
            {migrationMode === "merge"
              ? "只添加缺少的数据，现有的 Tower、集群和历史数据保持不变。"
              : "将清空并替换现有的业务数据和历史指标；操作前会自动生成导入前备份，可用于回退。"}
          </p>
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
          导入完成后，请在本页执行“服务重启”，新数据才会完全生效。
        </div>
        {migrationHealthMessage && <div className="inline-message">{migrationHealthMessage}</div>}
        {migrationMessage && <div className="inline-message">{migrationMessage}</div>}
      </div>
      <div className="service-operation-card service-migration-guide">
        <strong>使用说明</strong>
        <ul>
          <li><strong>导出迁移包</strong>：把 Tower 配置和全部历史数据打包下载，用于备份或搬到另一台服务器。导出时会自动生成一份“恢复密钥”，请与迁移包一起保存。</li>
          <li><strong>仅导出 Tower 配置</strong>：只导配置、不带历史数据，适合让新环境快速接入同一批 Tower。</li>
          <li><strong>恢复密钥</strong>：迁移包里的 Tower 密码是加密保存的，恢复时必须配上导出时的密钥才能解开；没带密钥也可以在导入后到 Tower 设置里重新输入密码。</li>
          <li><strong>导入</strong>：选择文件 → 选导入方式 → 导入 → 服务重启。“合并数据”只补缺的、最安全；“整库替换”会清空现有数据，请确认后再用。</li>
          <li><strong>健康检查</strong>：查看当前数据是否完整，只查看、不修改任何内容。</li>
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
