import { useQuery } from '@tanstack/react-query'
import { clsx } from 'clsx'
import { EarningsEntry } from '../types'
import { apiGetEarningsCalendar } from '../api/earnings'

function fmt$(v: number | null) {
  if (v == null) return '—'
  if (Math.abs(v) >= 1e9) return `$${(v/1e9).toFixed(1)}B`
  if (Math.abs(v) >= 1e6) return `$${(v/1e6).toFixed(1)}M`
  return `$${v.toFixed(2)}`
}

function RiskBadge({ level }: { level: 'high' | 'medium' | 'low' }) {
  const styles = {
    high:   'bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-300',
    medium: 'bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-300',
    low:    'bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-300',
  }
  return (
    <span className={clsx('text-xs px-2 py-0.5 rounded-full font-semibold uppercase', styles[level])}>
      {level} risk
    </span>
  )
}

function EarningsRow({ e }: { e: EarningsEntry }) {
  const daysText = e.days_out == null ? '—'
    : e.days_out < 0 ? `${Math.abs(e.days_out)}d ago`
    : e.days_out === 0 ? 'TODAY'
    : `in ${e.days_out}d`

  const daysColor = e.days_out == null ? 'text-ink-muted'
    : e.days_out < 0 ? 'text-ink-faint'
    : e.days_out === 0 ? 'text-red-600 font-bold'
    : e.days_out <= 7 ? 'text-amber-600 font-semibold'
    : 'text-ink-muted'

  return (
    <div className="grid grid-cols-[80px_1fr_90px_90px_100px_100px] gap-3 items-center py-3 border-b border-surface-border last:border-0 text-sm">
      <div className="font-bold text-ink">{e.ticker}</div>
      <div>
        <div className="text-ink text-xs font-medium truncate">{e.company}</div>
        <div className="text-ink-faint text-xs truncate">{e.sector}</div>
      </div>
      <div className={clsx('text-center', daysColor)}>{daysText}</div>
      <div className="text-center text-xs text-ink-muted">{e.earnings_date?.slice(0, 10) ?? '—'}</div>
      <div className="text-right">
        <div className="text-ink text-xs">{e.eps_estimate != null ? `EPS est. $${e.eps_estimate.toFixed(2)}` : '—'}</div>
        <div className="text-ink-faint text-xs">{e.rev_estimate != null ? `Rev ${fmt$(e.rev_estimate)}` : ''}</div>
      </div>
      <div className="text-right">
        <RiskBadge level={e.risk_level} />
      </div>
    </div>
  )
}

export function EarningsPage() {
  const { data = [], isLoading, error, refetch } = useQuery({
    queryKey: ['earnings-calendar'],
    queryFn: apiGetEarningsCalendar,
    staleTime: 1000 * 60 * 30,
  })

  const upcoming = data.filter(e => (e.days_out ?? 999) >= 0)
  const past     = data.filter(e => (e.days_out ?? 999) < 0)

  return (
    <div className="max-w-5xl mx-auto px-4 py-6 space-y-6">
      <div className="flex items-start justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold text-ink">Earnings Calendar</h1>
          <p className="text-sm text-ink-muted mt-0.5">
            Upcoming earnings dates for your watchlist and saved portfolio holdings.
            High-risk = earnings within 7 days — consider position size carefully.
          </p>
        </div>
        <button onClick={() => refetch()} className="btn-secondary text-sm px-4 py-2">Refresh</button>
      </div>

      {isLoading && (
        <div className="card p-8 text-center text-ink-muted text-sm">Loading earnings data…</div>
      )}

      {error && (
        <div className="card p-5 text-red-600 text-sm">
          Failed to load earnings data. Make sure you have holdings saved in your portfolio or watchlist.
        </div>
      )}

      {!isLoading && !error && data.length === 0 && (
        <div className="card p-8 text-center">
          <p className="text-ink-muted text-sm">No earnings data found.</p>
          <p className="text-ink-faint text-xs mt-1">Add stocks to your Watchlist or save your Portfolio to see upcoming earnings.</p>
        </div>
      )}

      {upcoming.length > 0 && (
        <div className="card overflow-hidden">
          <div className="px-5 py-4 border-b border-surface-border">
            <span className="font-semibold text-ink text-sm">Upcoming Earnings ({upcoming.length})</span>
          </div>
          <div className="overflow-x-auto">
            <div className="min-w-[600px] px-5">
              <div className="grid grid-cols-[80px_1fr_90px_90px_100px_100px] gap-3 py-2 text-xs text-ink-faint uppercase tracking-wide border-b border-surface-border">
                <span>Ticker</span><span>Company</span>
                <span className="text-center">When</span>
                <span className="text-center">Date</span>
                <span className="text-right">Estimates</span>
                <span className="text-right">Risk</span>
              </div>
              {upcoming.map(e => <EarningsRow key={e.ticker} e={e} />)}
            </div>
          </div>
        </div>
      )}

      {past.length > 0 && (
        <div className="card overflow-hidden">
          <div className="px-5 py-4 border-b border-surface-border">
            <span className="font-semibold text-ink-muted text-sm">Past Earnings ({past.length})</span>
          </div>
          <div className="overflow-x-auto">
            <div className="min-w-[600px] px-5">
              <div className="grid grid-cols-[80px_1fr_90px_90px_100px_100px] gap-3 py-2 text-xs text-ink-faint uppercase tracking-wide border-b border-surface-border">
                <span>Ticker</span><span>Company</span><span className="text-center">When</span><span className="text-center">Date</span><span className="text-right">Estimates</span><span className="text-right">Risk</span>
              </div>
              {past.map(e => <EarningsRow key={e.ticker} e={e} />)}
            </div>
          </div>
        </div>
      )}

      <p className="text-xs text-ink-faint text-center">
        Earnings dates from Yahoo Finance · may be estimated · always verify with the company's IR page
      </p>
    </div>
  )
}
