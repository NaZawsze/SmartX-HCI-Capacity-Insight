import type { LucideIcon } from "lucide-react";

interface MetricCardProps {
  label: string;
  value: string;
  hint?: string;
  icon: LucideIcon;
  tone?: "blue" | "green" | "orange" | "red";
}

export function MetricCard({ label, value, hint, icon: Icon, tone = "blue" }: MetricCardProps) {
  return (
    <div className={`metric-card ${tone}`}>
      <div className="metric-icon">
        <Icon size={18} />
      </div>
      <div>
        <div className="metric-label">{label}</div>
        <div className="metric-value">{value}</div>
        {hint && <div className="metric-hint">{hint}</div>}
      </div>
    </div>
  );
}

