import { ArrowDown, ArrowDownWideNarrow, ArrowUp, Building2, HardDrive, Search, Server, TrendingUp } from "lucide-react";
import type { ReactNode } from "react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Card } from "../components/Card";
import { MetricCard } from "../components/MetricCard";
import { Pager } from "../components/Pager";
import { TrendChart } from "../components/TrendChart";
import { api, formatBytes } from "../services/api";
import type { DashboardScope, DashboardSummary, MetricItem, VmDetail, VmTrend, VmUsageSummaryItem, VmVolume, VmVolumeRow } from "../types";

const trendRanges = [7, 14, 30, 90, 180] as const;
type TrendRange = (typeof trendRanges)[number];
type SortMode = "size" | "usage";
type VolumeSortField = "vm" | "used" | "occupied";
type SortDirection = "asc" | "desc";
type ClusterScope = Extract<DashboardScope, { type: "cluster" }>;

const VM_PAGE_SIZE = 100;
const VOLUME_PAGE_SIZE = 200;

interface VmsPageProps {
  refreshKey?: number;
  scope: DashboardScope;
  summary?: DashboardSummary | null;
  selectedVmId?: string;
  selectedVmName?: string;
  onSelectedVmChange?: (vmId: string) => void;
}

export function VmsPage({ refreshKey = 0, scope, summary, selectedVmId = "", selectedVmName = "", onSelectedVmChange }: VmsPageProps) {
  const [items, setItems] = useState<MetricItem[]>([]);
  const [selectedVm, setSelectedVm] = useState("");
  const [localScope, setLocalScope] = useState<DashboardScope | null>(null);
  const [query, setQuery] = useState("");
  const [trendDays, setTrendDays] = useState<TrendRange>(30);
  const [sortMode, setSortMode] = useState<SortMode>("size");
  const [trend, setTrend] = useState<VmTrend | null>(null);
  const [detail, setDetail] = useState<VmDetail | null>(null);
  const [currentVmVolumes, setCurrentVmVolumes] = useState<VmVolume[]>([]);
  const [vmPage, setVmPage] = useState(1);
  const [volumeRows, setVolumeRows] = useState<VmVolumeRow[]>([]);
  const [volumeTotal, setVolumeTotal] = useState(0);
  const [volumePage, setVolumePage] = useState(1);
  const [usageSummary, setUsageSummary] = useState<Map<string, VmUsageSummaryItem>>(new Map());
  const [volumeSort, setVolumeSort] = useState<{ field: VolumeSortField; direction: SortDirection }>({ field: "used", direction: "desc" });
  const searchInputRef = useRef<HTMLInputElement | null>(null);
  const selectedItemRef = useRef<HTMLButtonElement | null>(null);
  const lastOpenedVmNameRef = useRef("");
  const selectedVmIdRef = useRef(selectedVmId);
  const lastVmRequestKeyRef = useRef("");
  const effectiveScope = localScope ?? scope;
  const effectiveScopeKey = scopeKey(effectiveScope);
  const towerOptions = useMemo(() => vmTowerOptions(summary), [summary]);
  const clusterOptions = useMemo(() => vmClusterOptions(summary, effectiveScope), [effectiveScope, summary]);

  useEffect(() => {
    selectedVmIdRef.current = selectedVmId;
  }, [selectedVmId]);

  useEffect(() => {
    api.vms(effectiveScope).then((result) => {
      setItems(result);
      setVmPage(1);
      setSelectedVm((current) => {
        const externalSelectedVmId = selectedVmIdRef.current;
        if (externalSelectedVmId && result.some((item) => item.metric.vm_id === externalSelectedVmId)) return externalSelectedVmId;
        if (current && result.some((item) => item.metric.vm_id === current)) return current;
        return result[0]?.metric.vm_id || "";
      });
    });
  }, [effectiveScopeKey, refreshKey]);

  useEffect(() => {
    if (!selectedVm) {
      setTrend(null);
      setDetail(null);
      setCurrentVmVolumes([]);
      return;
    }
    const selectedItem = items.find((item) => item.metric.vm_id === selectedVm);
    const requestScope: ClusterScope | undefined = selectedItem
      ? scopeForVm(selectedItem) ?? clusterScopeOrUndefined(effectiveScope)
      : clusterScopeOrUndefined(effectiveScope);
    if (!requestScope) {
      setTrend(null);
      setDetail(null);
      setCurrentVmVolumes([]);
      return;
    }
    const requestKey = `${requestScope.towerId}-${requestScope.clusterId}-${selectedVm}-${trendDays}-${refreshKey}`;
    if (lastVmRequestKeyRef.current === requestKey) {
      return;
    }
    lastVmRequestKeyRef.current = requestKey;
    api.vmTrend(selectedVm, "used", trendDays, requestScope).then(setTrend).catch(() => setTrend(null));
    api.vmDetail(selectedVm, requestScope).then(setDetail).catch(() => setDetail(null));
    api.vmVolumes(selectedVm, requestScope).then((result) => setCurrentVmVolumes(result.volumes || [])).catch(() => setCurrentVmVolumes([]));
  }, [effectiveScopeKey, items, refreshKey, selectedVm, trendDays]);

  useEffect(() => {
    let cancelled = false;
    api
      .vmVolumesPage(effectiveScope, {
        page: volumePage,
        pageSize: VOLUME_PAGE_SIZE,
        sort: volumeSort.field,
        order: volumeSort.direction
      })
      .then((result) => {
        if (cancelled) return;
        setVolumeRows(result.volumes || []);
        setVolumeTotal(result.total || 0);
      })
      .catch(() => {
        if (cancelled) return;
        setVolumeRows([]);
        setVolumeTotal(0);
      });
    return () => {
      cancelled = true;
    };
  }, [effectiveScopeKey, refreshKey, volumePage, volumeSort]);

  useEffect(() => {
    api
      .vmVolumesUsageSummary(effectiveScope)
      .then((usages) => {
        setUsageSummary(new Map(usages.map((item) => [usageKey(item.tower_id, item.cluster_id, item.vm_id), item])));
      })
      .catch(() => setUsageSummary(new Map()));
  }, [effectiveScopeKey, refreshKey]);

  useEffect(() => {
    setLocalScope(null);
  }, [scope]);

  useEffect(() => {
    if (selectedVmName) {
      if (lastOpenedVmNameRef.current !== selectedVmName) {
        lastOpenedVmNameRef.current = selectedVmName;
        setQuery(selectedVmName);
      }
    }
  }, [selectedVmName]);

  useEffect(() => {
    if (selectedVmId) {
      setSelectedVm(selectedVmId);
    }
  }, [selectedVmId]);

  useEffect(() => {
    if (selectedVm) {
      onSelectedVmChange?.(selectedVm);
    }
  }, [onSelectedVmChange, selectedVm]);

  useEffect(() => {
    if (!selectedVm) return;
    window.requestAnimationFrame(() => {
      searchInputRef.current?.focus();
      selectedItemRef.current?.scrollIntoView({ block: "center", behavior: "smooth" });
    });
  }, [selectedVmId, selectedVmName]);

  const filtered = useMemo(() => {
    const term = query.trim().toLowerCase();
    const sorted = [...items].sort((left, right) => {
      if (sortMode === "usage") {
        return getVmUsageRatio(right, usageSummary) - getVmUsageRatio(left, usageSummary);
      }
      return (right.value ?? 0) - (left.value ?? 0);
    });
    if (!term) return sorted;
    return sorted.filter((item) => `${item.metric.vm} ${item.metric.cluster}`.toLowerCase().includes(term));
  }, [items, query, sortMode, usageSummary]);

  const pagedVms = useMemo(() => filtered.slice((vmPage - 1) * VM_PAGE_SIZE, vmPage * VM_PAGE_SIZE), [filtered, vmPage]);
  const current = filtered.find((item) => item.metric.vm_id === selectedVm) ?? items.find((item) => item.metric.vm_id === selectedVm);
  const selectedItemVisible = filtered.some((item) => item.metric.vm_id === selectedVm);

  useEffect(() => {
    if (!selectedVmId) return;
    const index = filtered.findIndex((item) => item.metric.vm_id === selectedVmId);
    if (index < 0) return;
    const targetPage = Math.floor(index / VM_PAGE_SIZE) + 1;
    setVmPage((currentPage) => (currentPage === targetPage ? currentPage : targetPage));
  }, [filtered, selectedVmId]);

  const towerSelectValue = towerValue(effectiveScope);
  const clusterSelectValue = scopeValue(effectiveScope);
  const allVolumesTitle = effectiveScope.type === "cluster" ? "当前集群虚拟卷" : "所有虚拟卷";
  const allVolumesSubtitle = effectiveScope.type === "cluster" ? "当前集群内全部虚拟机卷" : "当前范围内全部虚拟机卷";

  function selectVmFromVolume(volume: VmVolumeRow) {
    const vmId = String(volume.vm_id || "");
    if (!vmId) return;
    setSelectedVm(vmId);
    setQuery("");
  }

  function changeQuery(value: string) {
    setQuery(value);
    setVmPage(1);
  }

  function changeSortMode(mode: SortMode) {
    setSortMode(mode);
    setVmPage(1);
  }

  function changeVolumeSort(field: VolumeSortField) {
    setVolumeSort((currentSort) => ({
      field,
      direction: currentSort.field === field ? (currentSort.direction === "desc" ? "asc" : "desc") : field === "vm" ? "asc" : "desc",
    }));
    setVolumePage(1);
  }

  function changeTowerScope(value: string) {
    setSelectedVm("");
    setQuery("");
    setVmPage(1);
    setVolumePage(1);
    if (value === "all") {
      setLocalScope(null);
      return;
    }
    const towerId = Number(value);
    setLocalScope({ type: "tower", towerId });
  }

  function changeClusterScope(value: string) {
    setSelectedVm("");
    setQuery("");
    setVmPage(1);
    setVolumePage(1);
    if (value === "all") {
      if (effectiveScope.type === "tower" || effectiveScope.type === "cluster") {
        setLocalScope({ type: "tower", towerId: effectiveScope.towerId });
        return;
      }
      setLocalScope(null);
      return;
    }
    setLocalScope(scopeFromValue(value));
  }

  return (
    <div className="vm-page-grid">
      <div className="vm-summary-grid" aria-label="虚拟机页筛选与概览">
        <label className="metric-card vm-filter-card">
          <span className="metric-icon"><Building2 size={19} aria-label="Tower图标" /></span>
          <div className="vm-filter-copy">
            <span className="metric-label">Tower</span>
            <select aria-label="虚拟机页Tower" value={towerSelectValue} onChange={(event) => changeTowerScope(event.target.value)}>
              <option value="all">全部 Tower</option>
              {towerOptions.map((option) => (
                <option value={option.value} key={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </div>
        </label>
        <label className="metric-card vm-filter-card green">
          <span className="metric-icon"><HardDrive size={19} aria-label="集群图标" /></span>
          <div className="vm-filter-copy">
            <span className="metric-label">集群</span>
            <select aria-label="虚拟机页集群" value={clusterSelectValue} onChange={(event) => changeClusterScope(event.target.value)}>
            <option value="all">全部集群</option>
            {clusterOptions.map((option) => (
              <option value={option.value} key={option.value}>
                {option.label}
              </option>
            ))}
            </select>
          </div>
        </label>
        <MetricCard label="虚拟机" value={`${summary?.kpis.vm_count ?? items.length}`} hint="最近样本" icon={Server} />
        <MetricCard label="容量使用率" value={`${((summary?.kpis.used_ratio ?? 0) * 100).toFixed(2)}%`} hint={formatBytes(summary?.kpis.used_bytes)} icon={TrendingUp} tone="orange" />
      </div>

      <Card title="虚拟机" className="vm-list-card">
        <div className="vm-toolbar">
          <div className="sort-tabs" aria-label="虚拟机排序">
            <button type="button" className={sortMode === "size" ? "active" : ""} onClick={() => changeSortMode("size")}>
              <ArrowDownWideNarrow size={14} />
              容量
            </button>
            <button type="button" className={sortMode === "usage" ? "active" : ""} onClick={() => changeSortMode("usage")}>
              <ArrowDownWideNarrow size={14} />
              使用率
            </button>
          </div>
          <label className="mini-search">
            <Search size={15} />
            <input ref={searchInputRef} value={query} onChange={(event) => changeQuery(event.target.value)} placeholder="搜索 VM" />
          </label>
        </div>
        <div className="vm-list" aria-label="虚拟机列表">
          {pagedVms.map((item) => {
            const usage = getVmUsageRatio(item, usageSummary);
            return (
              <button
                type="button"
                key={item.metric.vm_id}
                ref={item.metric.vm_id === selectedVm && selectedItemVisible ? selectedItemRef : undefined}
                className={item.metric.vm_id === selectedVm ? "vm-item active" : "vm-item"}
                onClick={() => setSelectedVm(item.metric.vm_id)}
              >
                <span>{item.metric.vm || item.metric.vm_id}</span>
                <small className="vm-cluster">{item.metric.cluster}</small>
                <strong>{formatBytes(item.value)}</strong>
                <small className={usage >= 0.8 ? "vm-usage over-limit" : "vm-usage"}>{formatUsageLabel(item, usageSummary)}</small>
              </button>
            );
          })}
          {!filtered.length && <div className="empty-state">暂无 VM 数据</div>}
        </div>
        <Pager page={vmPage} pageSize={VM_PAGE_SIZE} total={filtered.length} onPageChange={setVmPage} label="虚拟机列表分页" unit="台" />
      </Card>

      <Card
        title={current?.metric.vm || "容量趋势"}
        className="trend-card"
        action={
          <div className="range-tabs" aria-label="趋势时间范围">
            {trendRanges.map((days) => (
              <button key={days} type="button" className={trendDays === days ? "active" : ""} onClick={() => setTrendDays(days)}>
                {days}天
              </button>
            ))}
          </div>
        }
      >
        <div className="trend-meta">
          <span>{current?.metric.cluster || "全部集群"}</span>
          <span className="trend-value-group">
            <strong>{formatBytes(detail?.used_bytes ?? current?.value)}</strong>
            {trend?.data_freshness && trend.data_freshness !== "fresh" && <small className="freshness-badge stale">非最新</small>}
          </span>
        </div>
        {trend?.data_freshness && trend.data_freshness !== "fresh" && (
          <div className="trend-freshness-warning">
            当前集群最近一次成功采集：{trend.latest_success_at || "暂无成功记录"}；存在缺采，趋势图可能不连续
            {trend.gap_dates?.length ? `。缺采日期：${trend.gap_dates.join("、")}` : ""}
          </div>
        )}
        <TrendChart points={trend?.points || []} referenceValue={current?.value} height={360} gapDates={trend?.gap_dates || []} />
      </Card>

      <Card title="当前虚拟机明细" subtitle={detail?.vm_name || current?.metric.vm || "未选择虚拟机"} className="current-volume-card">
        <VolumeTable>
          {currentVmVolumes.length ? currentVmVolumes.map(renderVolumeRow) : <div className="empty-state">暂无当前虚拟机卷数据</div>}
        </VolumeTable>
      </Card>

      <Card title={allVolumesTitle} subtitle={allVolumesSubtitle} className="volume-card all-volume-card">
        <VolumeTable variant="all" sort={volumeSort} onSort={changeVolumeSort} footer={<Pager page={volumePage} pageSize={VOLUME_PAGE_SIZE} total={volumeTotal} onPageChange={setVolumePage} label="所有虚拟卷分页" unit="个卷" />}>
          <div aria-label={allVolumesTitle}>
            {volumeRows.length ? volumeRows.map((volume, index) => renderAllVolumeRow(volume, index, selectVmFromVolume)) : <div className="empty-state">暂无虚拟卷数据</div>}
          </div>
        </VolumeTable>
      </Card>
    </div>
  );
}

function VolumeTable({ children, variant = "current", sort, onSort, footer }: { children: ReactNode; variant?: "current" | "all"; sort?: { field: VolumeSortField; direction: SortDirection }; onSort?: (field: VolumeSortField) => void; footer?: ReactNode }) {
  return (
    <div className={variant === "all" ? "volume-table volume-table-all" : "volume-table"}>
      <div className="volume-table-head">
        {variant === "all" && <SortableVolumeHeader field="vm" label="VM" sort={sort} onSort={onSort} />}
        {variant === "all" && <span>集群</span>}
        <span>虚拟卷名称</span>
        <SortableVolumeHeader field="used" label="实际使用空间" sort={sort} onSort={onSort} />
        <span>分配空间</span>
        <span>副本机制</span>
        <SortableVolumeHeader field="occupied" label="实际占用集群空间" sort={sort} onSort={onSort} />
      </div>
      <div className="volume-table-body auto-scrollbar">{children}</div>
      {footer}
    </div>
  );
}

function SortableVolumeHeader({ field, label, sort, onSort }: { field: VolumeSortField; label: string; sort?: { field: VolumeSortField; direction: SortDirection }; onSort?: (field: VolumeSortField) => void }) {
  if (!onSort || !sort) return <span>{label}</span>;
  const active = sort.field === field;
  const direction = active ? sort.direction : "desc";
  const nextDirection = active ? (direction === "desc" ? "asc" : "desc") : field === "vm" ? "asc" : "desc";
  return (
    <button
      type="button"
      className={active ? "volume-sort-button active" : "volume-sort-button"}
      onClick={() => onSort(field)}
      aria-label={`按${label}${nextDirection === "asc" ? "升序" : "降序"}排序`}
    >
      {label}
      {active && direction === "asc" ? <ArrowUp size={13} /> : <ArrowDown size={13} />}
    </button>
  );
}

function renderVolumeRow(volume: VmVolume, index?: number) {
  const key = volume.id || volume.volume_id || volume.name || volume.path || String(index ?? 0);
  const actualUsed = readSize(volume, ["used_bytes", "used_size", "used_size_bytes", "unique_logical_size", "guest_used_size", "guest_used_size_bytes"]);
  const provisioned = readSize(volume, ["provisioned_size", "provisioned_size_bytes", "size", "size_bytes", "capacity", "capacity_bytes"]);
  const actualOccupied = getOccupiedSize(volume, actualUsed);
  return (
    <div className="volume-table-row" key={key}>
      <span data-testid="volume-name" title={readVolumeName(volume)}>{readVolumeName(volume)}</span>
      <strong>{formatBytes(actualUsed)}</strong>
      <strong>{formatBytes(provisioned)}</strong>
      <span>{readVolumePolicy(volume) || "-"}</span>
      <strong>{formatBytes(actualOccupied)}</strong>
    </div>
  );
}

function renderAllVolumeRow(volume: VmVolumeRow, index?: number, onSelectVm?: (volume: VmVolumeRow) => void) {
  const key = `${volume.tower_id ?? ""}-${volume.cluster_id ?? ""}-${volume.vm_id ?? ""}-${volume.volume_id ?? volume.id ?? index}`;
  const actualUsed = readVolumeUsed(volume);
  const provisioned = readSize(volume, ["provisioned_size", "provisioned_size_bytes", "size", "size_bytes", "capacity", "capacity_bytes"]);
  const actualOccupied = getOccupiedSize(volume, actualUsed);
  const vmName = volume.vm_name || volume.vm_id || "-";
  return (
    <div className="volume-table-row" key={key}>
      {volume.vm_id && onSelectVm ? (
        <button className="volume-vm-link" type="button" title={vmName} onClick={() => onSelectVm(volume)}>
          {vmName}
        </button>
      ) : (
        <span title={vmName}>{vmName}</span>
      )}
      <span title={volume.cluster_name || volume.cluster_id || "-"}>{volume.cluster_name || volume.cluster_id || "-"}</span>
      <span data-testid="volume-name" title={readVolumeName(volume)}>{readVolumeName(volume)}</span>
      <strong>{formatBytes(actualUsed)}</strong>
      <strong>{formatBytes(provisioned)}</strong>
      <span>{readVolumePolicy(volume) || "-"}</span>
      <strong>{formatBytes(actualOccupied)}</strong>
    </div>
  );
}

function vmTowerOptions(summary?: DashboardSummary | null): Array<{ value: string; label: string }> {
  return (summary?.towers || [])
    .filter((tower) => tower.enabled)
    .map((tower) => ({ value: String(tower.id), label: tower.name }));
}

function vmClusterOptions(summary?: DashboardSummary | null, scope?: DashboardScope): Array<{ value: string; label: string }> {
  return (summary?.towers || [])
    .filter((tower) => scope?.type === "tower" || scope?.type === "cluster" ? tower.id === scope.towerId : true)
    .flatMap((tower) =>
      tower.clusters
        .filter((cluster) => cluster.enabled)
        .map((cluster) => ({
          value: `${tower.id}:${cluster.cluster_id}`,
          label: `${tower.name} / ${cluster.name || cluster.cluster_id}`,
        }))
    );
}

function towerValue(scope: DashboardScope): string {
  if (scope.type === "tower" || scope.type === "cluster") return String(scope.towerId);
  return "all";
}

function scopeValue(scope: DashboardScope): string {
  if (scope.type === "cluster") return `${scope.towerId}:${scope.clusterId}`;
  return "all";
}

function scopeFromValue(value: string): DashboardScope | null {
  if (value === "all") return null;
  const separator = value.indexOf(":");
  const towerId = Number(value.slice(0, separator));
  const clusterId = value.slice(separator + 1);
  if (!Number.isFinite(towerId) || !clusterId) return null;
  return { type: "cluster", towerId, clusterId };
}

function scopeKey(scope: DashboardScope): string {
  if (scope.type === "all") return "all";
  if (scope.type === "tower") return `tower-${scope.towerId}`;
  return `cluster-${scope.towerId}-${scope.clusterId}`;
}

function clusterScopeOrUndefined(scope: DashboardScope): ClusterScope | undefined {
  return scope.type === "cluster" ? scope : undefined;
}

function usageKey(towerId: unknown, clusterId: unknown, vmId: unknown): string {
  return `${String(towerId ?? "")}|${String(clusterId ?? "")}|${String(vmId ?? "")}`;
}

function getOccupiedSize(volume: VmVolume, actualUsed: number | null): number | null {
  const uniqueSize = readSize(volume, ["unique_size", "unique_size_bytes"]);
  if (uniqueSize !== null) return uniqueSize;
  if (actualUsed === null) return null;
  const replicaCount = numberish(
    volume.elf_storage_policy_replica_num ?? volume.replica_num ?? volume.replicaNum ?? volume.replica_count ?? volume.replicaCount
  );
  const thinProvision = Boolean(volume.elf_storage_policy_thin_provision ?? volume.thin_provision ?? volume.thinProvision);
  if (replicaCount && replicaCount > 0 && !thinProvision) return actualUsed * replicaCount;
  if (replicaCount && replicaCount > 0) return actualUsed * replicaCount;
  const ecData = numberish(volume.elf_storage_policy_ec_k ?? volume.ec_data ?? volume.ecData ?? volume.ec_k ?? volume.ecDataUnits);
  const ecParity = numberish(volume.elf_storage_policy_ec_m ?? volume.ec_parity ?? volume.ecParity ?? volume.ec_m ?? volume.ecParityUnits);
  if (ecData && ecParity) return actualUsed * ((ecData + ecParity) / ecData);
  return actualUsed;
}

function usageSummaryFor(item: MetricItem, usageSummary: Map<string, VmUsageSummaryItem>): VmUsageSummaryItem | undefined {
  return usageSummary.get(usageKey(item.metric.tower_id, item.metric.cluster_id, item.metric.vm_id));
}

function getVmUsageRatio(item: MetricItem, usageSummary: Map<string, VmUsageSummaryItem>): number {
  const entry = usageSummaryFor(item, usageSummary);
  if (entry && entry.provisioned_bytes > 0) return entry.used_bytes / entry.provisioned_bytes;
  const guest = item.guest_used ?? 0;
  const provisioned = item.provisioned ?? 0;
  if (guest > 0 && provisioned > 0) return item.guest_used_ratio ?? guest / provisioned;
  if (!item.provisioned || item.provisioned <= 0) return 0;
  return item.used_ratio ?? item.value / item.provisioned;
}

function formatRatio(item: MetricItem, usageSummary: Map<string, VmUsageSummaryItem>): string {
  const entry = usageSummaryFor(item, usageSummary);
  if (entry && entry.provisioned_bytes > 0) return `${((entry.used_bytes / entry.provisioned_bytes) * 100).toFixed(1)}%`;
  const guest = item.guest_used ?? 0;
  const provisioned = item.provisioned ?? 0;
  if (guest > 0 && provisioned > 0) {
    return `${((item.guest_used_ratio ?? guest / provisioned) * 100).toFixed(1)}%`;
  }
  if (!item.provisioned || item.provisioned <= 0) return "";
  const ratio = item.used_ratio ?? item.value / item.provisioned;
  return `${(ratio * 100).toFixed(1)}%`;
}

function formatUsageLabel(item: MetricItem, usageSummary: Map<string, VmUsageSummaryItem>): string {
  const ratio = formatRatio(item, usageSummary);
  return ratio ? `已使用 ${ratio}` : "";
}

function readVolumeUsed(volume: VmVolume): number | null {
  return readSize(volume, ["used_bytes", "used_size", "used_size_bytes", "unique_logical_size", "guest_used_size", "guest_used_size_bytes"]);
}

function scopeForVm(item: MetricItem): ClusterScope | undefined {
  const towerId = numberish(item.metric.tower_id);
  const clusterId = item.metric.cluster_id;
  if (!towerId || !clusterId) return undefined;
  return { type: "cluster", towerId, clusterId };
}

function readVolumeName(volume: VmVolume): string {
  return String(volume.name || volume.path || volume.id || "-");
}

function readSize(volume: VmVolume, keys: string[]): number | null {
  for (const key of keys) {
    const size = numberish(volume[key]);
    if (size !== null) return size;
  }
  return null;
}

function readVolumePolicy(volume: VmVolume): string {
  const ecData = numberish(volume.elf_storage_policy_ec_k ?? volume.ec_data ?? volume.ecData ?? volume.ec_k ?? volume.ecDataUnits);
  const ecParity = numberish(volume.elf_storage_policy_ec_m ?? volume.ec_parity ?? volume.ecParity ?? volume.ec_m ?? volume.ecParityUnits);
  if (ecData && ecParity) return `EC${ecData}+${ecParity}`;

  const replicaCount = numberish(
    volume.elf_storage_policy_replica_num ?? volume.replica_num ?? volume.replicaNum ?? volume.replica_count ?? volume.replicaCount
  );
  if (replicaCount) return `${replicaCount}副本`;

  const candidates = [volume.elf_storage_policy, volume.redundancy_policy, volume.redundancyPolicy, volume.replica_policy, volume.replicaPolicy, volume.storage_policy, volume.storagePolicy, volume.policy_name, volume.policyName, volume.policy, volume.replica_mode, volume.replicaMode, volume.ec_policy, volume.ecPolicy, volume.erasure_code, volume.erasureCode];
  for (const candidate of candidates) {
    const text = normalizePolicyValue(candidate);
    if (text) return text;
  }
  const raw = stringifyPolicy(volume);
  if (!raw) return "";
  const normalized = raw
    .replace(/[_\s-]+/g, " ")
    .replace(/(\d+)\s*[:xX/]\s*(\d+)/g, "EC$1+$2")
    .replace(/replica\s*(\d+)/i, "$1副本")
    .replace(/ec\s*(\d+)\s*\+\s*(\d+)/i, "EC$1+$2")
    .replace(/ec\s*(\d+)\s*[:xX/]\s*(\d+)/i, "EC$1+$2");
  if (/(副本|EC\d+\+\d+)/i.test(normalized)) return normalized;
  return raw;
}

function normalizePolicyValue(value: unknown): string {
  if (value && typeof value === "object") {
    const record = value as Record<string, unknown>;
    const direct = normalizePolicyValue(record.name ?? record.label ?? record.type ?? record.mode ?? record.policy);
    if (direct) return direct;
    const ecData = numberish(record.elf_storage_policy_ec_k ?? record.ec_data ?? record.ecData ?? record.ec_k ?? record.ecDataUnits);
    const ecParity = numberish(record.elf_storage_policy_ec_m ?? record.ec_parity ?? record.ecParity ?? record.ec_m ?? record.ecParityUnits);
    if (ecData && ecParity) return `EC${ecData}+${ecParity}`;
    const replicaCount = numberish(record.replica_num ?? record.replicaNum ?? record.replica_count ?? record.replicaCount);
    if (replicaCount) return `${replicaCount}副本`;
  }
  if (typeof value !== "string") return "";
  const trimmed = value.trim();
  if (!trimmed) return "";
  if (/^\d+$/.test(trimmed)) return `${trimmed}副本`;
  const compact = trimmed.replace(/\s+/g, "");
  const ecMatch = compact.match(/^ec[-_ ]?(\d+)[+/:xX](\d+)$/i);
  if (ecMatch) return `EC${ecMatch[1]}+${ecMatch[2]}`;
  const replicaMatch = compact.match(/^(?:replica|rep)\D*(\d+)$/i);
  if (replicaMatch) return `${replicaMatch[1]}副本`;
  const replicaPolicyMatch = compact.match(/^REPLICA_?(\d+)/i);
  if (replicaPolicyMatch) return `${replicaPolicyMatch[1]}副本`;
  const replicaTextMatch = compact.match(/(\d+).*(?:replica|rep|副本)|(?:replica|rep|副本).*(\d+)/i);
  if (replicaTextMatch) return `${replicaTextMatch[1] || replicaTextMatch[2]}副本`;
  if (/副本|EC\d+\+\d+/i.test(trimmed)) return trimmed;
  return trimmed;
}

function numberish(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function stringifyPolicy(volume: VmVolume): string {
  return [
    volume.elf_storage_policy,
    volume.redundancy_policy,
    volume.redundancyPolicy,
    volume.replica_policy,
    volume.replicaPolicy,
    volume.storage_policy,
    volume.storagePolicy,
    volume.policy_name,
    volume.policyName,
    volume.policy,
    volume.replica_mode,
    volume.replicaMode,
    volume.ec_policy,
    volume.ecPolicy,
    volume.erasure_code,
    volume.erasureCode,
  ]
    .filter((value): value is string | number => typeof value === "string" || typeof value === "number")
    .map((value) => String(value))
    .join(" ")
    .trim();
}
