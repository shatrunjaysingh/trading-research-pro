import client from './client'
import { MarketOverview } from '../types'

export async function apiMarketOverview(market = 'all'): Promise<MarketOverview> {
  const res = await client.get('/market/overview', { params: { market } })
  return res.data
}
