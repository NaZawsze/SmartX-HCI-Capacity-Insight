import type { UpgradeTask } from "../../types";
import { PageHeader, formatTime, formatVersionForDisplay, upgradeStatusText } from "./shared";

interface HistorySectionProps {
  active: boolean;
  upgradeHistory: UpgradeTask[];
  componentHistory: UpgradeTask[];
  reloadUpgradeHistory: () => Promise<void>;
  reloadComponentHistory: () => Promise<void>;
  onSelectHistoryItem: (task: UpgradeTask) => void;
}

export function HistorySection({ active, upgradeHistory, componentHistory, reloadUpgradeHistory, reloadComponentHistory, onSelectHistoryItem }: HistorySectionProps) {
  if (!active) return null;

  const allHistory = [...upgradeHistory.map((item) => ({ ...item, kind: item.kind || "platform" })), ...componentHistory].sort((left, right) => new Date(right.updated_at || right.uploaded_at || 0).getTime() - new Date(left.updated_at || left.uploaded_at || 0).getTime());
  return (
    <>
      <PageHeader eyebrow="升级中心" title="升级历史" action={<button className="secondary-button" type="button" onClick={() => { reloadUpgradeHistory().catch(() => undefined); reloadComponentHistory().catch(() => undefined); }}>刷新</button>} />
      <div className="service-history-table">
        <div className="service-history-head">
          <span>目标版本</span>
          <span>状态</span>
          <span>上传时间</span>
          <span>完成时间</span>
          <span>备份路径</span>
        </div>
        {allHistory.map((item) => (
          <button className="service-history-row" type="button" key={item.task_id} onClick={() => onSelectHistoryItem(item)}>
            <span>{item.kind === "component" ? "组件升级" : "平台升级"} · {formatVersionForDisplay(item.target_version)}</span>
            <span>{upgradeStatusText(item.status)}</span>
            <span>{formatTime(item.uploaded_at)}</span>
            <span>{formatTime(item.finished_at || item.rollback_finished_at)}</span>
            <span>{item.backup_path || "-"}</span>
          </button>
        ))}
        {!allHistory.length && <div className="empty-state">暂无升级历史</div>}
      </div>
    </>
  );
}
