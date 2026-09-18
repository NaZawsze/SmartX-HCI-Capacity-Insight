import { CheckCircle, Pencil, RefreshCw, ShieldCheck, Trash2 } from "lucide-react";
import { FormEvent, useEffect, useState } from "react";
import { Card } from "../components/Card";
import { TowerForm, emptyTowerForm, normalizeTowerCreatePayload, normalizeTowerUpdatePayload, type TowerFormState } from "../components/tower/TowerForm";
import { api } from "../services/api";
import type { Tower } from "../types";

export function SettingsPage() {
  const [towers, setTowers] = useState<Tower[]>([]);
  const [form, setForm] = useState<TowerFormState>(emptyTowerForm());
  const [editingTowerId, setEditingTowerId] = useState<number | null>(null);
  const [editForm, setEditForm] = useState<TowerFormState>(emptyTowerForm());
  const [message, setMessage] = useState("");
  const [testResult, setTestResult] = useState("");
  const [testing, setTesting] = useState(false);
  const [rowTesting, setRowTesting] = useState(false);
  const [rowTestMessage, setRowTestMessage] = useState("");
  const [deletingTowerId, setDeletingTowerId] = useState<number | null>(null);

  async function reload() {
    setTowers(await api.towers());
  }

  useEffect(() => {
    reload().catch(() => undefined);
  }, []);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setMessage("");
    try {
      await api.createTower(normalizeTowerCreatePayload(form));
      setForm(emptyTowerForm());
      setTestResult("");
      await reload();
      setMessage("Tower 已保存");
    } catch (exc) {
      setMessage(exc instanceof Error ? exc.message : "保存失败");
    }
  }

  async function testTower(id: number) {
    setRowTesting(true);
    setRowTestMessage("");
    try {
      const result = await api.testTower(id);
      setRowTestMessage(result.ok ? `✓ ${result.message}` : `✗ ${result.message}`);
    } catch (exc) {
      setRowTestMessage(exc instanceof Error ? `✗ ${exc.message}` : "✗ 测试失败");
    } finally {
      setRowTesting(false);
    }
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
      collection_minute: tower.collection_minute,
      collection_interval_minutes: tower.collection_interval_minutes ?? 60,
      collection_mode: tower.collection_mode === "daily" ? "daily" : "interval",
      collection_retry_enabled: tower.collection_retry_enabled ?? true,
      collection_retry_interval_minutes: tower.collection_retry_interval_minutes ?? 15,
      collection_retry_max_attempts: tower.collection_retry_max_attempts ?? 3
    });
    setMessage("");
  }

  async function submitEdit(event: FormEvent, towerId: number) {
    event.preventDefault();
    setMessage("");
    try {
      await api.updateTower(towerId, normalizeTowerUpdatePayload(editForm));
      setEditingTowerId(null);
      setEditForm(emptyTowerForm());
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

  async function setAllClusters(tower: Tower, enabled: boolean) {
    await Promise.all(tower.clusters.map((cluster) => api.updateCluster(tower.id, cluster.cluster_id, { enabled })));
    await reload();
  }

  async function testNewTowerConnection() {
    setTesting(true);
    setTestResult("");
    try {
      const result = await api.testTowerParams({
        base_url: form.base_url.trim(),
        username: form.username,
        password: form.password,
        api_token: form.api_token,
        verify_tls: form.verify_tls
      });
      setTestResult(result.ok ? `✓ ${result.message}` : `✗ ${result.message}`);
    } catch (exc) {
      setTestResult(exc instanceof Error ? `✗ ${exc.message}` : "✗ 测试失败");
    } finally {
      setTesting(false);
    }
  }

  async function confirmDeleteTower(id: number) {
    try {
      await api.deleteTower(id);
    } finally {
      setDeletingTowerId(null);
      await reload();
    }
  }

  return (
    <div className="settings-grid">
      <Card title="新增 Tower">
        <TowerForm
          mode="create"
          form={form}
          onChange={setForm}
          onSubmit={submit}
          message={message}
          onTestConnection={testNewTowerConnection}
          testing={testing}
          testResult={testResult}
        />
      </Card>

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
                <div className="tower-health-stack">
                  <span className={`tower-health ${tower.last_collection ? tower.last_collection.status : "none"}`}>
                    {tower.last_collection
                      ? `${tower.last_collection.status === "success" ? "✓" : "✗"} ${formatRelativeTime(tower.last_collection.finished_at)}采集`
                      : "未采集"}
                  </span>
                  {rowTestMessage && (
                    <span className={`tower-test-result ${rowTestMessage.startsWith("✓") ? "ok" : "fail"}`}>
                      {rowTestMessage}
                    </span>
                  )}
                </div>
                <button className="icon-button" title="编辑配置" type="button" onClick={() => startEdit(tower)}>
                  <Pencil size={16} />
                </button>
                <button className="icon-button" title={rowTesting ? "测试中…" : "测试连接"} type="button" disabled={rowTesting} onClick={() => testTower(tower.id)}>
                  <RefreshCw size={16} className={rowTesting ? "task-running-icon" : undefined} />
                </button>
                {deletingTowerId === tower.id ? (
                  <>
                    <button className="danger-confirm-button" type="button" onClick={() => confirmDeleteTower(tower.id)}>
                      确认删除
                    </button>
                    <button className="secondary-button compact" type="button" onClick={() => setDeletingTowerId(null)}>
                      取消
                    </button>
                  </>
                ) : (
                  <button className="icon-button danger" title="删除" type="button" onClick={() => setDeletingTowerId(tower.id)}>
                    <Trash2 size={16} />
                  </button>
                )}
              </div>
              {editingTowerId === tower.id && (
                <TowerForm
                  mode="edit"
                  form={editForm}
                  onChange={setEditForm}
                  onSubmit={(event) => submitEdit(event, tower.id)}
                  message={message}
                  tower={tower}
                  onToggleCluster={toggleCluster}
                  onSelectAllClusters={setAllClusters}
                  onCancel={() => setEditingTowerId(null)}
                />
              )}
            </div>
          ))}
          {!towers.length && <div className="empty-state">暂无 Tower 配置</div>}
        </div>
      </Card>
    </div>
  );
}

function formatRelativeTime(iso?: string | null): string {
  if (!iso) return "";
  const time = new Date(iso).getTime();
  if (!Number.isFinite(time)) return "";
  const minutes = Math.round((Date.now() - time) / 60000);
  if (minutes < 1) return "刚刚";
  if (minutes < 60) return `${minutes} 分钟前`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} 小时前`;
  return `${Math.round(hours / 24)} 天前`;
}
