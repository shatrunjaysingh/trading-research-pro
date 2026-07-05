import { NavLink } from 'react-router-dom'
import { clsx } from 'clsx'
import { useAuthStore } from '../../store/auth'

const NAV_ITEMS = [
  { to: '/market',    label: 'Market',    icon: '🌐' },
  { to: '/stocks',    label: 'Stocks',    icon: '📊' },
  { to: '/watchlist', label: 'Watchlist', icon: '👁' },
  { to: '/portfolio', label: 'Portfolio', icon: '💼' },
  { to: '/profile',   label: 'Profile',   icon: '👤' },
]

export function BottomNav() {
  const { user } = useAuthStore()
  if (!user) return null

  return (
    <nav className="fixed bottom-0 inset-x-0 z-40 bg-sidebar border-t border-white/10 flex safe-bottom">
      {NAV_ITEMS.map(({ to, label, icon }) => (
        <NavLink
          key={to}
          to={to}
          className={({ isActive }) =>
            clsx(
              'flex-1 flex flex-col items-center justify-center gap-0.5 py-2.5 text-[11px] font-medium transition-colors min-h-[52px]',
              isActive
                ? 'text-blue-400'
                : 'text-slate-400 active:text-white',
            )
          }
        >
          <span className="text-xl leading-none">{icon}</span>
          <span>{label}</span>
        </NavLink>
      ))}
    </nav>
  )
}
