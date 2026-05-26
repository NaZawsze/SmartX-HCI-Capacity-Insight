<<<<<<< Updated upstream
import { CheckCircle, Pencil, Plus, RefreshCw, Save, ShieldCheck, Trash2, X } from "lucide-react";
=======
import { CheckCircle, Download, FileUp, ListChecks, Pencil, Play, Plus, Power, RefreshCw, RotateCcw, Save, ShieldCheck, Trash2, Upload, X } from "lucide-react";
>>>>>>> Stashed changes
import { FormEvent, useEffect, useState } from "react";
import { Card } from "../components/Card";
import { api } from "../services/api";
import type { Tower, UpgradeTask } from "../types";

const emptyForm = {
  name: "",
  base_url: "",
  username: "",
  password: "",
  api_token: "",
  verify_tls: true,
  enabled: true,
  collection_hour: 2,
  collection_minute: 10
};

export function SettingsPage() {
  const [towers, setTowers] = useState<Tower[]>([]);
  const [form, setForm] = useState(emptyForm);
  const [editingTowerId, setEditingTowerId] = useState<number | null>(null);
  const [editForm, setEditForm] = useState(emptyForm);
  const [message, setMessage] = useState("");
<<<<<<< Updated upstream
=======
  const [migrationMessage, setMigrationMessage] = useState("");
  const [migrationBusy, setMigrationBusy] = useState(false);
  const [migrationFile, setMigrationFile] = useState<File | null>(null);
  const [migrationMode, setMigrationMode] = useState<"merge" | "overwrite">("merge");
  const [migrationConfirmed, setMigrationConfirmed] = useState(false);
  const [restartBusy, setRestartBusy] = useState(false);
  const [restartMessage, setRestartMessage] = useState("");
  const [upgradeVersion, setUpgradeVersion] = useState("");
  const [upgradeBusy, setUpgradeBusy] = useState(false);
  const [upgradeFile, setUpgradeFile] = useState<File | null>(null);
  const [upgradeTask, setUpgradeTask] = useState<UpgradeTask | null>(null);
  const [upgradeHistory, setUpgradeHistory] = useState<UpgradeTask[]>([]);
  const [upgradeMessage, setUpgradeMessage] = useState("");
>>>>>>> Stashed changes

  async function reload() {
    setTowers(await api.towers());
  }

  useEffect(() => {
    reload().catch(() => undefined);
    loadUpgradeMeta().catch(() => undefined);
  }, []);

  useEffect(() => {
    if (!upgradeTask || !["pending", "running"].includes(upgradeTask.status)) {
      return undefined;
    }
    const timer = window.setInterval(() => {
      api.upgradeStatus(upgradeTask.id).then(setUpgradeTask).catch(() => undefined);
    }, 2500);
    return () => window.clearInterval(timer);
  }, [upgradeTask?.id, upgradeTask?.status]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setMessage("");
    try {
      await api.createTower(normalizeTowerPayload(form));
      setForm(emptyForm);
      await reload();
      setMessage("Tower 已保存");
    } catch (exc) {
      setMessage(exc instanceof Error ? exc.message : "保存失败");
    }
  }

  async function testTower(id: number) {
    const result = await api.testTower(id);
    setMessage(result.message);
    await reload();
  }

  async function removeTower(id: number) {
    await api.deleteTower(id);
    await reload();
  }

  function startEdit(tower: Tower) {
    setEditingTowerId(tower.id);
    setEditForm({
      name: tower.name,
      base_url: tower.base_url,
      username: tower.username ?? "",
      password: "",
      api_token: "",
      verify_tls: tower.verify_tls,
      enabled: tower.enabled,
      collection_hour: tower.collection_hour,
      collection_minute: tower.collection_minute
    });
    setMessage("");
  }

  async function submitEdit(event: FormEvent, towerId: number) {
    event.preventDefault();
    setMessage("");
    try {
      await api.updateTower(towerId, normalizeTowerUpdatePayload(editForm));
      setEditingTowerId(null);
      setEditForm(emptyForm);
      await reload();
      setMessage("Tower 已更新");
    } catch (exc) {
      setMessage(exc instanceof Error ? exc.message : "更新失败");
    }
  }

  async function toggleCluster(towerId: number, clusterId: string, enabled: boolean) {
    await api.updateCluster(towerId, clusterId, { enabled });
    await reload();
  }

<<<<<<< Updated upstream
=======
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
      setMigrationMode("merge");
      setMigrationConfirmed(false);
      await reload();
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


  async function loadUpgradeMeta() {
    const [version, history] = await Promise.all([api.upgradeVersion(), api.upgradeHistory()]);
    setUpgradeVersion(version.version);
    setUpgradeHistory(history);
  }

  async function uploadUpgrade() {
    setUpgradeMessage("");
    if (!upgradeFile) {
      setUpgradeMessage("请选择升级包文件");
      return;
    }
    setUpgradeBusy(true);
    try {
      const task = await api.uploadUpgradePackage(upgradeFile);
      setUpgradeTask(task);
      setUpgradeMessage("升级包已上传，请先执行预检查。");
      setUpgradeFile(null);
      await loadUpgradeMeta();
    } catch (exc) {
      setUpgradeMessage(exc instanceof Error ? exc.message : "上传失败");
    } finally {
      setUpgradeBusy(false);
    }
  }

  async function precheckUpgrade() {
    if (!upgradeTask) return;
    setUpgradeMessage("");
    setUpgradeBusy(true);
    try {
      const task = await api.precheckUpgrade(upgradeTask.id);
      setUpgradeTask(task);
      setUpgradeMessage(task.status === "ready" ? "预检查通过，可以开始升级。" : "预检查未通过，请查看检查项。");
      await loadUpgradeMeta();
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
      const task = await api.startUpgrade(upgradeTask.id);
      setUpgradeTask(task);
      setUpgradeMessage("升级任务已提交，正在等待执行。");
      await loadUpgradeMeta();
    } catch (exc) {
      setUpgradeMessage(exc instanceof Error ? exc.message : "启动升级失败");
    } finally {
      setUpgradeBusy(false);
    }
  }

  async function rollbackUpgrade() {
    if (!upgradeTask) return;
    setUpgradeMessage("");
    setUpgradeBusy(true);
    try {
      const task = await api.rollbackUpgrade(upgradeTask.id);
      setUpgradeTask(task);
      setUpgradeMessage("回滚任务已提交。");
      await loadUpgradeMeta();
    } catch (exc) {
      setUpgradeMessage(exc instanceof Error ? exc.message : "回滚失败");
    } finally {
      setUpgradeBusy(false);
    }
  }

  async function selectHistoryTask(taskId: string) {
    setUpgradeMessage("");
    try {
      setUpgradeTask(await api.upgradeStatus(taskId));
    } catch (exc) {
      setUpgradeMessage(exc instanceof Error ? exc.message : "读取升级任务失败");
    }
  }

>>>>>>> Stashed changes
  return (
    <div className="settings-grid">
      <Card title="新增 Tower">
        <form className="settings-form" onSubmit={submit}>
          <label>
            名称
            <input value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} required />
          </label>
          <label>
            地址
            <input value={form.base_url} onChange={(event) => setForm({ ...form, base_url: event.target.value })} placeholder="https://tower.example.com" required />
          </label>
          <label>
            用户名
            <input value={form.username} onChange={(event) => setForm({ ...form, username: event.target.value })} />
          </label>
          <label>
            密码
            <input type="password" value={form.password} onChange={(event) => setForm({ ...form, password: event.target.value })} />
          </label>
          <label>
            API Token (可选)
            <input value={form.api_token} onChange={(event) => setForm({ ...form, api_token: event.target.value })} />
          </label>
          <div className="form-pair">
            <label>
              每日采集时间 - 小时
              <input type="number" min={0} max={23} value={form.collection_hour} onChange={(event) => setForm({ ...form, collection_hour: Number(event.target.value) })} />
            </label>
            <label>
              每日采集时间 - 分钟
              <input type="number" min={0} max={59} value={form.collection_minute} onChange={(event) => setForm({ ...form, collection_minute: Number(event.target.value) })} />
            </label>
          </div>
          <div className="form-hint">按 24 小时制设置每天自动采集的触发时间，例如 02:10 表示每天凌晨 2 点 10 分执行。</div>
          <label className="checkbox-line">
            <input type="checkbox" checked={form.verify_tls} onChange={(event) => setForm({ ...form, verify_tls: event.target.checked })} />
            校验 TLS 证书
          </label>
          {message && <div className="inline-message">{message}</div>}
          <button className="primary-button" type="submit">
            <Plus size={16} />
            创建
          </button>
        </form>
      </Card>

<<<<<<< Updated upstream
=======


      <Card title="数据迁移">
        <div className="migration-panel">
          <div className="migration-actions">
            <button className="primary-button" type="button" onClick={exportMigration} disabled={migrationBusy}>
              <Download size={16} />
              导出迁移包
            </button>
          </div>
          <div className="migration-import">
            <label>
              迁移包文件
              <input type="file" accept=".gz,.tgz,.tar.gz,application/gzip" onChange={(event) => setMigrationFile(event.target.files?.[0] ?? null)} disabled={migrationBusy} />
            </label>
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
          <div className="form-hint">默认补全缺失数据：业务库按唯一键保留已有记录，Prometheus 只补不存在的历史 block；覆盖导入会替换当前数据。导入后请重启服务使数据完全生效。</div>
          {migrationMessage && <div className="inline-message">{migrationMessage}</div>}
        </div>
      </Card>


      <Card title="服务管理">
        <div className="service-control-panel">
          <button className="secondary-button" type="button" onClick={restartServices} disabled={restartBusy}>
            <Power size={16} />
            {restartBusy ? "正在提交重启" : "重启数据服务"}
          </button>
          <div className="form-hint">用于导入数据后手动重启 web-api、collector-worker 和 Prometheus，使补全的数据完全生效。</div>
          {restartMessage && <div className="inline-message">{restartMessage}</div>}
        </div>
      </Card>

      <Card title="系统升级" className="wide-card">
        <div className="upgrade-panel">
          <div className="upgrade-summary">
            <span>当前版本</span>
            <strong>{upgradeVersion || "-"}</strong>
          </div>
          <div className="upgrade-upload-row">
            <label>
              升级包
              <input type="file" accept=".gz,.tgz,.tar.gz,application/gzip" onChange={(event) => setUpgradeFile(event.target.files?.[0] ?? null)} disabled={upgradeBusy} />
            </label>
            <button className="primary-button" type="button" onClick={uploadUpgrade} disabled={upgradeBusy || !upgradeFile}>
              <FileUp size={16} />
              上传升级包
            </button>
          </div>

          {upgradeTask && (
            <div className="upgrade-task">
              <div className="upgrade-task-header">
                <div>
                  <span>目标版本</span>
                  <strong>{upgradeTask.manifest?.version || "-"}</strong>
                </div>
                <span className={`upgrade-status status-${upgradeTask.status}`}>{upgradeTask.status}</span>
              </div>
              <div className="upgrade-meta-grid">
                <span>最低兼容版本：{upgradeTask.manifest?.min_version || "未限制"}</span>
                <span>数据库迁移：{upgradeTask.manifest?.database_migration ? "需要" : "不需要"}</span>
                <span>影响服务：{upgradeTask.manifest?.images?.map((item) => item.service).join("、") || "-"}</span>
              </div>
              {upgradeTask.manifest?.release_notes && <div className="form-hint">{upgradeTask.manifest.release_notes}</div>}

              <div className="upgrade-actions">
                <button className="secondary-button" type="button" onClick={precheckUpgrade} disabled={upgradeBusy || ["pending", "running"].includes(upgradeTask.status)}>
                  <ListChecks size={15} />
                  预检查
                </button>
                <button className="primary-button compact" type="button" onClick={startUpgrade} disabled={upgradeBusy || upgradeTask.status !== "ready"}>
                  <Play size={15} />
                  开始升级
                </button>
                <button className="secondary-button danger-button" type="button" onClick={rollbackUpgrade} disabled={upgradeBusy || !["failed", "rollback_ready", "success"].includes(upgradeTask.status)}>
                  <RotateCcw size={15} />
                  手动回滚
                </button>
              </div>

              {!!upgradeTask.precheck?.length && (
                <div className="upgrade-checks">
                  {upgradeTask.precheck.map((item) => (
                    <div className={item.ok ? "ok" : "failed"} key={item.name}>
                      <span>{item.name}</span>
                      <strong>{item.ok ? "通过" : "失败"}</strong>
                      <small>{item.message}</small>
                    </div>
                  ))}
                </div>
              )}

              {!!upgradeTask.steps?.length && (
                <div className="upgrade-steps">
                  {upgradeTask.steps.map((step) => (
                    <div className={`upgrade-step step-${step.status}`} key={step.key}>
                      <span>{step.label}</span>
                      <strong>{step.status}</strong>
                    </div>
                  ))}
                </div>
              )}

              {!!upgradeTask.logs?.length && <pre className="upgrade-log">{upgradeTask.logs.join("\n")}</pre>}
            </div>
          )}

          {!!upgradeHistory.length && (
            <div className="upgrade-history">
              <span>升级历史</span>
              {upgradeHistory.slice(0, 5).map((task) => (
                <button type="button" key={task.id} onClick={() => selectHistoryTask(task.id)}>
                  {task.manifest?.version || task.package_filename || task.id} · {task.status}
                </button>
              ))}
            </div>
          )}
          <div className="form-hint">升级只替换镜像，不覆盖 .env，不修改核心 volumes。升级前会自动生成数据备份。</div>
          {upgradeMessage && <div className="inline-message">{upgradeMessage}</div>}
        </div>
      </Card>

>>>>>>> Stashed changes
      <Card title="Tower 列表" className="wide-card">
        <div className="tower-table">
          {towers.map((tower) => (
            <div className="tower-row" key={tower.id}>
              <div>
                <strong>{tower.name}</strong>
                <span>{tower.base_url}</span>
              </div>
              <div className="tower-meta">
                <span>
                  <ShieldCheck size={14} />
                  {tower.verify_tls ? "TLS" : "跳过 TLS"}
                </span>
                <span>
                  <CheckCircle size={14} />
                  {tower.clusters.length} 集群
                </span>
              </div>
              <div className="row-actions">
                <button className="icon-button" title="编辑配置" type="button" onClick={() => startEdit(tower)}>
                  <Pencil size={16} />
                </button>
                <button className="icon-button" title="测试连接" type="button" onClick={() => testTower(tower.id)}>
                  <RefreshCw size={16} />
                </button>
                <button className="icon-button danger" title="删除" type="button" onClick={() => removeTower(tower.id)}>
                  <Trash2 size={16} />
                </button>
              </div>
              {editingTowerId === tower.id && (
                <form className="tower-edit-form" onSubmit={(event) => submitEdit(event, tower.id)}>
                  <label>
                    名称
                    <input value={editForm.name} onChange={(event) => setEditForm({ ...editForm, name: event.target.value })} required />
                  </label>
                  <label>
                    地址
                    <input value={editForm.base_url} onChange={(event) => setEditForm({ ...editForm, base_url: event.target.value })} required />
                  </label>
                  <label>
                    用户名
                    <input value={editForm.username} onChange={(event) => setEditForm({ ...editForm, username: event.target.value })} />
                  </label>
                  <label>
                    密码
                    <input type="password" value={editForm.password} onChange={(event) => setEditForm({ ...editForm, password: event.target.value })} placeholder="留空则不修改" />
                  </label>
                  <label>
                    API Token (可选)
                    <input value={editForm.api_token} onChange={(event) => setEditForm({ ...editForm, api_token: event.target.value })} placeholder="留空则不修改" />
                  </label>
                  <div className="form-pair">
                    <label>
                      每日采集时间 - 小时
                      <input type="number" min={0} max={23} value={editForm.collection_hour} onChange={(event) => setEditForm({ ...editForm, collection_hour: Number(event.target.value) })} />
                    </label>
                    <label>
                      每日采集时间 - 分钟
                      <input type="number" min={0} max={59} value={editForm.collection_minute} onChange={(event) => setEditForm({ ...editForm, collection_minute: Number(event.target.value) })} />
                    </label>
                  </div>
                  <div className="form-hint">密码和 API Token 留空时保留原配置。采集时间按 24 小时制设置每天自动采集的触发时间。</div>
                  <div className="tower-edit-options">
                    <label className="checkbox-line">
                      <input type="checkbox" checked={editForm.verify_tls} onChange={(event) => setEditForm({ ...editForm, verify_tls: event.target.checked })} />
                      校验 TLS 证书
                    </label>
                    <label className="checkbox-line">
                      <input type="checkbox" checked={editForm.enabled} onChange={(event) => setEditForm({ ...editForm, enabled: event.target.checked })} />
                      启用采集
                    </label>
                  </div>
                  <div className="tower-edit-actions">
                    <button className="secondary-button" type="button" onClick={() => setEditingTowerId(null)}>
                      <X size={15} />
                      取消
                    </button>
                    <button className="primary-button compact" type="submit">
                      <Save size={15} />
                      保存
                    </button>
                  </div>
                </form>
              )}
              {!!tower.clusters.length && (
                <div className="cluster-toggle-list">
                  {tower.clusters.map((cluster) => (
                    <label className="cluster-toggle" key={cluster.cluster_id}>
                      <input
                        type="checkbox"
                        checked={cluster.enabled}
                        onChange={(event) => toggleCluster(tower.id, cluster.cluster_id, event.target.checked)}
                      />
                      <span>{cluster.name}</span>
                    </label>
                  ))}
                </div>
              )}
            </div>
          ))}
          {!towers.length && <div className="empty-state">暂无 Tower 配置</div>}
        </div>
      </Card>
    </div>
  );
}

function normalizeTowerPayload(payload: typeof emptyForm) {
  return {
    ...payload,
    name: payload.name.trim(),
    base_url: payload.base_url.trim(),
    username: cleanOptional(payload.username),
    password: cleanOptional(payload.password),
    api_token: cleanOptional(payload.api_token)
  };
}

function normalizeTowerUpdatePayload(payload: typeof emptyForm) {
  const next: Record<string, string | number | boolean | null> = {
    name: payload.name.trim(),
    base_url: payload.base_url.trim(),
    username: cleanOptional(payload.username),
    verify_tls: payload.verify_tls,
    enabled: payload.enabled,
    collection_hour: payload.collection_hour,
    collection_minute: payload.collection_minute
  };
  const password = cleanOptional(payload.password);
  const apiToken = cleanOptional(payload.api_token);
  if (password !== null) {
    next.password = password;
  }
  if (apiToken !== null) {
    next.api_token = apiToken;
  }
  return next;
}

function cleanOptional(value: string): string | null {
  const trimmed = value.trim();
  return trimmed ? trimmed : null;
}
