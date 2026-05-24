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
  collection_minute: 10
};

const emptyPasswordForm = {
  current_password: "",
  new_password: "",
  confirm_password: ""
};

export function SettingsPage() {
  const [towers, setTowers] = useState<Tower[]>([]);
  const [form, setForm] = useState(emptyForm);
  const [editingTowerId, setEditingTowerId] = useState<number | null>(null);
  const [editForm, setEditForm] = useState(emptyForm);
  const [passwordForm, setPasswordForm] = useState(emptyPasswordForm);
  const [message, setMessage] = useState("");
  const [passwordMessage, setPasswordMessage] = useState("");

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

  async function submitPassword(event: FormEvent) {
    event.preventDefault();
    setPasswordMessage("");
    if (passwordForm.new_password !== passwordForm.confirm_password) {
      setPasswordMessage("两次输入的新密码不一致");
      return;
    }
    try {
      await api.changePassword(passwordForm);
      setPasswordForm(emptyPasswordForm);
      setPasswordMessage("平台密码已更新");
    } catch (exc) {
      setPasswordMessage(exc instanceof Error ? exc.message : "密码更新失败");
    }
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

      <Card title="平台密码">
        <form className="settings-form" onSubmit={submitPassword}>
          <label>
            当前密码
            <input type="password" value={passwordForm.current_password} onChange={(event) => setPasswordForm({ ...passwordForm, current_password: event.target.value })} required />
          </label>
          <label>
            新密码
            <input type="password" value={passwordForm.new_password} onChange={(event) => setPasswordForm({ ...passwordForm, new_password: event.target.value })} required />
          </label>
          <label>
            确认新密码
            <input type="password" value={passwordForm.confirm_password} onChange={(event) => setPasswordForm({ ...passwordForm, confirm_password: event.target.value })} required />
          </label>
          {passwordMessage && <div className="inline-message">{passwordMessage}</div>}
          <button className="primary-button" type="submit">
            <Save size={16} />
            修改密码
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
