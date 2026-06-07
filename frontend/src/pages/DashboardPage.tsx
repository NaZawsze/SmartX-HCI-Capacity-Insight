import { AlertTriangle, ArrowUpRight, Check, CircleCheck, HardDrive, MonitorCog, RefreshCw, Server, TrendingUp } from "lucide-react";
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
  onOpenRiskReport?: (scope: DashboardScope) => void;
}

export function DashboardPage({ summary, scope, onSummary, onSelectVm, onOpenRiskReport }: DashboardPageProps) {
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
  const topVms = sortMetricGrowthItems(summary?.day_fastest_growing_vms || summary?.top_vms || [], growthSort);
  const dayNewVms = summary?.day_new_vms || [];
  const risk = capacityRisk(summary?.capacity_risk, kpis?.used_ratio);
  const riskReportScope = reportScopeForRisk(summary?.capacity_risk);
  const clusterCapacityItems = clusterCapacityRows(summary?.clusters || []);

  function openRiskReport() {
    onOpenRiskReport?.(riskReportScope);
  }

  function openClusterReport(item: MetricItem) {
    const reportScope = reportScopeForCluster(item);
    if (reportScope) onOpenRiskReport?.(reportScope);
  }

  return (
    <div className="dashboard-grid">
      <div className="metrics-row dashboard-metrics-row">
        <button className={`metric-card capacity-risk-mini ${risk.tone} clickable-risk-card`} type="button" onClick={openRiskReport} title="查看容量风险报表">
          <div className="capacity-risk-mini-icon">
            {risk.tone === "normal" ? <Check size={28} strokeWidth={3} /> : <AlertTriangle size={28} strokeWidth={2.6} />}
          </div>
          <strong>{risk.title}</strong>
        </button>
        <MetricCard label="Tower" value={`${kpis?.tower_count ?? 0}`} hint="已纳管" icon={MonitorCog} />
        <MetricCard label="集群" value={`${kpis?.cluster_count ?? 0}`} hint="启用采集" icon={HardDrive} tone="green" />
        <MetricCard label="虚拟机" value={`${kpis?.vm_count ?? 0}`} hint="最近样本" icon={Server} />
        <MetricCard label="容量使用率" value={`${((kpis?.used_ratio ?? 0) * 100).toFixed(2)}%`} hint={formatBytes(kpis?.used_bytes)} icon={TrendingUp} tone="orange" />
      </div>

      <Card title="SmartX ZBS" subtitle={scopeLabel} className="wide-card">
        <StorageBar used={kpis?.used_bytes ?? 0} total={kpis?.total_bytes ?? 0} />
        <div className="cluster-capacity-section">
          <div className="cluster-capacity-head">
            <strong>集群容量明细</strong>
            <span>{clusterCapacityItems.length ? `${clusterCapacityItems.length} 个集群` : "暂无集群容量数据"}</span>
          </div>
          <div className="cluster-capacity-list auto-scrollbar">
            {clusterCapacityItems.length ? (
              clusterCapacityItems.map((item) => (
                <ClusterCapacityRow item={item} key={`${item.metric.tower_id || "tower"}-${item.metric.cluster_id || item.metric.cluster || "cluster"}`} onOpen={openClusterReport} />
              ))
            ) : (
              <div className="cluster-capacity-empty">暂无集群容量数据</div>
            )}
          </div>
        </div>
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
        subtitle={`${kpis?.vm_count ?? 0} 台中 ${topVms.length || 0} 台增长`}
        action={<GrowthSortTabs value={growthSort} onChange={setGrowthSort} />}
      >
        <div className="list-table growth-scroll auto-scrollbar">
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

      <Card title="本日新建 VM" subtitle={`${dayNewVms.length} 台新建`}>
        <div className="list-table growth-scroll auto-scrollbar">
          {dayNewVms.length ? (
            dayNewVms.slice(0, 20).map((item) => (
              <button
                className="table-row clickable"
                key={`${item.metric.tower_id}-${item.metric.cluster_id}-${item.metric.vm_id}`}
                type="button"
                onClick={() => onSelectVm(item.metric.vm_id, item.metric.vm || item.metric.vm_id)}
              >
                <span>{item.metric.vm || item.metric.vm_id}</span>
                <strong>{formatBytes(item.value)}</strong>
              </button>
            ))
          ) : (
            <div className="empty-state">暂无本日新建 VM</div>
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
        <button className={`risk-summary clickable-risk-summary ${risk.tone}`} type="button" onClick={openRiskReport}>
          {risk.tone === "normal" ? <CircleCheck size={38} /> : <AlertTriangle size={38} />}
          <strong>{risk.title}</strong>
          <span>{risk.description}</span>
        </button>
      </Card>
    </div>
  );
}

type GrowthSortMode = "amount" | "ratio";

function ClusterCapacityRow({ item, onOpen }: { item: MetricItem; onOpen: (item: MetricItem) => void }) {
  const total = item.total_bytes ?? 0;
  const used = item.value ?? 0;
  const ratio = total > 0 ? Math.min(Math.max(used / total, 0), 1) : 0;
  const tone = clusterCapacityTone(ratio, total);
  const reportScope = reportScopeForCluster(item);
  const content = (
    <>
      <div className="cluster-capacity-main">
        <strong>{item.metric.cluster || item.metric.cluster_id || "未知集群"}</strong>
        <span>{total > 0 ? `${(ratio * 100).toFixed(2)}%` : "数据不足"}</span>
      </div>
      <div className="cluster-capacity-progress">
        <div className="cluster-capacity-progress-fill" style={{ width: `${ratio * 100}%` }} />
      </div>
      <div className="cluster-capacity-meta">
        <span>已使用 {formatBytes(used)}</span>
        <span>{total > 0 ? `总容量 ${formatBytes(total)}` : "总容量 数据不足"}</span>
      </div>
    </>
  );
  if (!reportScope) {
    return <div className={`cluster-capacity-row ${tone}`}>{content}</div>;
  }
  return (
    <button className={`cluster-capacity-row ${tone}`} type="button" onClick={() => onOpen(item)}>
      {content}
    </button>
  );
}

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

function clusterCapacityRows(items: MetricItem[]): MetricItem[] {
  return [...items].sort((left, right) => clusterUsageRatio(right) - clusterUsageRatio(left));
}

function clusterUsageRatio(item: MetricItem): number {
  const total = item.total_bytes ?? 0;
  if (total <= 0) return 0;
  return (item.value ?? 0) / total;
}

function clusterCapacityTone(ratio: number, total: number): "normal" | "warning" | "danger" | "unknown" {
  if (total <= 0) return "unknown";
  if (ratio >= 0.8) return "danger";
  if (ratio >= 0.75) return "warning";
  return "normal";
}

function reportScopeForCluster(item: MetricItem): DashboardScope | undefined {
  const towerId = Number(item.metric.tower_id);
  const clusterId = item.metric.cluster_id ? String(item.metric.cluster_id) : "";
  if (!Number.isFinite(towerId) || !clusterId) return undefined;
  return { type: "cluster", towerId, clusterId };
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

function capacityRisk(
  clusterRisk?: DashboardSummary["capacity_risk"],
  usedRatio?: number | null
): { tone: "normal" | "warning" | "danger"; title: string; description: string } {
  if (clusterRisk) {
    const tone = clusterRisk.level === "high" ? "danger" : clusterRisk.level;
    return {
      tone,
      title: clusterRisk.title,
      description: clusterRisk.description || clusterRisk.message || "当前所有集群暂无明显容量风险"
    };
  }
  if (usedRatio == null || !Number.isFinite(usedRatio)) {
    return { tone: "normal", title: "暂无容量风险", description: "等待采集完成后显示容量风险。" };
  }
  const percent = `${(usedRatio * 100).toFixed(2)}%`;
  if (usedRatio >= 0.8) {
    return { tone: "danger", title: "容量高风险", description: `当前已使用 ${percent}，建议尽快确认扩容或清理计划。` };
  }
  if (usedRatio >= 0.75) {
    return { tone: "warning", title: "容量需关注", description: `当前已使用 ${percent}，建议关注增长趋势和重点 VM。` };
  }
  return { tone: "normal", title: "容量风险正常", description: `当前已使用 ${percent}，暂无明显容量风险。` };
}

function reportScopeForRisk(clusterRisk?: DashboardSummary["capacity_risk"]): DashboardScope {
  const target = clusterRisk?.top_clusters?.[0];
  const towerId = Number(target?.tower_id);
  const clusterId = target?.cluster_id ? String(target.cluster_id) : "";
  if (Number.isFinite(towerId) && clusterId) {
    return { type: "cluster", towerId, clusterId };
  }
  return { type: "all" };
}
