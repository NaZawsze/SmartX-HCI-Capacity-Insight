import { AlertTriangle, CheckCircle, Pencil, RefreshCw, ShieldCheck, Trash2 } from "lucide-react";
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
                <span className="tower-versions">Tower: {tower.tower_version || "-"}</span>
                <span className="tower-versions">SmartXOS: {osVersionsLabel(tower)}</span>
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
                  {/* 2026-10-07 用户口径（原话）：按**上一次成功采集时间**算，超过 24 小时
                      才出现——简单的「黄色三角感叹号 + 多少天」，24 小时内一律不显示。
                      从未成功过则显示「⚠ 未采集」。 */}
                  {(() => {
                    const days = staleDays(tower.last_success_at);
                    if (days === null) {
                      return (
                        <span className="tower-health stale">
                          <AlertTriangle size={14} />
                          未采集
                        </span>
                      );
                    }
                    if (days >= 1) {
                      return (
                        <span className="tower-health stale">
                          <AlertTriangle size={14} />
                          {days} 天
                        </span>
                      );
                    }
                    return null;
                  })()}
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

function parseBackendUtc(iso?: string | null): number | null {
  if (!iso) return null;
  // SQLite 的 CURRENT_TIMESTAMP 输出「YYYY-MM-DD HH:MM:SS」= UTC 且**不带时区**；
  // 直接 new Date() 会按浏览器本地时区解析（UTC+8 下凭空差 8 小时）。无时区信息时显式按 UTC。
  const normalized = /Z$|[+-]\d{2}:?\d{2}$/.test(iso) ? iso : `${iso.replace(" ", "T")}Z`;
  const time = new Date(normalized).getTime();
  return Number.isFinite(time) ? time : null;
}

//: 距上一次成功采集的天数（用户口径 2026-10-07）：
//: null = 从未成功（显示「未采集」）；0 = 24 小时内（正常，不显示）；>=1 = 超期天数。
function staleDays(lastSuccessAt?: string | null): number | null {
  const time = parseBackendUtc(lastSuccessAt);
  if (time === null) return null;
  const hours = (Date.now() - time) / 3_600_000;
  if (hours <= 24) return 0;
  return Math.floor(hours / 24);
}

//: 各集群 SMTX OS 版本去重后展示（一塔多集群、版本不同时并列；都没有显示 "-"）。
function osVersionsLabel(tower: Tower): string {
  const versions = Array.from(
    new Set(tower.clusters.map((cluster) => cluster.os_version).filter((value): value is string => Boolean(value)))
  );
  return versions.length ? versions.join(" / ") : "-";
}
