import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { apiGetUsers, apiGetLicenses, apiGetAudit, apiCreateUser, apiUpdateUser, apiDeactivateUser, apiActivateUser, apiGetTokenUsage, apiGetBacktest, apiRunHistoricalBacktest, apiGetHistoricalBacktest, apiGetRegime, apiSendDigest, apiGetDigestEmails, apiAddDigestEmail, apiToggleDigestEmail, apiDeleteDigestEmail } from '../api/admin'
import { RoleBadge, TierBadge, StatusBadge } from '../components/ui/Badge'
import { KpiCard } from '../components/ui/KpiCard'
import { Spinner } from '../components/ui/Spinner'
import type { User, License } from '../types'

const ROLE_LABELS: Record<string, string> = { admin:'Administrator', analyst:'Analyst', trader:'Trader', viewer:'Viewer' }
const TIER_COLORS: Record<string, string>  = { free:'#475569', professional:'#2563EB', enterprise:'#7C3AED' }

// ── Overview tab ───────────────────────────────────────────────────────────────
function OverviewTab({ users, licenses }: { users: User[]; licenses: License[] }) {
  const active  = users.filter(u => u.is_active).length
  const byRole  = users.reduce<Record<string,number>>((a,u) => ({...a,[u.role]:(a[u.role]||0)+1}),{})
  const now24h  = new Date(Date.now()-24*3600*1000).toISOString()
  const recent  = users.filter(u => u.last_login && u.last_login > now24h).length

  const [digestResult, setDigestResult] = useState<string | null>(null)
  const digestMut = useMutation({
    mutationFn: apiSendDigest,
    onSuccess: (data) => {
      if (data.skipped) setDigestResult(`Skipped: ${data.reason}`)
      else setDigestResult(`Sent to ${data.users_sent ?? 0} user(s). Picks: ${data.picks_count ?? 0}`)
    },
    onError: (e: unknown) => setDigestResult(`Error: ${(e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Unknown error'}`),
  })

  return (
    <div className="space-y-6">
      <div className="flex gap-4 flex-wrap">
        <KpiCard value={users.length}    label="Total Users" />
        <KpiCard value={active}          label="Active" />
        <KpiCard value={recent}          label="Logins (24h)" />
        <KpiCard value={licenses.length} label="License Plans" />
      </div>
      {/* Send Digest */}
      <div className="card p-5 border-l-4 border-primary">
        <div className="flex items-center justify-between flex-wrap gap-3">
          <div>
            <h3 className="font-bold text-ink">📧 Daily Email Digest</h3>
            <p className="text-sm text-ink-muted mt-0.5">Send the top 5 stock picks email to all opted-in users right now (bypasses time/day check).</p>
          </div>
          <div className="flex items-center gap-3">
            {digestResult && (
              <span className={`text-sm font-semibold px-3 py-1.5 rounded-lg ${digestResult.startsWith('Error') ? 'bg-red-50 text-red-600' : 'bg-green-50 text-green-700'}`}>
                {digestResult}
              </span>
            )}
            <button
              onClick={() => { setDigestResult(null); digestMut.mutate() }}
              disabled={digestMut.isPending}
              className="btn-primary disabled:opacity-50 flex items-center gap-2"
            >
              {digestMut.isPending ? <><Spinner /><span>Sending…</span></> : '📤 Send Digest Now'}
            </button>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div className="card p-4">
          <h3 className="font-bold text-sm mb-3">Users by Role</h3>
          <table className="w-full text-sm">
            <tbody className="divide-y divide-surface-border">
              {Object.entries(byRole).map(([r,c]) => (
                <tr key={r}><td className="py-2"><RoleBadge role={r} /></td><td className="py-2 text-right font-bold">{c}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="card p-4">
          <h3 className="font-bold text-sm mb-3">License Plans</h3>
          <table className="w-full text-sm">
            <thead><tr className="text-xs text-ink-faint uppercase">
              <th className="pb-2 text-left">Plan</th><th className="pb-2 text-center">Users</th><th className="pb-2 text-right">Max</th>
            </tr></thead>
            <tbody className="divide-y divide-surface-border">
              {licenses.map(l => (
                <tr key={l.id}>
                  <td className="py-2"><TierBadge tier={l.tier} /> <span className="ml-1.5 text-ink-muted">{l.name}</span></td>
                  <td className="py-2 text-center font-bold">{l.user_count}</td>
                  <td className="py-2 text-right text-ink-muted">{l.max_users}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}

// ── Users tab ──────────────────────────────────────────────────────────────────
function UsersTab({ users, licenses }: { users: User[]; licenses: License[] }) {
  const qc = useQueryClient()
  const [showAdd, setShowAdd] = useState(false)
  const [editing, setEditing] = useState<User | null>(null)
  const [form, setForm] = useState({ email:'', username:'', password:'', full_name:'', role:'viewer', license_id:'' })
  const [editForm, setEditForm] = useState({ role:'viewer', license_id:'', is_active:true })
  const [err, setErr] = useState('')

  const createMut = useMutation({
    mutationFn: () => apiCreateUser({ ...form, license_id: form.license_id ? Number(form.license_id) : null }),
    onSuccess: () => { qc.invalidateQueries({queryKey:['admin-users']}); setShowAdd(false); setForm({email:'',username:'',password:'',full_name:'',role:'viewer',license_id:''}) },
    onError: (e: unknown) => setErr((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || 'Failed'),
  })

  const updateMut = useMutation({
    mutationFn: (u: User) => apiUpdateUser(u.id, { role: editForm.role, license_id: editForm.license_id ? Number(editForm.license_id) : null, is_active: editForm.is_active }),
    onSuccess: () => { qc.invalidateQueries({queryKey:['admin-users']}); setEditing(null) },
  })

  const toggleMut = useMutation({
    mutationFn: (u: User) => u.is_active ? apiDeactivateUser(u.id) : apiActivateUser(u.id),
    onSuccess: () => qc.invalidateQueries({queryKey:['admin-users']}),
  })

  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center">
        <h2 className="font-bold text-ink">All Users ({users.length})</h2>
        <button onClick={() => setShowAdd(s => !s)} className="btn-primary text-sm">+ Add User</button>
      </div>

      {/* Add form */}
      {showAdd && (
        <div className="card p-5 border-primary/30">
          <h3 className="font-bold mb-4">New User</h3>
          <div className="grid grid-cols-2 gap-3 mb-3">
            {[['Full Name','full_name','text'],['Email','email','email'],['Username','username','text'],['Password','password','password']].map(([label,key,type]) => (
              <div key={key}>
                <label className="label">{label}</label>
                <input type={type} className="input" value={(form as Record<string,string>)[key]}
                  onChange={e => setForm(f => ({...f,[key]:e.target.value}))} />
              </div>
            ))}
            <div>
              <label className="label">Role</label>
              <select className="input" value={form.role} onChange={e => setForm(f => ({...f,role:e.target.value}))}>
                {Object.entries(ROLE_LABELS).map(([k,v]) => <option key={k} value={k}>{v}</option>)}
              </select>
            </div>
            <div>
              <label className="label">License</label>
              <select className="input" value={form.license_id} onChange={e => setForm(f => ({...f,license_id:e.target.value}))}>
                <option value="">None</option>
                {licenses.map(l => <option key={l.id} value={l.id}>{l.name} ({l.tier})</option>)}
              </select>
            </div>
          </div>
          {err && <p className="text-red-600 text-sm mb-3">{err}</p>}
          <div className="flex gap-2">
            <button onClick={() => createMut.mutate()} disabled={createMut.isPending} className="btn-primary text-sm">
              {createMut.isPending ? 'Creating…' : 'Create User'}
            </button>
            <button onClick={() => setShowAdd(false)} className="btn-secondary text-sm">Cancel</button>
          </div>
        </div>
      )}

      {/* Table */}
      <div className="card overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-surface-muted border-b border-surface-border">
            <tr>{['Name','Email','Role','License','Status','Last Login','Actions'].map(h => (
              <th key={h} className="px-4 py-3 text-left text-xs font-bold uppercase tracking-wide text-ink-faint">{h}</th>
            ))}</tr>
          </thead>
          <tbody className="divide-y divide-surface-border">
            {users.map(u => (
              <tr key={u.id} className="hover:bg-surface-muted/40 transition-colors">
                <td className="px-4 py-3 font-semibold text-ink">{u.full_name || '—'}</td>
                <td className="px-4 py-3 text-ink-muted text-xs">{u.email}</td>
                <td className="px-4 py-3"><RoleBadge role={u.role} /></td>
                <td className="px-4 py-3 text-xs text-ink-muted">{u.license_name || '—'}</td>
                <td className="px-4 py-3"><StatusBadge active={u.is_active} /></td>
                <td className="px-4 py-3 text-xs text-ink-muted">{u.last_login ? u.last_login.slice(0,16).replace('T',' ') : '—'}</td>
                <td className="px-4 py-3">
                  <div className="flex gap-1.5">
                    <button onClick={() => { setEditing(u); setEditForm({ role: u.role, license_id: String(u.license_id || ''), is_active: u.is_active }) }}
                      className="btn-secondary text-xs py-1">Edit</button>
                    <button onClick={() => toggleMut.mutate(u)}
                      className={`text-xs py-1 px-2 rounded-lg font-semibold transition-all ${u.is_active ? 'bg-red-50 text-red-600 hover:bg-red-100' : 'bg-green-50 text-green-700 hover:bg-green-100'}`}>
                      {u.is_active ? 'Deactivate' : 'Activate'}
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Edit modal — click backdrop or press ESC to close */}
      {editing && (
        <div
          className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4"
          onClick={() => setEditing(null)}
          onKeyDown={e => e.key === 'Escape' && setEditing(null)}
          role="dialog"
          tabIndex={-1}
        >
          <div
            className="bg-surface rounded-2xl shadow-xl p-6 w-full max-w-md border border-surface-border"
            onClick={e => e.stopPropagation()}
          >
            <div className="flex items-center justify-between mb-4">
              <h3 className="font-bold text-lg">Edit — {editing.full_name || editing.username}</h3>
              <button
                onClick={() => setEditing(null)}
                className="text-ink-faint hover:text-ink text-xl leading-none px-1"
                aria-label="Close"
              >
                ✕
              </button>
            </div>
            <div className="space-y-3">
              <div>
                <label className="label">Role</label>
                <select className="input" value={editForm.role} onChange={e => setEditForm(f => ({...f,role:e.target.value}))}>
                  {Object.entries(ROLE_LABELS).map(([k,v]) => <option key={k} value={k}>{v}</option>)}
                </select>
              </div>
              <div>
                <label className="label">License</label>
                <select className="input" value={editForm.license_id} onChange={e => setEditForm(f => ({...f,license_id:e.target.value}))}>
                  <option value="">None</option>
                  {licenses.map(l => <option key={l.id} value={l.id}>{l.name} ({l.tier})</option>)}
                </select>
              </div>
              <label className="flex items-center gap-2">
                <input type="checkbox" checked={editForm.is_active} onChange={e => setEditForm(f => ({...f,is_active:e.target.checked}))} className="accent-primary" />
                <span className="text-sm">Active</span>
              </label>
            </div>
            <div className="flex gap-2 mt-5">
              <button onClick={() => updateMut.mutate(editing)} disabled={updateMut.isPending} className="btn-primary text-sm">
                {updateMut.isPending ? 'Saving…' : 'Save'}
              </button>
              <button onClick={() => setEditing(null)} className="btn-secondary text-sm">Cancel</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

// ── Licenses tab ───────────────────────────────────────────────────────────────
function LicensesTab({ licenses }: { licenses: License[] }) {
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
      {licenses.map(l => (
        <div key={l.id} className="card p-5" style={{ borderTop: `3px solid ${TIER_COLORS[l.tier]||'#6B7280'}` }}>
          <div className="flex items-start justify-between mb-3">
            <div>
              <div className="font-bold text-ink">{l.name}</div>
              <TierBadge tier={l.tier} />
            </div>
            <StatusBadge active={l.is_active} />
          </div>
          <div className="text-xs text-ink-muted space-y-1">
            <div>Users: <strong>{l.user_count}/{l.max_users}</strong></div>
            <div>Max picks: <strong>{l.max_picks}</strong></div>
            <div>Modes: <strong>{l.allowed_modes || '—'}</strong></div>
            <div>Expires: <strong>{l.expires_at || 'Never'}</strong></div>
          </div>
          <div className="flex flex-wrap gap-1.5 mt-3">
            {[['✉','Email',l.can_email],['⬇','Export',l.can_export],['⚙','Admin',l.can_admin]].map(([icon,label,on]) => (
              <span key={label as string}
                className={`text-xs px-2 py-0.5 rounded font-semibold ${on ? 'bg-green-100 text-green-800' : 'bg-surface-muted text-ink-faint'}`}>
                {icon} {label}
              </span>
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}

// ── Audit tab ──────────────────────────────────────────────────────────────────
function AuditTab() {
  const { data: entries = [], refetch } = useQuery({ queryKey:['admin-audit'], queryFn:()=>apiGetAudit({limit:200}) })
  return (
    <div>
      <div className="flex justify-between mb-4">
        <h2 className="font-bold">Audit Log ({entries.length})</h2>
        <button onClick={() => refetch()} className="btn-secondary text-sm">🔄 Refresh</button>
      </div>
      <div className="card overflow-hidden">
        <table className="w-full text-xs">
          <thead className="bg-surface-muted border-b border-surface-border">
            <tr>{['Time','User','Action','Details'].map(h=>(
              <th key={h} className="px-4 py-3 text-left font-bold uppercase tracking-wide text-ink-faint">{h}</th>
            ))}</tr>
          </thead>
          <tbody className="divide-y divide-surface-border">
            {[...entries].reverse().map(e => (
              <tr key={e.id} className="hover:bg-surface-muted/40">
                <td className="px-4 py-2.5 text-ink-muted whitespace-nowrap">{e.created_at?.slice(0,19).replace('T',' ')}</td>
                <td className="px-4 py-2.5 font-medium">{e.username || '—'}</td>
                <td className="px-4 py-2.5"><span className="bg-surface-muted px-2 py-0.5 rounded font-mono">{e.action}</span></td>
                <td className="px-4 py-2.5 text-ink-muted max-w-xs truncate">{e.details}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// ── Backtest tab ───────────────────────────────────────────────────────────────
interface BacktestPick {
  id: number; run_date: string; sector: string; ticker: string
  score: number; confidence: number; signal: string
  entry_price: number | null; current_price: number | null
  return_current_pct: number | null
  return_5d_pct: number | null; price_5d: number | null
  return_30d_pct: number | null; price_30d: number | null
  rs_vs_spy: number | null; rs_vs_sector: number | null
  eps_surprise_pct: number | null; short_pct_float: number | null
  breakout_flag: boolean; squeeze_flag: boolean; earnings_flag: string | null
}
interface BacktestSummary {
  total_picks: number; buy_picks: number
  with_5d: number;  avg_5d_all_pct: number | null;  avg_5d_buy_pct: number | null;  win_rate_5d_buy_pct: number | null
  with_30d: number; avg_30d_all_pct: number | null; avg_30d_buy_pct: number | null; win_rate_30d_buy_pct: number | null
  breakout_avg_5d: number | null; squeeze_avg_5d: number | null
}
interface BacktestData { picks: BacktestPick[]; summary: BacktestSummary }

function Ret({ v, fallback = '—' }: { v: number | null; fallback?: string }) {
  if (v === null || v === undefined) return <span className="text-ink-faint">{fallback}</span>
  const cls = v > 0 ? 'text-green-600 font-bold' : v < 0 ? 'text-red-500 font-bold' : 'text-ink-muted'
  return <span className={cls}>{v > 0 ? '+' : ''}{v.toFixed(2)}%</span>
}

function pct(v: number | null) {
  if (v === null || v === undefined) return '—'
  return `${v > 0 ? '+' : ''}${v.toFixed(2)}%`
}

function BacktestTab() {
  const [days, setDays] = useState(60)
  const { data, isLoading, error, refetch } = useQuery<BacktestData>({
    queryKey: ['admin-backtest', days],
    queryFn:  () => apiGetBacktest(days),
  })

  if (isLoading) return <div className="flex items-center justify-center h-40"><Spinner /></div>
  if (error || !data) return <p className="text-red-500 text-sm">Failed to load backtest data.</p>

  const { picks, summary } = data
  const SIG: Record<string, string> = {
    BUY: 'bg-green-100 text-green-800', WATCH: 'bg-blue-100 text-blue-800', HOLD: 'bg-yellow-100 text-yellow-800',
  }

  return (
    <div className="space-y-6">
      {/* Controls */}
      <div className="flex items-center gap-4 flex-wrap">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium text-ink-muted">Look-back</span>
          {[30, 60, 90].map(d => (
            <button key={d} onClick={() => setDays(d)}
              className={`px-3 py-1 rounded-lg text-sm font-semibold transition-all
                ${days === d ? 'bg-primary text-white' : 'bg-surface-muted text-ink-muted hover:text-ink'}`}>
              {d}d
            </button>
          ))}
        </div>
        <button onClick={() => refetch()} className="btn-secondary text-sm ml-auto">🔄 Refresh</button>
      </div>

      {/* 5-day KPIs */}
      <div>
        <p className="text-xs font-bold uppercase tracking-wide text-ink-faint mb-2">5-Day Forward Returns</p>
        <div className="flex gap-3 flex-wrap">
          <KpiCard value={summary.with_5d}                                          label="Picks with 5D data" />
          <KpiCard value={pct(summary.avg_5d_buy_pct)}                              label="Avg BUY 5D return" />
          <KpiCard value={summary.win_rate_5d_buy_pct != null ? `${summary.win_rate_5d_buy_pct}%` : '—'} label="BUY Win Rate 5D" />
          <KpiCard value={pct(summary.avg_5d_all_pct)}                              label="Avg All 5D return" />
        </div>
      </div>

      {/* 30-day KPIs */}
      <div>
        <p className="text-xs font-bold uppercase tracking-wide text-ink-faint mb-2">30-Day Forward Returns</p>
        <div className="flex gap-3 flex-wrap">
          <KpiCard value={summary.with_30d}                                           label="Picks with 30D data" />
          <KpiCard value={pct(summary.avg_30d_buy_pct)}                               label="Avg BUY 30D return" />
          <KpiCard value={summary.win_rate_30d_buy_pct != null ? `${summary.win_rate_30d_buy_pct}%` : '—'} label="BUY Win Rate 30D" />
          <KpiCard value={pct(summary.avg_30d_all_pct)}                               label="Avg All 30D return" />
        </div>
      </div>

      {/* Flag performance */}
      {(summary.breakout_avg_5d != null || summary.squeeze_avg_5d != null) && (
        <div>
          <p className="text-xs font-bold uppercase tracking-wide text-ink-faint mb-2">Signal Flag Performance (5D avg)</p>
          <div className="flex gap-3 flex-wrap">
            {summary.breakout_avg_5d != null && <KpiCard value={pct(summary.breakout_avg_5d)} label="🚀 Breakout picks" />}
            {summary.squeeze_avg_5d  != null && <KpiCard value={pct(summary.squeeze_avg_5d)}  label="💥 Squeeze picks" />}
          </div>
        </div>
      )}

      {/* Pick history table */}
      {picks.length === 0 ? (
        <div className="card p-8 text-center text-ink-faint">
          <p className="text-lg mb-2">No backtest data yet</p>
          <p className="text-sm">Run the Research Dashboard in free mode — picks are automatically logged and returns filled after 5 / 30 trading days.</p>
        </div>
      ) : (
        <div className="card overflow-hidden">
          <div className="px-4 py-3 border-b border-surface-border bg-surface-muted flex items-center gap-3">
            <span className="text-sm font-bold">Pick History — {picks.length} entries</span>
            <span className="text-xs text-ink-faint">5D / 30D = actual prices on the 5th and 21st trading day after pick</span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="bg-surface-muted border-b border-surface-border">
                <tr>{['Date','Sector','Ticker','Score','Sig','Entry','5D ret','30D ret','Live','EPS surp','SI%','Flags'].map(h => (
                  <th key={h} className="px-3 py-2.5 text-left font-bold uppercase tracking-wide text-ink-faint whitespace-nowrap">{h}</th>
                ))}</tr>
              </thead>
              <tbody className="divide-y divide-surface-border">
                {picks.map(p => (
                  <tr key={p.id} className="hover:bg-surface-muted/40 transition-colors">
                    <td className="px-3 py-2 text-ink-muted whitespace-nowrap">{p.run_date}</td>
                    <td className="px-3 py-2 text-ink-muted capitalize">{p.sector}</td>
                    <td className="px-3 py-2 font-bold text-ink">{p.ticker}</td>
                    <td className="px-3 py-2 font-semibold">{p.score ?? '—'}</td>
                    <td className="px-3 py-2">
                      <span className={`px-1.5 py-0.5 rounded text-xs font-bold ${SIG[p.signal] ?? 'bg-surface-muted text-ink-muted'}`}>
                        {p.signal}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-ink-muted">{p.entry_price ? `$${p.entry_price.toFixed(2)}` : '—'}</td>
                    <td className="px-3 py-2"><Ret v={p.return_5d_pct} /></td>
                    <td className="px-3 py-2"><Ret v={p.return_30d_pct} /></td>
                    <td className="px-3 py-2 text-ink-faint text-xs">
                      {p.return_5d_pct === null && p.return_current_pct !== null
                        ? <span className="italic"><Ret v={p.return_current_pct} /></span>
                        : null}
                    </td>
                    <td className="px-3 py-2">
                      {p.eps_surprise_pct != null
                        ? <span className={p.eps_surprise_pct > 0 ? 'text-green-600' : 'text-red-500'}>
                            {p.eps_surprise_pct > 0 ? '+' : ''}{p.eps_surprise_pct.toFixed(1)}%
                          </span>
                        : <span className="text-ink-faint">—</span>}
                    </td>
                    <td className="px-3 py-2 text-ink-muted">{p.short_pct_float != null ? `${p.short_pct_float.toFixed(0)}%` : '—'}</td>
                    <td className="px-3 py-2 whitespace-nowrap">
                      {p.breakout_flag && <span title="Near 52-week high">🚀</span>}
                      {p.squeeze_flag  && <span title="Squeeze candidate">💥</span>}
                      {p.earnings_flag && <span title={`Earnings ${p.earnings_flag}`}>⚠</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}

// ── Token Usage tab ────────────────────────────────────────────────────────────
interface TokenStats {
  summary: { total_tokens: number; total_cost: number; today_tokens: number; today_cost: number; month_cost: number }
  by_feature: { feature: string; total_tokens: number; total_cost: number; call_count: number }[]
  by_user:    { username: string; total_tokens: number; total_cost: number; call_count: number }[]
  daily:      { date: string; total_tokens: number; total_cost: number; call_count: number }[]
  recent:     { id: number; username: string; feature: string; ticker: string | null; model: string; input_tokens: number; output_tokens: number; total_tokens: number; cost_usd: number; created_at: string }[]
}

function fmtCost(n: number) { return `$${n.toFixed(4)}` }
function fmtTokens(n: number) { return n >= 1_000_000 ? `${(n/1_000_000).toFixed(2)}M` : n >= 1_000 ? `${(n/1_000).toFixed(1)}K` : String(n) }

function TokenUsageTab() {
  const { data, isLoading, error, refetch } = useQuery<TokenStats>({
    queryKey: ['admin-token-usage'],
    queryFn: apiGetTokenUsage,
    refetchInterval: 60_000,
  })

  if (isLoading) return <div className="flex items-center justify-center h-40"><Spinner /></div>
  if (error || !data) return <p className="text-red-500 text-sm">Failed to load token usage data.</p>

  const { summary, by_feature, by_user, daily, recent } = data

  return (
    <div className="space-y-6">
      {/* KPI row */}
      <div className="flex gap-4 flex-wrap">
        <KpiCard value={fmtTokens(summary.total_tokens)} label="Total Tokens" />
        <KpiCard value={fmtCost(summary.total_cost)}     label="Total Cost" />
        <KpiCard value={fmtTokens(summary.today_tokens)} label="Today Tokens" />
        <KpiCard value={fmtCost(summary.today_cost)}     label="Today Cost" />
        <KpiCard value={fmtCost(summary.month_cost)}     label="This Month Cost" />
        <div className="ml-auto self-end">
          <button onClick={() => refetch()} className="btn-secondary text-sm">🔄 Refresh</button>
        </div>
      </div>

      {/* By feature + by user */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="card p-4">
          <h3 className="font-bold text-sm mb-3">By Feature</h3>
          <table className="w-full text-sm">
            <thead><tr className="text-xs text-ink-faint uppercase">
              <th className="pb-2 text-left">Feature</th>
              <th className="pb-2 text-right">Calls</th>
              <th className="pb-2 text-right">Tokens</th>
              <th className="pb-2 text-right">Cost</th>
            </tr></thead>
            <tbody className="divide-y divide-surface-border">
              {by_feature.map(r => (
                <tr key={r.feature}>
                  <td className="py-2 font-mono text-xs">{r.feature}</td>
                  <td className="py-2 text-right text-ink-muted">{r.call_count}</td>
                  <td className="py-2 text-right font-semibold">{fmtTokens(r.total_tokens)}</td>
                  <td className="py-2 text-right text-amber-600 font-semibold">{fmtCost(r.total_cost)}</td>
                </tr>
              ))}
              {by_feature.length === 0 && (
                <tr><td colSpan={4} className="py-4 text-center text-ink-faint">No data yet</td></tr>
              )}
            </tbody>
          </table>
        </div>

        <div className="card p-4">
          <h3 className="font-bold text-sm mb-3">Top Users</h3>
          <table className="w-full text-sm">
            <thead><tr className="text-xs text-ink-faint uppercase">
              <th className="pb-2 text-left">User</th>
              <th className="pb-2 text-right">Calls</th>
              <th className="pb-2 text-right">Tokens</th>
              <th className="pb-2 text-right">Cost</th>
            </tr></thead>
            <tbody className="divide-y divide-surface-border">
              {by_user.map(r => (
                <tr key={r.username}>
                  <td className="py-2 font-medium">{r.username || '—'}</td>
                  <td className="py-2 text-right text-ink-muted">{r.call_count}</td>
                  <td className="py-2 text-right font-semibold">{fmtTokens(r.total_tokens)}</td>
                  <td className="py-2 text-right text-amber-600 font-semibold">{fmtCost(r.total_cost)}</td>
                </tr>
              ))}
              {by_user.length === 0 && (
                <tr><td colSpan={4} className="py-4 text-center text-ink-faint">No data yet</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Daily breakdown */}
      <div className="card p-4">
        <h3 className="font-bold text-sm mb-3">Daily Usage (Last 30 Days)</h3>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead><tr className="text-xs text-ink-faint uppercase">
              <th className="pb-2 text-left">Date</th>
              <th className="pb-2 text-right">Calls</th>
              <th className="pb-2 text-right">Tokens</th>
              <th className="pb-2 text-right">Cost</th>
            </tr></thead>
            <tbody className="divide-y divide-surface-border">
              {[...daily].reverse().map(r => (
                <tr key={r.date}>
                  <td className="py-1.5 text-ink-muted font-mono text-xs">{r.date}</td>
                  <td className="py-1.5 text-right">{r.call_count}</td>
                  <td className="py-1.5 text-right font-semibold">{fmtTokens(r.total_tokens)}</td>
                  <td className="py-1.5 text-right text-amber-600 font-semibold">{fmtCost(r.total_cost)}</td>
                </tr>
              ))}
              {daily.length === 0 && (
                <tr><td colSpan={4} className="py-4 text-center text-ink-faint">No data yet</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Recent transactions */}
      <div className="card p-4">
        <h3 className="font-bold text-sm mb-3">Recent Transactions (Last 100)</h3>
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead><tr className="text-xs text-ink-faint uppercase">
              <th className="pb-2 text-left">Time</th>
              <th className="pb-2 text-left">User</th>
              <th className="pb-2 text-left">Feature</th>
              <th className="pb-2 text-left">Ticker</th>
              <th className="pb-2 text-left">Model</th>
              <th className="pb-2 text-right">Input</th>
              <th className="pb-2 text-right">Output</th>
              <th className="pb-2 text-right">Total</th>
              <th className="pb-2 text-right">Cost</th>
            </tr></thead>
            <tbody className="divide-y divide-surface-border">
              {recent.map(r => (
                <tr key={r.id} className="hover:bg-surface-muted/40">
                  <td className="py-1.5 text-ink-muted whitespace-nowrap">{r.created_at.slice(0,16).replace('T',' ')}</td>
                  <td className="py-1.5 font-medium">{r.username || '—'}</td>
                  <td className="py-1.5 font-mono">{r.feature}</td>
                  <td className="py-1.5 font-mono">{r.ticker || '—'}</td>
                  <td className="py-1.5 text-ink-muted max-w-[8rem] truncate">{r.model}</td>
                  <td className="py-1.5 text-right">{r.input_tokens.toLocaleString()}</td>
                  <td className="py-1.5 text-right">{r.output_tokens.toLocaleString()}</td>
                  <td className="py-1.5 text-right font-semibold">{r.total_tokens.toLocaleString()}</td>
                  <td className="py-1.5 text-right text-amber-600 font-semibold">{fmtCost(r.cost_usd)}</td>
                </tr>
              ))}
              {recent.length === 0 && (
                <tr><td colSpan={9} className="py-4 text-center text-ink-faint">No transactions yet</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}

// ── Historical Backtest tab ────────────────────────────────────────────────────
interface HistStats { avg: number | null; win_rate: number | null; sharpe: number | null; n: number }
interface HistPick {
  eval_date: string; ticker: string; rank: number; score: number; entry: number
  return_5d: number | null; return_21d: number | null; return_63d: number | null
  alpha_5d: number | null; alpha_21d: number | null
}
interface HistWeights { mom_3m: number; mom_1m: number; mom_1w: number; vol_ratio: number; pos_52w: number; rs_spy: number }
interface HistResult {
  message?: string
  n_evaluations: number; n_picks_total: number; years_back: number; top_n: number
  stats_5d: HistStats; stats_21d: HistStats; stats_63d: HistStats
  alpha_5d: HistStats; alpha_21d: HistStats
  default_weights: HistWeights; optimal_weights: HistWeights | null
  optimization_result: { in_sample_avg: number | null; out_sample_avg: number | null; in_sample_sharpe: number | null; out_sample_sharpe: number | null; n_train: number; n_test: number } | null
  picks: HistPick[]
  created_at?: string
}
interface RegimeInfo {
  regime: string; vix: number; spy_price: number; spy_vs_sma50: number; spy_vs_sma200: number
  score_multiplier: number; color: string; description: string; updated_at: string
}

const REGIME_BG: Record<string, string> = {
  BULL:    'bg-green-50  border-green-200  text-green-800  dark:bg-green-900/20  dark:border-green-700  dark:text-green-300',
  NEUTRAL: 'bg-yellow-50 border-yellow-200 text-yellow-800 dark:bg-yellow-900/20 dark:border-yellow-700 dark:text-yellow-300',
  BEAR:    'bg-orange-50 border-orange-200 text-orange-800 dark:bg-orange-900/20 dark:border-orange-700 dark:text-orange-300',
  CRISIS:  'bg-red-50    border-red-200    text-red-800    dark:bg-red-900/20    dark:border-red-700    dark:text-red-300',
}

function RegimeBanner({ regime }: { regime: RegimeInfo }) {
  const cls = REGIME_BG[regime.regime] ?? REGIME_BG.NEUTRAL
  const icon = { BULL: '🟢', NEUTRAL: '🟡', BEAR: '🟠', CRISIS: '🔴' }[regime.regime] ?? '🟡'
  return (
    <div className={`flex items-start gap-3 rounded-xl border px-4 py-3 text-sm ${cls}`}>
      <span className="text-lg leading-none mt-0.5">{icon}</span>
      <div className="flex-1 min-w-0">
        <span className="font-bold mr-2">Market Regime: {regime.regime}</span>
        <span className="opacity-80">{regime.description}</span>
        <span className="ml-3 opacity-60 text-xs">
          · Score multiplier: {regime.score_multiplier}×
          · SPY vs SMA50: {regime.spy_vs_sma50 > 0 ? '+' : ''}{regime.spy_vs_sma50.toFixed(1)}%
          · vs SMA200: {regime.spy_vs_sma200 > 0 ? '+' : ''}{regime.spy_vs_sma200.toFixed(1)}%
        </span>
      </div>
    </div>
  )
}

function HistoricalBacktestTab() {
  const [yearsBack, setYearsBack] = useState(2)
  const [topN, setTopN] = useState(5)
  const [running, setRunning] = useState(false)
  const [runResult, setRunResult] = useState<HistResult | null>(null)
  const [runError, setRunError] = useState<string | null>(null)
  const qc = useQueryClient()

  const { data: saved, isLoading } = useQuery<HistResult>({
    queryKey: ['hist-backtest'],
    queryFn: apiGetHistoricalBacktest,
  })

  const { data: regime } = useQuery<RegimeInfo>({
    queryKey: ['admin-regime'],
    queryFn:  apiGetRegime,
    staleTime: 3600_000,
  })

  const data: HistResult | null = runResult ?? (saved?.message ? null : saved ?? null)

  async function handleRun() {
    setRunning(true)
    setRunError(null)
    try {
      const res = await apiRunHistoricalBacktest({ years_back: yearsBack, top_n: topN })
      setRunResult(res)
      qc.invalidateQueries({ queryKey: ['hist-backtest'] })
    } catch (e: any) {
      setRunError(e?.response?.data?.detail ?? 'Backtest failed — check server logs.')
    } finally {
      setRunning(false)
    }
  }

  function wfmt(w: number) { return `${(w * 100).toFixed(0)}%` }

  if (isLoading) return <div className="flex items-center justify-center h-40"><Spinner /></div>

  return (
    <div className="space-y-6">
      {regime && <RegimeBanner regime={regime} />}

      {/* Controls */}
      <div className="card p-4 flex flex-wrap items-end gap-4">
        <div>
          <p className="text-xs text-ink-faint uppercase mb-1">History</p>
          <div className="flex gap-1">
            {[1, 2, 3].map(y => (
              <button key={y} onClick={() => setYearsBack(y)}
                className={`px-3 py-1.5 rounded-lg text-sm font-semibold transition-all
                  ${yearsBack === y ? 'bg-primary text-white' : 'bg-surface-muted text-ink-muted hover:text-ink'}`}>
                {y}y
              </button>
            ))}
          </div>
        </div>
        <div>
          <p className="text-xs text-ink-faint uppercase mb-1">Top N picks / eval</p>
          <div className="flex gap-1">
            {[3, 5, 10].map(n => (
              <button key={n} onClick={() => setTopN(n)}
                className={`px-3 py-1.5 rounded-lg text-sm font-semibold transition-all
                  ${topN === n ? 'bg-primary text-white' : 'bg-surface-muted text-ink-muted hover:text-ink'}`}>
                {n}
              </button>
            ))}
          </div>
        </div>
        <button onClick={handleRun} disabled={running}
          className="btn-primary ml-auto flex items-center gap-2 disabled:opacity-50">
          {running ? <><Spinner /><span>Running (~30s)…</span></> : '▶ Run Historical Backtest'}
        </button>
      </div>

      {runError && <p className="text-red-500 text-sm bg-red-50 dark:bg-red-900/20 rounded-lg px-4 py-3">{runError}</p>}

      {!data && !running && (
        <div className="card p-8 text-center text-ink-faint">
          <p className="text-lg mb-2">No historical backtest yet</p>
          <p className="text-sm">Click "Run Historical Backtest" above to simulate {yearsBack} years of monthly picks and measure actual forward returns.</p>
        </div>
      )}

      {data && (
        <>
          {/* Summary */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <div className="card p-4 text-center">
              <p className="text-2xl font-extrabold text-ink">{data.n_evaluations}</p>
              <p className="text-xs text-ink-faint mt-1">Evaluation Dates</p>
            </div>
            <div className="card p-4 text-center">
              <p className="text-2xl font-extrabold text-ink">{data.n_picks_total}</p>
              <p className="text-xs text-ink-faint mt-1">Total Picks Simulated</p>
            </div>
            <div className="card p-4 text-center">
              <p className={`text-2xl font-extrabold ${(data.stats_5d?.avg ?? 0) > 0 ? 'text-green-600' : 'text-red-500'}`}>
                {data.stats_5d?.avg != null ? `${data.stats_5d.avg > 0 ? '+' : ''}${data.stats_5d.avg.toFixed(2)}%` : '—'}
              </p>
              <p className="text-xs text-ink-faint mt-1">Avg 5D Return</p>
            </div>
            <div className="card p-4 text-center">
              <p className={`text-2xl font-extrabold ${(data.alpha_5d?.avg ?? 0) > 0 ? 'text-green-600' : 'text-red-500'}`}>
                {data.alpha_5d?.avg != null ? `${data.alpha_5d.avg > 0 ? '+' : ''}${data.alpha_5d.avg.toFixed(2)}%` : '—'}
              </p>
              <p className="text-xs text-ink-faint mt-1">Avg 5D Alpha vs SPY</p>
            </div>
          </div>

          {/* Performance table */}
          <div className="card overflow-hidden">
            <div className="px-4 py-3 border-b border-surface-border bg-surface-muted">
              <span className="text-sm font-bold">Return Statistics</span>
            </div>
            <table className="w-full text-sm">
              <thead className="bg-surface-muted border-b border-surface-border">
                <tr>
                  {['Horizon', 'Picks', 'Avg Return', 'Win Rate', 'Sharpe', 'Avg Alpha vs SPY'].map(h => (
                    <th key={h} className="px-4 py-2.5 text-left text-xs font-bold uppercase tracking-wide text-ink-faint">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-surface-border">
                {[
                  { label: '5-Day', s: data.stats_5d,  a: data.alpha_5d  },
                  { label: '21-Day',s: data.stats_21d, a: data.alpha_21d },
                  { label: '63-Day',s: data.stats_63d, a: null },
                ].map(({ label, s, a }) => (
                  <tr key={label} className="hover:bg-surface-muted/40">
                    <td className="px-4 py-2.5 font-semibold">{label}</td>
                    <td className="px-4 py-2.5 text-ink-muted">{s?.n ?? 0}</td>
                    <td className={`px-4 py-2.5 font-bold ${(s?.avg ?? 0) > 0 ? 'text-green-600' : (s?.avg ?? 0) < 0 ? 'text-red-500' : 'text-ink-muted'}`}>
                      {s?.avg != null ? `${s.avg > 0 ? '+' : ''}${s.avg.toFixed(2)}%` : '—'}
                    </td>
                    <td className="px-4 py-2.5">{s?.win_rate != null ? `${s.win_rate.toFixed(1)}%` : '—'}</td>
                    <td className="px-4 py-2.5">{s?.sharpe != null ? s.sharpe.toFixed(2) : '—'}</td>
                    <td className={`px-4 py-2.5 font-bold ${(a?.avg ?? 0) > 0 ? 'text-green-600' : (a?.avg ?? 0) < 0 ? 'text-red-500' : 'text-ink-faint'}`}>
                      {a?.avg != null ? `${a.avg > 0 ? '+' : ''}${a.avg.toFixed(2)}%` : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Weight comparison */}
          {data.optimal_weights && (
            <div className="card overflow-hidden">
              <div className="px-4 py-3 border-b border-surface-border bg-surface-muted flex items-center justify-between">
                <span className="text-sm font-bold">Walk-Forward Weight Optimisation</span>
                {data.optimization_result && (
                  <span className="text-xs text-ink-faint">
                    In-sample avg: <strong className={`${(data.optimization_result.in_sample_avg ?? 0) > 0 ? 'text-green-600' : 'text-red-500'}`}>
                      {data.optimization_result.in_sample_avg != null ? `${data.optimization_result.in_sample_avg > 0 ? '+' : ''}${data.optimization_result.in_sample_avg.toFixed(2)}%` : '—'}
                    </strong>
                    &nbsp;·&nbsp;Out-of-sample avg: <strong className={`${(data.optimization_result.out_sample_avg ?? 0) > 0 ? 'text-green-600' : 'text-red-500'}`}>
                      {data.optimization_result.out_sample_avg != null ? `${data.optimization_result.out_sample_avg > 0 ? '+' : ''}${data.optimization_result.out_sample_avg.toFixed(2)}%` : '—'}
                    </strong>
                    &nbsp;·&nbsp;Train={data.optimization_result.n_train} / Test={data.optimization_result.n_test}
                  </span>
                )}
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="bg-surface-muted border-b border-surface-border">
                    <tr>
                      <th className="px-4 py-2 text-left text-xs font-bold uppercase tracking-wide text-ink-faint">Factor</th>
                      <th className="px-4 py-2 text-left text-xs font-bold uppercase tracking-wide text-ink-faint">Default Weight</th>
                      <th className="px-4 py-2 text-left text-xs font-bold uppercase tracking-wide text-ink-faint">Optimal Weight</th>
                      <th className="px-4 py-2 text-left text-xs font-bold uppercase tracking-wide text-ink-faint">Change</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-surface-border">
                    {Object.entries(data.default_weights).map(([k, dw]) => {
                      const ow = (data.optimal_weights as any)?.[k] ?? 0
                      const delta = ow - dw
                      return (
                        <tr key={k} className="hover:bg-surface-muted/40">
                          <td className="px-4 py-2 font-mono text-sm">{k}</td>
                          <td className="px-4 py-2 text-ink-muted">{wfmt(dw)}</td>
                          <td className="px-4 py-2 font-bold">{wfmt(ow)}</td>
                          <td className={`px-4 py-2 text-sm font-semibold ${delta > 0.02 ? 'text-green-600' : delta < -0.02 ? 'text-red-500' : 'text-ink-muted'}`}>
                            {delta > 0 ? '+' : ''}{wfmt(delta)}
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Pick sample */}
          {data.picks && data.picks.length > 0 && (
            <div className="card overflow-hidden">
              <div className="px-4 py-3 border-b border-surface-border bg-surface-muted">
                <span className="text-sm font-bold">Recent Simulated Picks (last {data.picks.length})</span>
                <span className="ml-2 text-xs text-ink-faint">5D / 21D / 63D = actual returns measured N trading days after each monthly evaluation</span>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead className="bg-surface-muted border-b border-surface-border">
                    <tr>
                      {['Date', 'Ticker', 'Rank', 'Score', 'Entry', '5D ret', 'Alpha 5D', '21D ret', 'Alpha 21D', '63D ret'].map(h => (
                        <th key={h} className="px-3 py-2 text-left font-bold uppercase tracking-wide text-ink-faint whitespace-nowrap">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-surface-border">
                    {data.picks.map((p, i) => (
                      <tr key={i} className="hover:bg-surface-muted/40 transition-colors">
                        <td className="px-3 py-2 text-ink-muted whitespace-nowrap">{p.eval_date}</td>
                        <td className="px-3 py-2 font-bold text-ink">{p.ticker}</td>
                        <td className="px-3 py-2 text-ink-muted">#{p.rank}</td>
                        <td className="px-3 py-2 font-semibold">{p.score.toFixed(0)}</td>
                        <td className="px-3 py-2 text-ink-muted">${p.entry.toFixed(2)}</td>
                        <td className="px-3 py-2"><Ret v={p.return_5d} /></td>
                        <td className="px-3 py-2"><Ret v={p.alpha_5d} /></td>
                        <td className="px-3 py-2"><Ret v={p.return_21d} /></td>
                        <td className="px-3 py-2"><Ret v={p.alpha_21d} /></td>
                        <td className="px-3 py-2"><Ret v={p.return_63d} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
          {data.created_at && <p className="text-xs text-ink-faint">Last run: {new Date(data.created_at).toLocaleString()}</p>}
        </>
      )}
    </div>
  )
}

// ── Digest Email List tab ──────────────────────────────────────────────────────
interface DigestEmail { id: number; email: string; name: string; is_active: boolean; added_at: string }

function DigestEmailsTab() {
  const qc = useQueryClient()
  const [emailInput, setEmailInput] = useState('')
  const [nameInput, setNameInput]   = useState('')
  const [err, setErr] = useState('')

  const { data: list = [], isLoading } = useQuery<DigestEmail[]>({
    queryKey: ['digest-emails'],
    queryFn:  apiGetDigestEmails,
  })

  const addMut = useMutation({
    mutationFn: () => apiAddDigestEmail(emailInput.trim(), nameInput.trim()),
    onSuccess:  () => { qc.invalidateQueries({ queryKey: ['digest-emails'] }); setEmailInput(''); setNameInput(''); setErr('') },
    onError:    (e: unknown) => setErr((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || 'Failed to add'),
  })

  const toggleMut = useMutation({
    mutationFn: ({ id, is_active }: { id: number; is_active: boolean }) => apiToggleDigestEmail(id, is_active),
    onSuccess:  () => qc.invalidateQueries({ queryKey: ['digest-emails'] }),
  })

  const deleteMut = useMutation({
    mutationFn: (id: number) => apiDeleteDigestEmail(id),
    onSuccess:  () => qc.invalidateQueries({ queryKey: ['digest-emails'] }),
  })

  const active = list.filter(e => e.is_active).length

  return (
    <div className="space-y-6">
      <div className="flex gap-4 flex-wrap">
        <KpiCard value={list.length} label="Total Addresses" />
        <KpiCard value={active}      label="Active (will receive digest)" />
      </div>

      {/* Add form */}
      <div className="card p-5">
        <h3 className="font-bold text-ink mb-4">Add Email Address</h3>
        <div className="flex gap-3 flex-wrap items-end">
          <div className="flex-1 min-w-48">
            <label className="label">Email address</label>
            <input
              type="email"
              className="input"
              placeholder="someone@example.com"
              value={emailInput}
              onChange={e => setEmailInput(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && addMut.mutate()}
            />
          </div>
          <div className="flex-1 min-w-36">
            <label className="label">Name (optional)</label>
            <input
              type="text"
              className="input"
              placeholder="John"
              value={nameInput}
              onChange={e => setNameInput(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && addMut.mutate()}
            />
          </div>
          <button
            onClick={() => addMut.mutate()}
            disabled={addMut.isPending || !emailInput.trim()}
            className="btn-primary disabled:opacity-50"
          >
            {addMut.isPending ? 'Adding…' : '+ Add'}
          </button>
        </div>
        {err && <p className="text-red-600 text-sm mt-2">{err}</p>}
      </div>

      {/* List */}
      {isLoading ? (
        <div className="flex items-center justify-center h-32"><Spinner /></div>
      ) : list.length === 0 ? (
        <div className="card p-8 text-center text-ink-faint">
          <p className="text-lg mb-1">No email addresses yet</p>
          <p className="text-sm">Add addresses above — they'll receive the daily digest regardless of user accounts.</p>
        </div>
      ) : (
        <div className="card overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-surface-muted border-b border-surface-border">
              <tr>
                {['Email', 'Name', 'Added', 'Status', 'Actions'].map(h => (
                  <th key={h} className="px-4 py-3 text-left text-xs font-bold uppercase tracking-wide text-ink-faint">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-surface-border">
              {list.map(e => (
                <tr key={e.id} className="hover:bg-surface-muted/40 transition-colors">
                  <td className="px-4 py-3 font-medium text-ink">{e.email}</td>
                  <td className="px-4 py-3 text-ink-muted">{e.name || '—'}</td>
                  <td className="px-4 py-3 text-xs text-ink-muted">{e.added_at?.slice(0, 10)}</td>
                  <td className="px-4 py-3">
                    <span className={`text-xs px-2 py-0.5 rounded font-semibold ${e.is_active ? 'bg-green-100 text-green-800' : 'bg-surface-muted text-ink-faint'}`}>
                      {e.is_active ? 'Active' : 'Paused'}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex gap-1.5">
                      <button
                        onClick={() => toggleMut.mutate({ id: e.id, is_active: !e.is_active })}
                        className={`text-xs py-1 px-2 rounded-lg font-semibold transition-all ${e.is_active ? 'bg-yellow-50 text-yellow-700 hover:bg-yellow-100' : 'bg-green-50 text-green-700 hover:bg-green-100'}`}
                      >
                        {e.is_active ? 'Pause' : 'Resume'}
                      </button>
                      <button
                        onClick={() => deleteMut.mutate(e.id)}
                        className="text-xs py-1 px-2 rounded-lg font-semibold bg-red-50 text-red-600 hover:bg-red-100 transition-all"
                      >
                        Remove
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

// ── Main ───────────────────────────────────────────────────────────────────────
export function AdminPanel() {
  const [tab, setTab] = useState<'overview'|'users'|'licenses'|'audit'|'tokens'|'backtest'|'hist-backtest'|'digest-emails'>('overview')
  const { data: users    = [], isLoading: lu } = useQuery({ queryKey:['admin-users'],    queryFn:apiGetUsers })
  const { data: licenses = [], isLoading: ll } = useQuery({ queryKey:['admin-licenses'], queryFn:apiGetLicenses })

  if (lu || ll) return <div className="flex items-center justify-center h-64"><Spinner /></div>

  const TABS = [
    { key:'overview',      label:'📊 Overview' },
    { key:'users',         label:'👥 Users' },
    { key:'licenses',      label:'🔑 Licenses' },
    { key:'audit',         label:'📋 Audit Log' },
    { key:'tokens',        label:'💰 Token Usage' },
    { key:'backtest',      label:'📈 Backtest' },
    { key:'hist-backtest', label:'🔬 Hist Backtest' },
    { key:'digest-emails', label:'📧 Digest Emails' },
  ] as const

  return (
    <div className="p-6">
      <h1 className="text-2xl font-extrabold text-ink mb-1">Admin Panel</h1>
      <p className="text-ink-muted text-sm mb-6">Manage users, licenses, and review system activity</p>

      {/* Tab bar */}
      <div className="flex gap-1 bg-surface-muted p-1 rounded-xl border border-surface-border mb-6 w-fit">
        {TABS.map(t => (
          <button key={t.key} onClick={() => setTab(t.key)}
            className={`px-4 py-2 rounded-lg text-sm font-semibold transition-all
              ${tab===t.key ? 'bg-surface text-ink shadow-sm ring-1 ring-surface-border' : 'text-ink-muted hover:text-ink'}`}>
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'overview'  && <OverviewTab users={users} licenses={licenses} />}
      {tab === 'users'     && <UsersTab    users={users} licenses={licenses} />}
      {tab === 'licenses'  && <LicensesTab licenses={licenses} />}
      {tab === 'audit'     && <AuditTab />}
      {tab === 'tokens'        && <TokenUsageTab />}
      {tab === 'backtest'      && <BacktestTab />}
      {tab === 'hist-backtest' && <HistoricalBacktestTab />}
      {tab === 'digest-emails' && <DigestEmailsTab />}
    </div>
  )
}
