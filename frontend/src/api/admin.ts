import client from './client'
import type { User, License, AuditEntry } from '../types'

// Users
export const apiGetUsers  = () => client.get<User[]>('/admin/users').then(r => r.data)
export const apiCreateUser = (data: object) => client.post<User>('/admin/users', data).then(r => r.data)
export const apiUpdateUser = (id: number, data: object) => client.patch<User>(`/admin/users/${id}`, data).then(r => r.data)
export const apiDeactivateUser = (id: number) => client.post(`/admin/users/${id}/deactivate`)
export const apiActivateUser   = (id: number) => client.post(`/admin/users/${id}/activate`)
export const apiResetPassword  = (id: number, new_password: string) =>
  client.post(`/admin/users/${id}/reset-password`, { new_password })

// Licenses
export const apiGetLicenses    = () => client.get<License[]>('/admin/licenses').then(r => r.data)
export const apiCreateLicense  = (data: object) => client.post<License>('/admin/licenses', data).then(r => r.data)
export const apiUpdateLicense  = (id: number, data: object) => client.patch<License>(`/admin/licenses/${id}`, data).then(r => r.data)
export const apiDeactivateLicense = (id: number) => client.post(`/admin/licenses/${id}/deactivate`)

// Audit
export const apiGetAudit = (params?: { limit?: number; user_id?: number }) =>
  client.get<AuditEntry[]>('/admin/audit', { params }).then(r => r.data)

// Token usage
export const apiGetTokenUsage = () => client.get('/admin/token-usage').then(r => r.data)

// Backtest results
export const apiGetBacktest = (daysBack = 60) =>
  client.get('/admin/backtest', { params: { days_back: daysBack } }).then(r => r.data)

// Market regime
export const apiGetRegime = () =>
  client.get('/admin/regime').then(r => r.data)

// Historical backtest
export const apiRunHistoricalBacktest = (params?: { years_back?: number; top_n?: number }) =>
  client.post('/admin/historical-backtest', null, { params, timeout: 120_000 }).then(r => r.data)
export const apiGetHistoricalBacktest = () =>
  client.get('/admin/historical-backtest').then(r => r.data)

// Send digest
export const apiSendDigest = () =>
  client.post('/admin/send-digest').then(r => r.data)

// Test email (SMTP check)
export const apiTestEmail = (to: string) =>
  client.post('/admin/test-email', { to }, { timeout: 30_000 }).then(r => r.data)

// Digest email list
export const apiGetDigestEmails = () =>
  client.get('/admin/digest-emails').then(r => r.data)
export const apiAddDigestEmail = (email: string, name: string) =>
  client.post('/admin/digest-emails', { email, name }).then(r => r.data)
export const apiToggleDigestEmail = (id: number, is_active: boolean) =>
  client.patch(`/admin/digest-emails/${id}`, { is_active }).then(r => r.data)
export const apiDeleteDigestEmail = (id: number) =>
  client.delete(`/admin/digest-emails/${id}`).then(r => r.data)
