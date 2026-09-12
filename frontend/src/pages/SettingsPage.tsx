import { CheckCircle, Pencil, Plus, RefreshCw, Save, ShieldCheck, Trash2, X } from "lucide-react";
import { FormEvent, useEffect, useState } from "react";
import { Card } from "../components/Card";
import { api } from "../services/api";
import type { Tower } from "../types";

const emptyForm = {
  name: "",
  base_url: "",
  username: "",
  password: "",
  api_token: "",
  verify_tls: true,
  enabled: true,
  collection_hour: 2,
  collection_minute: 10,
  collection_interval_minutes: 60,
  collection_mode: "interval",
  collection_retry_enabled: true,
  collection_retry_interval_minutes: 15,
  collection_retry_max_attempts: 3
};

export function SettingsPage() {
  const [towers, setTowers] = useState<Tower[]>([]);
  const [form, setForm] = useState(emptyForm);
  const [editingTowerId, setEditingTowerId] = useState<number | null>(null);
  const [editForm, setEditForm] = useState(emptyForm);
  const [message, setMessage] = useState("");

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
          <ScheduleModeFields form={form} onChange={setForm} />
          <RetryFields form={form} onChange={setForm} />
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
                  <ScheduleModeFields form={editForm} onChange={setEditForm} />
                  <RetryFields form={editForm} onChange={setEditForm} />
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

type ScheduleForm = typeof emptyForm;

const SCHEDULE_MODES: Array<{ value: "daily" | "interval"; label: string }> = [
  { value: "daily", label: "每日定时" },
  { value: "interval", label: "按间隔" }
];

function ScheduleModeFields({ form, onChange }: { form: ScheduleForm; onChange: (next: ScheduleForm) => void }) {
  const mode: "daily" | "interval" = form.collection_mode === "daily" ? "daily" : "interval";
  return (
    <div className="schedule-fields">
      <div className="schedule-field-row">
        <span className="schedule-field-label">采集模式</span>
        <div className="schedule-mode-switch" role="tablist" aria-label="采集模式">
          {SCHEDULE_MODES.map((item) => (
            <button
              key={item.value}
              type="button"
              role="tab"
              aria-selected={mode === item.value}
              className={mode === item.value ? "schedule-mode-option active" : "schedule-mode-option"}
              onClick={() => onChange({ ...form, collection_mode: item.value })}
            >
              {item.label}
            </button>
          ))}
        </div>
      </div>
      {mode === "daily" && (
        <label className="schedule-field-row">
          <span className="schedule-field-label">每日采集时间</span>
          <input
            type="time"
            value={`${String(form.collection_hour).padStart(2, "0")}:${String(form.collection_minute).padStart(2, "0")}`}
            onChange={(event) => {
              const [hour, minute] = event.target.value.split(":").map((part) => Number(part));
              onChange({ ...form, collection_hour: Number.isFinite(hour) ? hour : 2, collection_minute: Number.isFinite(minute) ? minute : 0 });
            }}
          />
        </label>
      )}
      {mode === "interval" && (
        <>
          <label className="schedule-field-row">
            <span className="schedule-field-label">采集间隔 - 分钟</span>
            <input
              type="number"
              min={1}
              max={10080}
              value={form.collection_interval_minutes}
              onChange={(event) => onChange({ ...form, collection_interval_minutes: Number(event.target.value) })}
            />
          </label>
          <div className="form-hint">按固定间隔循环采集，默认 60 = 每小时一次。每日定时则每天固定钟点执行一次。</div>
        </>
      )}
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
    collection_minute: payload.collection_minute,
    collection_interval_minutes: payload.collection_interval_minutes,
    collection_mode: payload.collection_mode,
    collection_retry_enabled: payload.collection_retry_enabled,
    collection_retry_interval_minutes: payload.collection_retry_interval_minutes,
    collection_retry_max_attempts: payload.collection_retry_max_attempts
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

function RetryFields({ form, onChange }: { form: typeof emptyForm; onChange: (form: typeof emptyForm) => void }) {
  return (
    <div className="collection-retry-fields">
      <label className="checkbox-line">
        <input type="checkbox" aria-label="启用采集失败重试" checked={form.collection_retry_enabled} onChange={(event) => onChange({ ...form, collection_retry_enabled: event.target.checked })} />
        启用采集失败重试
      </label>
      <div className="form-pair">
        <label>
          重试间隔 - 分钟
          <input
            aria-label="重试间隔 - 分钟"
            type="number"
            min={1}
            max={1440}
            value={form.collection_retry_interval_minutes}
            onChange={(event) => onChange({ ...form, collection_retry_interval_minutes: Number(event.target.value) })}
          />
        </label>
        <label>
          最大重试次数
          <input
            aria-label="最大重试次数"
            type="number"
            min={0}
            max={10}
            value={form.collection_retry_max_attempts}
            onChange={(event) => onChange({ ...form, collection_retry_max_attempts: Number(event.target.value) })}
          />
        </label>
      </div>
      <div className="form-hint">定时采集失败时只重试失败 Tower/集群；默认每 15 分钟重试一次，最多重试 3 次。</div>
    </div>
  );
}

function cleanOptional(value: string): string | null {
  const trimmed = value.trim();
  return trimmed ? trimmed : null;
}
