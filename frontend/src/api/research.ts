import client from './client'
import { apiBase } from './native'
import type { ResearchConfig, SSEEvent } from '../types'

export const apiResearchConfig = () =>
  client.get<ResearchConfig>('/research/config').then(r => r.data)

export const apiResearchRegime = () =>
  client.get('/research/regime').then(r => r.data)

export interface RunResearchParams {
  mode: string
  selected_sectors: string[]
  top_n: number
  max_price: number | null
  send_email: boolean
  dividend_only?: boolean
  min_market_cap?: number
}

export async function* streamResearch(params: RunResearchParams): AsyncGenerator<SSEEvent> {
  const token = localStorage.getItem('access_token')
  const resp = await fetch(`${apiBase()}/api/v1/research/run`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(params),
  })

  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: resp.statusText }))
    yield { type: 'error', message: err.detail || 'Request failed' }
    return
  }

  const reader = resp.body!.getReader()
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
          yield JSON.parse(line.slice(6)) as SSEEvent
        } catch { /* skip malformed */ }
      }
    }
  }
}
