interface StatusPillProps {
  status?: string | null;
}

export function StatusPill({ status }: StatusPillProps) {
  const normalized = status || "unknown";
  // `partial_failed` 是采集侧"部分失败"的真实取值（collection/service.py），
  // 曾因前端只认 `partial` 而落到"未知"——2026-10-07 `.14` 实测抓到（部分失败显示未知，
  // 与右侧"采集异常：成功 N 个集群、失败 M 个集群"自相矛盾）。
  const partial = normalized === "partial" || normalized === "partial_failed";
  const tone =
    normalized === "success"
      ? "success"
      : partial || normalized === "running"
        ? "warning"
        : normalized === "failed"
          ? "danger"
          : "neutral";
  const label =
    normalized === "success"
      ? "正常"
      : partial
        ? "部分失败"
        : normalized === "running"
          ? "采集中"
          : normalized === "failed"
            ? "失败"
            : "未知";
  return <span className={`status-pill ${tone}`}>{label}</span>;
}
