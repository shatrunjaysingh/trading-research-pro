import client from './client'
import { MarketOverview, FearGreedIndex } from '../types'

export async function apiMarketOverview(market = 'all'): Promise<MarketOverview> {
  const res = await client.get('/market/overview', { params: { market } })
  return res.data
}

export const apiFearGreed = () =>
  client.get<FearGreedIndex>('/market/fear-greed').then(r => r.data)
