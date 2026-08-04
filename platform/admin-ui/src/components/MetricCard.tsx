import type { ReactNode } from "react";

export function MetricCard({ label, value, icon }: { label: string; value: number; icon: ReactNode }) {
  return (
    <article className="metric-card">
      <div className="metric-icon">{icon}</div>
      <div>
        <strong>{value}</strong>
        <span>{label}</span>
      </div>
    </article>
  );
}
