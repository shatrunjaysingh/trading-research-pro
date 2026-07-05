import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { clsx } from 'clsx'
import { apiGetWatchlist, apiAddToWatchlist, apiRemoveFromWatchlist } from '../api/watchlist'
import { WatchlistItem } from '../types'
import { useNavigate } from 'react-router-dom'

function fmtPrice(v: number | null): string {
  if (v == null) return '—'
  if (v < 1)    return `$${v.toFixed(4)}`
  return `$${v.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

function fmtMktCap(v: number | null): string {
  if (v == null) return '—'
  if (v >= 1e12) return `$${(v / 1e12).toFixed(2)}T`
  if (v >= 1e9)  return `$${(v / 1e9).toFixed(2)}B`
  if (v >= 1e6)  return `$${(v / 1e6).toFixed(2)}M`
  return `$${v.toLocaleString()}`
}

function ChangeChip({ pct }: { pct: number | null }) {
  if (pct == null) return <span className="text-ink-faint text-xs">—</span>
  const pos = pct >= 0
  return (
    <span className={clsx(
      'inline-flex items-center gap-0.5 text-xs font-semibold px-2 py-0.5 rounded-full',
      pos ? 'bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-400'
          : 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-400',
    )}>
      {pos ? '▲' : '▼'} {Math.abs(pct).toFixed(2)}%
    </span>
  )
}

function WatchlistRow({ item, onRemove, onAnalyse }: {
  item: WatchlistItem
  onRemove: (ticker: string) => void
  onAnalyse: (ticker: string) => void
}) {
  const [confirming, setConfirming] = useState(false)

  return (
    <div className="bg-surface rounded-xl border border-surface-border p-4 flex flex-col sm:flex-row sm:items-center gap-3">
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="font-bold text-ink text-base">{item.ticker}</span>
          <ChangeChip pct={item.day_change_pct} />
        </div>
        {item.notes && <p className="text-xs text-ink-muted mt-0.5 truncate">{item.notes}</p>}
        <p className="text-xs text-ink-faint mt-0.5">Added {new Date(item.added_at).toLocaleDateString()}</p>
      </div>

      <div className="flex items-center gap-6 flex-shrink-0">
        <div className="text-right">
          <div className="text-base font-bold text-ink">{fmtPrice(item.price)}</div>
          <div className="text-xs text-ink-faint">{fmtMktCap(item.market_cap)} mkt cap</div>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={() => onAnalyse(item.ticker)}
            className="text-xs px-3 py-1.5 rounded-lg bg-primary text-white font-medium hover:bg-primary/90 transition-colors"
          >
            Analyse
          </button>
          {confirming ? (
            <div className="flex items-center gap-1">
              <button
                onClick={() => { onRemove(item.ticker); setConfirming(false) }}
                className="text-xs px-2 py-1.5 rounded-lg bg-red-600 text-white font-medium"
              >
                Remove
              </button>
              <button
                onClick={() => setConfirming(false)}
                className="text-xs px-2 py-1.5 rounded-lg border border-surface-border text-ink-muted font-medium"
              >
                Cancel
              </button>
            </div>
          ) : (
            <button
              onClick={() => setConfirming(true)}
              className="text-xs px-2 py-1.5 rounded-lg border border-surface-border text-ink-muted hover:border-red-400 hover:text-red-500 font-medium transition-colors"
            >
              ✕
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

export function WatchlistPage() {
  const qc       = useQueryClient()
  const navigate = useNavigate()
  const [input, setInput] = useState('')
  const [notes, setNotes] = useState('')
  const [addErr, setAddErr] = useState('')

  const { data: items = [], isLoading, isError } = useQuery({
    queryKey:        ['watchlist'],
    queryFn:         apiGetWatchlist,
    refetchInterval: 60_000,
    staleTime:       30_000,
  })

  const addMut = useMutation({
    mutationFn: ({ ticker, notes }: { ticker: string; notes: string }) =>
      apiAddToWatchlist(ticker, notes),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['watchlist'] })
      setInput('')
      setNotes('')
      setAddErr('')
    },
    onError: (err: unknown) => {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setAddErr(msg || 'Failed to add ticker. Check the symbol and try again.')
    },
  })

  const removeMut = useMutation({
    mutationFn: apiRemoveFromWatchlist,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['watchlist'] }),
  })

  function handleAdd(e: React.FormEvent) {
    e.preventDefault()
    const t = input.trim().toUpperCase()
    if (!t) return
    setAddErr('')
    addMut.mutate({ ticker: t, notes: notes.trim() })
  }

  const sorted = [...items].sort((a, b) =>
    (b.day_change_pct ?? -Infinity) - (a.day_change_pct ?? -Infinity)
  )

  const totalGainers = items.filter(i => (i.day_change_pct ?? 0) > 0).length
  const totalLosers  = items.filter(i => (i.day_change_pct ?? 0) < 0).length

  return (
    <div className="min-h-screen bg-canvas">
      <div className="max-w-4xl mx-auto px-4 py-6 space-y-6">

        {/* Header */}
        <div>
          <h1 className="text-2xl font-bold text-ink">My Watchlist</h1>
          <p className="text-sm text-ink-muted mt-0.5">Track stocks you're watching · prices refresh every 60s</p>
        </div>

        {/* Add stock form */}
        <form onSubmit={handleAdd} className="bg-surface rounded-2xl border border-surface-border p-4 space-y-3">
          <p className="text-sm font-semibold text-ink">Add a Stock</p>
          <div className="flex gap-2 flex-wrap">
            <input
              value={input}
              onChange={e => setInput(e.target.value.toUpperCase())}
              placeholder="Ticker (e.g. AAPL)"
              className="flex-1 min-w-[120px] px-3 py-2 rounded-lg border border-surface-border bg-canvas text-ink text-sm font-mono focus:outline-none focus:border-primary"
              maxLength={10}
            />
            <input
              value={notes}
              onChange={e => setNotes(e.target.value)}
              placeholder="Notes (optional)"
              className="flex-[2] min-w-[160px] px-3 py-2 rounded-lg border border-surface-border bg-canvas text-ink text-sm focus:outline-none focus:border-primary"
              maxLength={200}
            />
            <button
              type="submit"
              disabled={addMut.isPending || !input.trim()}
              className="px-4 py-2 rounded-lg bg-primary text-white text-sm font-semibold disabled:opacity-50 hover:bg-primary/90 transition-colors"
            >
              {addMut.isPending ? 'Adding…' : '+ Add'}
            </button>
          </div>
          {addErr && <p className="text-xs text-red-500">{addErr}</p>}
        </form>

        {/* Stats bar */}
        {items.length > 0 && (
          <div className="flex gap-4 text-sm flex-wrap">
            <span className="text-ink-faint">{items.length} stocks</span>
            <span className="text-green-500 font-medium">▲ {totalGainers} gaining</span>
            <span className="text-red-500 font-medium">▼ {totalLosers} losing</span>
          </div>
        )}

        {/* List */}
        {isLoading && (
          <div className="space-y-3">
            {[1, 2, 3].map(i => (
              <div key={i} className="bg-surface rounded-xl border border-surface-border p-4 h-20 animate-pulse" />
            ))}
          </div>
        )}

        {isError && (
          <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-xl p-4 text-sm text-red-700 dark:text-red-400">
            Failed to load watchlist. Please refresh.
          </div>
        )}

        {!isLoading && !isError && items.length === 0 && (
          <div className="text-center py-16 text-ink-faint">
            <div className="text-5xl mb-3">👁</div>
            <div className="text-base font-semibold text-ink-muted mb-1">Your watchlist is empty</div>
            <div className="text-sm">Add tickers above to start tracking stocks you're watching.</div>
          </div>
        )}

        {!isLoading && sorted.length > 0 && (
          <div className="space-y-2">
            {sorted.map(item => (
              <WatchlistRow
                key={item.ticker}
                item={item}
                onRemove={(ticker) => removeMut.mutate(ticker)}
                onAnalyse={(ticker) => navigate(`/stocks?ticker=${ticker}`)}
              />
            ))}
          </div>
        )}

        {items.length > 0 && (
          <p className="text-xs text-ink-faint text-center">
            Prices from Yahoo Finance · ~15 min delay during market hours · Not investment advice
          </p>
        )}
      </div>
    </div>
  )
}
