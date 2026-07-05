import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { clsx } from 'clsx'
import { apiAnalyzePortfolio, HoldingInput } from '../api/portfolio'
import { PortfolioResult, PortfolioHolding } from '../types'

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmt$(v: number | null, decimals = 2): string {
  if (v == null) return '—'
  const abs = Math.abs(v)
  const sign = v < 0 ? '-' : ''
  if (abs >= 1e9) return `${sign}$${(abs / 1e9).toFixed(2)}B`
  if (abs >= 1e6) return `${sign}$${(abs / 1e6).toFixed(2)}M`
  if (abs >= 1e3) return `${sign}$${abs.toLocaleString('en-US', { minimumFractionDigits: 2 })}`
  return `${sign}$${abs.toFixed(decimals)}`
}

function pct(v: number | null): string {
  if (v == null) return '—'
  return `${v >= 0 ? '+' : ''}${v.toFixed(2)}%`
}

function pnlColor(v: number | null) {
  if (v == null || v === 0) return 'text-ink-muted'
  return v > 0 ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'
}

const SECTOR_COLORS: Record<string, string> = {
  'Technology':           '#6366f1',
  'Health Care':          '#22c55e',
  'Financials':           '#3b82f6',
  'Consumer Discretionary': '#f59e0b',
  'Communication Services': '#8b5cf6',
  'Industrials':          '#0ea5e9',
  'Consumer Staples':     '#84cc16',
  'Energy':               '#f97316',
  'Utilities':            '#06b6d4',
  'Real Estate':          '#ec4899',
  'Materials':            '#14b8a6',
  'Unknown':              '#94a3b8',
}

// ── Components ────────────────────────────────────────────────────────────────

function SectorPie({ breakdown }: { breakdown: Record<string, number> }) {
  const entries = Object.entries(breakdown)
  let cumulative = 0
  const slices = entries.map(([sector, pct]) => {
    const start = cumulative
    cumulative += pct
    return { sector, pct, start }
  })

  const r = 70
  const cx = 90
  const cy = 90

  function arc(startPct: number, endPct: number) {
    const startAngle = (startPct / 100) * 360 - 90
    const endAngle   = (endPct   / 100) * 360 - 90
    const rad = (deg: number) => (deg * Math.PI) / 180
    const x1  = cx + r * Math.cos(rad(startAngle))
    const y1  = cy + r * Math.sin(rad(startAngle))
    const x2  = cx + r * Math.cos(rad(endAngle))
    const y2  = cy + r * Math.sin(rad(endAngle))
    const large = endPct - startPct > 50 ? 1 : 0
    return `M ${cx} ${cy} L ${x1} ${y1} A ${r} ${r} 0 ${large} 1 ${x2} ${y2} Z`
  }

  return (
    <div className="flex flex-col sm:flex-row items-center gap-6">
      <svg width="180" height="180" className="flex-shrink-0">
        {slices.map(({ sector, pct, start }) => (
          <path key={sector} d={arc(start, start + pct)}
            fill={SECTOR_COLORS[sector] ?? '#94a3b8'} stroke="white" strokeWidth="1.5" />
        ))}
        <circle cx={cx} cy={cy} r={42} fill="var(--color-surface)" />
        <text x={cx} y={cy - 6} textAnchor="middle" className="fill-ink text-xs font-bold" fontSize="11">
          Sectors
        </text>
        <text x={cx} y={cy + 10} textAnchor="middle" className="fill-ink-muted text-xs" fontSize="10">
          {entries.length}
        </text>
      </svg>
      <div className="grid grid-cols-1 gap-1.5 flex-1">
        {slices.map(({ sector, pct }) => (
          <div key={sector} className="flex items-center gap-2">
            <span className="w-2.5 h-2.5 rounded-full flex-shrink-0"
              style={{ backgroundColor: SECTOR_COLORS[sector] ?? '#94a3b8' }} />
            <span className="text-xs text-ink truncate flex-1">{sector}</span>
            <span className="text-xs font-semibold text-ink-muted">{pct.toFixed(1)}%</span>
          </div>
        ))}
      </div>
    </div>
  )
}

function HoldingRow({ h }: { h: PortfolioHolding }) {
  if (h.error) {
    return (
      <div className="flex items-center gap-3 py-3 border-b border-surface-border last:border-0 text-red-500 text-sm">
        <span className="font-bold w-20">{h.ticker}</span>
        <span className="text-xs">{h.error}</span>
      </div>
    )
  }
  return (
    <div className="grid grid-cols-[80px_1fr_80px_80px_80px_80px_60px] gap-2 items-center py-3 border-b border-surface-border last:border-0 text-sm">
      <div>
        <div className="font-bold text-ink">{h.ticker}</div>
        <div className="text-xs text-ink-faint truncate">{h.sector}</div>
      </div>
      <div className="min-w-0">
        <div className="text-ink text-xs truncate">{h.company}</div>
        <div className="text-ink-faint text-xs">{h.shares} shares</div>
      </div>
      <div className="text-right">
        <div className="text-ink font-semibold">{fmt$(h.current_price)}</div>
        <div className={clsx('text-xs', pnlColor(h.day_change_pct))}>{pct(h.day_change_pct)}</div>
      </div>
      <div className="text-right">
        <div className="text-ink font-semibold">{fmt$(h.current_value)}</div>
        <div className="text-xs text-ink-faint">{h.weight.toFixed(1)}%</div>
      </div>
      <div className="text-right text-ink-faint text-xs">{fmt$(h.cost_basis)}</div>
      <div className="text-right">
        <div className={clsx('font-semibold', pnlColor(h.pnl))}>{fmt$(h.pnl)}</div>
        <div className={clsx('text-xs', pnlColor(h.pnl_pct))}>{pct(h.pnl_pct)}</div>
      </div>
      <div className="text-right text-xs text-ink-faint">{h.beta?.toFixed(2) ?? '—'}</div>
    </div>
  )
}

// ── Main Page ─────────────────────────────────────────────────────────────────

const PLACEHOLDER = [
  { ticker: 'AAPL', shares: 10, avg_cost: 150 },
  { ticker: 'MSFT', shares: 5,  avg_cost: 320 },
  { ticker: 'NVDA', shares: 8,  avg_cost: 400 },
]

export function PortfolioPage() {
  const [rows, setRows] = useState<HoldingInput[]>(PLACEHOLDER)
  const [result, setResult] = useState<PortfolioResult | null>(null)

  const mut = useMutation({
    mutationFn: apiAnalyzePortfolio,
    onSuccess:  setResult,
  })

  function addRow() {
    setRows(r => [...r, { ticker: '', shares: 0, avg_cost: 0 }])
  }

  function removeRow(i: number) {
    setRows(r => r.filter((_, idx) => idx !== i))
  }

  function updateRow(i: number, field: keyof HoldingInput, value: string) {
    setRows(r => r.map((row, idx) =>
      idx !== i ? row : { ...row, [field]: field === 'ticker' ? value.toUpperCase() : parseFloat(value) || 0 }
    ))
  }

  function handleAnalyse() {
    const valid = rows.filter(r => r.ticker.trim() && r.shares > 0 && r.avg_cost > 0)
    if (!valid.length) return
    mut.mutate(valid)
  }

  const s = result?.summary

  return (
    <div className="min-h-screen bg-canvas">
      <div className="max-w-6xl mx-auto px-4 py-6 space-y-6">

        <div>
          <h1 className="text-2xl font-bold text-ink">Portfolio Analyzer</h1>
          <p className="text-sm text-ink-muted mt-0.5">
            Enter your holdings to get P&L, portfolio beta, and sector allocation
          </p>
        </div>

        {/* Holdings input table */}
        <div className="bg-surface rounded-2xl border border-surface-border shadow-card overflow-hidden">
          <div className="px-5 py-4 border-b border-surface-border flex items-center justify-between">
            <span className="font-semibold text-ink text-sm">Your Holdings</span>
            <button onClick={addRow}
              className="text-xs px-3 py-1.5 rounded-lg bg-primary/10 text-primary border border-primary/20 hover:bg-primary/20 font-medium transition-colors">
              + Add Row
            </button>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-surface-border text-xs text-ink-faint uppercase tracking-wide">
                  <th className="text-left px-5 py-2.5">Ticker</th>
                  <th className="text-right px-3 py-2.5">Shares</th>
                  <th className="text-right px-3 py-2.5">Avg Cost ($)</th>
                  <th className="px-3 py-2.5" />
                </tr>
              </thead>
              <tbody>
                {rows.map((row, i) => (
                  <tr key={i} className="border-b border-surface-border last:border-0">
                    <td className="px-5 py-2">
                      <input value={row.ticker} onChange={e => updateRow(i, 'ticker', e.target.value)}
                        placeholder="AAPL"
                        className="w-24 px-2 py-1.5 rounded border border-surface-border bg-canvas text-ink text-sm font-mono uppercase focus:outline-none focus:border-primary" />
                    </td>
                    <td className="px-3 py-2">
                      <input type="number" value={row.shares || ''} onChange={e => updateRow(i, 'shares', e.target.value)}
                        min="0" step="0.0001" placeholder="10"
                        className="w-24 px-2 py-1.5 rounded border border-surface-border bg-canvas text-ink text-sm text-right focus:outline-none focus:border-primary" />
                    </td>
                    <td className="px-3 py-2">
                      <input type="number" value={row.avg_cost || ''} onChange={e => updateRow(i, 'avg_cost', e.target.value)}
                        min="0" step="0.01" placeholder="150.00"
                        className="w-28 px-2 py-1.5 rounded border border-surface-border bg-canvas text-ink text-sm text-right focus:outline-none focus:border-primary" />
                    </td>
                    <td className="px-3 py-2">
                      <button onClick={() => removeRow(i)}
                        className="text-ink-faint hover:text-red-500 transition-colors text-lg leading-none">✕</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="px-5 py-4 border-t border-surface-border">
            <button
              onClick={handleAnalyse}
              disabled={mut.isPending}
              className="px-5 py-2 rounded-lg bg-primary text-white font-semibold text-sm disabled:opacity-50 hover:bg-primary/90 transition-colors"
            >
              {mut.isPending ? 'Analysing…' : 'Analyse Portfolio'}
            </button>
            {mut.isError && (
              <span className="ml-3 text-xs text-red-500">Analysis failed. Check your tickers and try again.</span>
            )}
          </div>
        </div>

        {/* Results */}
        {result && s && (
          <div className="space-y-6">

            {/* Summary cards */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
              {[
                { label: 'Portfolio Value', value: fmt$(s.total_value), sub: `Cost ${fmt$(s.total_cost)}` },
                { label: 'Total P&L', value: fmt$(s.total_pnl), sub: pct(s.total_pnl_pct), color: pnlColor(s.total_pnl) },
                { label: 'Portfolio Beta', value: s.portfolio_beta.toFixed(2),
                  sub: s.portfolio_beta > 1.2 ? 'High risk' : s.portfolio_beta < 0.8 ? 'Defensive' : 'Market-like' },
                { label: 'Diversification', value: `${s.diversification.toFixed(0)}%`, sub: `${s.num_holdings} holdings` },
              ].map(card => (
                <div key={card.label} className="bg-surface rounded-2xl border border-surface-border shadow-card p-4">
                  <div className="text-xs text-ink-faint uppercase tracking-wide mb-1">{card.label}</div>
                  <div className={clsx('text-xl font-bold text-ink', card.color)}>{card.value}</div>
                  <div className={clsx('text-xs mt-0.5', card.color ?? 'text-ink-muted')}>{card.sub}</div>
                </div>
              ))}
            </div>

            {/* Sector breakdown + top weights */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              <div className="bg-surface rounded-2xl border border-surface-border shadow-card p-5">
                <h3 className="text-sm font-semibold text-ink mb-4">Sector Allocation</h3>
                <SectorPie breakdown={s.sector_breakdown} />
              </div>
              <div className="bg-surface rounded-2xl border border-surface-border shadow-card p-5">
                <h3 className="text-sm font-semibold text-ink mb-4">Top Holdings by Weight</h3>
                <div className="space-y-2.5">
                  {s.top5_by_weight.map(({ ticker, weight }) => (
                    <div key={ticker}>
                      <div className="flex justify-between text-xs mb-1">
                        <span className="font-semibold text-ink">{ticker}</span>
                        <span className="text-ink-muted">{weight.toFixed(1)}%</span>
                      </div>
                      <div className="h-2 bg-surface-muted rounded-full overflow-hidden">
                        <div className="h-full bg-primary rounded-full" style={{ width: `${weight}%` }} />
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>

            {/* Holdings detail table */}
            <div className="bg-surface rounded-2xl border border-surface-border shadow-card overflow-hidden">
              <div className="px-5 py-4 border-b border-surface-border">
                <span className="font-semibold text-ink text-sm">Holdings Detail</span>
              </div>
              <div className="overflow-x-auto">
                <div className="min-w-[700px]">
                  {/* Table header */}
                  <div className="grid grid-cols-[80px_1fr_80px_80px_80px_80px_60px] gap-2 px-5 py-2 text-xs text-ink-faint uppercase tracking-wide border-b border-surface-border">
                    <span>Ticker</span>
                    <span>Company</span>
                    <span className="text-right">Price</span>
                    <span className="text-right">Value</span>
                    <span className="text-right">Cost</span>
                    <span className="text-right">P&L</span>
                    <span className="text-right">Beta</span>
                  </div>
                  <div className="px-5">
                    {result.holdings.map(h => <HoldingRow key={h.ticker} h={h} />)}
                  </div>
                </div>
              </div>
            </div>

            <p className="text-xs text-ink-faint text-center">
              Prices from Yahoo Finance · ~15 min delay during market hours · Not investment advice
            </p>
          </div>
        )}
      </div>
    </div>
  )
}
