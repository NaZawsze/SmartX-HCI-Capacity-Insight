import { AlertCircle, ArrowUpRight, Database, HardDrive, RefreshCw, Server, TrendingUp } from "lucide-react";
import { useEffect, useState } from "react";
import { Card } from "../components/Card";
import { MetricCard } from "../components/MetricCard";
import { StatusPill } from "../components/StatusPill";
import { StorageBar } from "../components/StorageBar";
import { api, formatBytes } from "../services/api";
import type { DashboardScope, DashboardSummary, MetricItem } from "../types";

interface DashboardPageProps {
  summary: DashboardSummary | null;
  scope: DashboardScope;
  onSummary: (summary: DashboardSummary) => void;
  onSelectVm: (vmId: string, vmName?: string) => void;
}

export function DashboardPage({ summary, scope, onSummary, onSelectVm }: DashboardPageProps) {
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("");
  const [growthSort, setGrowthSort] = useState<GrowthSortMode>("amount");

  useEffect(() => {
    api.summary(scope).then(onSummary).catch(() => undefined);
  }, [onSummary, scope]);

  useEffect(() => {
    if (summary?.latest_run?.status !== "running") {
      return;
    }
    const timer = window.setInterval(() => {
      api.summary(scope).then(onSummary).catch(() => undefined);
    }, 5000);
    return () => window.clearInterval(timer);
  }, [onSummary, scope, summary?.latest_run?.status]);

  async function runCollection() {
    setLoading(true);
    setMessage("");
    try {
      const result = await api.runCollection();
      setMessage(result.message);
      onSummary(await api.summary(scope));
    } catch (exc) {
      setMessage(exc instanceof Error ? exc.message : "采集失败");
    } finally {
      setLoading(false);
    }
  }

  const kpis = summary?.kpis;
  const isRunning = summary?.latest_run?.status === "running";
  const runMessage = isRunning ? "采集正在执行，完成后会自动更新。" : summary?.latest_run?.message || "暂无采集记录";
  const scopeLabel = summary?.scope?.label || "全部数据中心";
  const towerLabel =
    scope.type === "all"
      ? "全部 Tower"
      : scope.type === "tower"
        ? summary?.towers.find((tower) => tower.id === scope.towerId)?.name || summary?.scope?.label || "当前 Tower"
        : summary?.towers.find((tower) => tower.id === scope.towerId)?.name || summary?.scope?.label || "当前 Tower";
  const topVms = sortMetricGrowthItems(summary?.top_vms || [], growthSort);

  return (
    <div className="dashboard-grid">
      <div className="metrics-row">
        <MetricCard label="Tower" value={`${kpis?.tower_count ?? 0}`} hint="已纳管" icon={Database} />
        <MetricCard label="集群" value={`${kpis?.cluster_count ?? 0}`} hint="启用采集" icon={HardDrive} tone="green" />
        <MetricCard label="虚拟机" value={`${kpis?.vm_count ?? 0}`} hint="最近样本" icon={Server} />
        <MetricCard label="容量使用率" value={`${((kpis?.used_ratio ?? 0) * 100).toFixed(2)}%`} hint={formatBytes(kpis?.used_bytes)} icon={TrendingUp} tone="orange" />
      </div>

      <Card title="SmartX ZBS" subtitle={scopeLabel} className="wide-card">
        <StorageBar used={kpis?.used_bytes ?? 0} total={kpis?.total_bytes ?? 0} />
      </Card>

      <Card
        title="采集状态"
        subtitle={scope.type === "all" ? "按 Tower 展示" : towerLabel}
        action={
          <button className="primary-button compact" type="button" onClick={runCollection} disabled={loading || isRunning}>
            <RefreshCw size={15} />
            {loading || isRunning ? "采集中" : "立即采集"}
          </button>
        }
      >
        <div className="tower-run-list">
          {(summary?.tower_runs?.length ? summary.tower_runs : []).map((item) => (
            <div className="run-state tower-run-row" key={item.tower_id}>
              <span className="tower-run-name">{item.tower_name}</span>
              <StatusPill status={item.status} />
              <span>{item.message || runMessage}</span>
            </div>
          ))}
          {!summary?.tower_runs?.length && (
            <div className="run-state">
              <StatusPill status={summary?.latest_run?.status} />
              <span>{runMessage}</span>
            </div>
          )}
        </div>
        {message && <div className="inline-message">{message}</div>}
      </Card>

      <Card
        title="日增长最快 VM"
        action={<GrowthSortTabs value={growthSort} onChange={setGrowthSort} />}
      >
        <div className="list-table growth-scroll">
          {topVms.length ? (
            topVms.map((item) => (
              <button
                className="table-row clickable"
                key={`${item.metric.vm_id}-${item.value}`}
                type="button"
                onClick={() => onSelectVm(item.metric.vm_id, item.metric.vm || item.metric.vm_id)}
              >
                <span>{item.metric.vm || item.metric.vm_id}</span>
                <strong className="growth-strong">
                  <ArrowUpRight size={14} />
                  {formatGrowthValue(item, growthSort, "天")}
                </strong>
              </button>
            ))
          ) : (
            <div className="empty-state">暂无增长数据</div>
          )}
        </div>
      </Card>

      <Card title={scope.type === "cluster" ? "当前集群容量" : "集群容量"} subtitle={scopeLabel}>
        <div className="list-table">
          {summary?.clusters?.length ? (
            summary.clusters.map((item) => (
              <div className="table-row" key={`${item.metric.cluster_id}-${item.value}`}>
                <span>{item.metric.cluster || item.metric.cluster_id}</span>
                <strong>{formatBytes(item.value)}</strong>
              </div>
            ))
          ) : (
            <div className="empty-state">暂无集群指标</div>
          )}
        </div>
      </Card>

      <Card title="风险提示">
        <div className="risk-empty">
          <AlertCircle size={38} />
          <span>报表生成后显示容量风险</span>
        </div>
      </Card>
    </div>
  );
}

type GrowthSortMode = "amount" | "ratio";

function GrowthSortTabs({ value, onChange }: { value: GrowthSortMode; onChange: (value: GrowthSortMode) => void }) {
  return (
    <div className="sort-tabs compact-tabs" aria-label="增长排序">
      <button type="button" className={value === "amount" ? "active" : ""} onClick={() => onChange("amount")}>
        增长量
      </button>
      <button type="button" className={value === "ratio" ? "active" : ""} onClick={() => onChange("ratio")}>
        增长率
      </button>
    </div>
  );
}

function sortMetricGrowthItems(items: MetricItem[], mode: GrowthSortMode): MetricItem[] {
  return [...items].sort((left, right) => growthSortValue(right, mode) - growthSortValue(left, mode));
}

function growthSortValue(item: MetricItem, mode: GrowthSortMode): number {
  if (mode === "ratio") return item.growth_ratio ?? 0;
  return item.growth_amount ?? item.value ?? 0;
}

function formatGrowthValue(item: MetricItem, mode: GrowthSortMode, unit: string): string {
  if (mode === "ratio") return formatPercent(item.growth_ratio);
  return `${formatBytes(item.growth_amount ?? item.value)}/${unit}`;
}

function formatPercent(value?: number | null): string {
  if (value == null || !Number.isFinite(value)) return "-";
  return `${(value * 100).toFixed(value >= 1 ? 0 : 1)}%`;
}
