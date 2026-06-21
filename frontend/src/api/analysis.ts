import { StockAnalysisRequest, StockSSEEvent, StockHistory } from '../types'
import { useAuthStore } from '../store/auth'
import client from './client'
import { apiBase } from './native'

export const fetchStockHistory = (ticker: string, period: string) =>
  client.get<StockHistory>('/analysis/history', { params: { ticker, period } }).then(r => r.data)

export const fetchStockSnapshot = (ticker: string) =>
  client.get<import('../types').PickSnapshot>('/analysis/snapshot', { params: { ticker } }).then(r => r.data)

export async function* streamStockAnalysis(
  params: StockAnalysisRequest,
): AsyncGenerator<StockSSEEvent> {
  const token = useAuthStore.getState().token
  const response = await fetch(`${apiBase()}/api/v1/analysis/stock`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify(params),
  })

  if (!response.ok) {
    const err = await response.json().catch(() => ({ detail: 'Request failed' }))
    throw new Error(err.detail || 'Analysis request failed')
  }

  const reader = response.body!.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break

    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() ?? ''

    for (const line of lines) {
      if (line.startsWith('data: ')) {
        try {
          const event = JSON.parse(line.slice(6)) as StockSSEEvent
          yield event
          if (event.type === 'done' || event.type === 'error') return
        } catch {
          // malformed line — skip
        }
      }
    }
  }
}
