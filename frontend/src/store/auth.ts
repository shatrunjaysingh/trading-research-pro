import { create } from 'zustand'
import type { User } from '../types'

interface AuthState {
  token: string | null
  user:  User | null
  setAuth: (token: string, user: User) => void
  clearAuth: () => void
}

export const useAuthStore = create<AuthState>((set) => ({
  token: localStorage.getItem('access_token'),
  user:  null,

  setAuth: (token, user) => {
    localStorage.setItem('access_token', token)
    set({ token, user })
    import('./market').then(m => m.useMarketStore.getState().loadPreferences()).catch(() => {})
  },

  clearAuth: () => {
    localStorage.removeItem('access_token')
    set({ token: null, user: null })
  },
}))
