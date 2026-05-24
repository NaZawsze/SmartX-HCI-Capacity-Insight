import { ArrowDownWideNarrow, Search } from "lucide-react";
import type { ReactNode } from "react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Card } from "../components/Card";
import { TrendChart } from "../components/TrendChart";
import { api, formatBytes } from "../services/api";
import type { MetricItem, VmTrend, VmVolume, VmVolumeSet } from "../types";

const trendRanges = [7, 14, 30, 90, 180] as const;
type TrendRange = (typeof trendRanges)[number];
type SortMode = "size" | "usage";

interface VmsPageProps {
  refreshKey?: number;
  selectedVmId?: string;
  selectedVmName?: string;
  onSelectedVmChange?: (vmId: string) => void;
}

export function VmsPage({ refreshKey = 0, selectedVmId = "", selectedVmName = "", onSelectedVmChange }: VmsPageProps) {
  const [items, setItems] = useState<MetricItem[]>([]);
  const [selectedVm, setSelectedVm] = useState("");
  const [query, setQuery] = useState("");
  const [trendDays, setTrendDays] = useState<TrendRange>(30);
  const [sortMode, setSortMode] = useState<SortMode>("size");
  const [trend, setTrend] = useState<VmTrend | null>(null);
  const [allVolumes, setAllVolumes] = useState<VmVolumeSet[]>([]);
  const searchInputRef = useRef<HTMLInputElement | null>(null);
  const selectedItemRef = useRef<HTMLButtonElement | null>(null);
  const lastOpenedVmNameRef = useRef("");

  useEffect(() => {
    api.vms().then((result) => {
      setItems(result);
      setSelectedVm((current) => {
        if (selectedVmId && result.some((item) => item.metric.vm_id === selectedVmId)) return selectedVmId;
        if (current && result.some((item) => item.metric.vm_id === current)) return current;
        return result[0]?.metric.vm_id || "";
      });
    });
  }, [refreshKey, selectedVmId]);

  useEffect(() => {
    api.vmVolumesAll().then(setAllVolumes).catch(() => setAllVolumes([]));
  }, [refreshKey]);

  useEffect(() => {
    if (!selectedVm) {
      setTrend(null);
      return;
    }
    api.vmTrend(selectedVm, "used", trendDays).then(setTrend).catch(() => setTrend(null));
  }, [refreshKey, selectedVm, trendDays]);

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
        return getVmUsageRatio(right, allVolumes) - getVmUsageRatio(left, allVolumes);
      }
      return (right.value ?? 0) - (left.value ?? 0);
    });
    if (!term) return sorted;
    return sorted.filter((item) => `${item.metric.vm} ${item.metric.cluster}`.toLowerCase().includes(term));
  }, [allVolumes, items, query, sortMode]);

  const current = filtered.find((item) => item.metric.vm_id === selectedVm) ?? items.find((item) => item.metric.vm_id === selectedVm);
  const currentVmVolumes = findCurrentVmVolumes(allVolumes, current, selectedVm);
  const selectedItemVisible = filtered.some((item) => item.metric.vm_id === selectedVm);

  return (
    <div className="vm-page-grid">
      <Card title="虚拟机" className="vm-list-card">
        <div className="vm-toolbar">
          <div className="sort-tabs" aria-label="虚拟机排序">
            <button type="button" className={sortMode === "size" ? "active" : ""} onClick={() => setSortMode("size")}>
              <ArrowDownWideNarrow size={14} />
              容量
            </button>
            <button type="button" className={sortMode === "usage" ? "active" : ""} onClick={() => setSortMode("usage")}>
              <ArrowDownWideNarrow size={14} />
              使用率
            </button>
          </div>
          <label className="mini-search">
            <Search size={15} />
            <input ref={searchInputRef} value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索 VM" />
          </label>
        </div>
        <div className="vm-list">
          {filtered.map((item) => {
            const usage = getVmUsageRatio(item, allVolumes);
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
                <small className={usage > 0.9 ? "vm-usage over-limit" : "vm-usage"}>{formatRatio(item, allVolumes)}</small>
              </button>
            );
          })}
          {!filtered.length && <div className="empty-state">暂无 VM 数据</div>}
        </div>
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
          <span>{current?.metric.cluster || "未选择集群"}</span>
          <strong>{formatBytes(current?.value)}</strong>
        </div>
        <TrendChart points={trend?.points || []} referenceValue={current?.value} height={360} />
      </Card>

      <Card title="当前虚拟机明细" subtitle={current?.metric.vm || "未选择虚拟机"} className="current-volume-card">
        <VolumeTable>
          {currentVmVolumes.length ? currentVmVolumes.map(renderVolumeRow) : <div className="empty-state">暂无当前虚拟机卷数据</div>}
        </VolumeTable>
      </Card>

      <Card title="所有虚拟卷明细" className="volume-card">
        <VolumeTable>
          {allVolumes.length ? (
            allVolumes.map((group) => (
              <div className="volume-group" key={`${group.tower_id}-${group.cluster_id}-${group.vm_id}`}>
                <div className="volume-group-title">{group.vm_id}</div>
                {group.volumes.map(renderVolumeRow)}
              </div>
            ))
          ) : (
            <div className="empty-state">暂无虚拟卷数据</div>
          )}
        </VolumeTable>
      </Card>
    </div>
  );
}

function VolumeTable({ children }: { children: ReactNode }) {
  return (
    <div className="volume-table">
      <div className="volume-table-head">
        <span>虚拟卷名称</span>
        <span>实际使用空间</span>
        <span>分配空间</span>
        <span>副本机制</span>
        <span>实际占用集群空间</span>
      </div>
      <div className="volume-table-body">{children}</div>
    </div>
  );
}

function findCurrentVmVolumes(allVolumes: VmVolumeSet[], current: MetricItem | undefined, selectedVm: string): VmVolume[] {
  const exact = allVolumes.find(
    (item) =>
      item.vm_id === selectedVm &&
      String(item.tower_id) === String(current?.metric.tower_id ?? "") &&
      String(item.cluster_id) === String(current?.metric.cluster_id ?? "")
  );
  if (exact) return exact.volumes;
  return allVolumes.find((item) => item.vm_id === selectedVm)?.volumes || [];
}

function renderVolumeRow(volume: VmVolume, index?: number) {
  const key = volume.id || volume.name || volume.path || String(index ?? 0);
  const actualUsed = readSize(volume, ["used_size", "used_size_bytes", "unique_logical_size", "guest_used_size", "guest_used_size_bytes"]);
  const provisioned = readSize(volume, ["provisioned_size", "provisioned_size_bytes", "size", "size_bytes", "capacity", "capacity_bytes"]);
  const actualOccupied = getOccupiedSize(volume, actualUsed);
  return (
    <div className="volume-table-row" key={key}>
      <span title={readVolumeName(volume)}>{readVolumeName(volume)}</span>
      <strong>{formatBytes(actualUsed)}</strong>
      <strong>{formatBytes(provisioned)}</strong>
      <span>{readVolumePolicy(volume) || "-"}</span>
      <strong>{formatBytes(actualOccupied)}</strong>
    </div>
  );
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

function getVmUsageRatio(item: MetricItem, allVolumes: VmVolumeSet[]): number {
  const volumeRatio = getVmVolumeUsageRatio(item, allVolumes);
  if (volumeRatio !== null) return volumeRatio;
  const guest = item.guest_used ?? 0;
  const provisioned = item.provisioned ?? 0;
  if (guest > 0 && provisioned > 0) return item.guest_used_ratio ?? guest / provisioned;
  if (!item.provisioned || item.provisioned <= 0) return 0;
  return item.used_ratio ?? item.value / item.provisioned;
}

function getVmVolumeUsageRatio(item: MetricItem, allVolumes: VmVolumeSet[]): number | null {
  const volumes = findCurrentVmVolumes(allVolumes, item, item.metric.vm_id);
  if (!volumes.length) return null;

  let used = 0;
  let provisioned = 0;
  for (const volume of volumes) {
    const volumeUsed = readSize(volume, ["used_size", "used_size_bytes"]);
    const volumeProvisioned = readSize(volume, ["provisioned_size", "provisioned_size_bytes", "size", "size_bytes", "capacity", "capacity_bytes"]);
    if (volumeUsed === null || volumeProvisioned === null || volumeUsed < 0 || volumeProvisioned <= 0) continue;
    used += volumeUsed;
    provisioned += volumeProvisioned;
  }

  if (provisioned <= 0) return null;
  return used / provisioned;
}

function formatRatio(item: MetricItem, allVolumes: VmVolumeSet[]): string {
  const volumeRatio = getVmVolumeUsageRatio(item, allVolumes);
  if (volumeRatio !== null) return `${(volumeRatio * 100).toFixed(1)}%`;
  const guest = item.guest_used ?? 0;
  const provisioned = item.provisioned ?? 0;
  if (guest > 0 && provisioned > 0) {
    return `${((item.guest_used_ratio ?? guest / provisioned) * 100).toFixed(1)}%`;
  }
  if (!item.provisioned || item.provisioned <= 0) return "";
  const ratio = item.used_ratio ?? item.value / item.provisioned;
  return `${(ratio * 100).toFixed(1)}%`;
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
