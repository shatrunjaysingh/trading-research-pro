import client from './client'
import { WatchlistItem } from '../types'

export const apiGetWatchlist = () =>
  client.get<WatchlistItem[]>('/watchlist').then(r => r.data)

export const apiAddToWatchlist = (ticker: string, notes = '') =>
  client.post<WatchlistItem>('/watchlist', { ticker, notes }).then(r => r.data)

export const apiRemoveFromWatchlist = (ticker: string) =>
  client.delete(`/watchlist/${encodeURIComponent(ticker)}`).then(r => r.data)

export const apiCheckWatchlist = (ticker: string) =>
  client.get<{ ticker: string; in_watchlist: boolean }>(`/watchlist/check/${encodeURIComponent(ticker)}`).then(r => r.data)
