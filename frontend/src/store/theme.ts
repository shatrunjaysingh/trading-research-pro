import { create } from 'zustand'
import { persist } from 'zustand/middleware'

type Theme = 'light' | 'dark'

interface ThemeStore {
  theme: Theme
  toggle: () => void
  setTheme: (t: Theme) => void
}

function applyTheme(t: Theme) {
  document.documentElement.classList.toggle('dark', t === 'dark')
}

export const useThemeStore = create<ThemeStore>()(
  persist(
    (set, get) => ({
      theme: 'light',
      setTheme: (theme) => { set({ theme }); applyTheme(theme) },
      toggle:   () => { const next = get().theme === 'light' ? 'dark' : 'light'; get().setTheme(next) },
    }),
    { name: 'theme-pref' },
  ),
)
