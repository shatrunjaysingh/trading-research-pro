import client from './client'
import { PriceAlert, AlertCondition } from '../types'

export const apiGetAlertPrefs = () =>
  client.get<{ digest_enabled: boolean }>('/alerts/preferences').then(r => r.data)

export const apiSetAlertPrefs = (enabled: boolean) =>
  client.put<{ digest_enabled: boolean }>('/alerts/preferences', { enabled }).then(r => r.data)

export const apiSendDigestNow = () =>
  client.post('/alerts/send-now').then(r => r.data)

// Price alerts
export const apiGetPriceAlerts = () =>
  client.get<PriceAlert[]>('/alerts/price').then(r => r.data)

export const apiCreatePriceAlert = (data: { ticker: string; condition: AlertCondition; target_price?: number; note?: string }) =>
  client.post<PriceAlert>('/alerts/price', data).then(r => r.data)

export const apiDeletePriceAlert = (id: number) =>
  client.delete<{ deleted: number }>(`/alerts/price/${id}`).then(r => r.data)

export const apiTogglePriceAlert = (id: number) =>
  client.patch<{ id: number; is_active: boolean }>(`/alerts/price/${id}/toggle`).then(r => r.data)
