interface KpiCardProps { value: string | number; label: string; sub?: string }

export function KpiCard({ value, label, sub }: KpiCardProps) {
  return (
    <div className="card p-5 flex-1 min-w-[140px]">
      <div className="text-3xl font-extrabold text-ink leading-tight">{value}</div>
      <div className="text-xs font-bold uppercase tracking-widest text-ink-faint mt-1.5">{label}</div>
      {sub && <div className="text-xs text-ink-muted mt-1">{sub}</div>}
    </div>
  )
}
