import client from './client'
import { EarningsEntry } from '../types'

export const apiGetEarningsCalendar = () =>
  client.get<EarningsEntry[]>('/earnings/calendar').then(r => r.data)
