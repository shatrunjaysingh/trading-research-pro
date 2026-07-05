import client from './client'
import { OptionsFlow } from '../types'

export const apiScanOptions = (tickers = '') =>
  client.get<OptionsFlow[]>('/options/scan', { params: tickers ? { tickers } : {} }).then(r => r.data)
