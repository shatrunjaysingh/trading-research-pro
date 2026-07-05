import { useQuery } from '@tanstack/react-query'
import { clsx } from 'clsx'
import { SectorData } from '../types'
import { apiGetSectorRotation } from '../api/market'

function retColor(v: number | null, isRs = false): string {
  if (v == null) return 'bg-surface-muted text-ink-faint'
  if (isRs) {
    if (v >= 3)  return 'bg-green-600 text-white'
    if (v >= 1)  return 'bg-green-400 text-white'
    if (v >= 0)  return 'bg-green-100 dark:bg-green-900/40 text-green-800 dark:text-green-200'
    if (v >= -1) return 'bg-red-100 dark:bg-red-900/40 text-red-800 dark:text-red-200'
    if (v >= -3) return 'bg-red-400 text-white'
    return 'bg-red-600 text-white'
  }
  if (v >= 5)  return 'bg-green-600 text-white'
  if (v >= 2)  return 'bg-green-400 text-white'
  if (v >= 0)  return 'bg-green-100 dark:bg-green-900/40 text-green-800 dark:text-green-200'
  if (v >= -2) return 'bg-red-100 dark:bg-red-900/40 text-red-800 dark:text-red-200'
  if (v >= -5) return 'bg-red-400 text-white'
  return 'bg-red-600 text-white'
}

function Cell({ v, isRs = false }: { v: number | null; isRs?: boolean }) {
  return (
    <div className={clsx('rounded-lg px-2 py-2 text-center text-xs font-semibold tabular-nums', retColor(v, isRs))}>
      {v == null ? '—' : `${v >= 0 ? '+' : ''}${v.toFixed(1)}%`}
    </div>
  )
}

export function SectorHeatmapPage() {
  const { data = [], isLoading, refetch } = useQuery({
    queryKey: ['sector-rotation'],
    queryFn: apiGetSectorRotation,
    staleTime: 1000 * 60 * 15,
  })

  const sorted = [...data].sort((a, b) => (b.rs_1m ?? -999) - (a.rs_1m ?? -999))

  return (
    <div className="max-w-6xl mx-auto px-4 py-6 space-y-6">
      <div className="flex items-start justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold text-ink">Sector Rotation Heatmap</h1>
          <p className="text-sm text-ink-muted mt-0.5">
            Which sectors are gaining or losing momentum vs SPY.
            <span className="text-green-600 font-medium"> Green</span> = outperforming ·
            <span className="text-red-600 font-medium"> Red</span> = underperforming ·
            RS = return vs SPY over period
          </p>
        </div>
        <button onClick={() => refetch()} className="btn-secondary text-sm px-4 py-2">Refresh</button>
      </div>

      {isLoading && (
        <div className="card p-8 text-center text-ink-muted text-sm">Computing sector data…</div>
      )}

      {!isLoading && sorted.length > 0 && (
        <div className="space-y-4">
          {/* Heatmap grid */}
          <div className="card overflow-hidden">
            <div className="px-5 py-4 border-b border-surface-border">
              <span className="font-semibold text-ink text-sm">Sector Performance & Relative Strength</span>
            </div>
            <div className="overflow-x-auto">
              <div className="min-w-[800px] p-4">
                {/* Header */}
                <div className="grid grid-cols-[160px_60px_1fr] gap-2 mb-2">
                  <div />
                  <div />
                  <div className="grid grid-cols-8 gap-1.5">
                    {['1W Ret', '1M Ret', '3M Ret', 'YTD Ret', '1W RS', '1M RS', '3M RS', 'vs SMA200'].map(h => (
                      <div key={h} className="text-center text-xs text-ink-faint font-semibold uppercase tracking-wide">{h}</div>
                    ))}
                  </div>
                </div>

                {sorted.map(s => (
                  <div key={s.sector} className="grid grid-cols-[160px_60px_1fr] gap-2 mb-1.5 items-center">
                    <div>
                      <div className="text-sm font-semibold text-ink truncate">{s.sector}</div>
                      <div className="text-xs text-ink-faint">{s.etf} · ${s.price.toFixed(2)}</div>
                    </div>
                    <div className="text-center">
                      <span className={clsx('text-lg', s.trend === 'up' ? 'text-green-500' : 'text-red-500')}>
                        {s.trend === 'up' ? '↑' : '↓'}
                      </span>
                    </div>
                    <div className="grid grid-cols-8 gap-1.5">
                      <Cell v={s.ret_1w} />
                      <Cell v={s.ret_1m} />
                      <Cell v={s.ret_3m} />
                      <Cell v={s.ret_ytd} />
                      <Cell v={s.rs_1w} isRs />
                      <Cell v={s.rs_1m} isRs />
                      <Cell v={s.rs_3m} isRs />
                      <Cell v={s.vs_sma200} />
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* Top/Bottom sectors */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div className="card p-5">
              <h3 className="font-semibold text-ink text-sm mb-3">Strongest Sectors (1M RS)</h3>
              <div className="space-y-2">
                {sorted.slice(0, 4).map((s, i) => (
                  <div key={s.sector} className="flex items-center gap-3">
                    <span className="w-5 h-5 rounded-full bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-300 flex items-center justify-center text-xs font-bold">{i+1}</span>
                    <div className="flex-1">
                      <div className="text-sm font-medium text-ink">{s.sector}</div>
                      <div className="text-xs text-ink-faint">{s.etf}</div>
                    </div>
                    <div className={clsx('text-sm font-semibold', (s.rs_1m ?? 0) >= 0 ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400')}>
                      {s.rs_1m != null ? `${s.rs_1m >= 0 ? '+' : ''}${s.rs_1m.toFixed(1)}%` : '—'}
                    </div>
                  </div>
                ))}
              </div>
            </div>
            <div className="card p-5">
              <h3 className="font-semibold text-ink text-sm mb-3">Weakest Sectors (1M RS)</h3>
              <div className="space-y-2">
                {sorted.slice(-4).reverse().map((s, i) => (
                  <div key={s.sector} className="flex items-center gap-3">
                    <span className="w-5 h-5 rounded-full bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-300 flex items-center justify-center text-xs font-bold">{i+1}</span>
                    <div className="flex-1">
                      <div className="text-sm font-medium text-ink">{s.sector}</div>
                      <div className="text-xs text-ink-faint">{s.etf}</div>
                    </div>
                    <div className={clsx('text-sm font-semibold', (s.rs_1m ?? 0) >= 0 ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400')}>
                      {s.rs_1m != null ? `${s.rs_1m >= 0 ? '+' : ''}${s.rs_1m.toFixed(1)}%` : '—'}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}

      <p className="text-xs text-ink-faint text-center">
        Data from Yahoo Finance sector ETFs (XLK, XLV, XLF, etc.) · RS = outperformance vs SPY · Updated on refresh
      </p>
    </div>
  )
}
