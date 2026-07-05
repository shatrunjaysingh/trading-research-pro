import client from './client'
import { PortfolioResult, PortfolioReview } from '../types'

export interface HoldingInput {
  ticker: string
  shares: number
  avg_cost: number
}

export const apiAnalyzePortfolio = (holdings: HoldingInput[]) =>
  client.post<PortfolioResult>('/portfolio/analyze', { holdings }).then(r => r.data)

export const apiGetSavedPortfolio = () =>
  client.get<{ holdings: HoldingInput[] }>('/portfolio/saved').then(r => r.data)

export const apiSavePortfolio = (holdings: HoldingInput[]) =>
  client.post<{ saved: number }>('/portfolio/save', { holdings }).then(r => r.data)

export const apiRemoveHolding = (ticker: string) =>
  client.delete<{ removed: string }>(`/portfolio/saved/${ticker}`).then(r => r.data)

export const apiGetPortfolioReview = () =>
  client.get<PortfolioReview>('/portfolio/review').then(r => r.data)

export const apiGetPortfolioBacktest = () =>
  client.get<import('../types').BacktestResult>('/portfolio/backtest').then(r => r.data)

export const apiGetPortfolioBenchmark = () =>
  client.get<import('../types').BenchmarkResult>('/portfolio/benchmark').then(r => r.data)

export const apiGetPortfolioNews = () =>
  client.get<import('../types').TickerNews[]>('/portfolio/news').then(r => r.data)
