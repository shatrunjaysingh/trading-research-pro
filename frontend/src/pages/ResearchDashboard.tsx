import { useState, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { apiResearchConfig, apiResearchRegime } from '../api/research'
import { useAuthStore } from '../store/auth'
import { useMarketStore } from '../store/market'
import { useResearchStream } from '../hooks/useResearchStream'
import { KpiCard } from '../components/ui/KpiCard'
import { SectorSection } from '../components/research/SectorSection'
import { Spinner } from '../components/ui/Spinner'
import { InfoTooltip } from '../components/ui/InfoTooltip'
import { MarketSelector } from '../components/ui/MarketSelector'
import { useLivePrices } from '../hooks/useLivePrices'
import type { FreePick } from '../types'

const SECTOR_ICONS: Record<string, string> = {
  technology:'💻', pharma:'💊', healthcare:'🏥', finance:'🏦',
  energy:'⚡', consumer:'🛍', industrials:'🏭', crypto:'₿', penny:'💰',
}

export function ResearchDashboard() {
  const { user } = useAuthStore()
  const selectedCountry = useMarketStore(s => s.selectedCountry)
  const [controlsOpen, setControlsOpen] = useState(false)
  const [mode, setMode]           = useState<'free'|'api'>('free')
  const [selectedSectors, setSectors] = useState<string[]>([])
  const [topN,    setTopN]        = useState(5)
  const [maxPrice, setMaxPrice]   = useState<number | null>(null)
  const [minMarketCap, setMinMarketCap] = useState(10_000_000)
  const [minConfidence, setMinConfidence] = useState(0)
  const [dividendOnly, setDividendOnly] = useState(false)
  const [sendEmail, setSendEmail] = useState(false)
  const [activeTab, setActiveTab] = useState<string | null>(null)

  const { run, isStreaming, progress, sections, error, isDone } = useResearchStream()

  // Collect all free-mode tickers for live price subscription
  const liveTickers = sections.flatMap(s =>
    Array.isArray(s.data) ? (s.data as FreePick[]).map(p => p.ticker) : []
  )
  const liveQuotes = useLivePrices(isDone ? liveTickers : [])

  const { data: cfg } = useQuery({
    queryKey: ['research-config'],
    queryFn:  apiResearchConfig,
  })

  const { data: regime } = useQuery({
    queryKey:  ['research-regime'],
    queryFn:   apiResearchRegime,
    staleTime: 3_600_000,
    retry:     false,
  })

  // Sync defaults from config
  useEffect(() => {
    if (cfg) {
      setTopN(cfg.default_top_n)
      if (!cfg.available_modes.includes(mode)) setMode(cfg.available_modes[0] || 'free')
    }
  }, [cfg])

  // Auto-select first tab when sections arrive
  useEffect(() => {
    if (sections.length > 0 && !activeTab) setActiveTab(sections[0].sector)
  }, [sections])

  const canDeepResearch = cfg?.available_modes.includes('api')
  const canEmail        = !!user?.can_email

  const toggleSector = (s: string) => {
    setSectors(prev => prev.includes(s) ? prev.filter(x => x !== s) : [...prev, s])
  }

  const handleRun = () => {
    setActiveTab(null)
    run({ mode, selected_sectors: selectedSectors, top_n: topN, max_price: maxPrice, send_email: sendEmail, dividend_only: dividendOnly, min_market_cap: minMarketCap })
  }

  const now = new Date()
  const marketOpen = now.getDay() > 0 && now.getDay() < 6 && now.getHours() >= 9 && (now.getHours() < 16 || (now.getHours() === 9 && now.getMinutes() >= 30))

  const totalPicks = sections.reduce((acc, s) => {
    const d = s.data
    if (Array.isArray(d)) return acc + d.length
    if (d && 'top_picks' in d) return acc + (d.top_picks?.length ?? 0)
    return acc
  }, 0)

  return (
    <div className="flex h-full relative">
      {/* ── Mobile backdrop ── */}
      {controlsOpen && (
        <div
          className="md:hidden fixed inset-0 z-20 bg-black/50 backdrop-blur-sm"
          onClick={() => setControlsOpen(false)}
        />
      )}

      {/* ── Filter FAB (mobile only) ── */}
      <div className="md:hidden fixed bottom-[76px] right-4 z-30">
        <button
          onClick={() => setControlsOpen(o => !o)}
          className="w-12 h-12 rounded-full bg-primary text-white shadow-xl flex items-center justify-center text-lg transition-transform active:scale-95"
          aria-label="Toggle filters"
        >
          {controlsOpen ? '✕' : '⚙'}
        </button>
      </div>

      {/* ── Left panel (desktop aside + mobile drawer) ── */}
      <aside className={[
        'w-72 flex-shrink-0 border-r border-surface-border bg-surface p-5 overflow-y-auto flex flex-col gap-5',
        // Mobile: fixed overlay drawer
        'fixed inset-y-0 left-0 z-30 shadow-2xl transition-transform duration-300 ease-in-out',
        // Desktop: static in flow
        'md:relative md:translate-x-0 md:shadow-none md:z-auto',
        // Mobile open/close
        controlsOpen ? 'translate-x-0' : '-translate-x-full',
      ].join(' ')}>
        {/* Mobile header */}
        <div className="md:hidden flex items-center justify-between -mb-1">
          <span className="font-bold text-ink">Filters</span>
          <button onClick={() => setControlsOpen(false)} className="text-ink-faint hover:text-ink p-1">✕</button>
        </div>

        {/* Market preference */}
        <div>
          <MarketSelector />
          {selectedCountry && selectedCountry.id !== 'US' && (
            <p className="text-xs text-amber-600 dark:text-amber-400 mt-2 bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded-lg px-2.5 py-1.5">
              Research scans use US sector ETFs. Your market preference applies to Stock Analysis.
            </p>
          )}
        </div>

        {/* Mode */}
        <div>
          <div className="flex items-center gap-1.5 mb-2">
            <p className="label mb-0">Analysis Mode</p>
            <InfoTooltip
              text="Free Scan uses yfinance data only — instant results. Deep Research sends each pick to Claude AI for narrative analysis — takes 2–5 minutes but provides much richer context."
              side="bottom"
              align="left"
            />
          </div>
          <div className="space-y-2">
            {[
              { key:'free', label:'⚡ Free Scan',     sub:'Instant · yfinance' },
              { key:'api',  label:'🔬 Deep Research', sub:'Claude AI · 2-5 min' },
            ].map(({ key, label, sub }) => (
              <button key={key}
                disabled={key === 'api' && !canDeepResearch}
                onClick={() => setMode(key as 'free'|'api')}
                className={`w-full flex items-start gap-3 p-3 rounded-xl border text-left transition-all
                  ${mode===key ? 'border-primary bg-primary/5' : 'border-surface-border hover:border-primary/40'}
                  ${key==='api' && !canDeepResearch ? 'opacity-40 cursor-not-allowed' : ''}`}>
                <div className="flex-1">
                  <div className={`text-sm font-semibold ${mode===key ? 'text-primary' : 'text-ink'}`}>{label}</div>
                  <div className="text-xs text-ink-muted mt-0.5">{sub}</div>
                </div>
                {mode===key && <div className="w-4 h-4 rounded-full bg-primary mt-0.5 flex-shrink-0" />}
              </button>
            ))}
            {!canDeepResearch && <p className="text-xs text-ink-faint">🔒 Upgrade for Deep Research</p>}
          </div>
        </div>

        {/* Sectors */}
        {cfg && (
          <div>
            <div className="flex items-center justify-between mb-2">
              <p className="label mb-0">Sectors</p>
              <button onClick={() => setSectors([])} className="text-xs text-primary hover:underline">
                {selectedSectors.length > 0 ? 'Clear' : 'All (default)'}
              </button>
            </div>
            <div className="flex flex-wrap gap-1.5">
              {cfg.available_sectors.map(s => {
                const active = selectedSectors.includes(s)
                return (
                  <button key={s} onClick={() => toggleSector(s)}
                    className={`px-2.5 py-1 rounded-lg text-xs font-semibold border transition-all
                      ${active ? 'bg-primary text-white border-primary' : 'border-surface-border text-ink-muted hover:border-primary hover:text-primary'}`}>
                    {SECTOR_ICONS[s]}{cfg.sector_labels[s] || s}
                  </button>
                )
              })}
            </div>
          </div>
        )}

        {/* Filters */}
        <div>
          <div className="flex items-center gap-1.5 mb-1">
            <p className="label mb-0">Picks per Sector</p>
            <InfoTooltip
              text="Maximum number of top-scoring stocks returned per sector. Higher values give more breadth but take longer to scan."
              align="left"
            />
          </div>
          <div className="flex items-center gap-3">
            <input type="range" min={1} max={cfg?.max_picks || 10} value={topN}
              onChange={e => setTopN(Number(e.target.value))}
              className="flex-1 accent-primary" />
            <span className="text-sm font-bold text-ink w-4">{topN}</span>
          </div>
        </div>

        <div>
          <div className="flex items-center gap-1.5 mb-1">
            <p className="label mb-0">Max Price ($)</p>
            <InfoTooltip
              text="Filter out stocks above this price per share. Useful for smaller portfolios or when looking for lower-priced entry points. Leave empty for no limit."
              align="left"
            />
          </div>
          <input type="number" className="input" min={0} step={1}
            placeholder="0 = no filter"
            value={maxPrice ?? ''} onChange={e => setMaxPrice(e.target.value ? Number(e.target.value) : null)} />
        </div>

        <div>
          <div className="flex items-center gap-1.5 mb-1">
            <p className="label mb-0">Min Market Cap (Penny)</p>
            <InfoTooltip
              text="Minimum market capitalisation when screening the Penny Stocks sector. Lower values include micro-caps but carry higher risk."
              align="left"
            />
          </div>
          <select
            className="input"
            value={minMarketCap}
            onChange={e => setMinMarketCap(Number(e.target.value))}
          >
            <option value={0}>No minimum</option>
            <option value={1_000_000}>$1M+</option>
            <option value={5_000_000}>$5M+</option>
            <option value={10_000_000}>$10M+ (default)</option>
            <option value={25_000_000}>$25M+</option>
            <option value={50_000_000}>$50M+</option>
            <option value={100_000_000}>$100M+</option>
            <option value={500_000_000}>$500M+</option>
          </select>
        </div>

        {mode === 'free' && (
          <div>
            <div className="flex items-center justify-between mb-1">
              <div className="flex items-center gap-1.5">
                <p className="label mb-0">Min Confidence</p>
                <InfoTooltip
                  text="Only show picks where at least this percentage of scoring factors agree on the signal direction (momentum score, volume score, position score). Higher = fewer but stronger signals."
                  align="left"
                />
              </div>
              <span className="text-xs font-bold text-ink-muted">
                {minConfidence === 0 ? 'All' : `≥${minConfidence}%`}
              </span>
            </div>
            <input type="range" min={0} max={100} step={33} value={minConfidence}
              onChange={e => setMinConfidence(Number(e.target.value))}
              className="w-full accent-primary" />
            <div className="flex justify-between text-xs text-ink-faint mt-0.5">
              <span>All</span><span>33%</span><span>67%</span><span>100%</span>
            </div>
          </div>
        )}

        {mode === 'free' && (
          <div className="flex items-start gap-2.5">
            <input type="checkbox" id="dividend-only" checked={dividendOnly} onChange={e => setDividendOnly(e.target.checked)}
              className="rounded accent-primary w-4 h-4 mt-0.5 flex-shrink-0" />
            <label htmlFor="dividend-only" className="cursor-pointer flex-1">
              <div className="text-sm font-medium text-ink">💰 Dividend payers only</div>
              <div className="text-xs text-ink-faint">Adds ~10s · fetches yield data</div>
            </label>
            <InfoTooltip
              text="When enabled, the scanner checks each candidate's dividend yield via Yahoo Finance and filters out non-payers. Only stocks currently paying a dividend appear in results."
              side="bottom"
              align="right"
            />
          </div>
        )}

        {canEmail && (
          <label className="flex items-center gap-2.5 cursor-pointer">
            <input type="checkbox" checked={sendEmail} onChange={e => setSendEmail(e.target.checked)}
              className="rounded accent-primary w-4 h-4" />
            <span className="text-sm font-medium text-ink">📧 Email results</span>
          </label>
        )}

        <button
          onClick={() => { setControlsOpen(false); handleRun() }}
          disabled={isStreaming || !cfg}
          className="btn-primary w-full py-3 text-base mt-auto"
        >
          {isStreaming ? <><Spinner size="sm" /> Running…</> : '▶ Run Research'}
        </button>
      </aside>

      {/* ── Right panel: results ── */}
      <main className="flex-1 overflow-y-auto p-4 md:p-6 min-w-0">
        {/* Disclaimer */}
        <div className="flex items-start gap-2 bg-amber-50 border border-amber-200 rounded-xl px-4 py-2.5 mb-4 dark:bg-amber-900/20 dark:border-amber-700">
          <span className="text-amber-500 text-sm leading-none mt-0.5 flex-shrink-0">⚠</span>
          <p className="text-xs text-amber-800 dark:text-amber-300">
            <strong>Research only — not investment advice.</strong> AI-generated picks are for informational purposes. Data may be delayed. Consult a licensed financial advisor before investing.
          </p>
        </div>

        {/* Header */}
        <div className="mb-6">
          <h1 className="text-2xl font-extrabold text-ink tracking-tight">Research Dashboard</h1>
          <p className="text-ink-muted text-sm mt-0.5">
            {now.toLocaleDateString('en-US',{weekday:'long',year:'numeric',month:'long',day:'numeric'})} · {now.toLocaleTimeString('en-US',{hour:'2-digit',minute:'2-digit'})} ET
            &nbsp;·&nbsp; <span className={marketOpen ? 'text-green-600' : 'text-red-500'}>
              {marketOpen ? '🟢 Market Open' : '🔴 Market Closed'}
            </span>
          </p>
        </div>

        {/* Regime banner */}
        {regime && regime.regime && (
          <div className={`flex items-start gap-3 rounded-xl border px-4 py-3 text-sm mb-4 ${
            regime.regime === 'BULL'    ? 'bg-green-50  border-green-200  text-green-800  dark:bg-green-900/20  dark:border-green-700  dark:text-green-300'  :
            regime.regime === 'BEAR'   ? 'bg-orange-50 border-orange-200 text-orange-800 dark:bg-orange-900/20 dark:border-orange-700 dark:text-orange-300' :
            regime.regime === 'CRISIS' ? 'bg-red-50    border-red-200    text-red-800    dark:bg-red-900/20    dark:border-red-700    dark:text-red-300'    :
                                         'bg-yellow-50 border-yellow-200 text-yellow-800 dark:bg-yellow-900/20 dark:border-yellow-700 dark:text-yellow-300'
          }`}>
            <span className="text-base leading-none mt-0.5">
              {regime.regime === 'BULL' ? '🟢' : regime.regime === 'BEAR' ? '🟠' : regime.regime === 'CRISIS' ? '🔴' : '🟡'}
            </span>
            <div className="flex-1 min-w-0">
              <span className="font-bold mr-2">Market Regime: {regime.regime}</span>
              <span className="opacity-80 text-xs">{regime.description}</span>
              {regime.score_multiplier !== 1.0 && (
                <span className="ml-2 text-xs opacity-60">· Scores {regime.score_multiplier > 1 ? 'boosted' : 'dampened'} {((Math.abs(regime.score_multiplier - 1)) * 100).toFixed(0)}%</span>
              )}
            </div>
          </div>
        )}

        {/* Idle state */}
        {!isStreaming && sections.length === 0 && !error && (
          <div className="flex flex-col items-center justify-center h-64 text-center">
            <div className="text-6xl mb-4">📡</div>
            <div className="text-lg font-semibold text-ink mb-1">Ready to research</div>
            <p className="text-ink-muted text-sm max-w-sm">
              Select your mode and sectors, then click <strong>▶ Run Research</strong>
            </p>
            {/* Mobile quick-start */}
            <button
              onClick={() => setControlsOpen(true)}
              className="md:hidden btn-primary mt-5 px-6 py-2.5"
            >
              ⚙ Open Filters
            </button>
          </div>
        )}

        {/* Streaming progress */}
        {isStreaming && (
          <div className="card p-4 mb-5">
            <div className="flex items-center gap-3 mb-3">
              <Spinner size="sm" />
              <span className="font-semibold text-ink text-sm">
                {mode === 'api' ? '🔬 Deep research in progress…' : '⚡ Screening markets…'}
              </span>
            </div>
            {progress.length > 0 && (
              <div className="bg-slate-900 rounded-lg p-3 text-xs font-mono text-green-400 max-h-40 overflow-y-auto">
                {progress.map((line, i) => <div key={i}>{line}</div>)}
              </div>
            )}
          </div>
        )}

        {/* Error */}
        {error && (
          <div className="card p-4 mb-5 border-red-200 bg-red-50">
            <div className="font-semibold text-red-700">❌ Research failed</div>
            <div className="text-sm text-red-600 mt-1">{error}</div>
          </div>
        )}

        {/* KPI row */}
        {sections.length > 0 && (
          <div className="flex gap-3 mb-6 flex-wrap">
            <KpiCard value={totalPicks}        label="Total Picks" />
            <KpiCard value={sections.length}   label="Sectors With Picks" />
            <KpiCard value={(selectedSectors.length || cfg?.available_sectors.length || 0)} label="Sectors Scanned" />
            <KpiCard value={mode === 'api' ? 'Deep' : 'Free Scan'} label="Mode" />
            {isDone && <KpiCard value="✓" label="Complete" />}
          </div>
        )}

        {/* Sector tabs + content */}
        {sections.length > 0 && (
          <div>
            {/* Tabs */}
            <div className="flex gap-1.5 flex-wrap mb-5 bg-surface-muted p-1 rounded-xl border border-surface-border">
              {sections.map(s => (
                <button key={s.sector} onClick={() => setActiveTab(s.sector)}
                  className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all
                    ${activeTab===s.sector ? 'bg-surface text-ink shadow-sm ring-1 ring-surface-border' : 'text-ink-muted hover:text-ink'}`}>
                  {SECTOR_ICONS[s.sector]}{s.label.replace(/\(.*\)/,'').trim()}
                </button>
              ))}
            </div>

            {/* Active section */}
            {sections.filter(s => s.sector === activeTab).map(s => (
              <SectorSection key={s.sector} section={s} minConfidence={minConfidence} liveQuotes={liveQuotes} />
            ))}
          </div>
        )}

        {/* Footer */}
        {isDone && (
          <div className="mt-8 pt-4 border-t border-surface-border flex justify-between text-xs text-ink-faint">
            <span>Research only — no trades have been placed</span>
            <span>Generated {now.toLocaleString()}</span>
          </div>
        )}
      </main>
    </div>
  )
}
