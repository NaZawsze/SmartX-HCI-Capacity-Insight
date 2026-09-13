import { Download, Info, Upload } from "lucide-react";
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
      setMigrationMessage("迁移包已生成");
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
    addTask({ id, kind: "export", title: "导出配置迁移包", detail: "正在导出 Tower 和集群配置", status: "running", progress: 30, logs: ["配置迁移只包含 Tower 与集群配置"] });
    try {
      const result = await api.exportConfigMigration((progress) => {
        const value = transferProgressValue(progress);
        updateTask(id, { progress: Math.max(30, Math.min(95, value)), detail: "正在下载配置迁移包" });
      });
      saveBlob(result.blob, result.filename || "smartx-config-migration.tar.gz");
      updateTask(id, {
        status: "succeeded",
        progress: 100,
        detail: result.filename || "配置迁移包已生成",
        logs: ["配置迁移包已生成", result.savedPath ? `服务器留档：${result.savedPath}` : "已完成浏览器下载"],
        links: result.downloadUrl ? [{ label: "下载", filename: result.filename, url: result.downloadUrl, path: result.savedPath }] : undefined
      });
      setMigrationMessage("配置迁移包已生成，仅包含 Tower 和集群配置");
    } catch (exc) {
      const message = exc instanceof Error ? exc.message : "配置迁移包导出失败";
      updateTask(id, { status: "failed", progress: 100, detail: message, logs: ["配置迁移包导出失败", message] });
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
            导出配置迁移包
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
          <button className={migrationMode === "overwrite" ? "secondary-button danger-button service-header-button" : "secondary-button service-header-button"} type="button" onClick={importMigration} disabled={migrationBusy || !migrationFile || (migrationMode === "overwrite" && !migrationConfirmed)}>
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
