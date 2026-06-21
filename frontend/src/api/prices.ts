import { apiBase } from './native'
import type { LiveQuote } from '../types'

export async function subscribeTickers(tickers: string[]): Promise<void> {
  const token = localStorage.getItem('access_token')
  await fetch(`${apiBase()}/api/v1/prices/subscribe`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(tickers),
  })
}

export async function* streamPrices(tickers: string[]): AsyncGenerator<LiveQuote> {
  const token = localStorage.getItem('access_token')
  const url   = `${apiBase()}/api/v1/prices/stream?tickers=${tickers.join(',')}`
  const resp  = await fetch(url, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  })
  if (!resp.ok || !resp.body) return

  const reader  = resp.body.getReader()
  const decoder = new TextDecoder()
  let   buffer  = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() ?? ''
    for (const line of lines) {
      if (line.startsWith('data: ')) {
        try {
          yield JSON.parse(line.slice(6)) as LiveQuote
        } catch { /* skip */ }
      }
    }
  }
}
