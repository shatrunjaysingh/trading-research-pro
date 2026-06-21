import { clsx } from 'clsx'
import { COUNTRIES } from '../../types/markets'
import { useMarketStore, useActiveExchanges } from '../../store/market'

interface MarketSelectorProps {
  disabled?: boolean
  onCountryChange?: () => void
}

export function MarketSelector({ disabled, onCountryChange }: MarketSelectorProps) {
  const { selectedCountry, selectedExchangeIds, selectCountry, toggleExchange, selectAllExchanges } = useMarketStore()
  const activeExchanges = useActiveExchanges()

  function handleSelectCountry(country: typeof selectedCountry) {
    selectCountry(country)
    onCountryChange?.()
  }

  return (
    <div className="space-y-2.5">
      {/* Country row */}
      <div>
        <label className="label mb-2">Market</label>
        <div className="flex gap-2 flex-wrap">
          <button
            onClick={() => handleSelectCountry(null)}
            disabled={disabled}
            className={clsx(
              'flex items-center gap-1.5 px-3 py-1.5 rounded-lg border text-sm font-medium transition-all',
              selectedCountry === null
                ? 'bg-primary text-white border-primary shadow-sm'
                : 'bg-surface text-ink-muted border-surface-border hover:border-primary/50 hover:text-ink',
            )}
          >
            <span className="text-base leading-none">🌐</span>
            <span>All Markets</span>
          </button>

          {COUNTRIES.map(c => (
            <button
              key={c.id}
              onClick={() => handleSelectCountry(c)}
              disabled={disabled}
              className={clsx(
                'flex items-center gap-1.5 px-3 py-1.5 rounded-lg border text-sm font-medium transition-all',
                selectedCountry?.id === c.id
                  ? 'bg-primary text-white border-primary shadow-sm'
                  : 'bg-surface text-ink-muted border-surface-border hover:border-primary/50 hover:text-ink',
              )}
            >
              <span className="text-base leading-none">{c.flag}</span>
              <span>{c.name}</span>
              <span className={clsx('text-xs', selectedCountry?.id === c.id ? 'text-white/70' : 'text-ink-faint')}>
                {c.currency}
              </span>
            </button>
          ))}
        </div>

        {selectedCountry === null && (
          <p className="text-xs text-ink-faint mt-1.5">
            Showing global data — include exchange suffix manually if needed (e.g.{' '}
            <code className="bg-surface-muted px-1 rounded">RELIANCE.NS</code>,{' '}
            <code className="bg-surface-muted px-1 rounded">SHEL.L</code>)
          </p>
        )}
      </div>

      {/* Exchange multi-select row (only when a country is chosen) */}
      {selectedCountry && (
        <div>
          <div className="flex items-center gap-2 mb-1.5">
            <span className="text-xs text-ink-faint">Exchange</span>
            <span className="text-xs text-ink-faint">·</span>
            <span className="text-xs text-ink-faint">
              {activeExchanges.length === selectedCountry.exchanges.length
                ? 'all selected'
                : `${activeExchanges.length} of ${selectedCountry.exchanges.length} selected`}
            </span>
            {activeExchanges.length < selectedCountry.exchanges.length && (
              <button
                onClick={selectAllExchanges}
                className="text-xs text-primary hover:underline"
              >
                Select all
              </button>
            )}
          </div>
          <div className="flex gap-2 flex-wrap">
            {selectedCountry.exchanges.map(ex => {
              const isOn = selectedExchangeIds.includes(ex.id)
              return (
                <button
                  key={ex.id}
                  onClick={() => toggleExchange(ex.id)}
                  disabled={disabled}
                  title={ex.fullName}
                  className={clsx(
                    'flex items-center gap-1.5 px-2.5 py-1 rounded-md border text-xs font-medium transition-all',
                    isOn
                      ? 'bg-primary/10 text-primary border-primary/40'
                      : 'bg-surface text-ink-faint border-surface-border hover:border-primary/30',
                  )}
                >
                  <span className={clsx('w-3 h-3 rounded-sm border flex items-center justify-center flex-shrink-0',
                    isOn ? 'bg-primary border-primary' : 'border-ink-faint',
                  )}>
                    {isOn && <svg className="w-2 h-2 text-white" viewBox="0 0 8 8" fill="currentColor"><path d="M1 4l2 2 4-4"/></svg>}
                  </span>
                  <span className="font-semibold">{ex.name}</span>
                  {ex.suffix && (
                    <code className={clsx('px-1 rounded text-[10px]', isOn ? 'bg-primary/10' : 'bg-surface-muted')}>
                      {ex.suffix}
                    </code>
                  )}
                </button>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}
