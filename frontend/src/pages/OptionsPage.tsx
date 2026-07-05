import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { clsx } from 'clsx'
import { OptionsFlow, UnusualOption } from '../types'
import { apiScanOptions } from '../api/options'

function PCSignalBadge({ signal }: { signal: string }) {
  const styles: Record<string, string> = {
    bullish: 'bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-300',
    bearish: 'bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-300',
    neutral: 'bg-surface-muted text-ink-muted',
  }
  return <span className={clsx('text-xs px-2 py-0.5 rounded-full font-semibold capitalize', styles[signal] ?? styles.neutral)}>{signal}</span>
}

function UnusualRow({ o }: { o: UnusualOption }) {
  return (
    <div className="flex items-center gap-3 py-2 border-b border-surface-border last:border-0 text-xs">
      <span className={clsx('w-10 text-center font-bold rounded px-1 py-0.5',
        o.type === 'call' ? 'bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-300' :
        'bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-300')}>
        {o.type.toUpperCase()}
      </span>
      <span className="text-ink font-medium">${o.strike.toFixed(0)} · {o.exp}</span>
      <span className="text-ink-muted">Vol: <strong>{o.volume.toLocaleString()}</strong></span>
      <span className="text-ink-muted">OI: {o.open_interest.toLocaleString()}</span>
      <span className={clsx('font-semibold', o.vol_oi_ratio > 5 ? 'text-amber-600' : 'text-ink')}>
        {o.vol_oi_ratio.toFixed(1)}x ratio
      </span>
      <span className="text-ink-faint">IV: {o.iv.toFixed(0)}%</span>
    </div>
  )
}

function OptionsCard({ flow }: { flow: OptionsFlow }) {
  const [open, setOpen] = useState(false)
  const pc = flow.put_call_ratio

  return (
    <div className="card overflow-hidden">
      <button className="w-full text-left px-5 py-4" onClick={() => setOpen(o => !o)}>
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <div className="flex items-center gap-3">
            <span className="text-lg font-bold text-ink">{flow.ticker}</span>
            {flow.price && <span className="text-sm text-ink-muted">${flow.price.toFixed(2)}</span>}
            <PCSignalBadge signal={flow.pc_signal} />
          </div>
          <div className="flex items-center gap-4 text-sm">
            <div className="text-center">
              <div className="text-xs text-ink-faint">P/C Ratio</div>
              <div className={clsx('font-bold', pc > 1.3 ? 'text-red-600' : pc < 0.7 ? 'text-green-600' : 'text-ink')}>{pc.toFixed(2)}</div>
            </div>
            <div className="text-center">
              <div className="text-xs text-ink-faint">Call Vol</div>
              <div className="font-semibold text-green-600">{flow.total_call_vol.toLocaleString()}</div>
            </div>
            <div className="text-center">
              <div className="text-xs text-ink-faint">Put Vol</div>
              <div className="font-semibold text-red-600">{flow.total_put_vol.toLocaleString()}</div>
            </div>
            {flow.avg_iv_pct && (
              <div className="text-center">
                <div className="text-xs text-ink-faint">Avg IV</div>
                <div className="font-semibold text-ink">{flow.avg_iv_pct.toFixed(0)}%</div>
              </div>
            )}
            {flow.unusual_activity.length > 0 && (
              <span className="text-xs bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-300 px-2 py-0.5 rounded-full font-semibold">
                {flow.unusual_activity.length} unusual
              </span>
            )}
            <span className="text-ink-faint text-lg">{open ? '▲' : '▼'}</span>
          </div>
        </div>
      </button>

      {open && flow.unusual_activity.length > 0 && (
        <div className="px-5 pb-4">
          <div className="text-xs font-semibold text-ink-muted uppercase tracking-wide mb-2">Unusual Activity (Vol/OI &gt; 2x)</div>
          {flow.unusual_activity.map((u, i) => <UnusualRow key={i} o={u} />)}
        </div>
      )}
      {open && flow.unusual_activity.length === 0 && (
        <div className="px-5 pb-4 text-xs text-ink-faint">No unusual volume detected.</div>
      )}
    </div>
  )
}

export function OptionsPage() {
  const [customTickers, setCustomTickers] = useState('')
  const [scanTickers, setScanTickers] = useState('')

  const { data = [], isLoading, refetch, isFetching } = useQuery({
    queryKey: ['options-scan', scanTickers],
    queryFn: () => apiScanOptions(scanTickers),
    enabled: false,
    retry: false,
  })

  function handleScan() {
    setScanTickers(customTickers)
    setTimeout(() => refetch(), 50)
  }

  return (
    <div className="max-w-4xl mx-auto px-4 py-6 space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-ink">Options Flow Scanner</h1>
        <p className="text-sm text-ink-muted mt-0.5">
          Put/call ratio, unusual volume, and IV for your watchlist + portfolio.
          High volume/OI ratio = unusual institutional interest.
        </p>
      </div>

      <div className="card p-5">
        <h2 className="font-semibold text-ink text-sm mb-3">Scan Options</h2>
        <div className="flex gap-3 flex-wrap">
          <input value={customTickers}
            onChange={e => setCustomTickers(e.target.value.toUpperCase())}
            placeholder="Leave blank to scan watchlist + portfolio, or enter: AAPL,TSLA,NVDA"
            className="input flex-1 min-w-[240px] font-mono text-sm" />
          <button onClick={handleScan} disabled={isLoading || isFetching}
            className="btn-primary px-5 py-2 disabled:opacity-50">
            {isFetching ? 'Scanning…' : 'Scan Options'}
          </button>
        </div>
        <p className="text-xs text-ink-faint mt-2">Scans the nearest 3 expiration dates. May take 30–60 seconds.</p>
      </div>

      {isFetching && (
        <div className="card p-8 text-center text-ink-muted text-sm">Scanning options chains…</div>
      )}

      {!isFetching && data.length > 0 && (
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold text-ink">{data.length} tickers scanned — sorted by unusual activity</h3>
          </div>
          {data.map(flow => <OptionsCard key={flow.ticker} flow={flow} />)}
        </div>
      )}

      <p className="text-xs text-ink-faint text-center">
        Data from Yahoo Finance · options pricing approximate · not investment advice
      </p>
    </div>
  )
}
