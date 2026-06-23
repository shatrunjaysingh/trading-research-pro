import { useState, Fragment } from 'react'
import { clsx } from 'clsx'
import type { Section, ApiSectionData, FreePick, ApiPick, LiveQuote, AnalystRating } from '../../types'
import { DownloadButton } from './PickCard'

// ── helpers ────────────────────────────────────────────────────────────────────

function signalCls(signal: string) {
  const s = signal.toUpperCase()
  if (s === 'BUY')   return 'bg-signal-buy-bg text-signal-buy'
  if (s === 'WATCH') return 'bg-signal-watch-bg text-signal-watch'
  if (s === 'HOLD')  return 'bg-signal-hold-bg text-signal-hold'
  return 'bg-red-100 text-red-700'
}

function signalBorderCls(signal: string) {
  const s = signal.toUpperCase()
  if (s === 'BUY')   return 'border-l-green-500'
  if (s === 'WATCH') return 'border-l-blue-500'
  if (s === 'HOLD')  return 'border-l-yellow-400'
  return 'border-l-red-500'
}

function confCls(c: number | null | undefined) {
  if (c == null) return ''
  if (c >= 67) return 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400'
  if (c >= 50) return 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400'
  return 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400'
}

function Th({ children }: { children: React.ReactNode }) {
  return <th className="px-3 py-2.5 text-left text-xs font-bold uppercase tracking-wide text-ink-faint whitespace-nowrap">{children}</th>
}

function Td({ children, className }: { children: React.ReactNode; className?: string }) {
  return <td className={clsx('px-3 py-2.5', className)}>{children}</td>
}

function MetricTile({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div className="bg-surface rounded-xl border border-surface-border p-3 text-center">
      <div className="text-[10px] font-bold uppercase tracking-wide text-ink-faint mb-1">{label}</div>
      <div className={clsx('text-base font-extrabold', color ?? 'text-ink')}>{value}</div>
    </div>
  )
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return <div className="text-[10px] font-bold uppercase tracking-wider text-ink-faint mb-1">{children}</div>
}

function SectionText({ text }: { text: string | null | undefined }) {
  if (!text) return null
  return <p className="text-sm text-ink-muted leading-relaxed">{text}</p>
}

// ── Free pick inline detail ────────────────────────────────────────────────────

function IndicatorRow({ label, value, note, noteColor }: { label: string; value: string; note?: string; noteColor?: string }) {
  return (
    <div className="flex items-center justify-between py-1.5 border-b border-surface-border/50 last:border-0">
      <span className="text-xs text-ink-muted">{label}</span>
      <div className="text-right">
        <span className="text-xs font-semibold text-ink">{value}</span>
        {note && <div className={clsx('text-[10px]', noteColor ?? 'text-ink-faint')}>{note}</div>}
      </div>
    </div>
  )
}

function FreePickDetail({ pick, sectorLabel }: { pick: FreePick; sectorLabel: string }) {
  const priceTiles = [
    { label: 'Day %',        value: `${pick.day_change_pct >= 0 ? '+' : ''}${pick.day_change_pct.toFixed(2)}%`, color: pick.day_change_pct >= 0 ? 'text-green-600' : 'text-red-500' },
    { label: '1W %',         value: pick.week_change_pct != null ? `${pick.week_change_pct >= 0 ? '+' : ''}${pick.week_change_pct.toFixed(2)}%` : '—', color: pick.week_change_pct != null ? (pick.week_change_pct >= 0 ? 'text-green-600' : 'text-red-500') : 'text-ink-faint' },
    { label: '3M %',         value: pick.qtr_change_pct != null ? `${pick.qtr_change_pct >= 0 ? '+' : ''}${pick.qtr_change_pct.toFixed(2)}%` : '—', color: pick.qtr_change_pct != null ? (pick.qtr_change_pct >= 0 ? 'text-green-600' : 'text-red-500') : 'text-ink-faint' },
    { label: 'Vol Ratio',    value: `${pick.vol_ratio.toFixed(2)}×`, color: pick.vol_ratio >= 1.5 ? 'text-blue-600' : 'text-ink' },
    { label: '52w Pos',      value: `${pick.pos_52w.toFixed(1)}%`,   color: 'text-ink' },
    ...(pick.dividend_yield != null && pick.dividend_yield > 0
      ? [{ label: 'Div Yield', value: `${(pick.dividend_yield * 100).toFixed(2)}%`, color: 'text-green-600' }]
      : []),
  ]

  const hasAnalyst     = pick.analyst_target != null || pick.analyst_consensus != null
  const hasInsider     = pick.insider_net_shares != null
  const hasTech        = pick.rsi != null || pick.macd != null || pick.sma50 != null
  const hasSplitHist   = pick.last_split_date != null
  const hasUpcomingSplit = pick.upcoming_split_date != null

  return (
    <div className="px-5 py-4 space-y-4">
      {pick.why_picked && (
        <div>
          <SectionLabel>Why Picked</SectionLabel>
          <SectionText text={pick.why_picked} />
        </div>
      )}

      {/* Price / momentum tiles */}
      <div className={clsx('grid gap-2', priceTiles.length >= 6 ? 'grid-cols-3 sm:grid-cols-6' : 'grid-cols-3 sm:grid-cols-5')}>
        {priceTiles.map(t => <MetricTile key={t.label} {...t} />)}
      </div>

      {/* Earnings warning */}
      {pick.earnings_flag && (
        <div className="flex items-center gap-2 bg-amber-50 dark:bg-amber-900/20 border border-amber-300 dark:border-amber-700 rounded-lg px-3 py-2 text-xs text-amber-800 dark:text-amber-300">
          <span>⚠</span>
          <span>Earnings {pick.earnings_days_out != null && pick.earnings_days_out <= 1 ? 'tomorrow' : `in ${pick.earnings_days_out} days`} — {pick.earnings_flag}{pick.earnings_penalty ? ` (−${pick.earnings_penalty} score penalty)` : ''}</span>
        </div>
      )}

      {/* Upcoming split announcement */}
      {hasUpcomingSplit && (
        <div className="flex items-center gap-2 bg-blue-50 dark:bg-blue-900/20 border border-blue-300 dark:border-blue-700 rounded-lg px-3 py-2 text-xs text-blue-800 dark:text-blue-300">
          <span>✂</span>
          <span>Stock split announced — effective {pick.upcoming_split_date}</span>
        </div>
      )}

      {/* Reverse split warning */}
      {hasSplitHist && pick.last_split_type === 'reverse' && (
        <div className="flex items-center gap-2 bg-red-50 dark:bg-red-900/20 border border-red-300 dark:border-red-700 rounded-lg px-3 py-2 text-xs text-red-800 dark:text-red-300">
          <span>⚠</span>
          <span>
            Reverse split {pick.last_split_ratio != null ? `(${pick.last_split_ratio}:1)` : ''} on {pick.last_split_date}
            {pick.split_score_adj ? ` — score adjusted ${pick.split_score_adj > 0 ? '+' : ''}${pick.split_score_adj} pts` : ''}
          </span>
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {/* Technical indicators */}
        {hasTech && (
          <div className="bg-surface rounded-xl border border-surface-border p-3">
            <SectionLabel>Technical Indicators</SectionLabel>
            {pick.rsi != null && (
              <IndicatorRow label="RSI (14)" value={pick.rsi.toFixed(1)}
                note={pick.rsi < 30 ? 'Oversold' : pick.rsi > 70 ? 'Overbought' : 'Neutral'}
                noteColor={pick.rsi < 30 ? 'text-green-600' : pick.rsi > 70 ? 'text-red-500' : 'text-ink-faint'} />
            )}
            {pick.macd != null && (
              <IndicatorRow label="MACD" value={pick.macd.toFixed(3)}
                note={pick.macd_signal != null ? (pick.macd > pick.macd_signal ? 'Bullish cross' : 'Bearish cross') : undefined}
                noteColor={pick.macd_signal != null ? (pick.macd > pick.macd_signal ? 'text-green-600' : 'text-red-500') : undefined} />
            )}
            {pick.sma50 != null && (
              <IndicatorRow label="SMA 50" value={`$${pick.sma50.toFixed(2)}`}
                note={pick.current_price > pick.sma50 ? 'Price above ▲' : 'Price below ▼'}
                noteColor={pick.current_price > pick.sma50 ? 'text-green-600' : 'text-red-500'} />
            )}
            {pick.sma200 != null && (
              <IndicatorRow label="SMA 200" value={`$${pick.sma200.toFixed(2)}`}
                note={pick.current_price > pick.sma200 ? 'Price above ▲' : 'Price below ▼'}
                noteColor={pick.current_price > pick.sma200 ? 'text-green-600' : 'text-red-500'} />
            )}
            {pick.vwap != null && (
              <IndicatorRow label="VWAP" value={`$${pick.vwap.toFixed(2)}`}
                note={pick.current_price > pick.vwap ? 'Above VWAP ▲' : 'Below VWAP ▼'}
                noteColor={pick.current_price > pick.vwap ? 'text-green-600' : 'text-red-500'} />
            )}
            {pick.atr_pct != null && (
              <IndicatorRow label="ATR %" value={`${pick.atr_pct.toFixed(2)}%`} note="Daily volatility" />
            )}
            {pick.bb_upper != null && pick.bb_lower != null && (
              <IndicatorRow label="Bollinger" value={`$${pick.bb_lower.toFixed(2)} – $${pick.bb_upper.toFixed(2)}`} />
            )}
          </div>
        )}

        {/* Analyst consensus */}
        {hasAnalyst && (
          <div className="bg-surface rounded-xl border border-surface-border p-3">
            <SectionLabel>Analyst Consensus</SectionLabel>
            {pick.analyst_consensus && (
              <IndicatorRow label="Rating" value={pick.analyst_consensus}
                note={pick.num_analysts != null ? `${pick.num_analysts} analyst${pick.num_analysts !== 1 ? 's' : ''}` : undefined} />
            )}
            {pick.analyst_target != null && (
              <IndicatorRow label="Price Target" value={`$${pick.analyst_target.toFixed(2)}`}
                note={pick.analyst_upside_pct != null ? `${pick.analyst_upside_pct >= 0 ? '+' : ''}${pick.analyst_upside_pct.toFixed(1)}% upside` : undefined}
                noteColor={pick.analyst_upside_pct != null ? (pick.analyst_upside_pct >= 0 ? 'text-green-600' : 'text-red-500') : undefined} />
            )}

            {/* Individual analyst ratings */}
            {pick.analyst_ratings && pick.analyst_ratings.length > 0 && (
              <div className="mt-2 pt-2 border-t border-surface-border/60">
                <div className="text-[10px] uppercase tracking-wide text-ink-faint mb-1.5">Recent Ratings</div>
                <div className="space-y-0">
                  {pick.analyst_ratings.slice(0, 8).map((r: AnalystRating, i: number) => {
                    const actionColor =
                      r.action === 'up'   ? 'text-green-600' :
                      r.action === 'down' ? 'text-red-500'   :
                      r.action === 'init' ? 'text-blue-600'  : 'text-ink-muted'
                    const actionLabel =
                      r.action === 'up'   ? '↑ Upgrade'   :
                      r.action === 'down' ? '↓ Downgrade' :
                      r.action === 'init' ? '● Initiated'  :
                      r.action === 'reit' ? '→ Reiterated' : '→ Maintained'
                    return (
                      <div key={i} className="flex items-center justify-between py-1 border-b border-surface-border/30 last:border-0">
                        <div className="flex items-center gap-1.5 min-w-0">
                          <span className="text-[10px] text-ink-muted whitespace-nowrap">{r.date}</span>
                          <span className="text-[10px] text-ink font-medium truncate max-w-[90px]">{r.firm}</span>
                        </div>
                        <div className="flex items-center gap-1.5 flex-shrink-0">
                          <span className="text-[10px] font-semibold text-ink">{r.to_grade}</span>
                          <span className={`text-[10px] font-bold ${actionColor}`}>{actionLabel}</span>
                        </div>
                      </div>
                    )
                  })}
                </div>
              </div>
            )}
          </div>
        )}

        {/* Insider / institutional */}
        {hasInsider && (
          <div className="bg-surface rounded-xl border border-surface-border p-3">
            <SectionLabel>Insider &amp; Institutional</SectionLabel>
            {pick.insider_net_shares != null && (
              <IndicatorRow
                label="Insider Net Shares"
                value={pick.insider_net_shares >= 0 ? `+${pick.insider_net_shares.toLocaleString()}` : pick.insider_net_shares.toLocaleString()}
                note={pick.insider_net_shares > 20000 ? 'Buying' : pick.insider_net_shares < -50000 ? 'Selling' : 'Neutral'}
                noteColor={pick.insider_net_shares > 20000 ? 'text-green-600' : pick.insider_net_shares < -50000 ? 'text-red-500' : 'text-ink-faint'}
              />
            )}
            {pick.inst_pct_held != null && pick.inst_pct_held > 0 && (
              <IndicatorRow label="Institutional" value={`${pick.inst_pct_held.toFixed(1)}%`} note="of float held" />
            )}
            {pick.inst_top10_signal && pick.inst_top10_signal !== 'neutral' && (
              <IndicatorRow
                label="Top 5 Holders (Q-o-Q)"
                value={pick.inst_top10_signal === 'buying'
                  ? `${pick.inst_top10_buyers} buying`
                  : pick.inst_top10_signal === 'selling'
                  ? `${pick.inst_top10_sellers} selling`
                  : 'Mixed'}
                note={pick.inst_top10_signal === 'buying' ? 'Accumulating' : pick.inst_top10_signal === 'selling' ? 'Reducing' : ''}
                noteColor={pick.inst_top10_signal === 'buying' ? 'text-green-600' : pick.inst_top10_signal === 'selling' ? 'text-red-500' : 'text-ink-faint'}
              />
            )}
            {pick.inst_top_holders && pick.inst_top_holders.length > 0 && (
              <div className="mt-2 pt-2 border-t border-surface-border/60">
                <div className="text-[10px] uppercase tracking-wide text-ink-faint mb-1.5">Top Holders</div>
                {pick.inst_top_holders.map((h, i) => (
                  <div key={i} className="flex justify-between items-center py-1">
                    <span className="text-xs text-ink-muted truncate max-w-[160px]">{h.holder}</span>
                    <span className="flex items-center gap-2 text-xs">
                      {h.pct_held != null && <span className="text-ink">{h.pct_held.toFixed(2)}%</span>}
                      {h.pct_change != null && (
                        <span className={h.pct_change > 0 ? 'text-green-600 font-semibold' : h.pct_change < 0 ? 'text-red-500 font-semibold' : 'text-ink-faint'}>
                          {h.pct_change > 0 ? '+' : ''}{h.pct_change.toFixed(1)}%
                        </span>
                      )}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Volume trend */}
        {pick.vol_trend_pct != null && (
          <div className="bg-surface rounded-xl border border-surface-border p-3">
            <SectionLabel>Volume Trend (30d vs Prior 30d)</SectionLabel>
            <IndicatorRow
              label="Volume Change"
              value={`${pick.vol_trend_pct > 0 ? '+' : ''}${pick.vol_trend_pct.toFixed(1)}%`}
              note={
                pick.vol_signal === 'accumulation' ? 'Institutional buying' :
                pick.vol_signal === 'distribution' ? 'Institutional selling' :
                pick.vol_signal === 'contraction'  ? 'Volume declining' : 'Neutral'
              }
              noteColor={
                pick.vol_signal === 'accumulation' ? 'text-green-600' :
                pick.vol_signal === 'distribution' ? 'text-red-500'  :
                pick.vol_signal === 'contraction'  ? 'text-amber-500' : 'text-ink-muted'
              }
            />
            {pick.vol_30d_avg != null && (
              <IndicatorRow
                label="Recent Avg (30d)"
                value={pick.vol_30d_avg >= 1e6 ? `${(pick.vol_30d_avg / 1e6).toFixed(1)}M` : pick.vol_30d_avg.toLocaleString()}
              />
            )}
            {pick.vol_prior_avg != null && (
              <IndicatorRow
                label="Prior Avg (30d)"
                value={pick.vol_prior_avg >= 1e6 ? `${(pick.vol_prior_avg / 1e6).toFixed(1)}M` : pick.vol_prior_avg.toLocaleString()}
              />
            )}
          </div>
        )}

        {/* Corporate actions */}
        {hasSplitHist && (
          <div className="bg-surface rounded-xl border border-surface-border p-3">
            <SectionLabel>Corporate Actions (5y)</SectionLabel>
            {pick.last_split_date && (
              <IndicatorRow
                label="Last Split"
                value={pick.last_split_type === 'forward'
                  ? `${pick.last_split_ratio}:1 Forward`
                  : `1:${pick.last_split_ratio != null ? (1 / pick.last_split_ratio).toFixed(0) : '?'} Reverse`}
                note={pick.last_split_date}
                noteColor={pick.last_split_type === 'reverse' ? 'text-red-500' : 'text-green-600'}
              />
            )}
            {pick.upcoming_split_date && (
              <IndicatorRow
                label="Announced Split"
                value={pick.upcoming_split_date}
                note="Upcoming"
                noteColor="text-blue-600"
              />
            )}
            {pick.split_score_adj != null && pick.split_score_adj !== 0 && (
              <IndicatorRow
                label="Score Impact"
                value={`${pick.split_score_adj > 0 ? '+' : ''}${pick.split_score_adj} pts`}
                noteColor={pick.split_score_adj < 0 ? 'text-red-500' : 'text-green-600'}
              />
            )}
          </div>
        )}
      </div>

      {/* SEC EDGAR insider summary */}
      {pick.sec_insider_summary && pick.sec_insider_summary.buy_count + pick.sec_insider_summary.sell_count > 0 && (() => {
        const s = pick.sec_insider_summary!
        const sigLabel: Record<string, string> = {
          strong_buy: 'Strong Buy', buy: 'Buy', neutral: 'Neutral',
          weak_sell: 'Weak Sell', sell: 'Sell',
        }
        const sigColor: Record<string, string> = {
          strong_buy: 'text-green-600', buy: 'text-green-500',
          neutral: 'text-ink-muted', weak_sell: 'text-red-400', sell: 'text-red-600',
        }
        return (
          <div className="bg-surface rounded-xl border border-surface-border p-3">
            <SectionLabel>SEC EDGAR Insider Activity (Form 4, 90d)</SectionLabel>
            <IndicatorRow
              label="Signal"
              value={sigLabel[s.signal] ?? s.signal}
              noteColor={sigColor[s.signal] ?? 'text-ink-muted'}
            />
            <IndicatorRow
              label="Buys"
              value={`${s.buy_count} txn`}
              note={s.buy_shares >= 1e6 ? `${(s.buy_shares / 1e6).toFixed(2)}M sh` : `${s.buy_shares.toLocaleString()} sh`}
              noteColor="text-green-600"
            />
            <IndicatorRow
              label="Sales"
              value={`${s.sell_count} txn`}
              note={s.sell_shares >= 1e6 ? `${(s.sell_shares / 1e6).toFixed(2)}M sh` : `${s.sell_shares.toLocaleString()} sh`}
              noteColor="text-red-500"
            />
            <IndicatorRow
              label="Net"
              value={`${s.net_shares >= 0 ? '+' : ''}${s.net_shares >= 1e6 ? `${(s.net_shares / 1e6).toFixed(2)}M` : s.net_shares.toLocaleString()}`}
              noteColor={s.net_shares >= 0 ? 'text-green-600' : 'text-red-500'}
            />
          </div>
        )
      })()}

      {/* Recent SEC filings */}
      {pick.sec_recent_filings && pick.sec_recent_filings.length > 0 && (
        <div className="bg-surface rounded-xl border border-surface-border p-3">
          <SectionLabel>Recent SEC Filings</SectionLabel>
          <div className="space-y-1">
            {pick.sec_recent_filings.slice(0, 5).map((f, i) => (
              <div key={i} className="flex items-center gap-2 py-1 border-b border-surface-border/40 last:border-0">
                <span className="text-[10px] font-bold bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300 px-1 py-0.5 rounded flex-shrink-0">{f.form}</span>
                <span className="text-[10px] text-ink-muted whitespace-nowrap">{f.date}</span>
                {f.description && <span className="text-[10px] text-ink truncate">{f.description}</span>}
                <a href={f.url} target="_blank" rel="noopener noreferrer"
                  className="ml-auto text-[10px] text-blue-600 hover:text-blue-800 whitespace-nowrap flex-shrink-0">↗</a>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="flex justify-end pt-1">
        <DownloadButton ticker={pick.ticker} pick={pick} mode="free" sectorLabel={sectorLabel} />
      </div>
    </div>
  )
}

// ── API pick inline detail ─────────────────────────────────────────────────────

function ApiPickDetail({ pick, sectorLabel }: { pick: ApiPick; sectorLabel: string }) {
  const hasLevels = pick.suggested_entry || pick.target_price || pick.stop_loss

  return (
    <div className="px-5 py-4 space-y-4">
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Left column */}
        <div className="space-y-3">
          {pick.why_picked && <div><SectionLabel>Why Picked</SectionLabel><SectionText text={pick.why_picked} /></div>}
          {pick.key_catalyst && <div><SectionLabel>Key Catalyst</SectionLabel><SectionText text={pick.key_catalyst} /></div>}
          {pick.sector_tailwind && <div><SectionLabel>Sector Tailwind</SectionLabel><SectionText text={pick.sector_tailwind} /></div>}
          {pick.technical_analysis && <div><SectionLabel>Technical Analysis</SectionLabel><SectionText text={pick.technical_analysis} /></div>}
          {pick.why_its_cheap && <div><SectionLabel>Why It's Cheap</SectionLabel><SectionText text={pick.why_its_cheap} /></div>}
          {pick.fundamental_snapshot && <div><SectionLabel>Fundamentals</SectionLabel><SectionText text={pick.fundamental_snapshot} /></div>}
        </div>

        {/* Right column */}
        <div className="space-y-3">
          {pick.news_summary && (
            <div>
              <SectionLabel>Latest News {pick.news_sentiment && <span className="text-ink-faint normal-case font-normal">· {pick.news_sentiment}</span>}</SectionLabel>
              <SectionText text={pick.news_summary} />
            </div>
          )}
          {pick.analyst_sentiment && <div><SectionLabel>Analyst View</SectionLabel><SectionText text={pick.analyst_sentiment} /></div>}
          {pick.business_viability && <div><SectionLabel>Business Viability</SectionLabel><SectionText text={pick.business_viability} /></div>}
          {pick.financial_health && <div><SectionLabel>Financial Health</SectionLabel><SectionText text={pick.financial_health} /></div>}
        </div>
      </div>

      {/* Trade levels */}
      {hasLevels && (
        <div>
          <SectionLabel>Trade Levels</SectionLabel>
          <div className="grid grid-cols-5 rounded-xl border border-surface-border overflow-hidden">
            {[
              { label: 'Entry',   val: pick.suggested_entry != null ? `$${pick.suggested_entry}` : '—', color: 'text-blue-600' },
              { label: 'Target',  val: pick.target_price    != null ? `$${pick.target_price}`    : '—', color: 'text-green-700' },
              { label: 'Stop',    val: pick.stop_loss       != null ? `$${pick.stop_loss}`        : '—', color: 'text-red-500' },
              { label: 'Upside',  val: pick.upside_pct      != null ? `${pick.upside_pct.toFixed(1)}%` : '—', color: 'text-purple-600' },
              { label: 'Horizon', val: pick.time_horizon    ?? '—', color: 'text-ink' },
            ].map((item, i) => (
              <div key={item.label} className={clsx('p-2.5 text-center', i < 4 && 'border-r border-surface-border')}>
                <div className="text-[10px] font-bold uppercase tracking-wide text-ink-faint">{item.label}</div>
                <div className={clsx('font-bold mt-1 text-sm', item.color)}>{item.val}</div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Risk factors */}
      {pick.risk_factors && pick.risk_factors.length > 0 && (
        <div>
          <SectionLabel>Risk Factors</SectionLabel>
          <div className="space-y-1.5">
            {pick.risk_factors.map((r, i) => (
              <div key={i} className="flex gap-2 bg-amber-50 dark:bg-amber-900/20 border-l-2 border-amber-400 rounded-r-md px-2.5 py-1.5 text-xs text-amber-900 dark:text-amber-300">
                <span>⚠</span><span>{r}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="flex justify-end pt-1">
        <DownloadButton ticker={pick.ticker} pick={pick} mode="api" sectorLabel={sectorLabel} />
      </div>
    </div>
  )
}

// ── Main component ─────────────────────────────────────────────────────────────

export function SectorSection({ section, minConfidence = 0, liveQuotes = {} }: {
  section: Section
  minConfidence?: number
  liveQuotes?: Record<string, LiveQuote>
}) {
  const [expanded, setExpanded] = useState<string | null>(null)
  const sectorLabel = section.label.replace(/\(.*\)/, '').trim()

  const toggle = (ticker: string) => setExpanded(e => e === ticker ? null : ticker)

  // ── API mode ────────────────────────────────────────────────────────────────
  if (section.mode === 'api') {
    const data = section.data as ApiSectionData

    return (
      <div>
        {data.market_summary && (
          <div className="bg-gradient-to-r from-blue-50 to-green-50 dark:from-blue-900/20 dark:to-green-900/20 border border-blue-200 dark:border-blue-800 rounded-xl p-4 mb-5 text-sm text-ink leading-relaxed">
            <span className="font-bold">📊 Market Context</span><br />{data.market_summary}
          </div>
        )}

        {(!data.top_picks || data.top_picks.length === 0) ? (
          <div className="text-center py-12 text-ink-muted">
            <div className="text-4xl mb-3">🔍</div>
            <div className="font-semibold">No picks met the 90%+ confidence threshold today</div>
            <div className="text-sm mt-1">Markets may be choppy. Check back tomorrow.</div>
          </div>
        ) : (
          <div className="rounded-xl border border-surface-border overflow-hidden overflow-x-auto mb-5">
            <table className="w-full text-sm border-collapse">
              <thead className="bg-surface-muted">
                <tr>
                  <Th>Rank</Th><Th>Ticker</Th><Th>Company</Th>
                  <Th>Score</Th><Th>Confidence</Th><Th>Signal</Th>
                  <Th>Price</Th><Th>Day %</Th><Th>Upside</Th>
                  <th className="w-8" />
                </tr>
              </thead>
              <tbody>
                {data.top_picks.map((p, i) => (
                  <Fragment key={p.ticker}>
                    {/* Summary row */}
                    <tr
                      onClick={() => toggle(p.ticker)}
                      className={clsx(
                        'border-t border-surface-border cursor-pointer transition-colors',
                        expanded === p.ticker ? 'bg-primary/5' : 'hover:bg-surface-muted/40',
                      )}
                    >
                      <Td className="text-ink-faint font-medium">#{p.rank ?? i+1}</Td>
                      <Td className="font-extrabold text-ink">{p.ticker}</Td>
                      <Td className="text-ink-muted max-w-[160px] truncate">{p.company_name}</Td>
                      <Td className="font-semibold">{p.score}</Td>
                      <Td>
                        {p.confidence_pct != null
                          ? <span className={clsx('text-xs font-bold px-2 py-0.5 rounded-full', confCls(p.confidence_pct))}>{p.confidence_pct}%</span>
                          : <span className="text-ink-faint">—</span>}
                      </Td>
                      <Td>
                        <span className={clsx('px-2 py-0.5 rounded-full text-xs font-bold', signalCls(p.signal))}>{p.signal}</span>
                      </Td>
                      <Td className="font-semibold">${p.current_price}</Td>
                      <Td className={clsx('font-semibold', Number(p.day_change_pct) >= 0 ? 'text-green-600' : 'text-red-500')}>
                        {Number(p.day_change_pct) >= 0 ? '+' : ''}{Number(p.day_change_pct).toFixed(1)}%
                      </Td>
                      <Td className="font-semibold text-purple-600">{p.upside_pct ? `${p.upside_pct.toFixed(1)}%` : '—'}</Td>
                      <Td className="text-ink-faint text-xs pr-4 text-center">{expanded === p.ticker ? '▲' : '▼'}</Td>
                    </tr>

                    {/* Inline detail row — sits directly below its summary row */}
                    {expanded === p.ticker && (
                      <tr className="border-t-0">
                        <td
                          colSpan={10}
                          className={clsx('p-0 border-t border-surface-border border-l-4', signalBorderCls(p.signal))}
                        >
                          <div className="bg-surface-muted/30">
                            <ApiPickDetail pick={p} sectorLabel={sectorLabel} />
                          </div>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {data.avoid_today && data.avoid_today.length > 0 && (
          <div className="mt-4 bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-700 rounded-xl px-4 py-3 text-sm text-amber-900 dark:text-amber-300">
            <span className="font-bold">⚠️ Avoid today:</span> {data.avoid_today.join(', ')}
            {data.avoid_reason && <div className="mt-1 opacity-80">{data.avoid_reason}</div>}
          </div>
        )}
      </div>
    )
  }

  // ── Free mode ───────────────────────────────────────────────────────────────
  const allPicks = section.data as FreePick[]
  const picks = minConfidence > 0
    ? allPicks.filter(p => (p.confidence ?? 0) >= minConfidence)
    : allPicks

  if (!allPicks || allPicks.length === 0) {
    return <div className="text-center py-12 text-ink-muted"><div className="text-4xl mb-3">📊</div><div>No qualifying picks today</div></div>
  }
  if (picks.length === 0) {
    return (
      <div className="text-center py-12 text-ink-muted">
        <div className="text-4xl mb-3">🔍</div>
        <div className="font-semibold">No picks meet the {minConfidence}% confidence threshold</div>
        <div className="text-sm mt-1">Lower the confidence filter to see more results</div>
      </div>
    )
  }

  return (
    <div>
      {minConfidence > 0 && (
        <p className="text-xs text-ink-faint mb-3">Showing {picks.length} of {allPicks.length} picks with ≥{minConfidence}% confidence</p>
      )}

      <div className="rounded-xl border border-surface-border overflow-hidden overflow-x-auto mb-3">
        <table className="w-full text-sm border-collapse">
          <thead className="bg-surface-muted">
            <tr>
              <Th>Rank</Th><Th>Ticker</Th><Th>Score</Th><Th>Conf</Th>
              <Th>Signal</Th><Th>Price</Th><Th>Day %</Th>
              <Th>3M %</Th><Th>Vol</Th><Th>Vol Trend</Th><Th>Analyst</Th><Th>Earnings</Th>
              <th className="w-8" />
            </tr>
          </thead>
          <tbody>
            {picks.map((p, i) => (
              <Fragment key={p.ticker}>
                {/* Summary row */}
                <tr
                  onClick={() => toggle(p.ticker)}
                  className={clsx(
                    'border-t border-surface-border cursor-pointer transition-colors',
                    expanded === p.ticker ? 'bg-primary/5' : 'hover:bg-surface-muted/40',
                  )}
                >
                  <Td className="text-ink-faint">#{i+1}</Td>
                  <Td className="font-extrabold text-ink">{p.ticker}</Td>
                  <Td className="font-semibold">{p.score}</Td>
                  <Td>
                    {p.confidence != null
                      ? <span className={clsx('text-xs font-bold px-2 py-0.5 rounded-full', confCls(p.confidence))}>{p.confidence}%</span>
                      : <span className="text-ink-faint">—</span>}
                  </Td>
                  <Td>
                    <span className={clsx('px-2 py-0.5 rounded-full text-xs font-bold', signalCls(p.signal))}>{p.signal}</span>
                  </Td>
                  <Td className="font-semibold">
                    {liveQuotes[p.ticker]?.price != null
                      ? <span className="flex items-center gap-1">
                          <span className="inline-block w-1.5 h-1.5 rounded-full bg-green-500 animate-pulse" />
                          ${liveQuotes[p.ticker]!.price!.toFixed(2)}
                        </span>
                      : `$${p.current_price.toFixed(2)}`}
                  </Td>
                  <Td className={clsx('font-semibold',
                    (liveQuotes[p.ticker]?.change_pct ?? p.day_change_pct) >= 0 ? 'text-green-600' : 'text-red-500')}>
                    {((liveQuotes[p.ticker]?.change_pct ?? p.day_change_pct) >= 0 ? '+' : '')}
                    {(liveQuotes[p.ticker]?.change_pct ?? p.day_change_pct).toFixed(2)}%
                  </Td>
                  <Td className={clsx('font-semibold', (p.qtr_change_pct ?? 0) >= 0 ? 'text-green-600' : 'text-red-500')}>
                    {p.qtr_change_pct != null ? `${p.qtr_change_pct >= 0 ? '+' : ''}${p.qtr_change_pct.toFixed(1)}%` : '—'}
                  </Td>
                  <Td>{p.vol_ratio.toFixed(2)}×</Td>
                  <Td>
                    {p.vol_trend_pct != null ? (
                      <span className={clsx('text-xs font-semibold',
                        p.vol_signal === 'accumulation' ? 'text-green-600' :
                        p.vol_signal === 'distribution' ? 'text-red-500'  :
                        p.vol_signal === 'contraction'  ? 'text-amber-500' : 'text-ink-muted'
                      )}>
                        {p.vol_trend_pct > 0 ? '+' : ''}{p.vol_trend_pct.toFixed(0)}%
                        <span className="ml-1 font-normal opacity-70">
                          {p.vol_signal === 'accumulation' ? '↑buy' :
                           p.vol_signal === 'distribution' ? '↓sell' :
                           p.vol_signal === 'contraction'  ? '↓thin' : ''}
                        </span>
                      </span>
                    ) : <span className="text-ink-faint">—</span>}
                  </Td>
                  <Td className="font-semibold text-purple-600 dark:text-purple-400">
                    {p.analyst_target != null
                      ? <>
                          ${p.analyst_target.toFixed(2)}
                          {p.analyst_upside_pct != null && (
                            <span className={clsx('ml-1 text-[10px]', p.analyst_upside_pct >= 0 ? 'text-green-600' : 'text-red-500')}>
                              {p.analyst_upside_pct >= 0 ? '+' : ''}{p.analyst_upside_pct.toFixed(0)}%
                            </span>
                          )}
                        </>
                      : <span className="text-ink-faint">—</span>}
                  </Td>
                  <Td>
                    {p.earnings_flag
                      ? <span className="text-amber-600 text-xs font-semibold">⚠ {p.earnings_days_out != null && p.earnings_days_out <= 1 ? 'Tomorrow' : `${p.earnings_days_out}d`}</span>
                      : <span className="text-ink-faint">—</span>}
                  </Td>
                  <Td className="text-ink-faint text-xs pr-4 text-center">{expanded === p.ticker ? '▲' : '▼'}</Td>
                </tr>

                {/* Inline detail row — sits directly below its summary row */}
                {expanded === p.ticker && (
                  <tr>
                    <td
                      colSpan={12}
                      className={clsx('p-0 border-t border-surface-border border-l-4', signalBorderCls(p.signal))}
                    >
                      <div className="bg-surface-muted/30">
                        <FreePickDetail pick={p} sectorLabel={sectorLabel} />
                      </div>
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>

      <p className="text-xs text-ink-faint mb-2">
        Click any row to expand details · Score = Momentum 40% · Volume Surge 30% · 52-Week Position 30% · Confidence = factor alignment
      </p>
    </div>
  )
}
