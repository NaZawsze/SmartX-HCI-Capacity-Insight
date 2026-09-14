import { FormEvent } from "react";
import { Plus, Save, X } from "lucide-react";
import type { Tower } from "../../types";

export interface TowerFormState {
  name: string;
  base_url: string;
  username: string;
  password: string;
  api_token: string;
  verify_tls: boolean;
  enabled: boolean;
  collection_hour: number;
  collection_minute: number;
  collection_interval_minutes: number;
  collection_mode: "daily" | "interval" | string;
  collection_retry_enabled: boolean;
  collection_retry_interval_minutes: number;
  collection_retry_max_attempts: number;
}

export function emptyTowerForm(): TowerFormState {
  return {
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
}

interface TowerFormProps {
  mode: "create" | "edit";
  form: TowerFormState;
  onChange: (next: TowerFormState) => void;
  onSubmit: (event: FormEvent) => void;
  message?: string;
  /** 用当前表单值发起连接测试（create 与 edit 均可用） */
  onTestConnection?: () => void;
  testing?: boolean;
  testResult?: string;
  /** edit-only：集群分区与取消按钮 */
  tower?: Tower;
  onToggleCluster?: (towerId: number, clusterId: string, enabled: boolean) => void;
  onSelectAllClusters?: (tower: Tower, enabled: boolean) => void;
  onCancel?: () => void;
}

export function TowerForm({ mode, form, onChange, onSubmit, message, onTestConnection, testing, testResult, tower, onToggleCluster, onSelectAllClusters, onCancel }: TowerFormProps) {
  const isEdit = mode === "edit";
  return (
    <form className={`settings-form tower-form${isEdit ? " tower-edit-form" : ""}`} onSubmit={onSubmit}>
      <section className="tower-form-section">
        <div className="tower-form-section-title">① 连接信息</div>
        <label>
          名称
          <input value={form.name} onChange={(event) => onChange({ ...form, name: event.target.value })} required />
        </label>
        <label>
          地址
          <input value={form.base_url} onChange={(event) => onChange({ ...form, base_url: event.target.value })} placeholder="https://tower.example.com" required />
        </label>
        <label>
          用户名
          <input value={form.username} onChange={(event) => onChange({ ...form, username: event.target.value })} />
        </label>
        <label>
          密码
          <input type="password" value={form.password} onChange={(event) => onChange({ ...form, password: event.target.value })} placeholder={isEdit ? "留空则不修改" : undefined} />
        </label>
        <label>
          API Token (可选)
          <input value={form.api_token} onChange={(event) => onChange({ ...form, api_token: event.target.value })} placeholder={isEdit ? "留空则不修改" : undefined} />
        </label>
        <div className="tower-form-checks">
          <label className="checkbox-line">
            <input type="checkbox" checked={form.verify_tls} onChange={(event) => onChange({ ...form, verify_tls: event.target.checked })} />
            校验 TLS 证书
          </label>
          <label className="checkbox-line">
            <input type="checkbox" checked={form.enabled} onChange={(event) => onChange({ ...form, enabled: event.target.checked })} />
            启用采集
          </label>
        </div>
        {onTestConnection && (
          <>
            <button className="secondary-button" type="button" disabled={testing} onClick={onTestConnection}>
              {testing ? "测试中…" : "测试连接"}
            </button>
            {testResult && <div className={`inline-message ${testResult.startsWith("✓") ? "test-ok" : "test-fail"}`}>{testResult}</div>}
          </>
        )}
      </section>
      <section className="tower-form-section">
        <div className="tower-form-section-title">② 采集计划</div>
        <ScheduleModeFields form={form} onChange={onChange} />
        <RetryFields form={form} onChange={onChange} />
      </section>
      {isEdit && tower && (
        <section className="tower-form-section">
          <div className="tower-form-section-title cluster-section-head">
            <span>③ 集群 ({tower.clusters.length})</span>
            {!!tower.clusters.length && (
              <label className="checkbox-line cluster-select-all">
                <input
                  type="checkbox"
                  checked={tower.clusters.every((cluster) => cluster.enabled)}
                  onChange={(event) => onSelectAllClusters?.(tower, event.target.checked)}
                />
                全选
              </label>
            )}
          </div>
          {!!tower.clusters.length ? (
            <div className="cluster-toggle-list">
              {tower.clusters.map((cluster) => (
                <label className="cluster-toggle" key={cluster.cluster_id}>
                  <input
                    type="checkbox"
                    checked={cluster.enabled}
                    onChange={(event) => onToggleCluster?.(tower.id, cluster.cluster_id, event.target.checked)}
                  />
                  <span>{cluster.name}</span>
                </label>
              ))}
            </div>
          ) : (
            <div className="form-hint">暂无集群，可在连接成功后同步。</div>
          )}
        </section>
      )}
      {message && <div className="inline-message">{message}</div>}
      <div className={isEdit ? "tower-edit-actions" : undefined}>
        {isEdit && onCancel && (
          <button className="secondary-button" type="button" onClick={onCancel}>
            <X size={15} />
            取消
          </button>
        )}
        <button className={isEdit ? "primary-button compact" : "primary-button"} type="submit">
          {isEdit ? <Save size={15} /> : <Plus size={16} />}
          {isEdit ? "保存" : "创建"}
        </button>
      </div>
    </form>
  );
}

const SCHEDULE_MODES: Array<{ value: "daily" | "interval"; label: string }> = [
  { value: "daily", label: "每日定时" },
  { value: "interval", label: "按间隔" }
];

function ScheduleModeFields({ form, onChange }: { form: TowerFormState; onChange: (next: TowerFormState) => void }) {
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

function RetryFields({ form, onChange }: { form: TowerFormState; onChange: (next: TowerFormState) => void }) {
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

export function normalizeTowerCreatePayload(payload: TowerFormState) {
  return {
    ...payload,
    name: payload.name.trim(),
    base_url: payload.base_url.trim(),
    username: cleanOptional(payload.username),
    password: cleanOptional(payload.password),
    api_token: cleanOptional(payload.api_token)
  };
}

export function normalizeTowerUpdatePayload(payload: TowerFormState) {
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

function cleanOptional(value: string): string | null {
  const trimmed = value.trim();
  return trimmed ? trimmed : null;
}
