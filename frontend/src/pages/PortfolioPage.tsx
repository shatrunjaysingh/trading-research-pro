import { useState, useEffect } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { clsx } from 'clsx'
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts'
import {
  apiAnalyzePortfolio,
  apiGetSavedPortfolio,
  apiSavePortfolio,
  apiGetPortfolioReview,
  apiGetPortfolioBacktest,
  apiGetPortfolioBenchmark,
  apiGetPortfolioNews,
  HoldingInput,
} from '../api/portfolio'
import { PortfolioResult, PortfolioHolding, ScoredHolding, PortfolioAction, BacktestResult, BenchmarkResult, TickerNews, PortfolioRisk } from '../types'

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

const ACTION_STYLES: Record<PortfolioAction, { bg: string; text: string; label: string }> = {
  add_more: { bg: 'bg-green-100 dark:bg-green-900/40', text: 'text-green-700 dark:text-green-300', label: 'ADD MORE' },
  hold:     { bg: 'bg-blue-100 dark:bg-blue-900/40',  text: 'text-blue-700 dark:text-blue-300',  label: 'HOLD' },
  reduce:   { bg: 'bg-amber-100 dark:bg-amber-900/40',text: 'text-amber-700 dark:text-amber-300',label: 'REDUCE' },
  sell:     { bg: 'bg-red-100 dark:bg-red-900/40',    text: 'text-red-700 dark:text-red-300',    label: 'SELL' },
}

function ActionBadge({ action }: { action: PortfolioAction }) {
  const s = ACTION_STYLES[action]
  return (
    <span className={clsx('inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-bold', s.bg, s.text)}>
      {s.label}
    </span>
  )
}

function ScoreBar({ score, max = 100 }: { score: number; max?: number }) {
  const pct = Math.min(100, (score / max) * 100)
  const color = score >= 70 ? 'bg-green-500' : score >= 50 ? 'bg-blue-500' : score >= 35 ? 'bg-amber-500' : 'bg-red-500'
  return (
    <div className="flex items-center gap-1.5">
      <div className="h-1.5 w-16 bg-surface-muted rounded-full overflow-hidden">
        <div className={clsx('h-full rounded-full', color)} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs font-semibold text-ink tabular-nums">{score.toFixed(0)}</span>
    </div>
  )
}

// ── Sector Pie ────────────────────────────────────────────────────────────────

function SectorPie({ breakdown }: { breakdown: Record<string, number> }) {
  const entries = Object.entries(breakdown)
  let cumulative = 0
  const slices = entries.map(([sector, pct]) => {
    const start = cumulative
    cumulative += pct
    return { sector, pct, start }
  })

  const r = 70; const cx = 90; const cy = 90
  function arc(startPct: number, endPct: number) {
    const startAngle = (startPct / 100) * 360 - 90
    const endAngle   = (endPct   / 100) * 360 - 90
    const rad = (deg: number) => (deg * Math.PI) / 180
    const x1  = cx + r * Math.cos(rad(startAngle)); const y1 = cy + r * Math.sin(rad(startAngle))
    const x2  = cx + r * Math.cos(rad(endAngle));   const y2 = cy + r * Math.sin(rad(endAngle))
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
        <text x={cx} y={cy - 6} textAnchor="middle" className="fill-ink" fontSize="11" fontWeight="bold">Sectors</text>
        <text x={cx} y={cy + 10} textAnchor="middle" className="fill-ink-muted" fontSize="10">{entries.length}</text>
      </svg>
      <div className="grid grid-cols-1 gap-1.5 flex-1">
        {slices.map(({ sector, pct }) => (
          <div key={sector} className="flex items-center gap-2">
            <span className="w-2.5 h-2.5 rounded-full flex-shrink-0" style={{ backgroundColor: SECTOR_COLORS[sector] ?? '#94a3b8' }} />
            <span className="text-xs text-ink truncate flex-1">{sector}</span>
            <span className="text-xs font-semibold text-ink-muted">{pct.toFixed(1)}%</span>
          </div>
        ))}
      </div>
    </div>
  )
}

// ── Holdings Row (P&L view) ───────────────────────────────────────────────────

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

// ── Scored Holding Row (Review view) ─────────────────────────────────────────

function ScoredHoldingRow({ h }: { h: ScoredHolding }) {
  const [open, setOpen] = useState(false)
  if (h.error) {
    return (
      <div className="flex items-center gap-3 py-3 border-b border-surface-border text-red-500 text-sm">
        <span className="font-bold w-20">{h.ticker}</span>
        <span className="text-xs">{h.error}</span>
      </div>
    )
  }
  return (
    <div className="border-b border-surface-border last:border-0">
      <button
        className="w-full text-left"
        onClick={() => setOpen(o => !o)}
      >
        <div className="grid grid-cols-[80px_1fr_110px_140px_80px_80px] gap-2 items-center py-3 px-1 hover:bg-surface-muted/50 transition-colors text-sm">
          <div>
            <div className="font-bold text-ink">{h.ticker}</div>
            <div className="text-xs text-ink-faint">{h.weight.toFixed(1)}%</div>
          </div>
          <div className="min-w-0">
            <div className="text-ink text-xs truncate">{h.company}</div>
            <div className="text-ink-faint text-xs">{h.sector}</div>
          </div>
          <div>
            <ActionBadge action={h.action} />
          </div>
          <div className="space-y-1">
            <div className="flex items-center gap-1 text-xs text-ink-faint">
              <span className="w-5">ST</span><ScoreBar score={h.st_score} />
            </div>
            <div className="flex items-center gap-1 text-xs text-ink-faint">
              <span className="w-5">LT</span><ScoreBar score={h.lt_score ?? 0} />
            </div>
          </div>
          <div className="text-center">
            <div className="text-sm font-bold text-ink">{h.rs_score}</div>
            <div className="text-xs text-ink-faint">RS</div>
          </div>
          <div className="text-right">
            <div className={clsx('font-semibold text-sm', pnlColor(h.pnl_pct))}>{pct(h.pnl_pct)}</div>
            <div className="text-xs text-ink-faint">{fmt$(h.current_price)}</div>
          </div>
        </div>
      </button>
      {open && h.action_reasons.length > 0 && (
        <div className={clsx('mx-1 mb-3 p-3 rounded-xl text-xs space-y-1',
          h.action === 'add_more' ? 'bg-green-50 dark:bg-green-950/30' :
          h.action === 'hold'     ? 'bg-blue-50 dark:bg-blue-950/30' :
          h.action === 'reduce'   ? 'bg-amber-50 dark:bg-amber-950/30' :
          'bg-red-50 dark:bg-red-950/30')}>
          {h.action_reasons.map((r, i) => (
            <div key={i} className="flex items-start gap-2">
              <span className="text-ink-faint mt-0.5">•</span>
              <span className="text-ink-muted">{r}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ── Position Sizer ────────────────────────────────────────────────────────────

function PortfolioRiskCard({ risk }: { risk: PortfolioRisk | null | undefined }) {
  if (!risk) return null

  const stat = (label: string, value: string, sub?: string, tone?: 'good' | 'ok' | 'bad') => {
    const toneCls = tone === 'good' ? 'text-green-600 dark:text-green-400'
      : tone === 'bad' ? 'text-red-600 dark:text-red-400'
      : tone === 'ok' ? 'text-amber-600 dark:text-amber-400' : 'text-ink'
    return (
      <div className="flex flex-col">
        <span className="text-[10px] text-ink-faint uppercase tracking-wider">{label}</span>
        <span className={clsx('text-lg font-bold', toneCls)}>{value}</span>
        {sub && <span className="text-[10px] text-ink-faint">{sub}</span>}
      </div>
    )
  }

  const betaTone = risk.portfolio_beta > 1.3 ? 'bad' : risk.portfolio_beta > 1.1 ? 'ok' : 'good'

  return (
    <div className="bg-surface rounded-2xl border border-surface-border shadow-card p-5 space-y-4">
      <div className="flex items-center justify-between">
        <span className="font-semibold text-ink text-sm">Portfolio Risk</span>
        <span className="text-[10px] text-ink-faint">{risk.risk_available ? '6-month daily returns' : 'limited data'}</span>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        {stat('Beta', risk.portfolio_beta.toFixed(2), 'vs market', betaTone)}
        {risk.portfolio_ann_vol_pct != null &&
          stat('Volatility', `${risk.portfolio_ann_vol_pct}%`, 'annualized')}
        {risk.diversification_ratio != null &&
          stat('Diversification', `${risk.diversification_ratio}×`,
            risk.diversification_ratio >= 1.3 ? 'well spread' : 'concentrated',
            risk.diversification_ratio >= 1.3 ? 'good' : 'ok')}
        {risk.est_var_95_1y_pct != null &&
          stat('1Y Downside', `-${risk.est_var_95_1y_pct}%`, '95% VaR',
            risk.est_var_95_1y_pct > 30 ? 'bad' : risk.est_var_95_1y_pct > 20 ? 'ok' : 'good')}
      </div>

      {/* Concentration flags */}
      {risk.sector_flags.length > 0 && (
        <div className="text-xs text-amber-700 dark:text-amber-400 bg-amber-50 dark:bg-amber-900/20 rounded-lg px-3 py-2">
          ⚠️ Concentrated: {risk.sector_flags.map(f => `${f.sector} ${f.weight}%`).join(', ')}
        </div>
      )}

      {/* Redundant (highly-correlated) pairs */}
      {risk.redundant_pairs && risk.redundant_pairs.length > 0 && (
        <div>
          <div className="text-[10px] text-ink-faint uppercase tracking-wider mb-1">Redundant risk (highly correlated)</div>
          <div className="flex flex-wrap gap-2">
            {risk.redundant_pairs.map((p, i) => (
              <span key={i} className="text-xs px-2 py-1 rounded-lg bg-surface-muted text-ink-muted"
                title={`${p.a} & ${p.b} move together (corr ${p.corr}) — effectively one bet at ${p.combined_weight}% of the book`}>
                {p.a}↔{p.b} · {p.corr}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Rebalancing suggestions (conviction × volatility targeted) */}
      {risk.target_weights && risk.target_weights.length > 0 && (
        <div>
          <div className="text-[10px] text-ink-faint uppercase tracking-wider mb-1">
            Suggested rebalance (conviction ÷ volatility)
          </div>
          <div className="space-y-1">
            {risk.target_weights.filter(t => Math.abs(t.delta_pct) >= 3).slice(0, 4).map(t => (
              <div key={t.ticker} className="flex items-center justify-between text-xs">
                <span className="font-semibold text-ink">{t.ticker}</span>
                <span className="text-ink-muted">
                  {t.current_pct}% → {t.target_pct}%
                  <span className={clsx('ml-2 font-bold', t.delta_pct > 0 ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400')}>
                    {t.delta_pct > 0 ? '+' : ''}{t.delta_pct}%
                  </span>
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function PositionSizerPanel({ portfolioValue }: { portfolioValue: number }) {
  const [pv, setPv] = useState(portfolioValue > 0 ? portfolioValue.toFixed(0) : '100000')
  const [risk, setRisk] = useState('1')
  const [entry, setEntry] = useState('')
  const [stop, setStop] = useState('')

  const pvN    = parseFloat(pv) || 0
  const riskN  = parseFloat(risk) || 1
  const entryN = parseFloat(entry) || 0
  const stopN  = parseFloat(stop) || 0

  const riskAmt  = pvN * riskN / 100
  const riskPerSh = entryN > 0 && stopN > 0 && entryN > stopN ? entryN - stopN : null
  const shares   = riskPerSh ? Math.floor(riskAmt / riskPerSh) : null
  const posValue = shares && entryN ? shares * entryN : null
  const posWeight = posValue && pvN ? (posValue / pvN * 100) : null
  const stopLossPct = entryN > 0 && stopN > 0 ? ((stopN - entryN) / entryN * 100) : null

  return (
    <div className="max-w-lg space-y-6">
      <div className="card p-5 space-y-4">
        <div>
          <h2 className="font-semibold text-ink mb-1">Position Sizing Calculator</h2>
          <p className="text-xs text-ink-muted">
            Risk only 1–2% of your portfolio per trade. Enter your entry and stop loss to calculate the right position size.
          </p>
        </div>

        {[
          ['Portfolio Value ($)', pv, setPv, '100000'],
          ['Risk per Trade (%)', risk, setRisk, '1'],
          ['Entry Price ($)', entry, setEntry, '150.00'],
          ['Stop Loss Price ($)', stop, setStop, '140.00'],
        ].map(([label, val, setter, placeholder]) => (
          <div key={label as string}>
            <label className="label">{label as string}</label>
            <input type="number" value={val as string}
              onChange={e => (setter as (v: string) => void)(e.target.value)}
              placeholder={placeholder as string} min="0" step="any" className="input" />
          </div>
        ))}
      </div>

      {entryN > 0 && stopN > 0 && (
        <div className="card p-5 space-y-3">
          <h3 className="font-semibold text-ink">Results</h3>
          {entryN <= stopN && (
            <p className="text-sm text-red-600">Entry price must be above stop loss price.</p>
          )}
          {riskPerSh && (
            <div className="grid grid-cols-2 gap-3">
              {[
                { label: 'Risk Amount', value: `$${riskAmt.toLocaleString('en-US', { maximumFractionDigits: 0 })}` },
                { label: 'Risk per Share', value: `$${riskPerSh.toFixed(2)}` },
                { label: 'Shares to Buy', value: shares?.toLocaleString() ?? '—', bold: true },
                { label: 'Position Value', value: posValue ? `$${posValue.toLocaleString('en-US', { maximumFractionDigits: 0 })}` : '—' },
                { label: 'Portfolio Weight', value: posWeight ? `${posWeight.toFixed(1)}%` : '—' },
                { label: 'Stop Loss', value: stopLossPct ? `${stopLossPct.toFixed(1)}%` : '—', color: 'text-red-600' },
              ].map(c => (
                <div key={c.label} className="bg-surface-muted rounded-xl p-3">
                  <div className="text-xs text-ink-faint uppercase tracking-wide">{c.label}</div>
                  <div className={clsx('text-lg font-bold mt-0.5', c.color ?? 'text-ink', c.bold ? 'text-2xl text-primary' : '')}>{c.value}</div>
                </div>
              ))}
            </div>
          )}
          <p className="text-xs text-ink-faint">
            Rule: if this trade hits your stop, you lose exactly ${riskAmt.toFixed(0)} ({risk}% of portfolio).
          </p>
        </div>
      )}
    </div>
  )
}

// ── Main Page ─────────────────────────────────────────────────────────────────

const PLACEHOLDER: HoldingInput[] = [
  { ticker: 'AAPL', shares: 10, avg_cost: 150 },
  { ticker: 'MSFT', shares: 5,  avg_cost: 320 },
  { ticker: 'NVDA', shares: 8,  avg_cost: 400 },
]

type Tab = 'holdings' | 'review' | 'backtest' | 'benchmark' | 'news' | 'sizer'

export function PortfolioPage() {
  const qc = useQueryClient()
  const [rows, setRows] = useState<HoldingInput[]>(PLACEHOLDER)
  const [result, setResult] = useState<PortfolioResult | null>(null)
  const [tab, setTab] = useState<Tab>('holdings')
  const [saveMsg, setSaveMsg] = useState('')

  // Load saved portfolio on mount
  const { data: savedData } = useQuery({
    queryKey: ['portfolio-saved'],
    queryFn: apiGetSavedPortfolio,
    retry: false,
  })

  useEffect(() => {
    if (savedData?.holdings?.length) {
      setRows(savedData.holdings)
    }
  }, [savedData])

  // Analyze portfolio (P&L view)
  const analyzeMut = useMutation({
    mutationFn: apiAnalyzePortfolio,
    onSuccess: setResult,
  })

  // Save portfolio
  const saveMut = useMutation({
    mutationFn: apiSavePortfolio,
    onSuccess: (data) => {
      setSaveMsg(`Saved ${data.saved} holdings`)
      qc.invalidateQueries({ queryKey: ['portfolio-saved'] })
      qc.invalidateQueries({ queryKey: ['portfolio-review'] })
      setTimeout(() => setSaveMsg(''), 3000)
    },
  })

  // Portfolio review (scored recommendations)
  const reviewQuery = useQuery({
    queryKey: ['portfolio-review'],
    queryFn: apiGetPortfolioReview,
    enabled: false,
    retry: false,
  })

  const backtestQuery = useQuery({ queryKey: ['portfolio-backtest'], queryFn: apiGetPortfolioBacktest, enabled: false, retry: false })
  const benchmarkQuery = useQuery({ queryKey: ['portfolio-benchmark'], queryFn: apiGetPortfolioBenchmark, enabled: false, retry: false })
  const newsQuery = useQuery({ queryKey: ['portfolio-news'], queryFn: apiGetPortfolioNews, enabled: false, retry: false })

  function addRow() { setRows(r => [...r, { ticker: '', shares: 0, avg_cost: 0 }]) }
  function removeRow(i: number) { setRows(r => r.filter((_, idx) => idx !== i)) }
  function updateRow(i: number, field: keyof HoldingInput, value: string) {
    setRows(r => r.map((row, idx) =>
      idx !== i ? row : { ...row, [field]: field === 'ticker' ? value.toUpperCase() : parseFloat(value) || 0 }
    ))
  }

  function handleAnalyse() {
    const valid = rows.filter(r => r.ticker.trim() && r.shares > 0 && r.avg_cost > 0)
    if (!valid.length) return
    analyzeMut.mutate(valid)
  }

  function handleSave() {
    const valid = rows.filter(r => r.ticker.trim() && r.shares > 0 && r.avg_cost > 0)
    if (!valid.length) return
    saveMut.mutate(valid)
  }

  function handleGetReview() {
    setTab('review')
    reviewQuery.refetch()
  }

  const s  = result?.summary
  const rv = reviewQuery.data

  return (
    <div className="min-h-screen bg-canvas">
      <div className="max-w-6xl mx-auto px-4 py-6 space-y-6">

        <div className="flex items-start justify-between flex-wrap gap-3">
          <div>
            <h1 className="text-2xl font-bold text-ink">Portfolio Analyzer</h1>
            <p className="text-sm text-ink-muted mt-0.5">
              Enter holdings · save to get daily email review · click "Daily Review" for today's action plan
            </p>
          </div>
          {savedData?.holdings?.length ? (
            <div className="text-xs text-green-700 dark:text-green-400 bg-green-50 dark:bg-green-950/30 px-3 py-1.5 rounded-lg border border-green-200 dark:border-green-800">
              Portfolio saved · included in daily digest
            </div>
          ) : null}
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

          <div className="px-5 py-4 border-t border-surface-border flex items-center gap-3 flex-wrap">
            <button onClick={handleAnalyse} disabled={analyzeMut.isPending}
              className="px-5 py-2 rounded-lg bg-primary text-white font-semibold text-sm disabled:opacity-50 hover:bg-primary/90 transition-colors">
              {analyzeMut.isPending ? 'Analysing…' : 'Analyse Portfolio'}
            </button>
            <button onClick={handleSave} disabled={saveMut.isPending}
              className="px-5 py-2 rounded-lg border border-primary text-primary font-semibold text-sm disabled:opacity-50 hover:bg-primary/10 transition-colors">
              {saveMut.isPending ? 'Saving…' : 'Save Portfolio'}
            </button>
            <button onClick={handleGetReview}
              disabled={reviewQuery.isFetching}
              className="px-5 py-2 rounded-lg bg-green-600 text-white font-semibold text-sm disabled:opacity-50 hover:bg-green-700 transition-colors">
              {reviewQuery.isFetching ? 'Scoring…' : 'Get Daily Review'}
            </button>
            {analyzeMut.isError && (
              <span className="text-xs text-red-500">Analysis failed. Check your tickers.</span>
            )}
            {saveMsg && <span className="text-xs text-green-600">{saveMsg}</span>}
            {saveMut.isError && (
              <span className="text-xs text-red-500">
                Save failed: {(saveMut.error as any)?.response?.data?.detail || 'Please try again'}
              </span>
            )}
          </div>
        </div>

        {/* Tabs */}
        {(result || rv || true) && (
          <div className="flex gap-1 bg-surface-muted rounded-xl p-1 w-fit flex-wrap">
            {(['holdings', 'review', 'backtest', 'benchmark', 'news', 'sizer'] as Tab[]).map(t => (
              <button key={t} onClick={() => {
                setTab(t)
                if (t === 'backtest') backtestQuery.refetch()
                if (t === 'benchmark') benchmarkQuery.refetch()
                if (t === 'news') newsQuery.refetch()
              }}
                className={clsx('px-4 py-1.5 rounded-lg text-sm font-medium transition-colors',
                  tab === t ? 'bg-surface text-ink shadow-sm' : 'text-ink-muted hover:text-ink')}>
                {t === 'holdings' ? 'P&L Overview' :
                 t === 'review'   ? 'Daily Review' :
                 t === 'backtest' ? 'Backtest' :
                 t === 'benchmark'? 'Benchmark' :
                 t === 'news'     ? 'News' :
                 'Position Sizer'}
              </button>
            ))}
          </div>
        )}

        {/* P&L: prompt to analyse first */}
        {tab === 'holdings' && !result && (
          <div className="card p-8 text-center text-ink-muted text-sm">
            Click <strong>Analyse Portfolio</strong> above to see your P&amp;L overview.
          </div>
        )}

        {/* P&L Overview Tab */}
        {tab === 'holdings' && result && s && (
          <div className="space-y-6">
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

            {/* Portfolio sparkline — compute from holdings data (current snapshot) */}
            {(() => {
              // Build a simple bar chart from the holdings showing value distribution
              const holdingBars = result.holdings
                .filter(h => h.current_value != null && !h.error)
                .sort((a, b) => (b.current_value ?? 0) - (a.current_value ?? 0))
                .map(h => ({
                  ticker: h.ticker,
                  value: h.current_value ?? 0,
                  pnl_pct: h.pnl_pct ?? 0,
                }))

              if (holdingBars.length === 0) return null

              return (
                <div className="card p-5">
                  <h3 className="text-sm font-semibold text-ink mb-4">Holdings by Value</h3>
                  <ResponsiveContainer width="100%" height={160}>
                    <AreaChart data={holdingBars} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
                      <XAxis dataKey="ticker" tick={{ fontSize: 11, fill: 'var(--color-ink-muted)' }} tickLine={false} axisLine={false} />
                      <YAxis tick={{ fontSize: 10, fill: 'var(--color-ink-faint)' }} tickLine={false} axisLine={false}
                        tickFormatter={(v: number) => v >= 1000 ? `$${(v/1000).toFixed(0)}k` : `$${v.toFixed(0)}`} width={52} />
                      <Tooltip
                        contentStyle={{ background: 'var(--color-surface)', border: '1px solid var(--color-surface-border)', borderRadius: 8, fontSize: 12 }}
                        formatter={(v, _name, props: any) => [
                          `$${Number(v).toLocaleString('en-US', {maximumFractionDigits: 0})} (${props.payload.pnl_pct >= 0 ? '+' : ''}${props.payload.pnl_pct.toFixed(1)}%)`,
                          'Value'
                        ]} />
                      <Area type="monotone" dataKey="value"
                        stroke="var(--color-primary)"
                        fill="var(--color-primary)"
                        fillOpacity={0.15}
                        strokeWidth={2} dot={{ r: 3, fill: 'var(--color-primary)' }} />
                    </AreaChart>
                  </ResponsiveContainer>
                </div>
              )
            })()}

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

            <div className="bg-surface rounded-2xl border border-surface-border shadow-card overflow-hidden">
              <div className="px-5 py-4 border-b border-surface-border">
                <span className="font-semibold text-ink text-sm">Holdings Detail</span>
              </div>
              <div className="overflow-x-auto">
                <div className="min-w-[700px]">
                  <div className="grid grid-cols-[80px_1fr_80px_80px_80px_80px_60px] gap-2 px-5 py-2 text-xs text-ink-faint uppercase tracking-wide border-b border-surface-border">
                    <span>Ticker</span><span>Company</span>
                    <span className="text-right">Price</span><span className="text-right">Value</span>
                    <span className="text-right">Cost</span><span className="text-right">P&L</span>
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

        {/* Daily Review Tab */}
        {tab === 'review' && (
          <div className="space-y-6">
            {reviewQuery.isFetching && (
              <div className="bg-surface rounded-2xl border border-surface-border shadow-card p-8 text-center">
                <div className="text-ink-muted text-sm">Scoring your holdings — this takes 20–60 seconds…</div>
                <div className="mt-3 flex justify-center gap-1">
                  {[0, 1, 2].map(i => (
                    <div key={i} className="w-2 h-2 bg-primary rounded-full animate-bounce"
                      style={{ animationDelay: `${i * 0.15}s` }} />
                  ))}
                </div>
              </div>
            )}

            {reviewQuery.isError && !reviewQuery.isFetching && (
              <div className="bg-red-50 dark:bg-red-950/20 border border-red-200 dark:border-red-800 rounded-2xl p-5 text-sm text-red-700 dark:text-red-400">
                Could not load review. Save your portfolio first, then try again.
              </div>
            )}

            {!reviewQuery.isFetching && !rv && !reviewQuery.isError && (
              <div className="card p-8 text-center text-ink-muted text-sm">
                Click <strong>Get Daily Review</strong> above to score your holdings and get action recommendations.
              </div>
            )}

            {rv && !reviewQuery.isFetching && (
              <>
                {/* Health + summary */}
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
                  {/* Health score */}
                  <div className="bg-surface rounded-2xl border border-surface-border shadow-card p-4">
                    <div className="text-xs text-ink-faint uppercase tracking-wide mb-1">Portfolio Health</div>
                    <div className={clsx('text-xl font-bold',
                      rv.summary.health_score >= 65 ? 'text-green-600 dark:text-green-400' :
                      rv.summary.health_score >= 50 ? 'text-blue-600 dark:text-blue-400' :
                      rv.summary.health_score >= 35 ? 'text-amber-600 dark:text-amber-400' :
                      'text-red-600 dark:text-red-400')}>
                      {rv.summary.health_score.toFixed(0)}/100
                    </div>
                    <div className="text-xs text-ink-muted mt-0.5">{rv.summary.num_holdings} holdings scored</div>
                  </div>

                  {/* P&L */}
                  <div className="bg-surface rounded-2xl border border-surface-border shadow-card p-4">
                    <div className="text-xs text-ink-faint uppercase tracking-wide mb-1">Total P&L</div>
                    <div className={clsx('text-xl font-bold', pnlColor(rv.summary.total_pnl))}>
                      {fmt$(rv.summary.total_pnl)}
                    </div>
                    <div className={clsx('text-xs mt-0.5', pnlColor(rv.summary.total_pnl_pct))}>
                      {pct(rv.summary.total_pnl_pct)}
                    </div>
                  </div>

                  {/* Action counts */}
                  {(['sell', 'add_more'] as PortfolioAction[]).map(a => {
                    const count = rv.summary.action_counts[a] ?? 0
                    const s = ACTION_STYLES[a]
                    return (
                      <div key={a} className="bg-surface rounded-2xl border border-surface-border shadow-card p-4">
                        <div className="text-xs text-ink-faint uppercase tracking-wide mb-1">
                          {a === 'sell' ? 'Exit Signals' : 'Add More'}
                        </div>
                        <div className={clsx('text-xl font-bold', s.text.split(' ')[0])}>{count}</div>
                        <div className="text-xs text-ink-muted mt-0.5">
                          {a === 'sell' ? 'holdings to exit' : 'conviction adds'}
                        </div>
                      </div>
                    )
                  })}
                </div>

                {/* Top recommendation */}
                <div className="bg-blue-50 dark:bg-blue-950/30 border border-blue-200 dark:border-blue-800 rounded-2xl p-4">
                  <div className="text-xs font-bold text-blue-600 dark:text-blue-400 uppercase tracking-wide mb-1">
                    Today's Top Recommendation
                  </div>
                  <div className="text-sm text-ink">{rv.summary.top_recommendation}</div>
                </div>

                {/* Portfolio-level risk analytics */}
                <PortfolioRiskCard risk={rv.risk} />

                {/* Holdings review table */}
                <div className="bg-surface rounded-2xl border border-surface-border shadow-card overflow-hidden">
                  <div className="px-5 py-4 border-b border-surface-border flex items-center justify-between">
                    <span className="font-semibold text-ink text-sm">Holding-by-Holding Action Plan</span>
                    <span className="text-xs text-ink-faint">Click a row to see the reasoning</span>
                  </div>
                  <div className="overflow-x-auto">
                    <div className="min-w-[700px] px-5">
                      {/* Header */}
                      <div className="grid grid-cols-[80px_1fr_110px_140px_80px_80px] gap-2 py-2 text-xs text-ink-faint uppercase tracking-wide border-b border-surface-border">
                        <span>Ticker</span>
                        <span>Company</span>
                        <span>Action</span>
                        <span>Scores</span>
                        <span className="text-center">RS</span>
                        <span className="text-right">P&L</span>
                      </div>
                      {rv.holdings.map(h => (
                        <ScoredHoldingRow key={h.ticker} h={h as ScoredHolding} />
                      ))}
                    </div>
                  </div>
                </div>

                {/* Legend */}
                <div className="flex flex-wrap gap-3 justify-center text-xs text-ink-muted">
                  {(Object.entries(ACTION_STYLES) as [PortfolioAction, typeof ACTION_STYLES[PortfolioAction]][]).map(([a, s]) => (
                    <div key={a} className={clsx('flex items-center gap-1.5 px-2.5 py-1 rounded-full', s.bg, s.text)}>
                      <span className="font-bold">{s.label}</span>
                      <span className="opacity-70">—</span>
                      <span>{a === 'add_more' ? 'Strong signals — build position' :
                             a === 'hold'     ? 'Neutral — stay the course' :
                             a === 'reduce'   ? 'Trim risk or protect gains' :
                             'Exit — poor momentum'}</span>
                    </div>
                  ))}
                </div>

                <p className="text-xs text-ink-faint text-center">
                  Scores based on technical momentum (ST), fundamental quality (LT), and relative strength vs SPY (RS).
                  Not investment advice · ~15 min delayed data
                </p>
              </>
            )}
          </div>
        )}

        {/* Backtest Tab */}
        {tab === 'backtest' && (
          <div className="space-y-4">
            {backtestQuery.isFetching && (
              <div className="card p-8 text-center text-ink-muted text-sm">Loading historical performance data…</div>
            )}
            {backtestQuery.isError && !backtestQuery.isFetching && (
              <div className="card p-5 text-red-600 text-sm">Failed to load backtest data. Save your portfolio first.</div>
            )}
            {!backtestQuery.isFetching && !backtestQuery.data && !backtestQuery.isError && (
              <div className="card p-8 text-center text-ink-muted text-sm">
                Click the <strong>Backtest</strong> tab to load historical return data for your holdings vs SPY.
              </div>
            )}
            {backtestQuery.data && !backtestQuery.isFetching && (() => {
              const bt = backtestQuery.data as BacktestResult
              const spy = bt.spy
              return (
                <div className="card overflow-hidden">
                  <div className="px-5 py-4 border-b border-surface-border">
                    <span className="font-semibold text-ink text-sm">Historical Performance vs SPY</span>
                  </div>
                  <div className="overflow-x-auto">
                    <div className="min-w-[680px] px-5">
                      <div className="grid grid-cols-[100px_80px_80px_80px_80px_80px_80px] gap-2 py-2 text-xs text-ink-faint uppercase tracking-wide border-b border-surface-border">
                        <span>Ticker</span>
                        <span className="text-right">Since Buy</span>
                        <span className="text-right">1W</span>
                        <span className="text-right">1M</span>
                        <span className="text-right">3M</span>
                        <span className="text-right">6M</span>
                        <span className="text-right">1Y</span>
                      </div>
                      {/* SPY reference row */}
                      <div className="grid grid-cols-[100px_80px_80px_80px_80px_80px_80px] gap-2 py-2.5 border-b border-surface-border text-xs bg-surface-muted/30">
                        <span className="font-bold text-ink-muted">SPY (Ref)</span>
                        <span className="text-right text-ink-faint">—</span>
                        {([spy.ret_1w, spy.ret_1m, spy.ret_3m, spy.ret_6m, spy.ret_1y] as (number | null)[]).map((v, i) => (
                          <span key={i} className={clsx('text-right font-medium', v == null ? 'text-ink-faint' : v >= 0 ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400')}>
                            {v == null ? '—' : `${v >= 0 ? '+' : ''}${v.toFixed(1)}%`}
                          </span>
                        ))}
                      </div>
                      {bt.holdings.map(h => (
                        <div key={h.ticker} className="grid grid-cols-[100px_80px_80px_80px_80px_80px_80px] gap-2 py-2.5 border-b border-surface-border last:border-0 text-xs items-center">
                          <span className="font-bold text-ink">{h.ticker}</span>
                          {([h.since_purchase_pct, h.ret_1w, h.ret_1m, h.ret_3m, h.ret_6m, h.ret_1y] as (number | null)[]).map((v, i) => (
                            <span key={i} className={clsx('text-right font-semibold', v == null ? 'text-ink-faint' : v >= 0 ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400')}>
                              {v == null ? '—' : `${v >= 0 ? '+' : ''}${v.toFixed(1)}%`}
                            </span>
                          ))}
                        </div>
                      ))}
                    </div>
                  </div>
                  <p className="px-5 py-3 text-xs text-ink-faint border-t border-surface-border">
                    "Since Buy" = return from avg cost basis to today · all other periods are trailing market returns
                  </p>
                </div>
              )
            })()}
          </div>
        )}

        {/* Benchmark Tab */}
        {tab === 'benchmark' && (
          <div className="space-y-4">
            {benchmarkQuery.isFetching && (
              <div className="card p-8 text-center text-ink-muted text-sm">Loading benchmark comparison…</div>
            )}
            {benchmarkQuery.isError && !benchmarkQuery.isFetching && (
              <div className="card p-5 text-red-600 text-sm">Failed to load benchmark data. Save your portfolio first.</div>
            )}
            {!benchmarkQuery.isFetching && !benchmarkQuery.data && !benchmarkQuery.isError && (
              <div className="card p-8 text-center text-ink-muted text-sm">
                Click <strong>Benchmark</strong> to compare your portfolio return vs SPY, QQQ, and other indices.
              </div>
            )}
            {benchmarkQuery.data && !benchmarkQuery.isFetching && (() => {
              const bm = benchmarkQuery.data as BenchmarkResult
              return (
                <div className="space-y-4">
                  <div className="grid grid-cols-2 sm:grid-cols-3 gap-4">
                    <div className="card p-4">
                      <div className="text-xs text-ink-faint uppercase tracking-wide mb-1">Your Portfolio Return</div>
                      <div className={clsx('text-2xl font-bold', bm.portfolio_return >= 0 ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400')}>
                        {bm.portfolio_return >= 0 ? '+' : ''}{bm.portfolio_return.toFixed(1)}%
                      </div>
                      <div className="text-xs text-ink-faint mt-0.5">vs avg cost basis</div>
                    </div>
                    <div className="card p-4">
                      <div className="text-xs text-ink-faint uppercase tracking-wide mb-1">Portfolio Value</div>
                      <div className="text-2xl font-bold text-ink">{fmt$(bm.total_value)}</div>
                      <div className="text-xs text-ink-faint mt-0.5">Cost: {fmt$(bm.total_cost)}</div>
                    </div>
                  </div>
                  <div className="card overflow-hidden">
                    <div className="px-5 py-4 border-b border-surface-border">
                      <span className="font-semibold text-ink text-sm">Benchmark Comparison (trailing returns)</span>
                    </div>
                    <div className="overflow-x-auto">
                      <div className="min-w-[580px] px-5">
                        <div className="grid grid-cols-[160px_80px_80px_80px_80px_80px] gap-2 py-2 text-xs text-ink-faint uppercase tracking-wide border-b border-surface-border">
                          <span>Benchmark</span>
                          <span className="text-right">1W</span>
                          <span className="text-right">1M</span>
                          <span className="text-right">3M</span>
                          <span className="text-right">6M</span>
                          <span className="text-right">1Y</span>
                        </div>
                        {bm.benchmarks.map(b => (
                          <div key={b.symbol} className="grid grid-cols-[160px_80px_80px_80px_80px_80px] gap-2 py-2.5 border-b border-surface-border last:border-0 text-xs items-center">
                            <div>
                              <div className="font-bold text-ink text-sm">{b.symbol}</div>
                              <div className="text-ink-faint">{b.name}</div>
                            </div>
                            {([b.ret_1w, b.ret_1m, b.ret_3m, b.ret_6m, b.ret_1y] as (number | null)[]).map((v, i) => (
                              <span key={i} className={clsx('text-right font-semibold', v == null ? 'text-ink-faint' : v >= 0 ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400')}>
                                {v == null ? '—' : `${v >= 0 ? '+' : ''}${v.toFixed(1)}%`}
                              </span>
                            ))}
                          </div>
                        ))}
                      </div>
                    </div>
                  </div>
                </div>
              )
            })()}
          </div>
        )}

        {/* News Tab */}
        {tab === 'news' && (
          <div className="space-y-4">
            {newsQuery.isFetching && (
              <div className="card p-8 text-center text-ink-muted text-sm">Fetching news and scoring sentiment with AI…</div>
            )}
            {newsQuery.isError && !newsQuery.isFetching && (
              <div className="card p-5 text-red-600 text-sm">Failed to load news. Save your portfolio first.</div>
            )}
            {!newsQuery.isFetching && !newsQuery.data && !newsQuery.isError && (
              <div className="card p-8 text-center text-ink-muted text-sm">
                Click <strong>News</strong> to load the latest news and AI sentiment for each holding.
              </div>
            )}
            {newsQuery.data && !newsQuery.isFetching && (newsQuery.data as TickerNews[]).map(tn => (
              <div key={tn.ticker} className="card overflow-hidden">
                <div className="px-5 py-3 border-b border-surface-border flex items-center justify-between flex-wrap gap-2">
                  <span className="font-bold text-ink text-base">{tn.ticker}</span>
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className={clsx('text-xs px-2.5 py-0.5 rounded-full font-semibold capitalize',
                      tn.sentiment === 'bullish' ? 'bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-300' :
                      tn.sentiment === 'bearish' ? 'bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-300' :
                      'bg-surface-muted text-ink-muted'
                    )}>{tn.sentiment}</span>
                    <span className="text-xs text-ink-faint">{tn.sentiment_reason}</span>
                  </div>
                </div>
                <div className="px-5 py-3 space-y-1">
                  {tn.articles.length === 0 && <div className="text-xs text-ink-faint py-2">No recent news found.</div>}
                  {tn.articles.map((a, i) => (
                    <a key={i} href={a.link} target="_blank" rel="noopener noreferrer"
                      className="flex items-start gap-2 py-2 border-b border-surface-border last:border-0 hover:bg-surface-muted/50 rounded-lg px-2 -mx-2 transition-colors group">
                      <div className="flex-1 min-w-0">
                        <div className="text-sm text-ink font-medium leading-snug group-hover:text-primary">{a.title}</div>
                        <div className="text-xs text-ink-faint mt-0.5">{a.publisher} · {a.published}</div>
                      </div>
                      <span className="text-ink-faint text-xs flex-shrink-0 mt-0.5">↗</span>
                    </a>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Position Sizer Tab */}
        {tab === 'sizer' && (
          <PositionSizerPanel portfolioValue={result?.summary.total_value ?? (reviewQuery.data?.summary.total_value ?? 0)} />
        )}

      </div>
    </div>
  )
}
