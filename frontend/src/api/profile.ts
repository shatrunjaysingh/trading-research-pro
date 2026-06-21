import client from './client'
import type { User, AuditEntry } from '../types'

export const apiGetProfile = () => client.get<User>('/profile').then(r => r.data)
export const apiUpdateProfile = (data: { full_name?: string }) =>
  client.patch<User>('/profile', data).then(r => r.data)
export const apiChangePassword = (current_password: string, new_password: string) =>
  client.post('/profile/change-password', { current_password, new_password })
export const apiMyAudit = (limit = 50) =>
  client.get<AuditEntry[]>('/profile/audit', { params: { limit } }).then(r => r.data)

export interface MarketPreferences {
  market_country?: string | null
  market_exchanges?: string[]
}

export const apiGetPreferences = () =>
  client.get<MarketPreferences>('/profile/preferences').then(r => r.data)

export const apiSavePreferences = (prefs: MarketPreferences) =>
  client.put('/profile/preferences', prefs)

export const apiExportData = () =>
  client.get('/profile/export').then(r => r.data)

export const apiDeleteAccount = (password: string) =>
  client.delete('/profile/me', { data: { password, confirm: 'DELETE MY ACCOUNT' } })
