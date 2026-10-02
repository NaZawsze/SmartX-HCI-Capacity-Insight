import { formatBytes } from "../services/api";

interface StorageBarProps {
  used: number;
  total: number;
  allocated?: number;
}

export function StorageBar({ used, total, allocated = 0 }: StorageBarProps) {
  const usedRatio = total > 0 ? Math.min(Math.max(used / total, 0), 1) : 0;
  const allocatedRatio = total > 0 ? Math.max(allocated, 0) / total : 0;
  const allocatedSegment = Math.max(0, Math.round((Math.min(allocatedRatio, 1) - usedRatio) * 1e6) / 1e6);
  return (
    <div className="storage-bar">
      <div className="storage-track">
        <div className="storage-fill" style={{ width: `${usedRatio * 100}%` }} />
        <div className="storage-fill-allocated" style={{ width: `${allocatedSegment * 100}%` }} />
      </div>
      <div className="storage-meta">
        <div className="storage-meta-item">
          <span className="storage-meta-label">已使用</span>
          <span className="storage-meta-value">{`${formatBytes(used)} · ${(usedRatio * 100).toFixed(2)}%`}</span>
        </div>
        <div className="storage-meta-item">
          <span className="storage-meta-label">总容量</span>
          <span className="storage-meta-value">{formatBytes(total)}</span>
        </div>
        <div className="storage-meta-item">
          <span className="storage-meta-label" title="CloudTower 性能层（performance tier）已分配容量；与左侧“已使用”（全集群物理占用，含副本）口径不同">性能层已分配</span>
          <span className="storage-meta-value">{`${formatBytes(allocated)} · ${(allocatedRatio * 100).toFixed(2)}%`}</span>
        </div>
      </div>
    </div>
  );
}
