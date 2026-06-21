import { create } from 'zustand'
import type { CountryConfig, ExchangeConfig } from '../types/markets'
import { COUNTRIES } from '../types/markets'

interface MarketState {
  selectedCountry: CountryConfig | null
  selectedExchangeIds: string[]
  selectCountry: (country: CountryConfig | null) => void
  toggleExchange: (id: string) => void
  selectAllExchanges: () => void
  loadPreferences: () => Promise<void>
  _persistPreferences: (country: CountryConfig | null, exchangeIds: string[]) => void
}

function _readLocalStorage(): { country: CountryConfig | null; exchangeIds: string[] } {
  try {
    const savedId = localStorage.getItem('trading_country')
    if (!savedId || savedId === 'all') return { country: null, exchangeIds: [] }
    const country = COUNTRIES.find(c => c.id === savedId) ?? null
    if (!country) return { country: null, exchangeIds: [] }
    const savedExchanges = localStorage.getItem('trading_exchanges')
    if (savedExchanges) {
      const ids = JSON.parse(savedExchanges) as string[]
      const valid = ids.filter(id => country.exchanges.some(e => e.id === id))
      if (valid.length) return { country, exchangeIds: valid }
    }
    return { country, exchangeIds: country.exchanges.map(e => e.id) }
  } catch {
    return { country: null, exchangeIds: [] }
  }
}

const _initial = _readLocalStorage()

export const useMarketStore = create<MarketState>((set, get) => ({
  selectedCountry: _initial.country,
  selectedExchangeIds: _initial.exchangeIds,

  selectCountry: (country) => {
    const ids = country ? country.exchanges.map(e => e.id) : []
    set({ selectedCountry: country, selectedExchangeIds: ids })
    get()._persistPreferences(country, ids)
  },

  toggleExchange: (id) => {
    const { selectedExchangeIds, selectedCountry, _persistPreferences } = get()
    let next: string[]
    if (selectedExchangeIds.includes(id)) {
      if (selectedExchangeIds.length <= 1) return
      next = selectedExchangeIds.filter(x => x !== id)
    } else {
      next = [...selectedExchangeIds, id]
    }
    set({ selectedExchangeIds: next })
    _persistPreferences(selectedCountry, next)
  },

  selectAllExchanges: () => {
    const { selectedCountry, _persistPreferences } = get()
    if (!selectedCountry) return
    const ids = selectedCountry.exchanges.map(e => e.id)
    set({ selectedExchangeIds: ids })
    _persistPreferences(selectedCountry, ids)
  },

  loadPreferences: async () => {
    try {
      const { apiGetPreferences } = await import('../api/profile')
      const prefs = await apiGetPreferences()
      const countryId = prefs?.market_country
      const exchangeIds = prefs?.market_exchanges
      if (countryId && countryId !== 'all') {
        const country = COUNTRIES.find(c => c.id === countryId) ?? null
        set({
          selectedCountry: country,
          selectedExchangeIds: exchangeIds?.length
            ? exchangeIds.filter(id => country?.exchanges.some(e => e.id === id))
            : (country?.exchanges.map(e => e.id) ?? []),
        })
      } else {
        set({ selectedCountry: null, selectedExchangeIds: [] })
      }
    } catch {
      // backend unavailable — keep localStorage state
    }
  },

  _persistPreferences: (country, exchangeIds) => {
    localStorage.setItem('trading_country', country?.id ?? 'all')
    localStorage.setItem('trading_exchanges', JSON.stringify(exchangeIds))
    import('../api/profile').then(({ apiSavePreferences }) => {
      apiSavePreferences({
        market_country: country?.id ?? null,
        market_exchanges: exchangeIds,
      }).catch(() => {})
    })
  },
}))

// Derived selectors

export function useActiveExchanges(): ExchangeConfig[] {
  const { selectedCountry, selectedExchangeIds } = useMarketStore()
  if (!selectedCountry) return []
  return selectedCountry.exchanges.filter(e => selectedExchangeIds.includes(e.id))
}

export function useCurrency(): string {
  return useMarketStore(s => s.selectedCountry?.currency ?? '$')
}
