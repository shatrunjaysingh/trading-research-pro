import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { clsx } from 'clsx'
import client from '../api/client'

interface ScreenerResult {
  ticker: string
  company: string
  price: number
  day_change_pct: number | null
  rs_score: number
  st_score: number
  lt_score: number | null
  st_signal: string
  composite: number
}

const apiScreenStocks = (params: { min_st: number; min_lt: number; min_rs: number; min_price: number }) =>
  client.get<{ results: ScreenerResult[]; universe_size: number }>('/research/screen', { params }).then(r => r.data)

function ScorePill({ score }: { score: number }) {
  const color = score >= 70 ? 'bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-300'
    : score >= 50 ? 'bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300'
    : score >= 35 ? 'bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-300'
    : 'bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-300'
  return (
    <span className={clsx('inline-flex items-center justify-center w-10 h-6 rounded text-xs font-bold tabular-nums', color)}>
      {score.toFixed(0)}
    </span>
  )
}

export function ScreenerPage() {
  const [minSt,    setMinSt]    = useState(60)
  const [minLt,    setMinLt]    = useState(0)
  const [minRs,    setMinRs]    = useState(60)
  const [minPrice, setMinPrice] = useState(5)
  const [enabled,  setEnabled]  = useState(false)
  const [params,   setParams]   = useState({ min_st: 60, min_lt: 0, min_rs: 60, min_price: 5 })

  const { data, isLoading, isFetching } = useQuery({
    queryKey: ['screener', params],
    queryFn:  () => apiScreenStocks(params),
    enabled,
    staleTime: 1000 * 60 * 5,
  })

  function handleRun() {
    setParams({ min_st: minSt, min_lt: minLt, min_rs: minRs, min_price: minPrice })
    setEnabled(true)
  }

  const results = data?.results ?? []

  return (
    <div className="max-w-6xl mx-auto px-4 py-6 space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-ink">Stock Screener</h1>
        <p className="text-sm text-ink-muted mt-0.5">
          Filter S&amp;P 100 + your watchlist by momentum scores. Scores run live — takes 30–90 seconds.
        </p>
      </div>

      {/* Filters */}
      <div className="card p-5">
        <h2 className="font-semibold text-ink text-sm mb-4">Filter Criteria</h2>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-4">
          {[
            { label: 'Min ST Score (momentum)', value: minSt, setter: setMinSt, hint: '60+ = good momentum' },
            { label: 'Min LT Score (fundamentals)', value: minLt, setter: setMinLt, hint: '0 = include all' },
            { label: 'Min RS Score (vs SPY)', value: minRs, setter: setMinRs, hint: '60+ = outperforming' },
            { label: 'Min Price ($)', value: minPrice, setter: setMinPrice, hint: 'filter out penny stocks' },
          ].map(({ label, value, setter, hint }) => (
            <div key={label}>
              <label className="label">{label}</label>
              <input type="number" value={value}
                onChange={e => setter(Number(e.target.value))}
                min="0" max="100" step="5"
                className="input text-sm" />
              <p className="text-xs text-ink-faint mt-0.5">{hint}</p>
            </div>
          ))}
        </div>

        {/* Preset buttons */}
        <div className="flex flex-wrap gap-2 mb-4">
          {[
            { label: 'IBD Leaders', minSt: 70, minLt: 65, minRs: 75, minPrice: 10 },
            { label: 'High Momentum', minSt: 75, minLt: 0, minRs: 70, minPrice: 5 },
            { label: 'Quality Growth', minSt: 55, minLt: 70, minRs: 60, minPrice: 20 },
            { label: 'All Stocks', minSt: 0, minLt: 0, minRs: 0, minPrice: 1 },
          ].map(preset => (
            <button key={preset.label}
              onClick={() => { setMinSt(preset.minSt); setMinLt(preset.minLt); setMinRs(preset.minRs); setMinPrice(preset.minPrice) }}
              className="text-xs px-3 py-1.5 rounded-lg border border-surface-border text-ink-muted hover:text-ink hover:bg-surface-muted transition-colors">
              {preset.label}
            </button>
          ))}
        </div>

        <button onClick={handleRun} disabled={isLoading || isFetching}
          className="btn-primary px-6 py-2.5 disabled:opacity-50 font-semibold">
          {isFetching ? 'Screening…' : 'Run Screen'}
        </button>
      </div>

      {/* Results */}
      {isFetching && (
        <div className="card p-8 text-center">
          <div className="text-ink-muted text-sm mb-3">Scoring {data?.universe_size ?? '100+'} stocks…</div>
          <div className="flex justify-center gap-1">
            {[0,1,2].map(i => (
              <div key={i} className="w-2 h-2 bg-primary rounded-full animate-bounce" style={{ animationDelay: `${i*0.15}s` }} />
            ))}
          </div>
        </div>
      )}

      {!isFetching && results.length > 0 && (
        <div className="card overflow-hidden">
          <div className="px-5 py-4 border-b border-surface-border flex items-center justify-between flex-wrap gap-2">
            <span className="font-semibold text-ink text-sm">
              {results.length} stocks matched · from {data?.universe_size} screened
            </span>
            <span className="text-xs text-ink-faint">Sorted by composite score (ST×40% + LT×30% + RS×30%)</span>
          </div>
          <div className="overflow-x-auto">
            <div className="min-w-[700px]">
              <div className="grid grid-cols-[80px_1fr_80px_80px_60px_60px_60px_70px] gap-2 px-5 py-2 text-xs text-ink-faint uppercase tracking-wide border-b border-surface-border">
                <span>Ticker</span>
                <span>Company</span>
                <span className="text-right">Price</span>
                <span className="text-right">Day Chg</span>
                <span className="text-center">ST</span>
                <span className="text-center">LT</span>
                <span className="text-center">RS</span>
                <span className="text-center">Score</span>
              </div>
              {results.map(r => (
                <div key={r.ticker}
                  className="grid grid-cols-[80px_1fr_80px_80px_60px_60px_60px_70px] gap-2 px-5 py-3 border-b border-surface-border last:border-0 items-center hover:bg-surface-muted/50 transition-colors text-sm">
                  <div className="font-bold text-ink">{r.ticker}</div>
                  <div className="text-ink-muted text-xs truncate">{r.company}</div>
                  <div className="text-right font-semibold text-ink">${r.price.toFixed(2)}</div>
                  <div className={clsx('text-right text-xs font-semibold',
                    r.day_change_pct == null ? 'text-ink-faint' :
                    r.day_change_pct >= 0 ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400')}>
                    {r.day_change_pct == null ? '—' : `${r.day_change_pct >= 0 ? '+' : ''}${r.day_change_pct.toFixed(2)}%`}
                  </div>
                  <div className="flex justify-center"><ScorePill score={r.st_score} /></div>
                  <div className="flex justify-center"><ScorePill score={r.lt_score ?? 0} /></div>
                  <div className="flex justify-center"><ScorePill score={r.rs_score} /></div>
                  <div className="flex justify-center">
                    <span className={clsx('text-sm font-bold', r.composite >= 70 ? 'text-green-600 dark:text-green-400' : r.composite >= 50 ? 'text-blue-600 dark:text-blue-400' : 'text-ink-muted')}>
                      {r.composite.toFixed(0)}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </div>
          <p className="px-5 py-3 text-xs text-ink-faint border-t border-surface-border">
            Scores: ST = short-term momentum · LT = fundamental quality · RS = relative strength vs SPY · Composite = weighted average
          </p>
        </div>
      )}

      {!isFetching && enabled && results.length === 0 && (
        <div className="card p-8 text-center text-ink-muted text-sm">
          No stocks matched your criteria. Try lowering the thresholds.
        </div>
      )}
    </div>
  )
}
