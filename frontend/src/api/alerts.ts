import client from './client'

export const apiGetAlertPrefs = () =>
  client.get<{ digest_enabled: boolean }>('/alerts/preferences').then(r => r.data)

export const apiSetAlertPrefs = (enabled: boolean) =>
  client.put<{ digest_enabled: boolean }>('/alerts/preferences', { enabled }).then(r => r.data)

export const apiSendDigestNow = () =>
  client.post('/alerts/send-now').then(r => r.data)
