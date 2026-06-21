import { useQuery } from '@tanstack/react-query'
import { clsx } from 'clsx'
import { apiMarketOverview } from '../api/market'
import { MarketTicker } from '../types'
import { useMarketStore } from '../store/market'
import { MarketSelector } from '../components/ui/MarketSelector'

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtPrice(v: number | null, decimals = 2): string {
  if (v == null) return '—'
  if (v >= 1000) return v.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  return v.toFixed(decimals)
}

function fmtChange(v: number | null, decimals = 2): string {
  if (v == null) return '—'
  return `${v >= 0 ? '+' : ''}${v.toFixed(decimals)}`
}

function chgColor(v: number | null): string {
  if (v == null) return 'text-ink-faint'
  return v > 0 ? 'text-green-500' : v < 0 ? 'text-red-500' : 'text-ink-muted'
}

function chgBg(v: number | null): string {
  if (v == null) return 'bg-surface-muted'
  if (v > 1)  return 'bg-green-600'
  if (v > 0)  return 'bg-green-400'
  if (v < -1) return 'bg-red-600'
  if (v < 0)  return 'bg-red-400'
  return 'bg-ink-faint'
}

// ── Index Card ────────────────────────────────────────────────────────────────

function IndexCard({ t }: { t: MarketTicker }) {
  const isVix = t.symbol === '^VIX'
  const vixLevel =
    isVix && t.price != null
      ? t.price < 15 ? { label: 'Low Fear',  color: 'text-green-500' }
      : t.price < 20 ? { label: 'Normal',    color: 'text-ink-muted' }
      : t.price < 30 ? { label: 'Elevated',  color: 'text-yellow-500' }
      :                { label: 'High Fear', color: 'text-red-500' }
      : null

  return (
    <div className="bg-surface rounded-2xl border border-surface-border shadow-card p-5 flex flex-col gap-2">
      <div className="flex items-start justify-between">
        <div>
          <div className="text-xs font-bold text-ink-faint uppercase tracking-wide">{t.symbol.replace('^', '')}</div>
          <div className="text-sm font-semibold text-ink mt-0.5">{t.name}</div>
        </div>
        {isVix && vixLevel && (
          <span className={clsx('text-xs font-bold px-2 py-0.5 rounded-full bg-surface-muted', vixLevel.color)}>
            {vixLevel.label}
          </span>
        )}
        {!isVix && t.change_pct != null && (
          <span className={clsx(
            'text-xs font-bold px-2 py-0.5 rounded-full',
            t.change_pct > 0 ? 'bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-400'
            : t.change_pct < 0 ? 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-400'
            : 'bg-surface-muted text-ink-muted',
          )}>
            {fmtChange(t.change_pct)}%
          </span>
        )}
      </div>

      <div className="mt-1">
        <div className="text-2xl font-extrabold text-ink">{fmtPrice(t.price)}</div>
        <div className={clsx('text-sm font-medium mt-0.5', chgColor(t.change_pct))}>
          {fmtChange(t.change)} &nbsp;({fmtChange(t.change_pct)}%)
        </div>
      </div>

      {t.pos_52w != null && (
        <div className="mt-1">
          <div className="flex justify-between text-xs text-ink-faint mb-1">
            <span>52W Low</span>
            <span>{t.pos_52w.toFixed(0)}% from low</span>
            <span>52W High</span>
          </div>
          <div className="relative h-1.5 bg-surface-muted rounded-full">
            <div className="absolute top-0 left-0 h-full bg-primary rounded-full" style={{ width: `${t.pos_52w}%` }} />
          </div>
        </div>
      )}

      {t.day_high != null && t.day_low != null && (
        <div className="text-xs text-ink-faint">
          Day: {fmtPrice(t.day_low)} – {fmtPrice(t.day_high)}
        </div>
      )}
    </div>
  )
}

// ── Sector Row ────────────────────────────────────────────────────────────────

function SectorBar({ t, maxAbs, currency = '$' }: { t: MarketTicker; maxAbs: number; currency?: string }) {
  const pct   = t.change_pct ?? 0
  const width = maxAbs > 0 ? Math.abs(pct) / maxAbs * 100 : 0

  return (
    <div className="flex items-center gap-3">
      <div className="w-32 text-xs font-medium text-ink truncate flex-shrink-0">{t.name}</div>
      <div className="flex-1">
        <div className="relative h-5 bg-surface-muted rounded overflow-hidden">
          <div
            className={clsx('absolute top-0 h-full rounded transition-all', chgBg(t.change_pct))}
            style={{ width: `${width}%`, left: pct >= 0 ? '50%' : `${50 - width}%` }}
          />
          <div className="absolute inset-0 flex items-center justify-center">
            <span className="text-xs font-bold text-white drop-shadow" style={{ textShadow: '0 0 4px rgba(0,0,0,0.6)' }}>
              {fmtChange(t.change_pct)}%
            </span>
          </div>
        </div>
      </div>
      <div className="w-20 text-right text-xs font-semibold text-ink flex-shrink-0">
        {currency}{fmtPrice(t.price)}
      </div>
    </div>
  )
}

// ── Asset Card ────────────────────────────────────────────────────────────────

function AssetCard({ t }: { t: MarketTicker }) {
  return (
    <div className="bg-surface rounded-xl border border-surface-border p-4 flex items-center justify-between gap-3">
      <div className="min-w-0">
        <div className="text-xs font-bold text-ink-faint uppercase tracking-wide">{t.symbol.replace('-USD', '')}</div>
        <div className="text-sm font-semibold text-ink truncate">{t.name}</div>
      </div>
      <div className="text-right flex-shrink-0">
        <div className="text-base font-bold text-ink">{fmtPrice(t.price, t.price != null && t.price < 1 ? 6 : 2)}</div>
        <div className={clsx('text-xs font-semibold', chgColor(t.change_pct))}>
          {fmtChange(t.change_pct)}%
        </div>
      </div>
    </div>
  )
}

// ── Skeleton ──────────────────────────────────────────────────────────────────

function Skeleton({ className }: { className?: string }) {
  return <div className={clsx('animate-pulse bg-surface-muted rounded', className)} />
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export function MarketDashboard() {
  const selectedCountry = useMarketStore(s => s.selectedCountry)
  const marketId = selectedCountry?.id ?? 'all'
  const currency = selectedCountry?.currency ?? '$'

  const { data, isLoading, isError, dataUpdatedAt, refetch, isFetching } = useQuery({
    queryKey:        ['market-overview', marketId],
    queryFn:         () => apiMarketOverview(marketId),
    refetchInterval: 60_000,
    staleTime:       30_000,
  })

  const lastUpdated = dataUpdatedAt
    ? new Date(dataUpdatedAt).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
    : null

  const dataAgeSeconds = dataUpdatedAt ? (Date.now() - dataUpdatedAt) / 1000 : 0
  const isStale = dataAgeSeconds > 900 && data?.market_open

  const sectors    = [...(data?.sectors ?? [])].sort((a, b) => (b.change_pct ?? 0) - (a.change_pct ?? 0))
  const maxSectorAbs = Math.max(...sectors.map(s => Math.abs(s.change_pct ?? 0)), 0.01)

  return (
    <div className="min-h-screen bg-canvas">
      <div className="max-w-7xl mx-auto px-4 py-6 space-y-6">

        {/* Header */}
        <div className="space-y-4">
          <div className="flex items-start justify-between flex-wrap gap-3">
            <div>
              <h1 className="text-2xl font-bold text-ink">Market Overview</h1>
              {data && (
                <p className="text-sm text-ink-muted mt-0.5">
                  As of {data.as_of} &nbsp;·&nbsp;
                  <span className={data.market_open ? 'text-green-500 font-semibold' : 'text-red-500 font-semibold'}>
                    {data.market_open ? '🟢 Market Open' : '🔴 Market Closed'}
                  </span>
                </p>
              )}
            </div>
            <div className="flex items-center gap-3">
              {lastUpdated && <span className="text-xs text-ink-faint">Updated {lastUpdated}</span>}
              <button
                onClick={() => refetch()}
                disabled={isFetching}
                className={clsx(
                  'text-xs px-3 py-1.5 rounded-lg border border-surface-border bg-surface text-ink-muted font-medium transition-all hover:border-primary/50 hover:text-ink',
                  isFetching && 'opacity-50 cursor-wait',
                )}
              >
                {isFetching ? 'Refreshing…' : '↻ Refresh'}
              </button>
            </div>
          </div>

          {/* Market selector */}
          <div className="bg-surface rounded-2xl border border-surface-border shadow-sm p-4">
            <MarketSelector onCountryChange={() => refetch()} />
          </div>
        </div>

        {isStale && (
          <div className="flex items-center gap-2 bg-amber-50 border border-amber-200 rounded-xl px-4 py-2.5 dark:bg-amber-900/20 dark:border-amber-700">
            <span className="text-amber-500 flex-shrink-0">⚠</span>
            <p className="text-xs text-amber-800 dark:text-amber-300">
              Market data is over 15 minutes old during market hours — prices may not reflect current conditions.{' '}
              <button onClick={() => refetch()} className="underline font-semibold">Refresh now</button>
            </p>
          </div>
        )}

        {isError && (
          <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-xl p-4 text-sm text-red-700 dark:text-red-400">
            Failed to load market data. Check that the backend is running.
          </div>
        )}

        {/* Major Indices */}
        <section>
          <h2 className="text-xs font-bold uppercase tracking-widest text-ink-faint mb-3">Major Indices</h2>
          {isLoading ? (
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-4">
              {Array.from({ length: 5 }).map((_, i) => (
                <div key={i} className="bg-surface rounded-2xl border border-surface-border p-5 space-y-3">
                  <Skeleton className="h-4 w-20" /><Skeleton className="h-8 w-28" /><Skeleton className="h-3 w-16" />
                </div>
              ))}
            </div>
          ) : (
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-4">
              {data?.indices.map(t => <IndexCard key={t.symbol} t={t} />)}
            </div>
          )}
        </section>

        {/* Sector Performance */}
        <section>
          <h2 className="text-xs font-bold uppercase tracking-widest text-ink-faint mb-3">Sector Performance (ETFs)</h2>
          <div className="bg-surface rounded-2xl border border-surface-border shadow-card p-5">
            {isLoading ? (
              <div className="space-y-3">{Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} className="h-5 w-full" />)}</div>
            ) : (
              <div className="space-y-2">{sectors.map(t => <SectorBar key={t.symbol} t={t} maxAbs={maxSectorAbs} currency={currency} />)}</div>
            )}
            <div className="mt-4 pt-3 border-t border-surface-border flex gap-4 text-xs text-ink-faint">
              <span className="flex items-center gap-1.5"><span className="w-3 h-2 rounded bg-green-500 inline-block" />Gaining</span>
              <span className="flex items-center gap-1.5"><span className="w-3 h-2 rounded bg-red-500 inline-block" />Losing</span>
              <span className="ml-auto">Sorted by day change · bars centred at 0%</span>
            </div>
          </div>
        </section>

        {/* Commodities + Crypto */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <section>
            <h2 className="text-xs font-bold uppercase tracking-widest text-ink-faint mb-3">Commodities & Bonds</h2>
            {isLoading
              ? <div className="space-y-2">{Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-16 rounded-xl" />)}</div>
              : <div className="space-y-2">{data?.commodities.map(t => <AssetCard key={t.symbol} t={t} />)}</div>}
          </section>
          <section>
            <h2 className="text-xs font-bold uppercase tracking-widest text-ink-faint mb-3">Crypto</h2>
            {isLoading
              ? <div className="space-y-2">{Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-16 rounded-xl" />)}</div>
              : <div className="space-y-2">{data?.crypto.map(t => <AssetCard key={t.symbol} t={t} />)}</div>}
          </section>
        </div>

        <p className="text-xs text-ink-faint text-center pb-2">
          Data from Yahoo Finance · Auto-refreshes every 60 seconds · ~15 min delay during market hours ·{' '}
          <span className="font-medium">Not investment advice</span>
        </p>
      </div>
    </div>
  )
}
