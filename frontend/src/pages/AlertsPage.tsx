import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { clsx } from 'clsx'
import { AlertCondition, PriceAlert } from '../types'
import { apiGetPriceAlerts, apiCreatePriceAlert, apiDeletePriceAlert, apiTogglePriceAlert } from '../api/alerts'

const CONDITIONS: { value: AlertCondition; label: string; needsTarget: boolean }[] = [
  { value: 'above',              label: 'Price rises above $X',       needsTarget: true  },
  { value: 'below',              label: 'Price falls below $X',        needsTarget: true  },
  { value: 'breakout_52w_high',  label: '52-week high breakout',       needsTarget: false },
  { value: 'breakdown_52w_low',  label: '52-week low breakdown',       needsTarget: false },
  { value: 'cross_sma50_up',     label: 'Crosses above 50-day SMA',   needsTarget: false },
  { value: 'cross_sma50_down',   label: 'Crosses below 50-day SMA',   needsTarget: false },
  { value: 'cross_sma200_up',    label: 'Crosses above 200-day SMA',  needsTarget: false },
  { value: 'cross_sma200_down',  label: 'Crosses below 200-day SMA',  needsTarget: false },
]

function AlertCard({ alert, onDelete, onToggle }: { alert: PriceAlert; onDelete: (id: number) => void; onToggle: (id: number) => void }) {
  const cond = CONDITIONS.find(c => c.value === alert.condition)
  const isTriggered = !!alert.triggered_at

  return (
    <div className={clsx('card p-4 flex items-start justify-between gap-3',
      isTriggered ? 'opacity-60' : '')}>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="font-bold text-ink text-base">{alert.ticker}</span>
          <span className={clsx('text-xs px-2 py-0.5 rounded-full font-medium',
            isTriggered ? 'bg-surface-muted text-ink-faint' :
            alert.is_active ? 'bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-300' :
            'bg-surface-muted text-ink-faint')}>
            {isTriggered ? 'Triggered' : alert.is_active ? 'Active' : 'Paused'}
          </span>
        </div>
        <div className="text-sm text-ink-muted mt-0.5">{cond?.label ?? alert.condition}</div>
        {alert.target_price != null && (
          <div className="text-xs text-ink-faint mt-0.5">Target: <strong>${Number(alert.target_price).toFixed(2)}</strong></div>
        )}
        {alert.note && <div className="text-xs text-ink-faint italic mt-0.5">"{alert.note}"</div>}
        {isTriggered && alert.triggered_at && (
          <div className="text-xs text-ink-faint mt-1">Triggered: {alert.triggered_at.slice(0, 16).replace('T', ' ')}</div>
        )}
      </div>
      {!isTriggered && (
        <div className="flex items-center gap-2 flex-shrink-0">
          <button onClick={() => onToggle(alert.id)}
            className={clsx('relative inline-flex h-5 w-9 items-center rounded-full transition-colors focus:outline-none',
              alert.is_active ? 'bg-green-500' : 'bg-surface-border')}>
            <span className={clsx('inline-block h-3.5 w-3.5 transform rounded-full bg-white shadow transition-transform',
              alert.is_active ? 'translate-x-4' : 'translate-x-0.5')} />
          </button>
          <button onClick={() => onDelete(alert.id)}
            className="text-ink-faint hover:text-red-500 transition-colors text-lg leading-none">✕</button>
        </div>
      )}
    </div>
  )
}

export function AlertsPage() {
  const qc = useQueryClient()
  const [ticker, setTicker] = useState('')
  const [condition, setCondition] = useState<AlertCondition>('above')
  const [targetPrice, setTargetPrice] = useState('')
  const [note, setNote] = useState('')
  const [err, setErr] = useState('')

  const condMeta = CONDITIONS.find(c => c.value === condition)

  const { data: alerts = [], isLoading } = useQuery({
    queryKey: ['price-alerts'],
    queryFn: apiGetPriceAlerts,
  })

  const createMut = useMutation({
    mutationFn: apiCreatePriceAlert,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['price-alerts'] })
      setTicker(''); setTargetPrice(''); setNote(''); setErr('')
    },
    onError: (e: any) => setErr(e?.response?.data?.detail || 'Failed to create alert'),
  })

  const deleteMut = useMutation({
    mutationFn: apiDeletePriceAlert,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['price-alerts'] }),
  })

  const toggleMut = useMutation({
    mutationFn: apiTogglePriceAlert,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['price-alerts'] }),
  })

  function handleCreate(e: React.FormEvent) {
    e.preventDefault()
    if (!ticker.trim()) { setErr('Enter a ticker'); return }
    if (condMeta?.needsTarget && !targetPrice) { setErr('Enter a target price'); return }
    setErr('')
    createMut.mutate({
      ticker: ticker.trim().toUpperCase(),
      condition,
      target_price: condMeta?.needsTarget ? parseFloat(targetPrice) : undefined,
      note: note.trim(),
    })
  }

  const active    = alerts.filter(a => !a.triggered_at && a.is_active)
  const paused    = alerts.filter(a => !a.triggered_at && !a.is_active)
  const triggered = alerts.filter(a => !!a.triggered_at)

  return (
    <div className="max-w-3xl mx-auto px-4 py-6 space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-ink">Price Alerts</h1>
        <p className="text-sm text-ink-muted mt-0.5">
          Get an email when a stock hits your target price or a key technical level.
          Alerts are checked every 5 minutes during market hours.
        </p>
      </div>

      {/* Create form */}
      <div className="card p-5">
        <h2 className="font-semibold text-ink mb-4">Create New Alert</h2>
        <form onSubmit={handleCreate} className="space-y-3">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label className="label">Ticker</label>
              <input value={ticker} onChange={e => setTicker(e.target.value.toUpperCase())}
                placeholder="AAPL" maxLength={10}
                className="input font-mono uppercase" />
            </div>
            <div>
              <label className="label">Condition</label>
              <select value={condition} onChange={e => setCondition(e.target.value as AlertCondition)}
                className="input">
                {CONDITIONS.map(c => <option key={c.value} value={c.value}>{c.label}</option>)}
              </select>
            </div>
          </div>

          {condMeta?.needsTarget && (
            <div>
              <label className="label">Target Price ($)</label>
              <input type="number" value={targetPrice} onChange={e => setTargetPrice(e.target.value)}
                placeholder="150.00" min="0" step="0.01" className="input" />
            </div>
          )}

          <div>
            <label className="label">Note (optional)</label>
            <input value={note} onChange={e => setNote(e.target.value)}
              placeholder="e.g. Entry point for breakout trade"
              className="input" />
          </div>

          {err && <p className="text-sm text-red-600 bg-red-50 dark:bg-red-950/20 p-2.5 rounded-lg">{err}</p>}

          <button type="submit" disabled={createMut.isPending}
            className="btn-primary px-5 py-2.5 disabled:opacity-50">
            {createMut.isPending ? 'Creating…' : 'Create Alert'}
          </button>
        </form>
      </div>

      {/* Alert lists */}
      {isLoading && <div className="text-ink-muted text-sm">Loading…</div>}

      {active.length > 0 && (
        <div className="space-y-2">
          <h3 className="text-sm font-semibold text-ink">Active ({active.length})</h3>
          {active.map(a => <AlertCard key={a.id} alert={a} onDelete={id => deleteMut.mutate(id)} onToggle={id => toggleMut.mutate(id)} />)}
        </div>
      )}

      {paused.length > 0 && (
        <div className="space-y-2">
          <h3 className="text-sm font-semibold text-ink-muted">Paused ({paused.length})</h3>
          {paused.map(a => <AlertCard key={a.id} alert={a} onDelete={id => deleteMut.mutate(id)} onToggle={id => toggleMut.mutate(id)} />)}
        </div>
      )}

      {triggered.length > 0 && (
        <div className="space-y-2">
          <h3 className="text-sm font-semibold text-ink-faint">Triggered History ({triggered.length})</h3>
          {triggered.map(a => <AlertCard key={a.id} alert={a} onDelete={id => deleteMut.mutate(id)} onToggle={id => toggleMut.mutate(id)} />)}
        </div>
      )}

      {!isLoading && alerts.length === 0 && (
        <div className="card p-8 text-center text-ink-muted text-sm">
          No alerts yet. Create one above to get notified when your target is hit.
        </div>
      )}
    </div>
  )
}
