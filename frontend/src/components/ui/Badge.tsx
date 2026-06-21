import { clsx } from 'clsx'

const ROLE_CLS: Record<string, string> = {
  admin:    'bg-role-admin   text-white',
  analyst:  'bg-role-analyst text-white',
  trader:   'bg-role-trader  text-white',
  viewer:   'bg-role-viewer  text-white',
}
const TIER_CLS: Record<string, string> = {
  free:         'bg-tier-free         text-white',
  professional: 'bg-tier-professional text-white',
  enterprise:   'bg-tier-enterprise   text-white',
}
const SIGNAL_CLS: Record<string, string> = {
  BUY:   'bg-signal-buy-bg   text-signal-buy   font-bold',
  WATCH: 'bg-signal-watch-bg text-signal-watch font-bold',
  HOLD:  'bg-signal-hold-bg  text-signal-hold  font-bold',
  SELL:  'bg-signal-sell-bg  text-signal-sell  font-bold',
}

const base = 'inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold'

export function RoleBadge({ role }: { role: string }) {
  const LABELS: Record<string, string> = { admin:'Admin', analyst:'Analyst', trader:'Trader', viewer:'Viewer' }
  return <span className={clsx(base, ROLE_CLS[role] ?? 'bg-gray-400 text-white')}>{LABELS[role] ?? role}</span>
}

export function TierBadge({ tier }: { tier: string }) {
  return <span className={clsx(base, TIER_CLS[tier] ?? 'bg-gray-400 text-white')}>{tier.charAt(0).toUpperCase()+tier.slice(1)}</span>
}

export function SignalBadge({ signal }: { signal: string }) {
  return <span className={clsx(base, SIGNAL_CLS[signal] ?? 'bg-gray-100 text-gray-600')}>{signal}</span>
}

export function StatusBadge({ active }: { active: boolean }) {
  return (
    <span className={clsx(base, active ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-700')}>
      {active ? 'Active' : 'Inactive'}
    </span>
  )
}
