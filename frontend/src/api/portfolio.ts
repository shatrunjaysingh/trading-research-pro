import client from './client'
import { PortfolioResult } from '../types'

export interface HoldingInput {
  ticker: string
  shares: number
  avg_cost: number
}

export const apiAnalyzePortfolio = (holdings: HoldingInput[]) =>
  client.post<PortfolioResult>('/portfolio/analyze', { holdings }).then(r => r.data)
