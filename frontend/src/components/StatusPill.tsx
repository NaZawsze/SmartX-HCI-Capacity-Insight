interface StatusPillProps {
  status?: string | null;
}

export function StatusPill({ status }: StatusPillProps) {
  const normalized = status || "unknown";
  const tone =
    normalized === "success"
      ? "success"
      : normalized === "partial" || normalized === "running"
        ? "warning"
        : normalized === "failed"
          ? "danger"
          : "neutral";
  const label =
    normalized === "success"
      ? "正常"
      : normalized === "partial"
        ? "部分失败"
        : normalized === "running"
          ? "采集中"
          : normalized === "failed"
            ? "失败"
            : "未知";
  return <span className={`status-pill ${tone}`}>{label}</span>;
}
