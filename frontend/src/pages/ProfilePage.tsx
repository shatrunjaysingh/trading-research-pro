import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useAuthStore } from '../store/auth'
import { apiChangePassword, apiMyAudit, apiExportData, apiDeleteAccount } from '../api/profile'
import { RoleBadge, TierBadge } from '../components/ui/Badge'

import type { User } from '../types'
type AuthUser = User | null
const PERMS: [string, (u: AuthUser) => boolean][] = [
  ['Free Research',   u => !!u],
  ['Deep Research',   u => u?.allowed_modes?.includes('api') ?? false],
  ['All Sectors',     u => u?.allowed_sectors === 'all' || (Array.isArray(u?.allowed_sectors) && u.allowed_sectors.includes('all'))],
  ['Penny Stocks',    u => u?.allowed_sectors === 'all' || (Array.isArray(u?.allowed_sectors) && u.allowed_sectors.includes('penny'))],
  ['Email Reports',   u => !!u?.can_email],
  ['Data Export',     u => !!u?.can_export],
  ['Admin Panel',     u => !!u?.can_admin],
]

export function ProfilePage() {
  const { user, clearAuth } = useAuthStore()
  const [curPwd,  setCurPwd]  = useState('')
  const [newPwd,  setNewPwd]  = useState('')
  const [confPwd, setConfPwd] = useState('')
  const [pwdErr,  setPwdErr]  = useState('')
  const [pwdOk,   setPwdOk]   = useState(false)
  const [loading, setLoading] = useState(false)

  const [exportLoading, setExportLoading] = useState(false)
  const [deleteStep, setDeleteStep]   = useState<'idle' | 'confirm' | 'loading'>('idle')
  const [deletePwd,  setDeletePwd]    = useState('')
  const [deleteErr,  setDeleteErr]    = useState('')

  const { data: audit = [] } = useQuery({ queryKey: ['my-audit'], queryFn: () => apiMyAudit(20) })

  const handleExport = async () => {
    setExportLoading(true)
    try {
      const data = await apiExportData()
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
      const url  = URL.createObjectURL(blob)
      const a    = document.createElement('a')
      a.href     = url
      a.download = `trading-research-data-export-${new Date().toISOString().slice(0,10)}.json`
      a.click()
      URL.revokeObjectURL(url)
    } catch { /* ignore */ } finally { setExportLoading(false) }
  }

  const handleDeleteAccount = async () => {
    if (!deletePwd) { setDeleteErr('Enter your password to confirm.'); return }
    setDeleteStep('loading'); setDeleteErr('')
    try {
      await apiDeleteAccount(deletePwd)
      clearAuth()
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setDeleteErr(msg || 'Deletion failed.')
      setDeleteStep('confirm')
    }
  }

  const handlePasswordChange = async (e: React.FormEvent) => {
    e.preventDefault()
    setPwdErr(''); setPwdOk(false)
    if (newPwd !== confPwd) { setPwdErr('Passwords do not match.'); return }
    setLoading(true)
    try {
      await apiChangePassword(curPwd, newPwd)
      setPwdOk(true)
      setCurPwd(''); setNewPwd(''); setConfPwd('')
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setPwdErr(msg || 'Failed to update password.')
    } finally { setLoading(false) }
  }

  if (!user) return null

  const fields = [
    ['Full Name',    user.full_name || '—'],
    ['Email',        user.email],
    ['Username',     `@${user.username}`],
    ['Member Since', user.created_at?.slice(0,10) || '—'],
    ['Last Login',   user.last_login?.slice(0,16).replace('T',' ') || '—'],
  ]

  return (
    <div className="p-6 max-w-4xl">
      <h1 className="text-2xl font-extrabold text-ink mb-1">My Profile</h1>
      <p className="text-ink-muted text-sm mb-6">Account details and security</p>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Account info */}
        <div className="space-y-5">
          <div className="card p-5">
            <h2 className="font-bold text-ink mb-4">Account Information</h2>
            <div className="divide-y divide-surface-border">
              {fields.map(([k, v]) => (
                <div key={k} className="flex justify-between py-3">
                  <span className="text-xs font-bold uppercase tracking-wide text-ink-faint">{k}</span>
                  <span className="text-sm font-medium text-ink">{v}</span>
                </div>
              ))}
              <div className="flex justify-between py-3">
                <span className="text-xs font-bold uppercase tracking-wide text-ink-faint">Role</span>
                <RoleBadge role={user.role} />
              </div>
              <div className="flex justify-between py-3">
                <span className="text-xs font-bold uppercase tracking-wide text-ink-faint">License</span>
                <div className="flex items-center gap-2">
                  <span className="text-sm text-ink-muted">{user.license_name || 'None'}</span>
                  {user.license_tier && <TierBadge tier={user.license_tier} />}
                </div>
              </div>
            </div>
          </div>

          {/* Permissions */}
          <div className="card p-5">
            <h2 className="font-bold text-ink mb-4">Access Permissions</h2>
            <div className="grid grid-cols-2 gap-2">
              {PERMS.map(([label, check]) => {
                const ok = check(user)
                return (
                  <div key={label} className={`flex items-center gap-2 text-sm py-1.5 ${ok ? 'text-green-700' : 'text-ink-faint'}`}>
                    <span>{ok ? '✅' : '🔒'}</span>
                    <span className="font-medium">{label}</span>
                  </div>
                )
              })}
            </div>
          </div>
        </div>

        {/* Right column */}
        <div className="space-y-5">
          {/* Change password */}
          <div className="card p-5">
            <h2 className="font-bold text-ink mb-4">Change Password</h2>
            <form onSubmit={handlePasswordChange} className="space-y-3">
              {[
                ['Current Password', curPwd, setCurPwd],
                ['New Password',     newPwd, setNewPwd],
                ['Confirm New',      confPwd, setConfPwd],
              ].map(([label, val, setter]) => (
                <div key={label as string}>
                  <label className="label">{label as string}</label>
                  <input type="password" className="input" value={val as string}
                    onChange={e => (setter as (v: string) => void)(e.target.value)} required />
                </div>
              ))}
              <p className="text-xs text-ink-faint">Min 8 chars · upper · lower · digit · special</p>
              {pwdErr && <p className="text-sm text-red-600 bg-red-50 p-2.5 rounded-lg">{pwdErr}</p>}
              {pwdOk  && <p className="text-sm text-green-700 bg-green-50 p-2.5 rounded-lg">✅ Password updated successfully</p>}
              <button type="submit" disabled={loading} className="btn-primary w-full py-2.5">
                {loading ? 'Updating…' : 'Update Password'}
              </button>
            </form>
          </div>

          {/* Recent activity */}
          {audit.length > 0 && (
            <div className="card p-5">
              <h2 className="font-bold text-ink mb-4">Recent Activity</h2>
              <div className="space-y-2">
                {audit.slice(0, 8).map(e => (
                  <div key={e.id} className="flex items-center gap-3 text-xs">
                    <span className="text-ink-faint shrink-0">{e.created_at?.slice(0,16).replace('T',' ')}</span>
                    <span className="bg-surface-muted text-ink-muted px-1.5 py-0.5 rounded font-mono shrink-0">{e.action}</span>
                    <span className="text-ink-muted truncate">{e.details}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Data & Privacy */}
          <div className="card p-5 space-y-4">
            <h2 className="font-bold text-ink">Data & Privacy</h2>

            {/* Export */}
            <div>
              <p className="text-sm text-ink-muted mb-2">
                Download a copy of all data we hold about you (GDPR Art. 20 — right to portability).
              </p>
              <button
                onClick={handleExport}
                disabled={exportLoading}
                className="btn-secondary text-sm px-4 py-2 disabled:opacity-50"
              >
                {exportLoading ? 'Preparing…' : '⬇ Export My Data (JSON)'}
              </button>
            </div>

            <hr className="border-surface-border" />

            {/* Delete account */}
            <div>
              <p className="text-sm font-semibold text-red-600 mb-1">Delete Account</p>
              <p className="text-xs text-ink-muted mb-3">
                Permanently anonymises your account (GDPR Art. 17 — right to erasure).
                Audit records are retained as required by financial regulations.
                This action <strong>cannot be undone</strong>.
              </p>

              {deleteStep === 'idle' && (
                <button
                  onClick={() => setDeleteStep('confirm')}
                  className="text-sm px-4 py-2 rounded-lg border border-red-300 text-red-600 hover:bg-red-50 transition-colors"
                >
                  Delete My Account
                </button>
              )}

              {(deleteStep === 'confirm' || deleteStep === 'loading') && (
                <div className="space-y-2 bg-red-50 border border-red-200 rounded-xl p-4">
                  <p className="text-xs font-semibold text-red-700">Confirm deletion — enter your password:</p>
                  <input
                    type="password"
                    className="input text-sm"
                    placeholder="Your current password"
                    value={deletePwd}
                    onChange={e => setDeletePwd(e.target.value)}
                  />
                  {deleteErr && <p className="text-xs text-red-700">{deleteErr}</p>}
                  <div className="flex gap-2">
                    <button
                      onClick={handleDeleteAccount}
                      disabled={deleteStep === 'loading'}
                      className="text-sm px-4 py-1.5 rounded-lg bg-red-600 text-white hover:bg-red-700 disabled:opacity-50"
                    >
                      {deleteStep === 'loading' ? 'Deleting…' : 'Confirm Delete'}
                    </button>
                    <button
                      onClick={() => { setDeleteStep('idle'); setDeletePwd(''); setDeleteErr('') }}
                      className="text-sm px-4 py-1.5 rounded-lg border border-surface-border text-ink-muted hover:text-ink"
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
