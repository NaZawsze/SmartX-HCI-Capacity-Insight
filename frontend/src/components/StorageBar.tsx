import { formatBytes } from "../services/api";

interface StorageBarProps {
  used: number;
  total: number;
}

export function StorageBar({ used, total }: StorageBarProps) {
  const ratio = total > 0 ? Math.min(used / total, 1) : 0;
  return (
    <div className="storage-bar">
      <div className="storage-track">
        <div className="storage-fill" style={{ width: `${ratio * 100}%` }} />
      </div>
      <div className="storage-meta">
        <span>已使用 {formatBytes(used)}</span>
        <strong>{(ratio * 100).toFixed(2)}%</strong>
        <span>总容量 {formatBytes(total)}</span>
      </div>
    </div>
  );
}

