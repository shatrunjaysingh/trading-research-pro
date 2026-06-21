import { useThemeStore } from '../../store/theme'

export function ThemeToggle() {
  const { theme, toggle } = useThemeStore()
  return (
    <button
      onClick={toggle}
      title={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
      style={{
        display: 'flex', alignItems: 'center', gap: '8px',
        width: '100%', padding: '10px 12px', borderRadius: '8px',
        background: 'transparent', border: 'none', cursor: 'pointer',
        color: '#94A3B8', fontSize: '14px', fontWeight: 500,
        transition: 'background 0.15s',
      }}
      onMouseEnter={e => (e.currentTarget.style.background = 'rgba(255,255,255,0.08)')}
      onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
    >
      <span style={{ fontSize: '16px' }}>{theme === 'dark' ? '☀️' : '🌙'}</span>
      {theme === 'dark' ? 'Light Mode' : 'Dark Mode'}
    </button>
  )
}
