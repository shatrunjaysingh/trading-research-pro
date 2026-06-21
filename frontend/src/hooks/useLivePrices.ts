import { useState, useEffect, useRef, useCallback } from 'react'
import { streamPrices, subscribeTickers } from '../api/prices'
import type { LiveQuote } from '../types'

export function useLivePrices(tickers: string[]): Record<string, LiveQuote> {
  const [quotes, setQuotes] = useState<Record<string, LiveQuote>>({})
  const abortRef  = useRef<AbortController | null>(null)
  const tickerKey = [...tickers].sort().join(',')

  const startStream = useCallback(async (ts: string[], signal: AbortSignal) => {
    if (!ts.length) return
    try {
      await subscribeTickers(ts)
    } catch { /* best-effort */ }
    try {
      for await (const q of streamPrices(ts)) {
        if (signal.aborted) break
        if (q.ticker && q.price != null) {
          setQuotes(prev => ({ ...prev, [q.ticker]: q }))
        }
      }
    } catch { /* stream closed */ }
  }, [])

  useEffect(() => {
    if (!tickers.length) return
    abortRef.current?.abort()
    const ctrl = new AbortController()
    abortRef.current = ctrl
    setQuotes({})
    startStream(tickers, ctrl.signal)
    return () => ctrl.abort()
  }, [tickerKey])

  return quotes
}
