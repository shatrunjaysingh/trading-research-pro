import { StockAnalysisRequest, StockSSEEvent, StockHistory, StockAnalysisResult } from '../types'
import { useAuthStore } from '../store/auth'
import client from './client'
import { apiBase } from './native'

export type ChatRole = 'user' | 'assistant'
export interface ChatMsg { role: ChatRole; content: string }
export type ChatSSEEvent =
  | { type: 'delta'; text: string }
  | { type: 'done' }
  | { type: 'error'; message: string }

function buildStockContext(result: StockAnalysisResult): Record<string, unknown> {
  const t = result.technical
  const f = result.fundamentals
  const a = result.analyst
  const s = result.sec_insider_summary
  return {
    ticker:           result.ticker,
    company:          result.company_name,
    price:            t?.current_price,
    signal:           t?.signal,
    score:            t?.score,
    day_change_pct:   t?.day_change_pct,
    week_change_pct:  t?.week_change_pct,
    month_change_pct: t?.month_change_pct,
    high_52w:         t?.high_52w,
    low_52w:          t?.low_52w,
    rsi:              t?.rsi,
    macd:             t?.macd,
    sma50:            t?.sma50,
    sma200:           t?.sma200,
    vol_signal:       t?.vol_signal,
    vol_trend_pct:    t?.vol_trend_pct,
    pe_ratio:         f?.pe_ratio,
    forward_pe:       f?.forward_pe,
    eps:              f?.eps,
    revenue:          f?.revenue,
    profit_margin:    f?.profit_margin,
    debt_to_equity:   f?.debt_to_equity,
    return_on_equity: f?.return_on_equity,
    market_cap:       f?.market_cap,
    dividend_yield:   f?.dividend_yield,
    beta:             f?.beta,
    analyst_rating:   a?.recommendation,
    analyst_target:   a?.target_mean,
    analyst_upside:   a?.upside_pct,
    num_analysts:     a?.num_analysts,
    insider_signal:   s?.signal ?? null,
    insider_net_shares: s?.net_shares ?? null,
    ai_analysis:      result.ai_analysis,
  }
}

export async function* streamStockChat(
  result: StockAnalysisResult,
  message: string,
  history: ChatMsg[],
): AsyncGenerator<ChatSSEEvent> {
  const token = useAuthStore.getState().token
  const response = await fetch(`${apiBase()}/api/v1/analysis/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify({
      ticker:  result.ticker,
      message,
      history,
      context: buildStockContext(result),
    }),
  })

  if (!response.ok) {
    const err = await response.json().catch(() => ({ detail: 'Chat request failed' }))
    throw new Error(err.detail || 'Chat request failed')
  }

  const reader  = response.body!.getReader()
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
          const event = JSON.parse(line.slice(6)) as ChatSSEEvent
          yield event
          if (event.type === 'done' || event.type === 'error') return
        } catch { /* skip malformed */ }
      }
    }
  }
}

export const fetchStockHistory = (ticker: string, period: string) =>
  client.get<StockHistory>('/analysis/history', { params: { ticker, period } }).then(r => r.data)

export const fetchStockSnapshot = (ticker: string) =>
  client.get<import('../types').PickSnapshot>('/analysis/snapshot', { params: { ticker } }).then(r => r.data)

export const apiGetPriceHistory = (ticker: string, period = '6mo') =>
  client.get<{ ticker: string; period: string; data: import('../types').PriceBar[] }>(`/analysis/price-history/${ticker}`, { params: { period } }).then(r => r.data)

export const apiGetVerdict = (result: StockAnalysisResult) =>
  client.post('/analysis/verdict', result, { timeout: 45_000 }).then(r => r.data)

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
