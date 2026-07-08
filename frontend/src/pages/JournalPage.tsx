import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { clsx } from 'clsx'
import client from '../api/client'

interface Trade {
  id: number
  ticker: string
  direction: 'long' | 'short'
  entry_date: string
  exit_date: string | null
  entry_price: number
  exit_price: number | null
  shares: number
  setup: string
  notes: string
  outcome: 'win' | 'loss' | 'breakeven' | 'open'
  realized_pnl: number | null
  realized_pnl_pct: number | null
  created_at: string
}

interface TradeForm {
  ticker: string
  direction: 'long' | 'short'
  entry_date: string
  exit_date: string
  entry_price: string
  exit_price: string
  shares: string
  setup: string
  notes: string
}

const EMPTY_FORM: TradeForm = {
  ticker: '', direction: 'long', entry_date: '', exit_date: '',
  entry_price: '', exit_price: '', shares: '', setup: '', notes: '',
}

const apiGetTrades   = () => client.get<Trade[]>('/journal').then(r => r.data)
const apiCreateTrade = (data: object) => client.post<Trade>('/journal', data).then(r => r.data)
const apiUpdateTrade = (id: number, data: object) => client.put<Trade>(`/journal/${id}`, data).then(r => r.data)
const apiDeleteTrade = (id: number) => client.delete(`/journal/${id}`).then(r => r.data)

const OUTCOME_STYLES: Record<string, string> = {
  win:       'bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-300',
  loss:      'bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-300',
  breakeven: 'bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-300',
  open:      'bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300',
}

function OutcomeBadge({ outcome }: { outcome: string }) {
  return (
    <span className={clsx('text-xs px-2 py-0.5 rounded-full font-semibold capitalize', OUTCOME_STYLES[outcome] ?? OUTCOME_STYLES.open)}>
      {outcome}
    </span>
  )
}

export function JournalPage() {
  const qc = useQueryClient()
  const [form, setForm]         = useState<TradeForm>(EMPTY_FORM)
  const [editId, setEditId]     = useState<number | null>(null)
  const [showForm, setShowForm] = useState(false)
  const [filter, setFilter]     = useState<'all' | 'open' | 'win' | 'loss'>('all')

  const { data: trades = [], isLoading } = useQuery({ queryKey: ['journal'], queryFn: apiGetTrades })

  const createMut = useMutation({
    mutationFn: apiCreateTrade,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['journal'] }); setForm(EMPTY_FORM); setShowForm(false) },
  })
  const updateMut = useMutation({
    mutationFn: ({ id, data }: { id: number; data: object }) => apiUpdateTrade(id, data),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['journal'] }); setEditId(null); setForm(EMPTY_FORM); setShowForm(false) },
  })
  const deleteMut = useMutation({
    mutationFn: apiDeleteTrade,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['journal'] }),
  })

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    const payload = {
      ticker: form.ticker.toUpperCase().trim(),
      direction: form.direction,
      entry_date: form.entry_date,
      exit_date: form.exit_date || null,
      entry_price: parseFloat(form.entry_price),
      exit_price: form.exit_price ? parseFloat(form.exit_price) : null,
      shares: parseFloat(form.shares),
      setup: form.setup,
      notes: form.notes,
    }
    if (editId != null) {
      updateMut.mutate({ id: editId, data: payload })
    } else {
      createMut.mutate(payload)
    }
  }

  function startEdit(t: Trade) {
    setEditId(t.id)
    setForm({
      ticker: t.ticker,
      direction: t.direction,
      entry_date: t.entry_date.slice(0, 10),
      exit_date: t.exit_date?.slice(0, 10) ?? '',
      entry_price: String(t.entry_price),
      exit_price: t.exit_price ? String(t.exit_price) : '',
      shares: String(t.shares),
      setup: t.setup,
      notes: t.notes,
    })
    setShowForm(true)
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  function cancelEdit() {
    setEditId(null)
    setForm(EMPTY_FORM)
    setShowForm(false)
  }

  const filtered = trades.filter(t => filter === 'all' || t.outcome === filter)

  // Stats
  const closed  = trades.filter(t => t.outcome !== 'open')
  const wins    = closed.filter(t => t.outcome === 'win').length
  const winRate = closed.length ? Math.round(wins / closed.length * 100) : null
  const totalPnl = closed.reduce((sum, t) => sum + (t.realized_pnl ?? 0), 0)

  return (
    <div className="max-w-5xl mx-auto px-4 py-6 space-y-6">
      <div className="flex items-start justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold text-ink">Trade Journal</h1>
          <p className="text-sm text-ink-muted mt-0.5">Track entries, exits, and P&amp;L for every trade. Build a history of what works.</p>
        </div>
        <button onClick={() => { setShowForm(s => !s); if (editId) cancelEdit() }}
          className="btn-primary px-4 py-2 text-sm">
          {showForm && editId == null ? 'Cancel' : '+ Log Trade'}
        </button>
      </div>

      {/* Stats row */}
      {closed.length > 0 && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
          {[
            { label: 'Total Trades', value: trades.length.toString() },
            { label: 'Win Rate', value: winRate != null ? `${winRate}%` : '—', color: winRate != null && winRate >= 50 ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400' },
            { label: 'Realized P&L', value: `${totalPnl >= 0 ? '+' : ''}$${totalPnl.toLocaleString('en-US', {maximumFractionDigits: 0})}`, color: totalPnl >= 0 ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400' },
            { label: 'Open Trades', value: trades.filter(t => t.outcome === 'open').length.toString(), color: 'text-blue-600 dark:text-blue-400' },
          ].map(card => (
            <div key={card.label} className="card p-4">
              <div className="text-xs text-ink-faint uppercase tracking-wide mb-1">{card.label}</div>
              <div className={clsx('text-xl font-bold', card.color ?? 'text-ink')}>{card.value}</div>
            </div>
          ))}
        </div>
      )}

      {/* Form */}
      {showForm && (
        <div className="card p-5">
          <h2 className="font-semibold text-ink mb-4">{editId != null ? 'Edit Trade' : 'Log New Trade'}</h2>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
              <div>
                <label className="label">Ticker *</label>
                <input value={form.ticker} onChange={e => setForm(f => ({ ...f, ticker: e.target.value.toUpperCase() }))}
                  placeholder="AAPL" required className="input font-mono uppercase" />
              </div>
              <div>
                <label className="label">Direction</label>
                <select value={form.direction} onChange={e => setForm(f => ({ ...f, direction: e.target.value as 'long' | 'short' }))}
                  className="input">
                  <option value="long">Long</option>
                  <option value="short">Short</option>
                </select>
              </div>
              <div>
                <label className="label">Shares *</label>
                <input type="number" value={form.shares} onChange={e => setForm(f => ({ ...f, shares: e.target.value }))}
                  placeholder="100" min="0" step="any" required className="input" />
              </div>
              <div>
                <label className="label">Entry Date *</label>
                <input type="date" value={form.entry_date} onChange={e => setForm(f => ({ ...f, entry_date: e.target.value }))}
                  required className="input" />
              </div>
              <div>
                <label className="label">Entry Price ($) *</label>
                <input type="number" value={form.entry_price} onChange={e => setForm(f => ({ ...f, entry_price: e.target.value }))}
                  placeholder="150.00" min="0" step="any" required className="input" />
              </div>
              <div>
                <label className="label">Exit Date</label>
                <input type="date" value={form.exit_date} onChange={e => setForm(f => ({ ...f, exit_date: e.target.value }))}
                  className="input" />
              </div>
              <div>
                <label className="label">Exit Price ($)</label>
                <input type="number" value={form.exit_price} onChange={e => setForm(f => ({ ...f, exit_price: e.target.value }))}
                  placeholder="160.00" min="0" step="any" className="input" />
              </div>
              <div>
                <label className="label">Setup / Strategy</label>
                <input value={form.setup} onChange={e => setForm(f => ({ ...f, setup: e.target.value }))}
                  placeholder="e.g. Breakout from base, IBD RS50" className="input" />
              </div>
            </div>
            <div>
              <label className="label">Notes</label>
              <textarea value={form.notes} onChange={e => setForm(f => ({ ...f, notes: e.target.value }))}
                placeholder="Why did you take this trade? What did you learn?"
                rows={3} className="input resize-none" />
            </div>
            <div className="flex gap-3 flex-wrap">
              <button type="submit" disabled={createMut.isPending || updateMut.isPending}
                className="btn-primary px-5 py-2 disabled:opacity-50">
                {createMut.isPending || updateMut.isPending ? 'Saving…' : editId != null ? 'Update Trade' : 'Save Trade'}
              </button>
              {editId != null && (
                <button type="button" onClick={cancelEdit} className="btn-secondary px-5 py-2">Cancel</button>
              )}
            </div>
          </form>
        </div>
      )}

      {/* Filter tabs */}
      <div className="flex gap-1 bg-surface-muted rounded-xl p-1 w-fit">
        {(['all', 'open', 'win', 'loss'] as const).map(f => (
          <button key={f} onClick={() => setFilter(f)}
            className={clsx('px-4 py-1.5 rounded-lg text-sm font-medium transition-colors capitalize',
              filter === f ? 'bg-surface text-ink shadow-sm' : 'text-ink-muted hover:text-ink')}>
            {f} {f !== 'all' ? `(${trades.filter(t => t.outcome === f).length})` : `(${trades.length})`}
          </button>
        ))}
      </div>

      {/* Trade list */}
      {isLoading && <div className="card p-6 text-center text-ink-muted text-sm">Loading trades…</div>}

      {!isLoading && filtered.length === 0 && (
        <div className="card p-8 text-center text-ink-muted text-sm">
          {trades.length === 0 ? 'No trades yet. Click "+ Log Trade" to record your first trade.' : 'No trades match this filter.'}
        </div>
      )}

      {filtered.length > 0 && (
        <div className="card overflow-hidden">
          <div className="overflow-x-auto">
            <div className="min-w-[700px]">
              <div className="grid grid-cols-[70px_60px_80px_80px_80px_80px_80px_90px_1fr_80px] gap-2 px-5 py-2 text-xs text-ink-faint uppercase tracking-wide border-b border-surface-border">
                <span>Ticker</span><span>Dir</span><span>Entry</span><span className="text-right">Entry $</span>
                <span className="text-right">Exit $</span><span className="text-right">Shares</span>
                <span className="text-right">P&L</span><span className="text-center">Outcome</span>
                <span>Setup</span><span className="text-center">Actions</span>
              </div>
              {filtered.map(t => (
                <div key={t.id} className="group">
                  <div className="grid grid-cols-[70px_60px_80px_80px_80px_80px_80px_90px_1fr_80px] gap-2 px-5 py-3 border-b border-surface-border last:border-0 items-center text-sm hover:bg-surface-muted/50 transition-colors">
                    <div className="font-bold text-ink">{t.ticker}</div>
                    <div className={clsx('text-xs font-semibold', t.direction === 'long' ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400')}>
                      {t.direction.toUpperCase()}
                    </div>
                    <div className="text-xs text-ink-muted">{t.entry_date.slice(0, 10)}</div>
                    <div className="text-right text-ink">${Number(t.entry_price).toFixed(2)}</div>
                    <div className="text-right text-ink-muted">{t.exit_price ? `$${Number(t.exit_price).toFixed(2)}` : '—'}</div>
                    <div className="text-right text-ink-muted">{Number(t.shares).toLocaleString()}</div>
                    <div className={clsx('text-right font-semibold text-xs', t.realized_pnl == null ? 'text-ink-faint' : t.realized_pnl >= 0 ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400')}>
                      {t.realized_pnl == null ? '—' : `${t.realized_pnl >= 0 ? '+' : ''}$${Math.abs(t.realized_pnl).toFixed(0)}`}
                      {t.realized_pnl_pct != null && <div className="text-ink-faint">{t.realized_pnl_pct >= 0 ? '+' : ''}{t.realized_pnl_pct.toFixed(1)}%</div>}
                    </div>
                    <div className="flex justify-center"><OutcomeBadge outcome={t.outcome} /></div>
                    <div className="text-xs text-ink-faint truncate">{t.setup || '—'}</div>
                    <div className="flex justify-center gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
                      <button onClick={() => startEdit(t)} className="text-xs text-primary hover:underline">Edit</button>
                      <button onClick={() => { if (confirm(`Delete ${t.ticker} trade?`)) deleteMut.mutate(t.id) }}
                        className="text-xs text-red-500 hover:underline">Del</button>
                    </div>
                  </div>
                  {t.notes && (
                    <div className="px-5 pb-2 text-xs text-ink-faint italic border-b border-surface-border last:border-0">
                      "{t.notes}"
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
