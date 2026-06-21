import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuthStore } from '../store/auth'
import { apiLogin, apiRegister } from '../api/auth'

export function AuthPage() {
  const [tab, setTab] = useState<'signin' | 'signup'>('signin')
  const { setAuth } = useAuthStore()
  const navigate = useNavigate()

  // Sign-in state
  const [siEmail, setSiEmail] = useState('')
  const [siPwd,   setSiPwd]   = useState('')
  const [siErr,   setSiErr]   = useState('')
  const [siLoading, setSiLoading] = useState(false)

  // Sign-up state
  const [suName,    setSuName]    = useState('')
  const [suEmail,   setSuEmail]   = useState('')
  const [suUser,    setSuUser]    = useState('')
  const [suPwd,     setSuPwd]     = useState('')
  const [suConf,    setSuConf]    = useState('')
  const [suConsent, setSuConsent] = useState(false)
  const [suErr,     setSuErr]     = useState('')
  const [suLoading, setSuLoading] = useState(false)

  const handleSignIn = async (e: React.FormEvent) => {
    e.preventDefault()
    setSiErr(''); setSiLoading(true)
    try {
      const data = await apiLogin(siEmail, siPwd)
      setAuth(data.access_token, data.user)
      navigate('/research')
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setSiErr(msg || 'Login failed.')
    } finally { setSiLoading(false) }
  }

  const handleSignUp = async (e: React.FormEvent) => {
    e.preventDefault()
    setSuErr('')
    if (suPwd !== suConf) { setSuErr('Passwords do not match.'); return }
    setSuLoading(true)
    if (!suConsent) { setSuErr('You must accept the disclaimer and Terms of Use to create an account.'); return }
    try {
      const data = await apiRegister({ email: suEmail, username: suUser, password: suPwd, full_name: suName, consent: true })
      setAuth(data.access_token, data.user)
      navigate('/research')
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setSuErr(msg || 'Registration failed.')
    } finally { setSuLoading(false) }
  }

  return (
    <div className="min-h-screen bg-canvas flex items-center justify-center p-4">
      <div className="w-full max-w-md">
        {/* Hero */}
        <div className="text-center mb-8">
          <div className="text-5xl mb-3">📈</div>
          <h1 className="text-3xl font-extrabold text-ink tracking-tight">TradingResearch Pro</h1>
          <p className="text-ink-muted mt-1.5 text-sm">Institutional-grade market intelligence</p>
        </div>

        <div className="card p-6">
          {/* Tab switcher */}
          <div className="flex bg-surface-muted rounded-lg p-1 mb-6">
            {(['signin','signup'] as const).map(t => (
              <button key={t} onClick={() => setTab(t)}
                className={`flex-1 py-2 rounded-md text-sm font-semibold transition-all ${
                  tab === t ? 'bg-surface text-ink shadow-sm ring-1 ring-surface-border' : 'text-ink-muted hover:text-ink'}`}>
                {t === 'signin' ? 'Sign In' : 'Create Account'}
              </button>
            ))}
          </div>

          {/* Sign In */}
          {tab === 'signin' && (
            <form onSubmit={handleSignIn} className="space-y-4">
              <div>
                <label className="label">Email</label>
                <input className="input" type="email" placeholder="you@company.com"
                  value={siEmail} onChange={e => setSiEmail(e.target.value)} required />
              </div>
              <div>
                <label className="label">Password</label>
                <input className="input" type="password" placeholder="••••••••"
                  value={siPwd} onChange={e => setSiPwd(e.target.value)} required />
              </div>
              {siErr && <p className="text-red-600 text-sm bg-red-50 p-2.5 rounded-lg">{siErr}</p>}
              <button type="submit" disabled={siLoading} className="btn-primary w-full py-2.5">
                {siLoading ? 'Signing in…' : 'Sign In →'}
              </button>
            </form>
          )}

          {/* Sign Up */}
          {tab === 'signup' && (
            <form onSubmit={handleSignUp} className="space-y-4">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="label">Full Name</label>
                  <input className="input" placeholder="Jane Smith"
                    value={suName} onChange={e => setSuName(e.target.value)} required />
                </div>
                <div>
                  <label className="label">Username</label>
                  <input className="input" placeholder="jsmith"
                    value={suUser} onChange={e => setSuUser(e.target.value)} required />
                </div>
              </div>
              <div>
                <label className="label">Email</label>
                <input className="input" type="email" placeholder="you@company.com"
                  value={suEmail} onChange={e => setSuEmail(e.target.value)} required />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="label">Password</label>
                  <input className="input" type="password"
                    value={suPwd} onChange={e => setSuPwd(e.target.value)} required />
                </div>
                <div>
                  <label className="label">Confirm</label>
                  <input className="input" type="password"
                    value={suConf} onChange={e => setSuConf(e.target.value)} required />
                </div>
              </div>
              <p className="text-xs text-ink-faint">Min 8 chars · upper · lower · digit · special</p>

              {/* Consent checkbox */}
              <label className="flex items-start gap-2.5 cursor-pointer group">
                <input
                  type="checkbox"
                  checked={suConsent}
                  onChange={e => setSuConsent(e.target.checked)}
                  className="mt-0.5 w-4 h-4 accent-primary flex-shrink-0"
                />
                <span className="text-xs text-ink-muted leading-relaxed">
                  I understand that TradingResearch Pro provides AI-generated research for{' '}
                  <strong className="text-ink">informational purposes only</strong> and does not
                  constitute investment advice. I will not make investment decisions based solely
                  on this platform. I agree to the{' '}
                  <span className="text-primary underline">Terms of Use</span> and{' '}
                  <span className="text-primary underline">Privacy Policy</span>.
                </span>
              </label>

              {suErr && <p className="text-red-600 text-sm bg-red-50 p-2.5 rounded-lg">{suErr}</p>}
              <button type="submit" disabled={suLoading || !suConsent} className="btn-primary w-full py-2.5 disabled:opacity-50 disabled:cursor-not-allowed">
                {suLoading ? 'Creating…' : 'Create Account →'}
              </button>
            </form>
          )}

          <p className="text-center text-xs text-ink-faint mt-5">
            Research only · Not financial advice
          </p>
        </div>
      </div>
    </div>
  )
}
