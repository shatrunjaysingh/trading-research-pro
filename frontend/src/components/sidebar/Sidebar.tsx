import { NavLink, useNavigate } from 'react-router-dom'
import { clsx } from 'clsx'
import { useAuthStore } from '../../store/auth'
import { apiLogout } from '../../api/auth'
import { RoleBadge, TierBadge } from '../ui/Badge'
import { ThemeToggle } from '../ui/ThemeToggle'

const NAV = [
  { to: '/market',   label: 'Market Overview', icon: '🌐' },
  { to: '/research', label: 'Research',        icon: '🔍' },
  { to: '/stocks',   label: 'Stock Analysis',  icon: '📊' },
  { to: '/admin',    label: 'Admin Panel',     icon: '⚙️', admin: true },
  { to: '/profile',  label: 'My Profile',      icon: '👤' },
]

export function Sidebar({ onClose }: { onClose?: () => void } = {}) {
  const { user, clearAuth } = useAuthStore()
  const navigate = useNavigate()

  const handleLogout = async () => {
    try { await apiLogout() } catch { /* ignore */ }
    clearAuth()
    navigate('/login')
  }

  if (!user) return null

  return (
    <aside className="flex flex-col w-64 min-h-full bg-sidebar text-slate-300 flex-shrink-0">
      {/* Brand */}
      <div className="px-5 pt-6 pb-4 border-b border-white/10">
        <div className="flex items-center gap-2.5">
          <span className="text-xl">📈</span>
          <span className="font-extrabold text-white text-base tracking-tight flex-1">TradingResearch Pro</span>
          {onClose && (
            <button
              onClick={onClose}
              className="w-7 h-7 flex items-center justify-center rounded-lg hover:bg-white/10 text-slate-400 hover:text-white transition-colors text-lg"
              aria-label="Close menu"
            >
              ✕
            </button>
          )}
        </div>
      </div>

      {/* User card */}
      <div className="mx-3 mt-4 bg-white/5 rounded-xl p-3.5 border border-white/10">
        <div className="font-semibold text-white text-sm truncate">{user.full_name || user.username}</div>
        <div className="text-xs text-slate-400 truncate mt-0.5">{user.email}</div>
        <div className="flex gap-1.5 mt-2.5 flex-wrap">
          <RoleBadge role={user.role} />
          {user.license_tier && <TierBadge tier={user.license_tier} />}
        </div>
      </div>

      {/* Nav */}
      <nav className="flex-1 px-3 mt-5 space-y-1">
        <p className="px-2 text-xs font-bold uppercase tracking-widest text-slate-500 mb-2">Navigation</p>
        {NAV.map(({ to, label, icon, admin }) => {
          if (admin && user.role !== 'admin') return null
          return (
            <NavLink key={to} to={to} onClick={onClose}
              className={({ isActive }) => clsx(
                'flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-all',
                isActive
                  ? 'bg-primary text-white'
                  : 'text-slate-400 hover:bg-white/10 hover:text-white',
              )}>
              <span>{icon}</span>
              {label}
            </NavLink>
          )
        })}
      </nav>

      {/* Bottom */}
      <div className="px-3 pb-5 space-y-1">
        <ThemeToggle />
        <button onClick={handleLogout}
          className="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium text-slate-400 hover:bg-white/10 hover:text-white transition-all">
          <span>↩</span> Sign Out
        </button>

        {/* License info */}
        <div className="mx-1 text-xs text-slate-500 leading-relaxed">
          <div><span className="text-slate-400 font-semibold">License</span> &nbsp;{user.license_name || 'Free Tier'}</div>
          <div><span className="text-slate-400 font-semibold">Max picks</span> &nbsp;{user.max_picks ?? 3}</div>
        </div>
      </div>
    </aside>
  )
}
