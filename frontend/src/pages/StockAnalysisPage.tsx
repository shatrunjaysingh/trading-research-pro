import { useState, useRef, useMemo, useEffect, useCallback } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  ComposedChart, Area, Bar, Line, XAxis, YAxis,
  CartesianGrid, Tooltip as RechartTooltip, ResponsiveContainer, LineChart,
  ReferenceLine, Tooltip,
} from 'recharts'
import { useAuthStore } from '../store/auth'
import { useMarketStore, useActiveExchanges } from '../store/market'
import { COUNTRIES, formatTicker } from '../types/markets'
import { streamStockAnalysis, fetchStockHistory, streamStockChat, ChatMsg, apiGetPriceHistory, fetchStockSnapshot, apiGetVerdict } from '../api/analysis'
import { apiAddToWatchlist, apiRemoveFromWatchlist, apiCheckWatchlist } from '../api/watchlist'
import {
  StockAnalysisResult, TechnicalSnapshot, FundamentalSnapshot,
  AnalystSnapshot, IndicatorKey, StockAnalysisRequest,
  SecInsiderTransaction, SecInsiderSummary, SecRecentFiling,
  TechnicalPattern, RSRating, HorizonAnalysis, FactorAnalysis, FinancialHealth,
} from '../types'
import { clsx } from 'clsx'
import { InfoTooltip } from '../components/ui/InfoTooltip'

// ── Constants ─────────────────────────────────────────────────────────────────

const INDICATOR_OPTIONS: { key: IndicatorKey; label: string; desc: string }[] = [
  { key: 'rsi',       label: 'RSI',             desc: 'Relative Strength Index (0–100). Below 30 = oversold (potential buy), above 70 = overbought (potential sell). Period controls sensitivity.' },
  { key: 'macd',      label: 'MACD',            desc: 'Moving Average Convergence Divergence. When the MACD line crosses above the Signal line it is bullish; crossing below is bearish.' },
  { key: 'sma50',     label: '50-day SMA',      desc: 'Simple Moving Average over 50 days — medium-term trend indicator. Price above SMA is bullish; price below is bearish.' },
  { key: 'sma200',    label: '200-day SMA',     desc: 'Simple Moving Average over 200 days — the key long-term trend line. Price above = bull market; price below = bear market territory.' },
  { key: 'sma20',     label: '20-day SMA',      desc: 'Short-term moving average often used as the centerline in Bollinger Bands. Useful for spotting short-term trend shifts.' },
  { key: 'bollinger', label: 'Bollinger Bands', desc: 'Price envelope (SMA ± N standard deviations). Price near the upper band = overbought; near the lower band = oversold. Bands widen in volatile markets.' },
  { key: 'volume',    label: 'Volume Analysis', desc: 'Today\'s volume vs the 3-month average. A big price move on high volume confirms conviction; low volume moves may be false breakouts.' },
]

const INCLUDE_INFO: Record<string, string> = {
  news:         'Analyzes recent news headlines for positive/negative sentiment and weights it in the final signal.',
  fundamentals: 'Fetches P/E ratio, EPS, market cap, revenue, debt/equity, ROE, and more from Yahoo Finance.',
  peers:        'Compares this stock\'s metrics against similar companies in the same sector to gauge relative value.',
}

const FUNDAMENTAL_INFO: Record<string, string> = {
  'Market Cap':     'Total market value = share price × shares outstanding. Small-cap < $2B, Mid $2–10B, Large > $10B.',
  'P/E Ratio':      'Price-to-Earnings (trailing). Lower can mean undervalued vs peers; a high P/E implies growth expectations. Compare within the same sector.',
  'Forward P/E':    'P/E using next 12 months\' estimated earnings. Useful for comparing current vs expected valuation.',
  'EPS (TTM)':      'Earnings Per Share over the trailing 12 months — company net profit divided by shares outstanding.',
  'Revenue':        'Total income from sales (trailing 12 months). Focus on the growth rate over time rather than the absolute number.',
  'Profit Margin':  'Net income ÷ Revenue. Higher margins = more efficient business. Typical margins vary widely by industry.',
  'Debt/Equity':    'Total debt ÷ shareholder equity. Above 2.0 may signal financial risk, though capital-intensive sectors naturally carry more debt.',
  'Current Ratio':  'Current assets ÷ current liabilities. Above 1.0 means the company can cover near-term obligations; below 1.0 may indicate liquidity risk.',
  'ROE':            'Return on Equity: net income ÷ shareholder equity. Measures how efficiently management uses investor capital. Compare to sector peers.',
  'Dividend Yield': 'Annual dividend ÷ share price. An income metric — compare to sector averages and current bond yields.',
  'Beta':           'Measures price volatility relative to the market (S&P 500). Beta >1 = more volatile; <1 = more stable; negative = moves inversely to market.',
}

const MACD_PRESETS = [
  { label: 'Standard (12/26/9)', fast: 12, slow: 26, sig: 9 },
  { label: 'Faster (8/17/9)',    fast: 8,  slow: 17, sig: 9 },
  { label: 'Slower (21/55/13)', fast: 21, slow: 55, sig: 13 },
] as const

const PERIOD_OPTIONS = [
  { value: '1d', label: '1 Day' },
  { value: '1w', label: '1 Week' },
  { value: '1m', label: '1 Month' },
  { value: '3m', label: '3 Months' },
  { value: '6m', label: '6 Months' },
  { value: '1y', label: '1 Year' },
] as const

const SIGNAL_STYLE: Record<string, string> = {
  buy:   'bg-green-100 text-green-800 border border-green-300',
  watch: 'bg-blue-100 text-blue-800 border border-blue-300',
  hold:  'bg-yellow-100 text-yellow-700 border border-yellow-300',
  sell:  'bg-red-100 text-red-800 border border-red-300',
}


// ── Helpers ───────────────────────────────────────────────────────────────────

function fmt(v: number | null | undefined, decimals = 2, prefix = '', suffix = ''): string {
  if (v == null) return '—'
  return `${prefix}${v.toFixed(decimals)}${suffix}`
}

function fmtBig(v: number | null | undefined, currency = '$'): string {
  if (v == null) return '—'
  if (v >= 1e12) return `${currency}${(v / 1e12).toFixed(2)}T`
  if (v >= 1e9)  return `${currency}${(v / 1e9).toFixed(2)}B`
  if (v >= 1e6)  return `${currency}${(v / 1e6).toFixed(2)}M`
  return `${currency}${v.toFixed(0)}`
}

function chgColor(v: number | null): string {
  if (v == null) return 'text-ink-muted'
  return v >= 0 ? 'text-green-600' : 'text-red-600'
}

// ── Sub-components ────────────────────────────────────────────────────────────

function MetricCard({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="bg-surface rounded-xl border border-surface-border p-4 flex flex-col gap-1">
      <span className="text-xs font-medium text-ink-muted uppercase tracking-wide">{label}</span>
      <span className="text-xl font-bold text-ink">{value}</span>
      {sub && <span className="text-xs text-ink-faint">{sub}</span>}
    </div>
  )
}

function IndicatorRow({ label, value, note, noteColor, info }: { label: string; value: string; note?: string; noteColor?: string; info?: string }) {
  return (
    <div className="flex items-center justify-between py-2 border-b border-surface-border/60 last:border-0">
      <span className="flex items-center gap-1.5 text-sm text-ink-muted">
        {label}
        {info && <InfoTooltip text={info} align="left" />}
      </span>
      <div className="text-right">
        <span className="text-sm font-semibold text-ink">{value}</span>
        {note && <div className={`text-xs ${noteColor ?? 'text-ink-faint'}`}>{note}</div>}
      </div>
    </div>
  )
}

function TechnicalPanel({
  tech,
  requested,
  rsiPeriod = 14,
  macdFast = 12,
  macdSlow = 26,
  macdSig = 9,
  bbPeriod = 20,
  bbStd = 2.0,
  currency = '$',
}: {
  tech: TechnicalSnapshot
  requested: string[]
  rsiPeriod?: number
  macdFast?: number
  macdSlow?: number
  macdSig?: number
  bbPeriod?: number
  bbStd?: number
  currency?: string
}) {
  const ind = new Set(requested)

  return (
    <div className="space-y-4">
      {/* Price row */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <MetricCard
          label="Current Price"
          value={fmt(tech.current_price, 2, currency)}
          sub={`Prev close ${fmt(tech.prev_close, 2, currency)}`}
        />
        <MetricCard
          label="Day Change"
          value={tech.day_change_pct != null ? `${tech.day_change_pct >= 0 ? '+' : ''}${tech.day_change_pct.toFixed(2)}%` : '—'}
          sub="vs previous close"
        />
        <MetricCard
          label="52-Week Range"
          value={`${fmt(tech.low_52w, 2, currency)} – ${fmt(tech.high_52w, 2, currency)}`}
          sub={tech.pos_52w_pct != null ? `${tech.pos_52w_pct.toFixed(0)}% from low` : undefined}
        />
        <MetricCard
          label="Volume"
          value={tech.last_volume != null ? (tech.last_volume >= 1e6 ? `${(tech.last_volume / 1e6).toFixed(1)}M` : tech.last_volume.toLocaleString()) : '—'}
          sub={tech.vol_ratio != null ? `${tech.vol_ratio.toFixed(2)}× avg` : undefined}
        />
      </div>

      {/* Score + signal + confidence */}
      <div className="bg-surface rounded-xl border border-surface-border p-4 flex items-center gap-4">
        <div className="flex-1 space-y-3">
          {/* Momentum score */}
          <div>
            <div className="flex justify-between items-center mb-1">
              <div className="text-xs font-medium text-ink-muted uppercase tracking-wide">
                Momentum Score
                <span className="ml-1.5 text-[10px] normal-case font-normal text-ink-faint">(always 3-month daily)</span>
              </div>
              <div className="text-xs text-ink-faint">{tech.score.toFixed(1)} / 100</div>
            </div>
            <div className="relative h-2.5 bg-surface-muted rounded-full overflow-hidden">
              <div
                className={clsx('h-full rounded-full transition-all', {
                  'bg-green-500':  tech.score >= 65,
                  'bg-blue-500':   tech.score >= 52,
                  'bg-yellow-400': tech.score >= 38,
                  'bg-red-500':    tech.score < 38,
                })}
                style={{ width: `${tech.score}%` }}
              />
            </div>
          </div>
          {/* Confidence */}
          <div>
            <div className="flex justify-between items-center mb-1">
              <div className="text-xs font-medium text-ink-muted uppercase tracking-wide">
                Indicator Confidence
              </div>
              <div className={clsx('text-xs font-semibold', tech.confidence >= 70 ? 'text-green-500' : tech.confidence >= 50 ? 'text-yellow-500' : 'text-red-500')}>
                {tech.confidence.toFixed(0)}%
              </div>
            </div>
            <div className="relative h-2.5 bg-surface-muted rounded-full overflow-hidden">
              <div
                className={clsx('h-full rounded-full transition-all', {
                  'bg-green-500':  tech.confidence >= 70,
                  'bg-yellow-400': tech.confidence >= 50,
                  'bg-red-500':    tech.confidence < 50,
                })}
                style={{ width: `${tech.confidence}%` }}
              />
            </div>
            <div className="text-xs text-ink-faint mt-0.5">
              {tech.confidence >= 70 ? 'High — indicators strongly agree'
               : tech.confidence >= 50 ? 'Moderate — mixed signals'
               : 'Low — indicators disagree, caution advised'}
            </div>
          </div>
        </div>
        <span className={clsx('px-3 py-1 rounded-full text-sm font-bold uppercase flex-shrink-0', SIGNAL_STYLE[tech.signal] ?? SIGNAL_STYLE.hold)}>
          {tech.signal}
        </span>
      </div>

      {/* Indicator detail */}
      <div className="bg-surface rounded-xl border border-surface-border p-4">
        <div className="text-sm font-semibold text-ink mb-3">Technical Indicators</div>

        {ind.has('rsi') && tech.rsi != null && (
          <IndicatorRow
            label={`RSI (${rsiPeriod})`}
            value={tech.rsi.toFixed(2)}
            note={tech.rsi < 30 ? 'Oversold' : tech.rsi > 70 ? 'Overbought' : 'Neutral'}
            info="Relative Strength Index (0–100). Below 30 = oversold (potential buy signal), above 70 = overbought (potential sell signal). The period controls how many days are used."
          />
        )}

        {ind.has('macd') && tech.macd != null && (
          <>
            <IndicatorRow
              label={`MACD (${macdFast}/${macdSlow}/${macdSig})`}
              value={tech.macd.toFixed(4)}
              info="MACD = fast EMA minus slow EMA. Positive values mean the short-term average is above the long-term average (bullish momentum)."
            />
            {tech.macd_signal != null && (
              <IndicatorRow
                label="Signal Line"
                value={tech.macd_signal.toFixed(4)}
                note={tech.macd > tech.macd_signal ? 'Bullish crossover' : 'Bearish crossover'}
                info={`${macdSig}-period EMA of the MACD line. When MACD crosses above this line it's a buy signal; crossing below is a sell signal.`}
              />
            )}
            {tech.macd_hist != null && (
              <IndicatorRow
                label="Histogram"
                value={tech.macd_hist.toFixed(4)}
                info="MACD minus Signal Line. Positive and growing = strengthening bullish momentum. Negative and falling = strengthening bearish momentum."
              />
            )}
          </>
        )}

        {ind.has('sma20') && tech.sma20 != null && (
          <IndicatorRow
            label="20-day SMA"
            value={fmt(tech.sma20, 2, '$')}
            note={tech.current_price ? (tech.current_price > tech.sma20 ? 'Price above' : 'Price below') : undefined}
            info="Average closing price over 20 trading days. Often used as the midline for Bollinger Bands. Price holding above it suggests short-term uptrend."
          />
        )}

        {ind.has('sma50') && tech.sma50 != null && (
          <IndicatorRow
            label="50-day SMA"
            value={fmt(tech.sma50, 2, '$')}
            note={tech.current_price ? (tech.current_price > tech.sma50 ? 'Price above' : 'Price below') : undefined}
            info="Average closing price over 50 trading days — medium-term trend. A 'golden cross' occurs when the 50-day crosses above the 200-day (bullish)."
          />
        )}

        {ind.has('sma200') && tech.sma200 != null && (
          <IndicatorRow
            label="200-day SMA"
            value={fmt(tech.sma200, 2, '$')}
            note={tech.current_price ? (tech.current_price > tech.sma200 ? 'Price above (bullish)' : 'Price below (bearish)') : undefined}
            info="Average closing price over 200 trading days — the primary long-term trend indicator. Price above it is generally considered a bull market; below is bear market territory."
          />
        )}

        {ind.has('bollinger') && tech.bb_upper != null && (
          <>
            <IndicatorRow
              label={`BB Upper (${bbPeriod}, ${bbStd}σ)`}
              value={fmt(tech.bb_upper, 2, '$')}
              info={`Upper Bollinger Band = ${bbPeriod}-day SMA + ${bbStd}× standard deviation. Price touching the upper band can signal overbought conditions.`}
            />
            <IndicatorRow
              label="BB Middle"
              value={fmt(tech.bb_mid, 2, '$')}
              info={`The ${bbPeriod}-day simple moving average — the centerline of the Bollinger Band envelope.`}
            />
            <IndicatorRow
              label="BB Lower"
              value={fmt(tech.bb_lower, 2, '$')}
              info={`Lower Bollinger Band = ${bbPeriod}-day SMA − ${bbStd}× standard deviation. Price touching the lower band can signal oversold conditions.`}
            />
          </>
        )}

        {ind.has('volume') && (
          <>
            {tech.last_volume != null && (
              <IndicatorRow
                label="Today's Volume"
                value={tech.last_volume.toLocaleString()}
                info="Number of shares traded today. High volume confirms price moves; low volume may indicate weak conviction."
              />
            )}
            {tech.avg_volume != null && (
              <IndicatorRow
                label="Avg Volume (3mo)"
                value={tech.avg_volume.toLocaleString()}
                note={tech.vol_ratio != null ? `Ratio: ${tech.vol_ratio.toFixed(2)}×` : undefined}
                info="Average daily volume over the past 3 months. A ratio above 1.5× indicates unusually high interest — often significant on breakout days."
              />
            )}
          </>
        )}

        {/* Period returns */}
        <div className="mt-3 pt-3 border-t border-surface-border/60 grid grid-cols-3 gap-2">
          {[
            { label: '1D',  val: tech.day_change_pct   },
            { label: '1W',  val: tech.week_change_pct  },
            { label: '1M',  val: tech.month_change_pct },
          ].map(({ label, val }) => (
            <div key={label} className="text-center">
              <div className="text-xs text-ink-faint">{label} return</div>
              <div className={clsx('text-sm font-semibold', chgColor(val))}>
                {val != null ? `${val >= 0 ? '+' : ''}${val.toFixed(2)}%` : '—'}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

function FundamentalsPanel({ fund, currency = '$' }: { fund: FundamentalSnapshot; currency?: string }) {
  const fwdEpsStr = (() => {
    if (fund.forward_eps == null || fund.eps == null) return fmt(fund.eps, 2, currency)
    const pct = fund.eps_growth != null ? ` (${fund.eps_growth > 0 ? '+' : ''}${(fund.eps_growth * 100).toFixed(1)}% fwd)` : ''
    return `${currency}${fund.eps?.toFixed(2)} → ${currency}${fund.forward_eps.toFixed(2)}${pct}`
  })()

  const splitStr = fund.last_split_date
    ? fund.last_split_type === 'forward'
      ? `${fund.last_split_ratio}:1 Forward · ${fund.last_split_date}`
      : `1:${fund.last_split_ratio != null ? (1 / fund.last_split_ratio).toFixed(0) : '?'} Reverse · ${fund.last_split_date}`
    : null

  const rows = [
    { label: 'Market Cap',      value: fmtBig(fund.market_cap, currency) },
    { label: 'P/E Ratio',       value: fmt(fund.pe_ratio, 2) },
    { label: 'Forward P/E',     value: fmt(fund.forward_pe, 2) },
    { label: 'EPS (TTM → Fwd)', value: fwdEpsStr },
    { label: 'EPS Surprise',    value: fund.eps_surprise_pct != null ? `${fund.eps_surprise_pct > 0 ? '+' : ''}${fund.eps_surprise_pct.toFixed(1)}% vs est` : '—' },
    { label: 'Revenue',         value: fmtBig(fund.revenue, currency) },
    { label: 'Revenue Growth',  value: fund.revenue_growth != null ? `${(fund.revenue_growth * 100).toFixed(1)}%` : '—' },
    { label: 'Profit Margin',   value: fund.profit_margin != null ? `${(fund.profit_margin * 100).toFixed(1)}%` : '—' },
    { label: 'Debt/Equity',     value: fmt(fund.debt_to_equity, 2) },
    { label: 'Current Ratio',   value: fmt(fund.current_ratio, 2) },
    { label: 'ROE',             value: fund.return_on_equity != null ? `${(fund.return_on_equity * 100).toFixed(1)}%` : '—' },
    { label: 'Dividend Yield',  value: fund.dividend_yield != null ? `${(fund.dividend_yield * 100).toFixed(2)}%` : '—' },
    { label: 'Beta',            value: fmt(fund.beta, 2) },
    { label: 'Short Interest',  value: fund.short_pct_float != null ? `${(fund.short_pct_float * 100).toFixed(1)}% float` : '—' },
  ]

  const valueColor = (label: string): string => {
    if (label === 'EPS Surprise' && fund.eps_surprise_pct != null)
      return fund.eps_surprise_pct > 0 ? 'text-green-600' : 'text-red-500'
    if (label === 'Last Split (5y)' && fund.last_split_type === 'reverse') return 'text-red-500'
    if (label === 'Last Split (5y)' && fund.last_split_type === 'forward') return 'text-green-600'
    if (label === 'Upcoming Split') return 'text-blue-600 font-bold'
    return 'text-ink'
  }

  return (
    <div className="bg-surface rounded-xl border border-surface-border p-4">
      <div className="text-sm font-semibold text-ink mb-3">Fundamental Snapshot</div>
      {fund.sector && (
        <div className="text-xs text-ink-muted mb-3">
          <span className="font-medium">{fund.sector}</span>
          {fund.industry && <> · {fund.industry}</>}
        </div>
      )}

      <div className="divide-y divide-surface-border/60">
        {rows.map(({ label, value }) => (
          <div key={label} className="flex justify-between items-center py-2">
            <span className="flex items-center gap-1.5 text-sm text-ink-muted">
              {label}
              {FUNDAMENTAL_INFO[label] && (
                <InfoTooltip text={FUNDAMENTAL_INFO[label]} align="left" />
              )}
            </span>
            <span className={`text-sm font-semibold ${valueColor(label)}`}>{value}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

const REC_STYLE: Record<string, string> = {
  strong_buy:   'bg-green-600 text-white',
  buy:          'bg-green-100 text-green-800 border border-green-300',
  hold:         'bg-yellow-100 text-yellow-700 border border-yellow-300',
  underperform: 'bg-orange-100 text-orange-700 border border-orange-300',
  sell:         'bg-red-100 text-red-800 border border-red-300',
}

function AnalystPanel({ analyst, currentPrice, currency = '$' }: { analyst: AnalystSnapshot; currentPrice: number | null; currency?: string }) {
  const recKey = analyst.recommendation_key?.toLowerCase() ?? ''
  const chipStyle = REC_STYLE[recKey] ?? 'bg-surface-muted text-ink border border-surface-border'

  // For the price target bar: position current price and mean target within low-high range
  const hasTargets = analyst.target_low != null && analyst.target_high != null && analyst.target_high > analyst.target_low
  const rangeSpan  = hasTargets ? analyst.target_high! - analyst.target_low! : 0

  function pct(val: number | null) {
    if (!hasTargets || val == null) return null
    return Math.max(0, Math.min(100, ((val - analyst.target_low!) / rangeSpan) * 100))
  }

  const currentPct = currentPrice != null ? pct(currentPrice) : null
  const meanPct    = pct(analyst.target_mean)
  const medianPct  = pct(analyst.target_median)

  const meanScale = analyst.recommendation_mean  // 1–5
  const scaleW    = meanScale != null ? ((meanScale - 1) / 4) * 100 : null

  return (
    <div className="bg-surface rounded-xl border border-surface-border p-4 space-y-4">
      <div className="text-sm font-semibold text-ink">Analyst Consensus</div>

      {/* Recommendation chip + mean score */}
      <div className="flex items-center gap-3">
        {analyst.recommendation ? (
          <span className={clsx('px-3 py-1 rounded-full text-sm font-bold', chipStyle)}>
            {analyst.recommendation}
          </span>
        ) : (
          <span className="text-sm text-ink-faint">No consensus available</span>
        )}
        {analyst.num_analysts != null && (
          <span className="text-xs text-ink-faint">{analyst.num_analysts} analyst{analyst.num_analysts !== 1 ? 's' : ''}</span>
        )}
        {analyst.upside_pct != null && (
          <span className={clsx('ml-auto text-sm font-bold', analyst.upside_pct >= 0 ? 'text-green-600' : 'text-red-600')}>
            {analyst.upside_pct >= 0 ? '+' : ''}{analyst.upside_pct.toFixed(1)}% upside
          </span>
        )}
      </div>

      {/* Rating scale 1–5 */}
      {analyst.recommendation_mean != null && (
        <div>
          <div className="flex justify-between text-xs text-ink-faint mb-1">
            <span>Strong Buy</span>
            <span>Buy</span>
            <span>Hold</span>
            <span>Sell</span>
            <span>Strong Sell</span>
          </div>
          <div className="relative h-2 rounded-full bg-gradient-to-r from-green-500 via-yellow-400 to-red-500">
            {scaleW != null && (
              <div
                className="absolute top-1/2 -translate-y-1/2 w-3 h-3 rounded-full bg-surface border-2 border-ink-muted shadow"
                style={{ left: `calc(${scaleW}% - 6px)` }}
              />
            )}
          </div>
          <div className="text-xs text-center text-ink-muted mt-1">
            Mean: {analyst.recommendation_mean.toFixed(2)} / 5.0
          </div>
        </div>
      )}

      {/* Price target range bar */}
      {hasTargets && (
        <div>
          <div className="text-xs font-medium text-ink-muted mb-2">Price Target Range</div>
          <div className="relative h-6">
            {/* Track */}
            <div className="absolute top-1/2 -translate-y-1/2 left-0 right-0 h-1.5 bg-surface-muted rounded-full" />
            {/* Fill: low to high */}
            <div className="absolute top-1/2 -translate-y-1/2 h-1.5 bg-blue-200 rounded-full" style={{ left: '0%', right: '0%' }} />
            {/* Mean target marker */}
            {meanPct != null && (
              <div className="absolute top-1/2 -translate-y-1/2 w-3 h-3 rounded-full bg-blue-600 border-2 border-white shadow"
                style={{ left: `calc(${meanPct}% - 6px)` }}
                title={`Mean target: ${currency}${analyst.target_mean?.toFixed(2)}`}
              />
            )}
            {/* Median target marker */}
            {medianPct != null && medianPct !== meanPct && (
              <div className="absolute top-1/2 -translate-y-1/2 w-2.5 h-2.5 rounded-full bg-indigo-400 border-2 border-white shadow"
                style={{ left: `calc(${medianPct}% - 5px)` }}
                title={`Median target: ${currency}${analyst.target_median?.toFixed(2)}`}
              />
            )}
            {/* Current price marker */}
            {currentPct != null && (
              <div className="absolute top-1/2 -translate-y-1/2 w-2.5 h-4 rounded bg-ink-muted"
                style={{ left: `calc(${currentPct}% - 5px)` }}
                title={`Current: ${currency}${currentPrice?.toFixed(2)}`}
              />
            )}
          </div>
          <div className="flex justify-between text-xs text-ink-faint mt-1">
            <span>{currency}{analyst.target_low?.toFixed(2)} low</span>
            {analyst.target_mean != null && (
              <span className="text-blue-600 font-medium">{currency}{analyst.target_mean.toFixed(2)} mean</span>
            )}
            <span>{currency}{analyst.target_high?.toFixed(2)} high</span>
          </div>
        </div>
      )}

      {/* Compact table */}
      <div className="divide-y divide-surface-border/60 text-sm">
        {[
          { label: 'Target (Mean)',   value: analyst.target_mean   != null ? `${currency}${analyst.target_mean.toFixed(2)}`   : '—' },
          { label: 'Target (Median)', value: analyst.target_median != null ? `${currency}${analyst.target_median.toFixed(2)}` : '—' },
          { label: 'Target High',    value: analyst.target_high   != null ? `${currency}${analyst.target_high.toFixed(2)}`   : '—' },
          { label: 'Target Low',     value: analyst.target_low    != null ? `${currency}${analyst.target_low.toFixed(2)}`    : '—' },
        ].map(({ label, value }) => (
          <div key={label} className="flex justify-between py-1.5">
            <span className="text-ink-muted">{label}</span>
            <span className="font-semibold text-ink">{value}</span>
          </div>
        ))}
      </div>

      {/* Individual analyst ratings */}
      {analyst.ratings && analyst.ratings.length > 0 && (
        <div>
          <div className="text-xs font-semibold text-ink-muted uppercase tracking-wide mb-2">
            Recent Analyst Ratings (Last 12 Months)
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-ink-faint border-b border-surface-border">
                  <th className="text-left py-1.5 font-medium pr-3">Date</th>
                  <th className="text-left py-1.5 font-medium pr-3">Firm</th>
                  <th className="text-left py-1.5 font-medium pr-3">Rating</th>
                  <th className="text-left py-1.5 font-medium pr-3">From</th>
                  <th className="text-left py-1.5 font-medium">Action</th>
                </tr>
              </thead>
              <tbody>
                {analyst.ratings.map((r, i) => {
                  const actionColor =
                    r.action === 'up'   ? 'text-green-600' :
                    r.action === 'down' ? 'text-red-500'   :
                    r.action === 'init' ? 'text-blue-600'  : 'text-ink-muted'
                  const actionLabel =
                    r.action === 'up'   ? 'Upgrade'   :
                    r.action === 'down' ? 'Downgrade' :
                    r.action === 'init' ? 'Initiated' :
                    r.action === 'reit' ? 'Reiterated':
                    r.action === 'main' ? 'Maintained': r.action
                  return (
                    <tr key={i} className="border-b border-surface-border/40 last:border-0 hover:bg-surface-muted/30">
                      <td className="py-1.5 text-ink-muted pr-3 whitespace-nowrap">{r.date}</td>
                      <td className="py-1.5 text-ink pr-3 max-w-[120px] truncate font-medium">{r.firm || '—'}</td>
                      <td className="py-1.5 pr-3 font-semibold text-ink">{r.to_grade || '—'}</td>
                      <td className="py-1.5 pr-3 text-ink-muted">{r.from_grade || '—'}</td>
                      <td className={`py-1.5 font-semibold ${actionColor}`}>{actionLabel}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}

function computeSMA(closes: number[], period: number): (number | null)[] {
  return closes.map((_, i) => {
    if (i < period - 1) return null
    const slice = closes.slice(i - period + 1, i + 1)
    return slice.reduce((a, b) => a + b, 0) / period
  })
}

function StockChartPanel({
  ticker,
  period,
  indicators,
  eps,
  currency = '$',
}: {
  ticker: string
  period: string
  indicators: string[]
  eps: number | null | undefined
  currency?: string
}) {
  const [showPE, setShowPE] = useState(false)

  const { data, isLoading, isError } = useQuery({
    queryKey: ['stock-history', ticker, period],
    queryFn: () => fetchStockHistory(ticker, period),
    staleTime: 5 * 60 * 1000,
  })

  const chartData = useMemo(() => {
    if (!data?.bars?.length) return []
    const closes = data.bars.map(b => b.close ?? 0)
    const sma20v  = computeSMA(closes, 20)
    const sma50v  = computeSMA(closes, 50)
    const sma200v = computeSMA(closes, 200)

    return data.bars.map((bar, i) => ({
      ...bar,
      close:  bar.close  != null ? +bar.close.toFixed(4)  : null,
      sma20:  indicators.includes('sma20')   ? sma20v[i]  : undefined,
      sma50:  indicators.includes('sma50')   ? sma50v[i]  : undefined,
      sma200: indicators.includes('sma200')  ? sma200v[i] : undefined,
      pe:     showPE && eps && eps > 0 && bar.close
                ? +( bar.close / Math.abs(eps) ).toFixed(1)
                : undefined,
    }))
  }, [data, indicators, eps, showPE])

  const TooltipContent = ({ active, payload, label }: { active?: boolean; payload?: { dataKey: string; value: number; color: string; name: string }[]; label?: string }) => {
    if (!active || !payload?.length) return null
    return (
      <div className="bg-surface border border-surface-border rounded-lg p-3 text-xs shadow-lg">
        <div className="font-semibold text-ink mb-1.5 text-[11px]">{label}</div>
        {payload.map(p => (
          <div key={p.dataKey} className="flex items-center gap-2 py-0.5">
            <span className="w-2 h-2 rounded-full flex-shrink-0" style={{ background: p.color }} />
            <span className="text-ink-muted">{p.name}:</span>
            <span className="font-medium text-ink">
              {p.dataKey === 'volume'
                ? p.value >= 1e6 ? `${(p.value / 1e6).toFixed(2)}M` : p.value.toLocaleString()
                : p.dataKey === 'pe' ? `${p.value}x`
                : `${currency}${Number(p.value).toFixed(2)}`}
            </span>
          </div>
        ))}
      </div>
    )
  }

  if (isLoading) {
    return (
      <div className="bg-surface rounded-xl border border-surface-border p-4 h-52 flex items-center justify-center">
        <div className="flex items-center gap-2 text-ink-muted text-sm">
          <span className="w-4 h-4 rounded-full border-2 border-primary border-t-transparent animate-spin" />
          Loading chart…
        </div>
      </div>
    )
  }

  if (isError || !chartData.length) {
    return (
      <div className="bg-surface rounded-xl border border-surface-border p-4 h-20 flex items-center justify-center text-sm text-ink-muted">
        Chart data unavailable
      </div>
    )
  }

  const prices  = chartData.map(d => d.close).filter((v): v is number => v != null)
  const minPx   = Math.min(...prices) * 0.995
  const maxPx   = Math.max(...prices) * 1.005

  const tickInterval = chartData.length <= 30 ? 3 : chartData.length <= 90 ? 9 : 20

  return (
    <div className="bg-surface rounded-xl border border-surface-border p-4 space-y-3">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div className="text-sm font-semibold text-ink">Price & Volume — {period.toUpperCase()}</div>
        <div className="flex items-center gap-2 flex-wrap">
          {eps && Math.abs(eps) > 0.01 && (
            <button
              onClick={() => setShowPE(v => !v)}
              className={clsx(
                'px-2.5 py-1 rounded-lg border text-xs font-medium transition-all',
                showPE
                  ? 'bg-purple-600 text-white border-purple-600'
                  : 'bg-surface-muted text-ink-muted border-surface-border hover:border-primary/50',
              )}
            >
              P/E Chart
            </button>
          )}
          <span className="text-xs text-ink-faint">{chartData.length} bars</span>
        </div>
      </div>

      {/* Price + Volume */}
      <ResponsiveContainer width="100%" height={300}>
        <ComposedChart data={chartData} margin={{ top: 4, right: 50, bottom: 0, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--color-surface-border)" />
          <XAxis
            dataKey="date"
            tick={{ fontSize: 10, fill: 'var(--color-ink-faint)' }}
            tickLine={false}
            interval={tickInterval}
          />
          <YAxis
            yAxisId="price"
            domain={[minPx, maxPx]}
            tick={{ fontSize: 10, fill: 'var(--color-ink-faint)' }}
            tickLine={false}
            tickFormatter={v => `${currency}${Number(v).toFixed(0)}`}
            width={56}
          />
          <YAxis
            yAxisId="vol"
            orientation="right"
            tick={{ fontSize: 10, fill: 'var(--color-ink-faint)' }}
            tickLine={false}
            tickFormatter={v => v >= 1e6 ? `${(v / 1e6).toFixed(0)}M` : `${(v / 1e3).toFixed(0)}K`}
            width={46}
          />
          <RechartTooltip content={<TooltipContent />} />

          <Area
            yAxisId="price"
            dataKey="close"
            name="Close"
            stroke="#3b82f6"
            fill="#3b82f615"
            strokeWidth={1.5}
            dot={false}
            activeDot={{ r: 3, fill: '#3b82f6' }}
          />
          {indicators.includes('sma20') && (
            <Line yAxisId="price" dataKey="sma20" name="SMA 20" stroke="#10b981" strokeWidth={1} dot={false} />
          )}
          {indicators.includes('sma50') && (
            <Line yAxisId="price" dataKey="sma50" name="SMA 50" stroke="#f97316" strokeWidth={1.5} dot={false} />
          )}
          {indicators.includes('sma200') && (
            <Line yAxisId="price" dataKey="sma200" name="SMA 200" stroke="#ef4444" strokeWidth={1.5} dot={false} />
          )}
          <Bar
            yAxisId="vol"
            dataKey="volume"
            name="Volume"
            fill="#64748b"
            opacity={0.3}
            radius={[1, 1, 0, 0]}
          />
        </ComposedChart>
      </ResponsiveContainer>

      {/* P/E mini-chart */}
      {showPE && eps && Math.abs(eps) > 0.01 && (
        <div className="pt-3 border-t border-surface-border">
          <div className="text-xs text-ink-faint mb-2">
            P/E Ratio (estimated · trailing EPS {fmt(eps, 2, currency)})
          </div>
          <ResponsiveContainer width="100%" height={90}>
            <LineChart data={chartData} margin={{ top: 2, right: 50, bottom: 0, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--color-surface-border)" />
              <XAxis dataKey="date" hide />
              <YAxis
                domain={['auto', 'auto']}
                tick={{ fontSize: 10, fill: 'var(--color-ink-faint)' }}
                tickLine={false}
                tickFormatter={v => `${Number(v).toFixed(0)}x`}
                width={36}
              />
              <RechartTooltip formatter={(v) => [typeof v === 'number' ? `${v.toFixed(1)}x` : '—', 'P/E']} />
              <Line dataKey="pe" name="P/E" stroke="#8b5cf6" strokeWidth={1.5} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Legend */}
      <div className="flex flex-wrap gap-4 text-[11px] text-ink-faint pt-1">
        <span className="flex items-center gap-1.5"><span className="w-4 h-px bg-blue-500 inline-block" /> Close price</span>
        <span className="flex items-center gap-1.5"><span className="w-4 h-2 bg-slate-500 opacity-60 inline-block rounded-sm" /> Volume</span>
        {indicators.includes('sma20')  && <span className="flex items-center gap-1.5"><span className="w-4 h-px bg-emerald-500 inline-block" /> SMA 20</span>}
        {indicators.includes('sma50')  && <span className="flex items-center gap-1.5"><span className="w-4 h-px bg-orange-500 inline-block" /> SMA 50</span>}
        {indicators.includes('sma200') && <span className="flex items-center gap-1.5"><span className="w-4 h-px bg-red-500 inline-block" /> SMA 200</span>}
        {showPE && <span className="flex items-center gap-1.5"><span className="w-4 h-px bg-purple-500 inline-block" /> P/E</span>}
      </div>
    </div>
  )
}

const STALE_THRESHOLD_SECONDS = 900  // 15 minutes

function CacheBadge({ result, onRefresh }: { result: StockAnalysisResult; onRefresh: () => void }) {
  if (!result.cached) return null
  const ageSeconds = result.cache_age_seconds ?? 0
  const ageMin = Math.round(ageSeconds / 60)
  const isStale = ageSeconds > STALE_THRESHOLD_SECONDS
  return (
    <div className="flex items-center gap-2 mt-1.5 flex-wrap">
      <span className={clsx(
        'flex items-center gap-1 text-xs px-2 py-0.5 rounded-full border',
        isStale
          ? 'text-amber-700 bg-amber-50 border-amber-300 dark:text-amber-400 dark:bg-amber-900/20 dark:border-amber-700'
          : 'text-ink-faint bg-surface-muted border-surface-border',
      )}>
        <svg className="w-3 h-3" viewBox="0 0 16 16" fill="currentColor">
          <path d="M8 1a7 7 0 100 14A7 7 0 008 1zM0 8a8 8 0 1116 0A8 8 0 010 8z"/>
          <path d="M7.5 4.5a.5.5 0 011 0v3.793l2.354 2.353a.5.5 0 01-.708.708l-2.5-2.5A.5.5 0 017.5 8.5V4.5z"/>
        </svg>
        {isStale ? `Data may be stale (${ageMin}m old)` : `Cached · ${ageMin}m ago`}
      </span>
      <button onClick={onRefresh} className="text-xs text-primary hover:underline font-medium">
        Refresh
      </button>
    </div>
  )
}

type RiskLevel = 'LOW' | 'MEDIUM' | 'HIGH' | 'UNKNOWN'

function calcRisk(result: StockAnalysisResult): RiskLevel {
  const beta    = result.fundamentals?.beta
  const rsi     = result.technical?.rsi
  const dayChg  = result.technical?.day_change_pct
  if (beta == null && rsi == null && dayChg == null) return 'UNKNOWN'
  if (
    (beta != null && beta > 1.5) ||
    (dayChg != null && Math.abs(dayChg) > 5) ||
    (rsi != null && (rsi < 20 || rsi > 80))
  ) return 'HIGH'
  if (
    (beta == null || beta < 0.7) &&
    (dayChg == null || Math.abs(dayChg) < 2) &&
    (rsi == null || (rsi >= 35 && rsi <= 65))
  ) return 'LOW'
  return 'MEDIUM'
}

const RISK_STYLE: Record<RiskLevel, string> = {
  HIGH:    'bg-red-100 text-red-700 border-red-300 dark:bg-red-900/20 dark:text-red-400 dark:border-red-700',
  MEDIUM:  'bg-yellow-100 text-yellow-700 border-yellow-300 dark:bg-yellow-900/20 dark:text-yellow-400 dark:border-yellow-700',
  LOW:     'bg-green-100 text-green-700 border-green-300 dark:bg-green-900/20 dark:text-green-400 dark:border-green-700',
  UNKNOWN: 'bg-surface-muted text-ink-faint border-surface-border',
}

function ResultBanner({ result, onRefresh, currency = '$' }: { result: StockAnalysisResult; onRefresh: () => void; currency?: string }) {
  const tech    = result.technical
  const signal  = tech?.signal ?? 'hold'
  const risk    = calcRisk(result)

  const bannerBg: Record<string, string> = {
    buy:   'bg-gradient-to-r from-green-50 to-emerald-50 border-green-200 dark:from-green-900/20 dark:to-emerald-900/20 dark:border-green-800',
    watch: 'bg-gradient-to-r from-blue-50 to-cyan-50 border-blue-200 dark:from-blue-900/20 dark:to-cyan-900/20 dark:border-blue-800',
    hold:  'bg-gradient-to-r from-yellow-50 to-amber-50 border-yellow-200 dark:from-yellow-900/20 dark:to-amber-900/20 dark:border-yellow-800',
    sell:  'bg-gradient-to-r from-red-50 to-pink-50 border-red-200 dark:from-red-900/20 dark:to-pink-900/20 dark:border-red-800',
  }
  const pillBg: Record<string, string> = {
    buy:   'bg-green-600 text-white',
    watch: 'bg-blue-600 text-white',
    hold:  'bg-yellow-500 text-white',
    sell:  'bg-red-600 text-white',
  }
  const confColor =
    tech?.confidence != null
      ? tech.confidence >= 70 ? 'text-green-600 dark:text-green-400'
        : tech.confidence >= 50 ? 'text-yellow-500 dark:text-yellow-400'
        : 'text-red-500 dark:text-red-400'
      : 'text-ink-muted'
  const confLabel =
    tech?.confidence != null
      ? tech.confidence >= 70 ? 'High conviction'
        : tech.confidence >= 50 ? 'Mixed signals'
        : 'Low conviction'
      : ''

  return (
    <div className={clsx('rounded-2xl border p-5', bannerBg[signal] ?? bannerBg.hold)}>
      <div className="flex flex-wrap items-center gap-4">
        {/* Ticker + company */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-3 flex-wrap">
            <h2 className="text-3xl font-extrabold text-ink tracking-tight">{result.ticker}</h2>
            <span className={clsx('px-4 py-1.5 rounded-full text-sm font-bold uppercase tracking-wider', pillBg[signal] ?? pillBg.hold)}>
              {signal}
            </span>
          </div>
          {result.company_name && (
            <p className="text-ink-muted text-sm mt-1">{result.company_name}</p>
          )}
          <div className="flex items-center gap-2 flex-wrap mt-0.5">
            <p className="text-xs text-ink-faint">{result.time_period} · {result.mode} · {result.requested_indicators.join(', ')}</p>
            <span className={clsx('text-xs font-semibold px-2 py-0.5 rounded-full border', RISK_STYLE[risk])}>
              {risk === 'UNKNOWN' ? 'Risk: —' : `${risk} RISK`}
            </span>
          </div>
          <CacheBadge result={result} onRefresh={onRefresh} />
          <div className="mt-2">
            <WatchlistButton ticker={result.ticker} />
          </div>
        </div>

        {/* Score + Confidence */}
        {tech && (
          <div className="flex items-center gap-6 shrink-0">
            <div className="text-center">
              <div className="text-3xl font-extrabold text-ink leading-none">{tech.score.toFixed(0)}</div>
              <div className="text-xs text-ink-muted mt-0.5">Momentum</div>
            </div>
            <div className="w-px h-10 bg-surface-border" />
            <div className="text-center">
              <div className={clsx('text-3xl font-extrabold leading-none', confColor)}>{tech.confidence.toFixed(0)}%</div>
              <div className="text-xs text-ink-muted mt-0.5">{confLabel}</div>
            </div>
          </div>
        )}

        {/* Price */}
        {tech?.current_price != null && (
          <div className="text-right shrink-0">
            <div className="text-2xl font-extrabold text-ink">{currency}{tech.current_price.toFixed(2)}</div>
            <div className={clsx('text-sm font-semibold', chgColor(tech.day_change_pct))}>
              {tech.day_change_pct != null
                ? `${tech.day_change_pct >= 0 ? '+' : ''}${tech.day_change_pct.toFixed(2)}%`
                : '—'}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

function AIAnalysisPanel({ text }: { text: string }) {
  return (
    <div className="bg-gradient-to-br from-blue-50 to-indigo-50 rounded-xl border border-blue-200 p-5">
      <div className="flex items-start justify-between gap-3 mb-3 flex-wrap">
        <div className="flex items-center gap-2">
          <span className="text-blue-600 font-bold text-sm">AI Analysis</span>
          <span className="text-xs text-blue-400 bg-blue-100 px-2 py-0.5 rounded-full">Generated by Claude</span>
          <span className="text-xs text-ink-faint bg-surface-muted border border-surface-border px-2 py-0.5 rounded-full">Not reviewed by a licensed analyst</span>
        </div>
      </div>
      <div className="prose prose-sm max-w-none text-ink whitespace-pre-wrap leading-relaxed">
        {text}
      </div>
      <p className="text-xs text-ink-faint border-t border-blue-200 mt-4 pt-3">
        This AI-generated analysis is for informational purposes only and does not constitute investment advice.
        Past performance is not indicative of future results. Always consult a licensed financial advisor before making investment decisions.
      </p>
    </div>
  )
}

// ── Stock Chat Panel ──────────────────────────────────────────────────────────

interface DisplayMsg { role: 'user' | 'assistant'; content: string; streaming?: boolean }

function StockChatPanel({ result, currency = '$' }: { result: StockAnalysisResult; currency?: string }) {
  const [messages, setMessages] = useState<DisplayMsg[]>([])
  const [input, setInput]       = useState('')
  const [busy, setBusy]         = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const send = useCallback(async () => {
    const text = input.trim()
    if (!text || busy) return
    setInput('')

    const userMsg: DisplayMsg = { role: 'user', content: text }
    setMessages(prev => [...prev, userMsg, { role: 'assistant', content: '', streaming: true }])
    setBusy(true)

    const history: ChatMsg[] = messages.map(m => ({ role: m.role, content: m.content }))

    try {
      let accumulated = ''
      for await (const event of streamStockChat(result, text, history)) {
        if (event.type === 'delta') {
          accumulated += event.text
          setMessages(prev => {
            const next = [...prev]
            next[next.length - 1] = { role: 'assistant', content: accumulated, streaming: true }
            return next
          })
        } else if (event.type === 'done') {
          setMessages(prev => {
            const next = [...prev]
            next[next.length - 1] = { role: 'assistant', content: accumulated }
            return next
          })
        } else if (event.type === 'error') {
          setMessages(prev => {
            const next = [...prev]
            next[next.length - 1] = { role: 'assistant', content: `Error: ${event.message}` }
            return next
          })
        }
      }
    } catch (err: unknown) {
      setMessages(prev => {
        const next = [...prev]
        next[next.length - 1] = { role: 'assistant', content: `Failed to get response. Please try again.` }
        return next
      })
    } finally {
      setBusy(false)
    }
  }, [input, busy, messages, result])

  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() }
  }

  const SUGGESTIONS = [
    'What are the key risks for this stock?',
    'Is the valuation cheap or expensive?',
    'What does the insider activity signal?',
    'Summarise the technical setup',
  ]

  return (
    <div className="bg-surface rounded-xl border border-surface-border flex flex-col" style={{ height: '480px' }}>
      {/* Header */}
      <div className="flex items-center gap-2 px-4 py-3 border-b border-surface-border flex-shrink-0">
        <div className="w-2 h-2 rounded-full bg-green-400" />
        <span className="text-sm font-semibold text-ink">Ask about {result.ticker}</span>
        {result.company_name && <span className="text-xs text-ink-faint">· {result.company_name}</span>}
        {messages.length > 0 && (
          <button onClick={() => setMessages([])}
            className="ml-auto text-xs text-ink-faint hover:text-ink-muted transition-colors">
            Clear
          </button>
        )}
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3 min-h-0">
        {messages.length === 0 ? (
          <div className="h-full flex flex-col items-center justify-center gap-4">
            <p className="text-sm text-ink-faint text-center">
              Ask anything about {result.ticker} — technicals, fundamentals, risks, valuation.
            </p>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 w-full max-w-sm">
              {SUGGESTIONS.map(s => (
                <button key={s} onClick={() => { setInput(s); }}
                  className="text-xs text-left px-3 py-2 rounded-lg border border-surface-border bg-surface-muted hover:bg-surface-border/50 text-ink-muted transition-colors">
                  {s}
                </button>
              ))}
            </div>
          </div>
        ) : (
          messages.map((m, i) => (
            <div key={i} className={clsx('flex gap-2', m.role === 'user' ? 'justify-end' : 'justify-start')}>
              {m.role === 'assistant' && (
                <div className="w-6 h-6 rounded-full bg-blue-100 dark:bg-blue-900/40 flex items-center justify-center flex-shrink-0 mt-0.5">
                  <span className="text-[10px] font-bold text-blue-600 dark:text-blue-400">AI</span>
                </div>
              )}
              <div className={clsx(
                'max-w-[80%] rounded-2xl px-3 py-2 text-sm leading-relaxed',
                m.role === 'user'
                  ? 'bg-blue-600 text-white rounded-tr-sm'
                  : 'bg-surface-muted text-ink rounded-tl-sm',
              )}>
                {m.content || (m.streaming && <span className="inline-block w-2 h-4 bg-ink-muted/50 animate-pulse rounded" />)}
              </div>
            </div>
          ))
        )}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="px-4 py-3 border-t border-surface-border flex-shrink-0">
        <div className="flex gap-2">
          <textarea
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={onKey}
            placeholder={`Ask about ${result.ticker}…`}
            rows={1}
            disabled={busy}
            className="flex-1 resize-none rounded-xl border border-surface-border bg-surface-muted px-3 py-2 text-sm text-ink placeholder:text-ink-faint focus:outline-none focus:ring-2 focus:ring-primary/40 disabled:opacity-50"
            style={{ minHeight: '40px', maxHeight: '120px' }}
          />
          <button
            onClick={send}
            disabled={busy || !input.trim()}
            className="flex-shrink-0 w-10 h-10 rounded-xl bg-blue-600 hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed text-white flex items-center justify-center transition-colors"
          >
            {busy
              ? <span className="w-4 h-4 rounded-full border-2 border-white/30 border-t-white animate-spin" />
              : <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" /></svg>
            }
          </button>
        </div>
        <p className="text-[10px] text-ink-faint mt-1.5 text-center">For research only — not investment advice · Enter to send</p>
      </div>
    </div>
  )
}

// ── RS Rating Panel ───────────────────────────────────────────────────────────

function RSRatingBadge({ rs }: { rs: RSRating }) {
  const score = rs.rs_score
  const color = score >= 90 ? '#16a34a' : score >= 80 ? '#22c55e' : score >= 70 ? '#3b82f6'
    : score >= 50 ? '#eab308' : '#ef4444'
  const label = score >= 90 ? 'Elite' : score >= 80 ? 'Strong' : score >= 70 ? 'Above Avg'
    : score >= 50 ? 'Average' : 'Lagging'

  return (
    <div className="flex items-center gap-3 bg-surface rounded-xl border border-surface-border px-4 py-3">
      {/* Circular score */}
      <div className="relative flex-shrink-0">
        <svg width="56" height="56">
          <circle cx="28" cy="28" r="24" fill="none" stroke="var(--color-surface-muted)" strokeWidth="5" />
          <circle cx="28" cy="28" r="24" fill="none" stroke={color} strokeWidth="5"
            strokeDasharray={`${score / 100 * 150.8} 150.8`}
            strokeLinecap="round" transform="rotate(-90 28 28)" />
          <text x="28" y="33" textAnchor="middle" fontSize="14" fontWeight="bold" fill={color}>{score}</text>
        </svg>
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="text-sm font-bold text-ink">RS Rating</span>
          <span className="text-xs px-2 py-0.5 rounded-full font-semibold" style={{ backgroundColor: color + '20', color }}>{label}</span>
        </div>
        <p className="text-xs text-ink-faint mt-0.5">Relative Strength vs S&P 500 (1 = worst, 99 = best)</p>
        <div className="flex gap-3 mt-1 text-xs text-ink-muted flex-wrap">
          {rs.vs_spy_3m != null && (
            <span className={rs.vs_spy_3m >= 0 ? 'text-green-600' : 'text-red-500'}>
              3m: {rs.vs_spy_3m >= 0 ? '+' : ''}{rs.vs_spy_3m.toFixed(1)}% vs SPY
            </span>
          )}
          {rs.vs_spy_12m != null && (
            <span className={rs.vs_spy_12m >= 0 ? 'text-green-600' : 'text-red-500'}>
              12m: {rs.vs_spy_12m >= 0 ? '+' : ''}{rs.vs_spy_12m.toFixed(1)}% vs SPY
            </span>
          )}
        </div>
      </div>
    </div>
  )
}

// ── Horizon Analysis Panel (ST + LT) ─────────────────────────────────────────

function HorizonPanel({ st, lt }: { st: HorizonAnalysis | null | undefined; lt: HorizonAnalysis | null | undefined }) {
  if (!st && !lt) return null

  const signalColor = (sig: string) =>
    sig === 'strong buy' ? 'text-green-700 dark:text-green-400 bg-green-100 dark:bg-green-900/30'
    : sig === 'buy' ? 'text-green-600 dark:text-green-400 bg-green-50 dark:bg-green-900/20'
    : sig === 'watch' ? 'text-blue-600 dark:text-blue-400 bg-blue-50 dark:bg-blue-900/20'
    : sig === 'hold' ? 'text-yellow-600 dark:text-yellow-400 bg-yellow-50 dark:bg-yellow-900/20'
    : 'text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20'

  function HorizonCard({ analysis, horizon, label, desc }: {
    analysis: HorizonAnalysis; horizon: string; label: string; desc: string
  }) {
    const barColor = analysis.score >= 65 ? 'bg-green-500' : analysis.score >= 52 ? 'bg-blue-500'
      : analysis.score >= 38 ? 'bg-yellow-500' : 'bg-red-500'
    return (
      <div className="bg-surface rounded-xl border border-surface-border p-4 flex-1 min-w-0">
        <div className="flex items-start justify-between gap-2 mb-3">
          <div>
            <div className="text-xs font-bold text-ink-faint uppercase tracking-wider">{label}</div>
            <div className="text-xs text-ink-faint mt-0.5">{desc}</div>
          </div>
          <span className={clsx('text-xs px-2.5 py-1 rounded-full font-bold flex-shrink-0', signalColor(analysis.signal))}>
            {analysis.signal.toUpperCase()}
          </span>
        </div>
        {/* Score bar */}
        <div className="mb-3">
          <div className="flex justify-between text-xs mb-1">
            <span className="text-ink-faint">Score</span>
            <span className="font-bold text-ink">{analysis.score.toFixed(0)}/100</span>
          </div>
          <div className="h-2 bg-surface-muted rounded-full overflow-hidden">
            <div className={clsx('h-full rounded-full', barColor)} style={{ width: `${analysis.score}%` }} />
          </div>
        </div>
        {/* Top reasons */}
        {analysis.reasoning.length > 0 && (
          <ul className="space-y-1.5">
            {analysis.reasoning.slice(0, 4).map((r, i) => (
              <li key={i} className="flex items-start gap-1.5 text-xs text-ink-muted">
                <span className="text-green-500 flex-shrink-0 mt-0.5">•</span>
                <span>{r}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    )
  }

  return (
    <div className="space-y-2">
      <div className="text-xs font-bold text-ink-faint uppercase tracking-widest px-1">Investment Horizon Analysis</div>
      <div className="flex gap-3 flex-col sm:flex-row">
        {st && <HorizonCard analysis={st} horizon="st" label="Short-Term (1–4 weeks)" desc="Technical momentum + RS rating + multi-timeframe" />}
        {lt && <HorizonCard analysis={lt} horizon="lt" label="Long-Term (3–12 months)" desc="Fundamental quality + RS rating + trend structure" />}
      </div>
    </div>
  )
}

// ── Factor Decomposition Panel (institutional cross-sectional ranking) ─────────

const FACTOR_META: { key: string; label: string; desc: string }[] = [
  { key: 'momentum',  label: 'Momentum',            desc: 'Trend & relative strength' },
  { key: 'quality',   label: 'Quality',             desc: 'ROE, margins, low leverage' },
  { key: 'value',     label: 'Value',               desc: 'Earnings / cash yield' },
  { key: 'growth',    label: 'Growth',              desc: 'EPS & revenue growth' },
  { key: 'revisions', label: 'Revisions & Sentiment', desc: 'Analyst, surprise, short interest' },
  { key: 'low_vol',   label: 'Low Volatility',      desc: 'Beta & ATR (defensive)' },
]

function FactorPanel({ fa }: { fa: FactorAnalysis | null | undefined }) {
  if (!fa || !fa.families) return null

  const pctColor = (p: number | null) =>
    p == null ? 'bg-surface-muted'
    : p >= 70 ? 'bg-green-500' : p >= 50 ? 'bg-blue-500'
    : p >= 30 ? 'bg-yellow-500' : 'bg-red-500'

  const compColor = fa.composite >= 65 ? 'text-green-600 dark:text-green-400'
    : fa.composite >= 50 ? 'text-blue-600 dark:text-blue-400'
    : fa.composite >= 35 ? 'text-yellow-600 dark:text-yellow-400'
    : 'text-red-600 dark:text-red-400'

  const crossSectional = fa.basis === 'cross-sectional'

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between px-1">
        <div className="text-xs font-bold text-ink-faint uppercase tracking-widest">Factor Decomposition</div>
        <span
          className="text-[10px] px-2 py-0.5 rounded-full bg-surface-muted text-ink-faint"
          title={crossSectional
            ? `Percentiles are cross-sectional vs ${fa.universe_n ?? '—'} large-caps (as of ${fa.universe_date ?? '—'})`
            : 'Ranked against baseline anchors until the daily universe distribution is recorded'}
        >
          {crossSectional ? `vs universe · n=${fa.universe_n ?? '—'}` : 'baseline'}
        </span>
      </div>
      <div className="bg-surface rounded-xl border border-surface-border p-4">
        {/* Composite + conviction header */}
        <div className="flex items-center justify-between gap-4 mb-4 pb-3 border-b border-surface-border">
          <div>
            <div className="text-xs text-ink-faint uppercase tracking-wider">Composite</div>
            <div className={clsx('text-2xl font-bold', compColor)}>{fa.composite.toFixed(0)}<span className="text-sm text-ink-faint">/100</span></div>
          </div>
          <div className="text-right">
            <div className="text-xs text-ink-faint uppercase tracking-wider">Conviction</div>
            <div className="text-2xl font-bold text-ink">{fa.conviction.toFixed(0)}<span className="text-sm text-ink-faint">%</span></div>
            <div className="text-[10px] text-ink-faint">factor breadth</div>
          </div>
        </div>
        {/* Per-family percentile bars */}
        <div className="space-y-2.5">
          {FACTOR_META.map(({ key, label, desc }) => {
            const fam = fa.families[key]
            const p = fam?.percentile ?? null
            const w = fa.weights?.[key]
            return (
              <div key={key}>
                <div className="flex items-baseline justify-between text-xs mb-1">
                  <span className="font-semibold text-ink" title={desc}>
                    {label}
                    {w != null && <span className="text-ink-faint font-normal ml-1.5">{(w * 100).toFixed(0)}%</span>}
                  </span>
                  <span className={clsx('font-bold', p == null ? 'text-ink-faint' : 'text-ink')}>
                    {p == null ? 'n/a' : `${p.toFixed(0)}${crossSectional ? 'th pct' : ''}`}
                  </span>
                </div>
                <div className="h-2 bg-surface-muted rounded-full overflow-hidden">
                  <div className={clsx('h-full rounded-full transition-all', pctColor(p))} style={{ width: `${p ?? 0}%` }} />
                </div>
              </div>
            )
          })}
        </div>
        <div className="text-[10px] text-ink-faint mt-3 leading-relaxed">
          {crossSectional
            ? 'Each factor is this stock’s percentile rank vs the large-cap universe. High Value + low Momentum/Quality is a classic value trap; high across the board is a leader.'
            : 'Ranked against baseline norms. Run the daily digest to record a live universe distribution for true cross-sectional ranking.'}
        </div>
      </div>
    </div>
  )
}

// ── Financial Health strip (Piotroski, Altman-Z, ROIC, FCF) ───────────────────

function FinancialHealthStrip({ h, inline = false }: { h: FinancialHealth | null | undefined; inline?: boolean }) {
  if (!h) return null
  const has = [h.piotroski, h.altman_z, h.roic, h.fcf_yield, h.fcf_conversion, h.revision_score]
    .some((v) => v != null)
  if (!has) return null

  const chip = (label: string, value: string, tone: 'good' | 'ok' | 'bad' | 'neutral', title: string) => {
    const toneCls =
      tone === 'good' ? 'text-green-700 dark:text-green-400 bg-green-50 dark:bg-green-900/20'
      : tone === 'bad' ? 'text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20'
      : tone === 'ok' ? 'text-yellow-700 dark:text-yellow-400 bg-yellow-50 dark:bg-yellow-900/20'
      : 'text-ink-muted bg-surface-muted'
    return (
      <div key={label} className={clsx('flex flex-col px-3 py-2 rounded-lg', toneCls)} title={title}>
        <span className="text-[10px] uppercase tracking-wider opacity-80">{label}</span>
        <span className="text-sm font-bold">{value}</span>
      </div>
    )
  }

  const chips: React.ReactNode[] = []
  if (h.piotroski != null)
    chips.push(chip('Piotroski', `${h.piotroski}/9`,
      h.piotroski >= 7 ? 'good' : h.piotroski >= 4 ? 'ok' : 'bad',
      '9-point fundamental-strength checklist (profitability, leverage, efficiency)'))
  if (h.altman_z != null)
    chips.push(chip('Altman-Z', h.altman_z.toFixed(1),
      h.altman_z >= 3 ? 'good' : h.altman_z >= 1.8 ? 'ok' : 'bad',
      'Bankruptcy risk: >3 safe, 1.8–3 grey zone, <1.8 distress'))
  if (h.roic != null)
    chips.push(chip('ROIC', `${(h.roic * 100).toFixed(0)}%`,
      (h.roic_excess ?? 0) > 0.05 ? 'good' : (h.roic_excess ?? 0) > 0 ? 'ok' : 'bad',
      'Return on invested capital vs ~9% cost of capital — the test of value creation'))
  if (h.fcf_yield != null)
    chips.push(chip('FCF Yield', `${(h.fcf_yield * 100).toFixed(1)}%`,
      h.fcf_yield > 0.05 ? 'good' : h.fcf_yield > 0.02 ? 'ok' : 'neutral',
      'Free cash flow / market cap — a cleaner cheapness gauge than P/E'))
  if (h.fcf_conversion != null)
    chips.push(chip('FCF Conv.', `${(h.fcf_conversion * 100).toFixed(0)}%`,
      h.fcf_conversion >= 0.8 ? 'good' : h.fcf_conversion >= 0.5 ? 'ok' : 'bad',
      'FCF / net income — are profits real cash or accounting?'))
  if (h.revision_score != null && h.revision_score !== 0)
    chips.push(chip('Revisions', `${h.revision_score > 0 ? '+' : ''}${h.revision_score.toFixed(0)}`,
      h.revision_score > 0 ? 'good' : 'bad',
      'Net analyst upgrades − downgrades (estimate momentum)'))

  if (inline) {
    return <div className="flex flex-wrap gap-2">{chips}</div>
  }
  return (
    <div className="space-y-2">
      <div className="text-xs font-bold text-ink-faint uppercase tracking-widest px-1">Financial Health</div>
      <div className="bg-surface rounded-xl border border-surface-border p-3 flex flex-wrap gap-2">
        {chips}
      </div>
    </div>
  )
}

// ── Decision Summary (consolidated hero) ──────────────────────────────────────

// Plain-English explanations shown via (i) tooltips on the rating.
const COMPOSITE_INFO = 'A single 0–100 rating blending six factors — momentum, quality, value, growth, analyst revisions and low-volatility. 65+ leans Buy, 52–64 Watch, 38–51 Hold, under 38 Sell.'
const CONVICTION_INFO = 'How much to trust the rating — NOT how bullish it is. High only when the six factors agree and the score sits clearly inside a band. Low means the signals conflict, so treat the rating with caution.'
const FACTOR_INFO = "Each bar is this stock's percentile rank on that factor (0–100). Green ≥70 = strong (top tier), blue 50–69 = above average, yellow 30–49 = below average, red under 30 = weak (bottom tier)."

// Plain-English reading of each factor when it's strong (hi) vs weak (lo) —
// turns "Low Volatility 0th pct" into "Very high volatility", etc.
const FACTOR_PLAIN: Record<string, { hi: string; lo: string }> = {
  momentum:  { hi: 'Strong price momentum',   lo: 'Weak / falling momentum' },
  quality:   { hi: 'High-quality business',   lo: 'Poor business quality' },
  value:     { hi: 'Attractively valued',     lo: 'Expensive valuation' },
  growth:    { hi: 'Strong growth',           lo: 'Weak growth' },
  revisions: { hi: 'Analysts turning bullish', lo: 'Analysts turning bearish' },
  low_vol:   { hi: 'Low, stable volatility',  lo: 'Very high volatility' },
}

// Financial-distress detection from the health metrics. Returns human-readable
// reasons; a non-empty list surfaces the ⚠️ warning on the rating.
function distressReasons(h: FinancialHealth | null | undefined): string[] {
  if (!h) return []
  const out: string[] = []
  if (h.altman_z != null && h.altman_z < 1.8)
    out.push(`Altman-Z ${h.altman_z.toFixed(1)} (distress zone, < 1.8)`)
  if (h.piotroski != null && h.piotroski <= 2)
    out.push(`Piotroski ${h.piotroski}/9 (weak fundamentals)`)
  if (h.roic != null && h.roic < 0)
    out.push(`ROIC ${(h.roic * 100).toFixed(0)}% (destroying capital)`)
  if (h.fcf_yield != null && h.fcf_yield < 0)
    out.push(`FCF yield ${(h.fcf_yield * 100).toFixed(1)}% (burning cash)`)
  return out
}

// Shared signal derivation used by the rating hero and analysis panel.
function deriveDecision(result: StockAnalysisResult) {
  const tech = result.technical
  const fa   = result.factor_analysis
  const composite  = fa?.composite ?? tech?.score ?? 50
  const conviction = fa?.conviction ?? tech?.confidence ?? 0
  const signal = composite >= 65 ? 'buy' : composite >= 52 ? 'watch' : composite >= 38 ? 'hold' : 'sell'
  return { composite, conviction, signal }
}

const SIGNAL_LABEL: Record<string, string> = { buy: 'BUY', watch: 'WATCH', hold: 'HOLD', sell: 'SELL' }

// DecisionSummary — the ONLY thing shown up top: the final rating + a one-line
// plain-English takeaway. Everything else lives in collapsible panels below.
function DecisionSummary({ result, onRefresh, currency = '$' }: { result: StockAnalysisResult; onRefresh: () => void; currency?: string }) {
  const tech = result.technical
  const fa   = result.factor_analysis
  const { composite, conviction, signal } = deriveDecision(result)
  const distress = distressReasons(result.financial_health)

  const pill: Record<string, string> = {
    buy: 'bg-green-600 text-white', watch: 'bg-blue-600 text-white',
    hold: 'bg-yellow-500 text-white', sell: 'bg-red-600 text-white',
  }
  const bg: Record<string, string> = {
    buy:   'from-green-50 to-emerald-50 border-green-200 dark:from-green-900/20 dark:to-emerald-900/20 dark:border-green-800',
    watch: 'from-blue-50 to-cyan-50 border-blue-200 dark:from-blue-900/20 dark:to-cyan-900/20 dark:border-blue-800',
    hold:  'from-yellow-50 to-amber-50 border-yellow-200 dark:from-yellow-900/20 dark:to-amber-900/20 dark:border-yellow-800',
    sell:  'from-red-50 to-pink-50 border-red-200 dark:from-red-900/20 dark:to-pink-900/20 dark:border-red-800',
  }
  const convLabel = conviction >= 70 ? 'high conviction' : conviction >= 50 ? 'moderate conviction' : 'low conviction'

  // Split factors into plain-English strengths (top tier) and risks (bottom tier).
  const strengths: string[] = []
  const risks: string[] = []
  if (fa?.families) {
    const ranked = FACTOR_META
      .map(m => ({ key: m.key, p: fa.families[m.key]?.percentile ?? null }))
      .filter((x): x is { key: string; p: number } => x.p != null)
    ranked.filter(x => x.p >= 60).sort((a, b) => b.p - a.p)
      .forEach(x => strengths.push(`${FACTOR_PLAIN[x.key]?.hi ?? x.key} (${x.p.toFixed(0)})`))
    ranked.filter(x => x.p <= 40).sort((a, b) => a.p - b.p)
      .forEach(x => risks.push(`${FACTOR_PLAIN[x.key]?.lo ?? x.key} (${x.p.toFixed(0)})`))
  }
  const distressed = distress.length > 0
  if (distressed) risks.unshift('Financial distress (see below)')

  // One plain-English verdict sentence.
  const convClause = conviction < 50 ? ' Signals conflict, so conviction is low.'
    : conviction >= 70 ? ' The factors broadly agree.' : ''
  const verdict = distressed
    ? `High-risk ${SIGNAL_LABEL[signal]} — a momentum move on a financially distressed company. Treat as speculative only.${convClause}`
    : ({
        buy:   'Attractive across most factors — a genuine leader.',
        watch: 'Constructive, but not decisive yet — worth watching.',
        hold:  'A middling setup with no clear edge either way.',
        sell:  'Weak across the factors — better opportunities elsewhere.',
      } as Record<string, string>)[signal] + convClause

  // Rating gauge: marker position + zone boundaries (Sell<38, Hold<52, Watch<65, Buy).
  const markerPct = Math.max(0, Math.min(100, composite))

  return (
    <div className={clsx('rounded-2xl border bg-gradient-to-r p-5 space-y-4', bg[signal])}>
      {/* Header: ticker / price / company */}
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div className="min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <h2 className="text-2xl font-extrabold text-ink tracking-tight">{result.ticker}</h2>
            {tech?.current_price != null && (
              <span className="text-lg font-bold text-ink">{currency}{tech.current_price.toFixed(2)}</span>
            )}
            {tech?.day_change_pct != null && (
              <span className={clsx('text-sm font-semibold', chgColor(tech.day_change_pct))}>
                {tech.day_change_pct >= 0 ? '+' : ''}{tech.day_change_pct.toFixed(2)}%
              </span>
            )}
          </div>
          {result.company_name && <p className="text-ink-muted text-sm mt-0.5 truncate">{result.company_name}</p>}
          <div className="mt-2 flex items-center gap-3 flex-wrap">
            <WatchlistButton ticker={result.ticker} />
            <CacheBadge result={result} onRefresh={onRefresh} />
          </div>
        </div>
        <div className="text-center shrink-0">
          <span className={clsx('inline-block px-4 py-2 rounded-xl text-lg font-black uppercase tracking-wider', pill[signal])}>
            {SIGNAL_LABEL[signal]}
          </span>
          <div className="flex items-center justify-center gap-1 text-[11px] text-ink-muted mt-1">
            {conviction.toFixed(0)}% · {convLabel} <InfoTooltip text={CONVICTION_INFO} align="right" />
          </div>
        </div>
      </div>

      {/* Verdict sentence — the human takeaway */}
      <p className="text-sm font-medium text-ink leading-snug">{verdict}</p>

      {/* Rating gauge */}
      <div>
        <div className="flex items-center gap-1 text-[10px] text-ink-faint uppercase tracking-wide mb-1">
          Rating {composite.toFixed(0)}/100 <InfoTooltip text={COMPOSITE_INFO} align="left" />
        </div>
        <div className="relative h-2.5 rounded-full bg-gradient-to-r from-red-500 via-yellow-400 to-green-500">
          <div className="absolute -top-1 w-1 bg-ink rounded-full shadow" style={{ left: `calc(${markerPct}% - 2px)`, height: '1.15rem' }} />
        </div>
        <div className="flex justify-between text-[9px] text-ink-faint mt-1">
          <span>Sell</span><span>Hold</span><span>Watch</span><span>Buy</span>
        </div>
      </div>

      {/* Strengths vs Risks — plain English */}
      {(strengths.length > 0 || risks.length > 0) && (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 pt-1">
          <div>
            <div className="text-[10px] font-bold uppercase tracking-wider text-green-600 dark:text-green-400 mb-1.5">✓ Strengths</div>
            {strengths.length ? (
              <ul className="space-y-1">
                {strengths.map((s, i) => <li key={i} className="text-xs text-ink-muted flex gap-1.5"><span className="text-green-500">•</span>{s}</li>)}
              </ul>
            ) : <p className="text-xs text-ink-faint">No standout strengths</p>}
          </div>
          <div>
            <div className="text-[10px] font-bold uppercase tracking-wider text-red-500 dark:text-red-400 mb-1.5">⚠ Risks</div>
            {risks.length ? (
              <ul className="space-y-1">
                {risks.map((r, i) => <li key={i} className="text-xs text-ink-muted flex gap-1.5"><span className="text-red-400">•</span>{r}</li>)}
              </ul>
            ) : <p className="text-xs text-ink-faint">No major red flags</p>}
          </div>
        </div>
      )}

      {/* Financial-distress detail (when flagged) */}
      {distressed && (
        <div className="flex items-start gap-2 rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-300 dark:border-red-700 px-3 py-2 text-xs text-red-700 dark:text-red-300">
          <span className="mt-0.5">⚠️</span>
          <span><strong>Distress signals:</strong> {distress.join(' · ')}</span>
        </div>
      )}
    </div>
  )
}

// AnalysisDetail — factor breakdown + supporting metrics + financial health.
// Lives inside a collapsible panel so the top of the page stays a clean rating.
function AnalysisDetail({ result }: { result: StockAnalysisResult }) {
  const fa = result.factor_analysis
  const rs = result.rs_rating
  const st = result.st_analysis
  const lt = result.lt_analysis
  const pctColor = (p: number | null) =>
    p == null ? 'bg-surface-muted' : p >= 70 ? 'bg-green-500' : p >= 50 ? 'bg-blue-500' : p >= 30 ? 'bg-yellow-500' : 'bg-red-500'

  return (
    <div className="space-y-4">
      {fa?.families && (
        <div>
          <div className="flex items-center justify-between mb-2">
            <span className="flex items-center gap-1 text-xs font-semibold text-ink">
              Factor breakdown <InfoTooltip text={FACTOR_INFO} align="left" />
            </span>
            <span className="text-[10px] text-ink-faint">
              {fa.basis === 'cross-sectional' ? `percentile vs ${fa.universe_n ?? '—'} peers` : 'baseline ranking'}
            </span>
          </div>
          {/* Colour legend */}
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 mb-2 text-[10px] text-ink-faint">
            {[
              { c: 'bg-green-500', t: '≥70 strong' },
              { c: 'bg-blue-500', t: '50–69 above avg' },
              { c: 'bg-yellow-500', t: '30–49 below avg' },
              { c: 'bg-red-500', t: '<30 weak' },
            ].map(({ c, t }) => (
              <span key={t} className="flex items-center gap-1">
                <span className={clsx('w-2.5 h-2.5 rounded-full', c)} />{t}
              </span>
            ))}
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-2">
            {FACTOR_META.map(({ key, label, desc }) => {
              const p = fa.families[key]?.percentile ?? null
              return (
                <div key={key} className="flex items-center gap-2" title={desc}>
                  <span className="text-xs text-ink-muted w-32 shrink-0">{label}</span>
                  <div className="h-2 flex-1 bg-surface-muted rounded-full overflow-hidden">
                    <div className={clsx('h-full rounded-full', pctColor(p))} style={{ width: `${p ?? 0}%` }} />
                  </div>
                  <span className="text-xs font-bold text-ink w-8 text-right">{p == null ? '—' : p.toFixed(0)}</span>
                </div>
              )
            })}
          </div>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-ink-muted">
        {rs && <span>RS <strong className="text-ink">{rs.rs_score}</strong></span>}
        {st && <span>Short-term <strong className="text-ink">{st.score.toFixed(0)}</strong> · {st.signal}</span>}
        {lt && <span>Long-term <strong className="text-ink">{lt.score.toFixed(0)}</strong> · {lt.signal}</span>}
        {result.weekly?.trend_w && <span>Weekly <strong className="text-ink">{result.weekly.trend_w === 'up' ? '↑ up' : '↓ down'}</strong></span>}
      </div>

      <FinancialHealthStrip h={result.financial_health} inline />
    </div>
  )
}

// ── Collapsible section wrapper (progressive disclosure) ──────────────────────

function Section({ title, subtitle, children, defaultOpen = false }: { title: string; subtitle?: string; children: React.ReactNode; defaultOpen?: boolean }) {
  return (
    <details open={defaultOpen} className="group">
      <summary className="flex items-center gap-2 cursor-pointer select-none list-none px-1 py-1.5 text-xs font-bold uppercase tracking-widest text-ink-faint hover:text-ink">
        <span className="text-[10px] transition-transform group-open:rotate-90">▶</span>
        <span>{title}</span>
        {subtitle && <span className="normal-case tracking-normal font-normal text-ink-faint/70">· {subtitle}</span>}
      </summary>
      <div className="mt-2 space-y-4">{children}</div>
    </details>
  )
}

// ── Patterns Panel ────────────────────────────────────────────────────────────

function PatternsPanel({ patterns }: { patterns: TechnicalPattern[] }) {
  if (!patterns.length) return null
  return (
    <div className="bg-surface rounded-xl border border-surface-border p-4">
      <div className="text-sm font-semibold text-ink mb-3">Technical Patterns Detected</div>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        {patterns.map(p => (
          <div key={p.name} className={clsx(
            'rounded-lg border px-3 py-2.5',
            p.signal === 'bullish' ? 'bg-green-50 border-green-200 dark:bg-green-900/20 dark:border-green-700'
            : p.signal === 'bearish' ? 'bg-red-50 border-red-200 dark:bg-red-900/20 dark:border-red-700'
            : 'bg-surface-muted border-surface-border',
          )}>
            <div className="flex items-center gap-2 mb-1">
              <span className="text-base leading-none">
                {p.signal === 'bullish' ? '🟢' : p.signal === 'bearish' ? '🔴' : '⚪'}
              </span>
              <span className={clsx(
                'text-xs font-bold',
                p.signal === 'bullish' ? 'text-green-700 dark:text-green-400'
                : p.signal === 'bearish' ? 'text-red-700 dark:text-red-400'
                : 'text-ink-muted',
              )}>
                {p.name}
              </span>
              <span className={clsx(
                'ml-auto text-[10px] px-1.5 py-0.5 rounded font-medium',
                p.strength === 'strong' ? 'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-400'
                : 'bg-surface-muted text-ink-faint',
              )}>
                {p.strength}
              </span>
            </div>
            <p className="text-xs text-ink-muted leading-snug">{p.description}</p>
          </div>
        ))}
      </div>
    </div>
  )
}

// ── Final Verdict Card ────────────────────────────────────────────────────────

const VC: Record<string, { label: string; color: string; bg: string; icon: string }> = {
  'STRONG BUY': { label: 'STRONG BUY', color: 'text-emerald-700 dark:text-emerald-300', bg: 'bg-emerald-50 dark:bg-emerald-900/25', icon: '🟢' },
  'BUY':        { label: 'BUY',        color: 'text-green-700  dark:text-green-300',    bg: 'bg-green-50  dark:bg-green-900/25',    icon: '🟢' },
  'WATCH':      { label: 'WATCH',      color: 'text-blue-700   dark:text-blue-300',     bg: 'bg-blue-50   dark:bg-blue-900/25',     icon: '🔵' },
  'HOLD':       { label: 'HOLD',       color: 'text-amber-700  dark:text-amber-300',    bg: 'bg-amber-50  dark:bg-amber-900/25',    icon: '🟡' },
  'SELL':       { label: 'SELL',       color: 'text-red-700    dark:text-red-300',      bg: 'bg-red-50    dark:bg-red-900/25',      icon: '🔴' },
}

function FinalVerdictCard({ result, currency = '$' }: { result: StockAnalysisResult; currency?: string }) {
  const [verdict, setVerdict] = useState<Record<string, unknown> | null>(null)
  const [loading, setLoading] = useState(false)
  const [err, setErr]         = useState<string | null>(null)

  const price = result.technical?.current_price ?? 0
  const fmt   = (v: number | null | undefined) =>
    v ? `${currency}${v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : '—'
  const pct   = (v: number | null | undefined, base: number) =>
    v && base ? `${v >= base ? '+' : ''}${((v - base) / base * 100).toFixed(1)}%` : ''

  async function fetchVerdict() {
    setLoading(true); setErr(null); setVerdict(null)
    try {
      const v = await apiGetVerdict(result)
      setVerdict(v)
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Analysis failed'
      setErr(msg)
    } finally {
      setLoading(false)
    }
  }

  if (!result.st_analysis && !result.lt_analysis) return null

  const overall = (verdict?.overall as string) ?? ''
  const oCfg    = VC[overall] ?? null
  const stV     = (verdict?.st_verdict as string) ?? ''
  const ltV     = (verdict?.lt_verdict as string) ?? ''
  const stCfg   = VC[stV] ?? null
  const ltCfg   = VC[ltV] ?? null
  const conv    = (verdict?.conviction as string) ?? ''
  const convColor = conv === 'HIGH' ? 'text-emerald-600' : conv === 'MEDIUM' ? 'text-amber-600' : 'text-red-500'

  return (
    <div className="card overflow-hidden border-2 border-primary/30">
      {/* Header */}
      <div className="bg-gradient-to-r from-slate-800 to-slate-700 px-5 py-4 flex items-center justify-between flex-wrap gap-3">
        <div>
          <div className="text-white font-extrabold text-lg tracking-tight">🎯 Final Verdict — {result.ticker}</div>
          <div className="text-slate-400 text-xs mt-0.5">AI analyses every signal — technical, fundamental, momentum & sentiment — before deciding</div>
        </div>
        {!verdict && (
          <button onClick={fetchVerdict} disabled={loading}
            className="bg-primary hover:bg-primary/90 text-white text-sm font-bold px-5 py-2.5 rounded-xl disabled:opacity-60 flex items-center gap-2">
            {loading ? <><span className="animate-spin">⟳</span> Analysing…</> : '✨ Get AI Verdict'}
          </button>
        )}
        {verdict && oCfg && (
          <div className={`text-lg font-black px-5 py-2 rounded-xl ${oCfg.bg} ${oCfg.color} border border-current/20`}>
            {oCfg.icon} {oCfg.label}
            {conv && <span className={`ml-3 text-xs font-bold uppercase ${convColor}`}>· {conv} conviction</span>}
          </div>
        )}
      </div>

      {err && (
        <div className="p-4 bg-red-50 dark:bg-red-900/20 text-red-600 text-sm">{err}</div>
      )}

      {loading && (
        <div className="p-10 flex flex-col items-center gap-3 text-ink-muted">
          <div className="text-3xl animate-spin">⟳</div>
          <p className="text-sm">Reading every metric carefully — RSI, MACD, fundamentals, analyst consensus, patterns…</p>
        </div>
      )}

      {verdict && (
        <>
          {/* Summary + thesis type + variant perception */}
          {!!(verdict.summary || verdict.thesis_type || verdict.variant_perception) && (
            <div className="px-5 py-4 bg-surface-muted border-b border-surface-border space-y-3">
              {!!verdict.thesis_type && (
                <span className="inline-block text-[11px] font-bold uppercase tracking-wide px-2.5 py-1 rounded-full bg-primary/10 text-primary">
                  {verdict.thesis_type as string}
                </span>
              )}
              {!!verdict.summary && <p className="text-sm text-ink leading-relaxed">{verdict.summary as string}</p>}
              {!!verdict.variant_perception && (
                <div className="border-l-2 border-primary/50 pl-3">
                  <div className="text-[10px] font-bold uppercase tracking-wider text-primary mb-0.5">Variant Perception — the edge</div>
                  <p className="text-xs text-ink-muted leading-relaxed italic">{verdict.variant_perception as string}</p>
                </div>
              )}
            </div>
          )}

          {/* ST + LT columns */}
          <div className="grid grid-cols-1 sm:grid-cols-2 divide-y sm:divide-y-0 sm:divide-x divide-surface-border">
            {/* Short-term */}
            <div className={`p-5 ${stCfg?.bg ?? ''}`}>
              <div className="text-xs font-bold uppercase tracking-widest text-ink-faint mb-2">Short-Term · 1–4 Weeks</div>
              {stCfg && <div className={`text-2xl font-black mb-3 ${stCfg.color}`}>{stCfg.icon} {stCfg.label}</div>}
              {!!verdict.st_reasoning && (
                <p className="text-xs text-ink-muted leading-relaxed mb-3">{verdict.st_reasoning as string}</p>
              )}
              <div className="grid grid-cols-2 gap-2 text-xs">
                <div className="bg-white/60 dark:bg-white/5 rounded-lg p-2.5">
                  <div className="text-ink-faint mb-0.5">4-week target</div>
                  <div className="font-black text-sm text-green-600">{fmt(verdict.st_target as number)}</div>
                  <div className="text-green-600 font-semibold">{pct(verdict.st_target as number, price)}</div>
                </div>
                <div className="bg-red-50 dark:bg-red-900/20 rounded-lg p-2.5">
                  <div className="text-ink-faint mb-0.5">Stop loss</div>
                  <div className="font-black text-sm text-red-600">{fmt(verdict.st_stop as number)}</div>
                  <div className="text-red-500 font-semibold">{pct(verdict.st_stop as number, price)}</div>
                </div>
              </div>
            </div>

            {/* Long-term */}
            <div className={`p-5 ${ltCfg?.bg ?? ''}`}>
              <div className="text-xs font-bold uppercase tracking-widest text-ink-faint mb-2">Long-Term · 3–12 Months</div>
              {ltCfg && <div className={`text-2xl font-black mb-3 ${ltCfg.color}`}>{ltCfg.icon} {ltCfg.label}</div>}
              {!!verdict.lt_reasoning && (
                <p className="text-xs text-ink-muted leading-relaxed mb-3">{verdict.lt_reasoning as string}</p>
              )}
              <div className="grid grid-cols-2 gap-2 text-xs">
                <div className="bg-white/60 dark:bg-white/5 rounded-lg p-2.5">
                  <div className="text-ink-faint mb-0.5">12-month target</div>
                  <div className="font-black text-sm text-green-600">{fmt(verdict.lt_target as number)}</div>
                  <div className="text-green-600 font-semibold">{pct(verdict.lt_target as number, price)}</div>
                </div>
                <div className="bg-amber-50 dark:bg-amber-900/20 rounded-lg p-2.5">
                  <div className="text-ink-faint mb-0.5">Key support</div>
                  <div className="font-black text-sm text-amber-700">{fmt(verdict.lt_support as number)}</div>
                  <div className="text-amber-600 font-semibold">{pct(verdict.lt_support as number, price)}</div>
                </div>
              </div>
            </div>
          </div>

          {/* Catalysts + Risks */}
          <div className="grid grid-cols-1 sm:grid-cols-2 divide-y sm:divide-y-0 sm:divide-x divide-surface-border border-t border-surface-border">
            {Array.isArray(verdict.key_catalysts) && verdict.key_catalysts.length > 0 && (
              <div className="p-4">
                <div className="text-xs font-bold uppercase tracking-wide text-green-600 mb-2">✅ Key Catalysts</div>
                <ul className="space-y-1.5">
                  {(verdict.key_catalysts as string[]).map((c, i) => (
                    <li key={i} className="text-xs text-ink-muted flex gap-1.5"><span className="text-green-500 flex-shrink-0 mt-0.5">▸</span>{c}</li>
                  ))}
                </ul>
              </div>
            )}
            {Array.isArray(verdict.key_risks) && verdict.key_risks.length > 0 && (
              <div className="p-4">
                <div className="text-xs font-bold uppercase tracking-wide text-red-500 mb-2">⚠️ Key Risks</div>
                <ul className="space-y-1.5">
                  {(verdict.key_risks as string[]).map((r, i) => (
                    <li key={i} className="text-xs text-ink-muted flex gap-1.5"><span className="text-red-400 flex-shrink-0 mt-0.5">▸</span>{r}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>

          {/* Invalidation ("what would change my mind") + sell discipline */}
          {(Array.isArray(verdict.invalidation) && verdict.invalidation.length > 0 ||
            Array.isArray(verdict.sell_rules) && verdict.sell_rules.length > 0) && (
            <div className="grid grid-cols-1 sm:grid-cols-2 divide-y sm:divide-y-0 sm:divide-x divide-surface-border border-t border-surface-border">
              {Array.isArray(verdict.invalidation) && verdict.invalidation.length > 0 && (
                <div className="p-4">
                  <div className="text-xs font-bold uppercase tracking-wide text-amber-600 mb-2">🔄 What Would Change My Mind</div>
                  <ul className="space-y-1.5">
                    {(verdict.invalidation as string[]).map((r, i) => (
                      <li key={i} className="text-xs text-ink-muted flex gap-1.5"><span className="text-amber-500 flex-shrink-0 mt-0.5">▸</span>{r}</li>
                    ))}
                  </ul>
                </div>
              )}
              {Array.isArray(verdict.sell_rules) && verdict.sell_rules.length > 0 && (
                <div className="p-4">
                  <div className="text-xs font-bold uppercase tracking-wide text-ink-faint mb-2">🚪 Sell Discipline</div>
                  <ul className="space-y-1.5">
                    {(verdict.sell_rules as string[]).map((r, i) => (
                      <li key={i} className="text-xs text-ink-muted flex gap-1.5"><span className="text-ink-faint flex-shrink-0 mt-0.5">▸</span>{r}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}

          <div className="border-t border-surface-border px-5 py-3 bg-surface-muted flex items-center justify-between flex-wrap gap-2">
            <span className="text-xs text-ink-faint">RS Rating <strong className="text-ink">{result.rs_rating?.rs_score ?? '—'}</strong>/100</span>
            <button onClick={fetchVerdict} className="text-xs text-primary hover:underline">↺ Refresh verdict</button>
            <span className="text-xs text-ink-faint italic">Not financial advice</span>
          </div>
        </>
      )}
    </div>
  )
}

// ── Watchlist Button ──────────────────────────────────────────────────────────

function WatchlistButton({ ticker }: { ticker: string }) {
  const qc = useQueryClient()

  const { data } = useQuery({
    queryKey: ['wl-check', ticker],
    queryFn:  () => apiCheckWatchlist(ticker),
    staleTime: 30_000,
  })

  const inList = data?.in_watchlist ?? false

  const addMut = useMutation({
    mutationFn: () => apiAddToWatchlist(ticker),
    onSuccess:  () => qc.invalidateQueries({ queryKey: ['wl-check', ticker] }),
  })

  const remMut = useMutation({
    mutationFn: () => apiRemoveFromWatchlist(ticker),
    onSuccess:  () => qc.invalidateQueries({ queryKey: ['wl-check', ticker] }),
  })

  const busy = addMut.isPending || remMut.isPending

  return (
    <button
      onClick={() => inList ? remMut.mutate() : addMut.mutate()}
      disabled={busy}
      className={clsx(
        'flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg font-medium border transition-colors disabled:opacity-50',
        inList
          ? 'bg-amber-50 border-amber-300 text-amber-700 hover:bg-red-50 hover:border-red-300 hover:text-red-600 dark:bg-amber-900/20 dark:border-amber-600 dark:text-amber-400'
          : 'bg-surface border-surface-border text-ink-muted hover:border-primary/50 hover:text-primary',
      )}
    >
      {busy ? '…' : inList ? '👁 Watching' : '+ Watchlist'}
    </button>
  )
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export function StockAnalysisPage() {
  const { user } = useAuthStore()
  const isAdmin   = user?.role === 'admin'
  const canUseApi = isAdmin  // AI Deep Dive and Final Verdict are admin-only

  // Pre-fill ticker from URL query param (e.g. /stocks?ticker=AAPL from watchlist)
  const urlParams = new URLSearchParams(typeof window !== 'undefined' ? window.location.search : '')
  const [ticker, setTicker] = useState(urlParams.get('ticker') ?? '')
  const [mode, setMode] = useState<'free' | 'api'>(canUseApi ? 'api' : 'free')
  const [period, setPeriod] = useState<StockAnalysisRequest['time_period']>('3m')
  const [indicators, setIndicators] = useState<IndicatorKey[]>(['rsi', 'macd', 'sma50', 'sma200', 'volume'])
  const [includeNews, setIncludeNews] = useState(true)
  const [includeFundamentals, setIncludeFundamentals] = useState(true)
  const [includePeers, setIncludePeers] = useState(false)
  // Indicator params
  const [rsiPeriod, setRsiPeriod] = useState(14)
  const [bbPeriod, setBbPeriod] = useState(20)
  const [bbStd, setBbStd] = useState(2.0)
  const [macdFast, setMacdFast] = useState(12)
  const [macdSlow, setMacdSlow] = useState(26)
  const [macdSig, setMacdSig] = useState(9)

  const { selectedCountry, selectedExchangeIds, selectCountry: _selectCountry, toggleExchange: _toggleExchange, selectAllExchanges } = useMarketStore()
  const activeExchanges = useActiveExchanges()
  const singleExchange = activeExchanges.length === 1 ? activeExchanges[0] : null
  const currency = selectedCountry?.currency ?? '$'

  function selectCountry(country: typeof selectedCountry) {
    _selectCountry(country)
    setResult(null)
  }

  function toggleExchange(id: string) {
    _toggleExchange(id)
    setResult(null)
  }

  const [isRunning, setIsRunning] = useState(false)
  const [progress, setProgress] = useState<string[]>([])
  const [result, setResult] = useState<StockAnalysisResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const abortRef = useRef(false)

  const [chartPeriod, setChartPeriod] = useState('6mo')
  const { data: priceHistory, isLoading: chartLoading } = useQuery({
    queryKey: ['price-history', ticker, chartPeriod],
    queryFn: () => apiGetPriceHistory(ticker, chartPeriod),
    enabled: !!ticker && ticker.length >= 1,
    staleTime: 1000 * 60 * 15,
  })

  const { data: companySnap } = useQuery({
    queryKey: ['company-snap', ticker],
    queryFn: () => fetchStockSnapshot(ticker.trim().toUpperCase()),
    enabled: !!ticker && ticker.trim().length >= 1,
    staleTime: 1000 * 60 * 60,
    retry: false,
  })

  function toggleIndicator(key: IndicatorKey) {
    setIndicators(prev =>
      prev.includes(key) ? prev.filter(k => k !== key) : [...prev, key],
    )
  }

  async function handleRun(forceRefresh = false) {
    const sym = formatTicker(ticker, activeExchanges)
    if (!sym) return

    setIsRunning(true)
    setProgress([])
    setResult(null)
    setError(null)
    abortRef.current = false

    try {
      const stream = streamStockAnalysis({
        ticker: sym,
        mode,
        time_period: period,
        indicators,
        include_news: includeNews,
        include_fundamentals: includeFundamentals,
        include_peers: includePeers,
        rsi_period: rsiPeriod,
        bb_period: bbPeriod,
        bb_std: bbStd,
        macd_fast: macdFast,
        macd_slow: macdSlow,
        macd_signal_period: macdSig,
        force_refresh: forceRefresh,
      })

      for await (const event of stream) {
        if (abortRef.current) break
        if (event.type === 'progress') {
          setProgress(p => [...p, event.message])
        } else if (event.type === 'result') {
          setResult(event.data)
        } else if (event.type === 'error') {
          setError(event.message)
          break
        } else if (event.type === 'done') {
          break
        }
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Unknown error')
    } finally {
      setIsRunning(false)
    }
  }

  return (
    <div className="min-h-screen bg-canvas">
      <div className="max-w-6xl mx-auto px-3 sm:px-4 py-4 sm:py-6 space-y-4 sm:space-y-6">

        {/* Header */}
        <div>
          <h1 className="text-2xl font-bold text-ink">Stock Analysis</h1>
          <p className="text-sm text-ink-muted mt-0.5">Deep analysis for any stock or ticker — choose your parameters</p>
        </div>

        {/* Config card */}
        <div className="bg-surface rounded-2xl border border-surface-border shadow-sm p-6 space-y-6">

          {/* Market selector */}
          <div className="space-y-2.5">
            {/* Row 1 — country (All Markets + individual countries) */}
            <div>
              <label className="label mb-2">Market</label>
              <div className="flex gap-2 flex-wrap">

                {/* All Markets option */}
                <button
                  onClick={() => selectCountry(null)}
                  disabled={isRunning}
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

                {/* Per-country buttons */}
                {COUNTRIES.map(c => (
                  <button
                    key={c.id}
                    onClick={() => selectCountry(c)}
                    disabled={isRunning}
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
                  No suffix is auto-appended — include the exchange suffix manually if needed (e.g. <code className="bg-surface-muted px-1 rounded">RELIANCE.NS</code>, <code className="bg-surface-muted px-1 rounded">SHEL.L</code>)
                </p>
              )}
            </div>

            {/* Row 2 — exchange multi-select (only when a country is chosen) */}
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
                        disabled={isRunning}
                        title={ex.fullName}
                        className={clsx(
                          'flex items-center gap-1.5 px-2.5 py-1 rounded-md border text-xs font-medium transition-all',
                          isOn
                            ? 'bg-primary/10 text-primary border-primary/40'
                            : 'bg-surface text-ink-faint border-surface-border hover:border-primary/30',
                        )}
                      >
                        <span className={clsx('w-3 h-3 rounded-sm border flex items-center justify-center flex-shrink-0',
                          isOn ? 'bg-primary border-primary' : 'border-ink-faint'
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
                <p className="text-xs text-ink-faint mt-1">
                  {singleExchange
                    ? `${singleExchange.fullName} — suffix ${singleExchange.suffix} auto-appended`
                    : activeExchanges.length > 1
                    ? 'Multiple exchanges — include suffix manually (e.g. RELIANCE.NS) or type ticker only for yfinance default'
                    : ''}
                </p>
              </div>
            )}
          </div>

          {/* Ticker + run */}
          <div className="flex gap-3">
            <div className="flex-1">
              <label className="label">
                Stock Ticker / Symbol
                {singleExchange?.suffix && (
                  <span className="ml-1.5 font-normal text-ink-faint">
                    (suffix <code className="bg-surface-muted px-1 rounded text-xs">{singleExchange.suffix}</code> auto-appended)
                  </span>
                )}
              </label>
              <input
                className="input font-mono text-lg uppercase"
                placeholder={singleExchange ? `e.g. ${singleExchange.examples}` : activeExchanges.length > 0 ? `e.g. ${activeExchanges[0].examples}` : 'e.g. AAPL, RELIANCE.NS, SHEL.L, 7203.T, BHP.AX'}
                value={ticker}
                onChange={e => setTicker(e.target.value.toUpperCase())}
                onKeyDown={e => e.key === 'Enter' && !isRunning && handleRun()}
                disabled={isRunning}
              />
            </div>
            <div className="flex items-end">
              <button
                className={clsx('btn btn-primary h-10 px-6 whitespace-nowrap', isRunning && 'opacity-60 cursor-not-allowed')}
                onClick={isRunning ? () => { abortRef.current = true } : () => handleRun()}
                disabled={!ticker.trim() && !isRunning}
              >
                {isRunning ? (
                  <span className="flex items-center gap-2">
                    <span className="animate-spin h-4 w-4 border-2 border-white border-t-transparent rounded-full" />
                    Stop
                  </span>
                ) : 'Analyze'}
              </button>
            </div>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">

            {/* Analysis mode */}
            <div>
              <label className="label">Analysis Mode</label>
              <div className="flex gap-2">
                {(['free', 'api'] as const).map(m => (
                  <button
                    key={m}
                    disabled={m === 'api' && !canUseApi}
                    onClick={() => setMode(m)}
                    className={clsx(
                      'flex-1 py-2 rounded-lg border text-sm font-medium transition-all',
                      mode === m
                        ? 'bg-blue-600 text-white border-blue-600'
                        : 'bg-surface-muted text-ink-muted border-surface-border hover:border-primary/50',
                      m === 'api' && !canUseApi && 'opacity-40 cursor-not-allowed',
                    )}
                  >
                    {m === 'free' ? 'Free (yfinance)' : '✨ AI Deep Dive'}
                  </button>
                ))}
              </div>
              {!canUseApi && (
                <p className="text-xs text-ink-faint mt-1.5">AI Deep Dive and Final Verdict are available to admin users only</p>
              )}
              {mode === 'api' && canUseApi && (
                <p className="text-xs text-blue-600 mt-1.5">Claude will generate a narrative analysis + Final Verdict with price targets</p>
              )}
            </div>

            {/* Time period */}
            <div>
              <label className="label">Time Period</label>
              <div className="grid grid-cols-3 gap-1.5">
                {PERIOD_OPTIONS.map(({ value, label }) => (
                  <button
                    key={value}
                    onClick={() => setPeriod(value)}
                    className={clsx(
                      'py-1.5 rounded-lg border text-sm font-medium transition-all',
                      period === value
                        ? 'bg-blue-600 text-white border-blue-600'
                        : 'bg-surface-muted text-ink-muted border-surface-border hover:border-primary/50',
                    )}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </div>

            {/* Include options */}
            <div>
              <label className="label">Include in Analysis</label>
              <div className="space-y-2">
                {[
                  { key: 'news',         label: 'News Sentiment',           state: includeNews,         set: setIncludeNews },
                  { key: 'fundamentals', label: 'Fundamentals (P/E, etc.)', state: includeFundamentals, set: setIncludeFundamentals },
                  { key: 'peers',        label: 'Peer Comparison',          state: includePeers,        set: setIncludePeers },
                ].map(({ key, label, state, set }) => (
                  <div key={key} className="flex items-center gap-2">
                    <div
                      onClick={() => set(!state)}
                      className={clsx(
                        'w-8 h-4 rounded-full transition-colors relative cursor-pointer flex-shrink-0',
                        state ? 'bg-blue-600' : 'bg-surface-border',
                      )}
                    >
                      <div className={clsx(
                        'absolute top-0.5 left-0.5 w-3 h-3 bg-surface rounded-full transition-transform',
                        state ? 'translate-x-4' : 'translate-x-0',
                      )} />
                    </div>
                    <span
                      className="text-sm text-ink-muted hover:text-ink cursor-pointer"
                      onClick={() => set(!state)}
                    >
                      {label}
                    </span>
                    <InfoTooltip text={INCLUDE_INFO[key]} />
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* Indicator selection */}
          <div>
            <label className="label">Technical Indicators</label>
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-2">
              {INDICATOR_OPTIONS.map(({ key, label, desc }) => {
                const active = indicators.includes(key)
                const paramTag =
                  key === 'rsi' && active ? ` (${rsiPeriod})` :
                  key === 'bollinger' && active ? ` (${bbPeriod}, ${bbStd}σ)` :
                  key === 'macd' && active ? ` (${macdFast}/${macdSlow}/${macdSig})` : ''
                return (
                  <button
                    key={key}
                    onClick={() => toggleIndicator(key)}
                    className={clsx(
                      'text-left px-3 py-2 rounded-lg border text-sm transition-all',
                      active
                        ? 'bg-blue-50 text-blue-700 border-blue-300 font-medium'
                        : 'bg-surface-muted text-ink-muted border-surface-border hover:border-surface-border hover:text-ink',
                    )}
                  >
                    <div className="flex items-center gap-1.5">
                      <span className={clsx('w-2 h-2 rounded-full flex-shrink-0', active ? 'bg-blue-500' : 'bg-ink-faint')} />
                      <span className="flex-1 min-w-0">
                        {label}<span className="text-xs font-normal opacity-70">{paramTag}</span>
                      </span>
                      <InfoTooltip text={desc} side="top" align="right" />
                    </div>
                  </button>
                )
              })}
            </div>
            <p className="text-xs text-ink-faint mt-1.5">
              {indicators.length === 0 ? 'No indicators selected — only price data will be shown' : `${indicators.length} indicator${indicators.length > 1 ? 's' : ''} selected`}
            </p>
          </div>

          {/* Indicator parameter settings — only shown when configurable indicators are active */}
          {(indicators.includes('rsi') || indicators.includes('macd') || indicators.includes('bollinger')) && (
            <div>
              <label className="label">Indicator Settings</label>
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">

                {indicators.includes('rsi') && (
                  <div className="bg-surface-muted rounded-xl border border-surface-border p-3">
                    <div className="flex items-center gap-1.5 text-xs font-semibold text-ink-muted mb-2">
                      RSI Period
                      <InfoTooltip
                        text="Shorter periods (7–9) react faster to price changes but generate more noise. Wilder's original standard is 14. Use 21 for smoother, more reliable signals on longer timeframes."
                        align="left"
                      />
                    </div>
                    <div className="flex gap-1.5">
                      {[7, 9, 14, 21].map(p => (
                        <button key={p} onClick={() => setRsiPeriod(p)}
                          className={clsx('flex-1 py-1.5 rounded-lg text-xs font-medium border transition-all',
                            rsiPeriod === p
                              ? 'bg-blue-600 text-white border-blue-600'
                              : 'bg-surface text-ink-muted border-surface-border hover:border-primary/50',
                          )}
                        >{p}</button>
                      ))}
                    </div>
                    <p className="text-xs text-ink-faint mt-1.5">
                      {rsiPeriod === 7 ? 'Short-term, more sensitive' : rsiPeriod === 9 ? 'Fast signals' : rsiPeriod === 14 ? 'Standard (Wilder)' : 'Smoother, fewer signals'}
                    </p>
                  </div>
                )}

                {indicators.includes('bollinger') && (
                  <div className="bg-surface-muted rounded-xl border border-surface-border p-3 space-y-2">
                    <div className="flex items-center gap-1.5 text-xs font-semibold text-ink-muted">
                      Bollinger Bands
                      <InfoTooltip
                        text="Bollinger Bands = SMA ± (N × standard deviation). Period controls the SMA length; std deviations control band width. Wider bands (2.5–3σ) catch only extreme moves; tighter bands (1.5σ) give more frequent signals."
                        align="left"
                      />
                    </div>
                    <div>
                      <div className="text-xs text-ink-faint mb-1">Period</div>
                      <div className="flex gap-1.5">
                        {[10, 20, 50].map(p => (
                          <button key={p} onClick={() => setBbPeriod(p)}
                            className={clsx('flex-1 py-1 rounded-lg text-xs font-medium border transition-all',
                              bbPeriod === p
                                ? 'bg-blue-600 text-white border-blue-600'
                                : 'bg-surface text-ink-muted border-surface-border hover:border-primary/50',
                            )}
                          >{p}</button>
                        ))}
                      </div>
                    </div>
                    <div>
                      <div className="flex items-center gap-1 text-xs text-ink-faint mb-1">
                        Std Deviations (band width)
                        <InfoTooltip
                          text="2σ covers ~95% of price action statistically. Use 1.5σ for more frequent signals (noisier); use 2.5–3σ to flag only the most extreme overbought/oversold conditions."
                          side="bottom"
                          align="left"
                        />
                      </div>
                      <div className="flex gap-1.5">
                        {[1.5, 2.0, 2.5, 3.0].map(s => (
                          <button key={s} onClick={() => setBbStd(s)}
                            className={clsx('flex-1 py-1 rounded-lg text-xs font-medium border transition-all',
                              bbStd === s
                                ? 'bg-blue-600 text-white border-blue-600'
                                : 'bg-surface text-ink-muted border-surface-border hover:border-primary/50',
                            )}
                          >{s}</button>
                        ))}
                      </div>
                    </div>
                  </div>
                )}

                {indicators.includes('macd') && (
                  <div className="bg-surface-muted rounded-xl border border-surface-border p-3">
                    <div className="flex items-center gap-1.5 text-xs font-semibold text-ink-muted mb-2">
                      MACD Preset
                      <InfoTooltip
                        text="Fast/Slow/Signal periods. Standard (12/26/9) works for most daily charts. Faster (8/17/9) reacts quicker but has more false signals. Slower (21/55/13) is better for weekly swing trades."
                        align="left"
                      />
                    </div>
                    <div className="space-y-1.5">
                      {MACD_PRESETS.map(preset => (
                        <button key={preset.label}
                          onClick={() => { setMacdFast(preset.fast); setMacdSlow(preset.slow); setMacdSig(preset.sig) }}
                          className={clsx(
                            'w-full text-left px-2.5 py-1.5 rounded-lg text-xs font-medium border transition-all',
                            macdFast === preset.fast && macdSlow === preset.slow && macdSig === preset.sig
                              ? 'bg-blue-600 text-white border-blue-600'
                              : 'bg-surface text-ink-muted border-surface-border hover:border-primary/50',
                          )}
                        >{preset.label}</button>
                      ))}
                    </div>
                  </div>
                )}

              </div>
            </div>
          )}
        </div>

        {/* Progress */}
        {isRunning && progress.length > 0 && (
          <div className="bg-slate-900 rounded-xl p-4">
            <div className="flex items-center gap-2 mb-2">
              <span className="w-2 h-2 rounded-full bg-green-400 animate-pulse" />
              <span className="text-xs font-mono text-green-400">ANALYZING</span>
            </div>
            {progress.map((msg, i) => (
              <div key={i} className="text-xs font-mono text-slate-300 py-0.5">
                {'>'} {msg}
              </div>
            ))}
          </div>
        )}

        {/* Error */}
        {error && (
          <div className="bg-red-50 border border-red-200 rounded-xl p-4 text-sm text-red-700">
            <span className="font-semibold">Error: </span>{error}
          </div>
        )}

        {/* Company brief card — shown as soon as snapshot data loads */}
        {companySnap && (companySnap as any).company_name && (
          <div className="card p-5">
            <div className="flex items-start justify-between gap-4 flex-wrap">
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-lg font-extrabold text-ink">{(companySnap as any).company_name}</span>
                  <span className="text-sm text-ink-faint font-mono">{ticker.toUpperCase()}</span>
                  {(companySnap as any).sector && (
                    <span className="text-xs px-2 py-0.5 rounded-full bg-primary/10 text-primary font-medium">
                      {(companySnap as any).sector}
                    </span>
                  )}
                  {(companySnap as any).industry && (
                    <span className="text-xs px-2 py-0.5 rounded-full bg-surface-muted text-ink-muted font-medium">
                      {(companySnap as any).industry}
                    </span>
                  )}
                </div>

                {(companySnap as any).description && (
                  <p className="text-sm text-ink-muted mt-2 leading-relaxed line-clamp-4">
                    {(companySnap as any).description}
                  </p>
                )}
              </div>

              {/* Key stats */}
              <div className="flex flex-col gap-1.5 text-xs text-right flex-shrink-0">
                {(companySnap as any).market_cap && (
                  <div>
                    <span className="text-ink-faint">Market Cap </span>
                    <span className="font-semibold text-ink">
                      {(companySnap as any).market_cap >= 1e12
                        ? `$${((companySnap as any).market_cap / 1e12).toFixed(2)}T`
                        : (companySnap as any).market_cap >= 1e9
                        ? `$${((companySnap as any).market_cap / 1e9).toFixed(1)}B`
                        : `$${((companySnap as any).market_cap / 1e6).toFixed(0)}M`}
                    </span>
                  </div>
                )}
                {(companySnap as any).employees && (
                  <div>
                    <span className="text-ink-faint">Employees </span>
                    <span className="font-semibold text-ink">{Number((companySnap as any).employees).toLocaleString()}</span>
                  </div>
                )}
                {(companySnap as any).website && (
                  <a href={(companySnap as any).website} target="_blank" rel="noopener noreferrer"
                    className="text-primary hover:underline">
                    {(companySnap as any).website.replace(/^https?:\/\/(www\.)?/, '')}
                  </a>
                )}
              </div>
            </div>
          </div>
        )}

        {/* Price history chart — shown whenever a ticker is entered */}
        {priceHistory?.data && priceHistory.data.length > 0 && (
          <div className="card p-5">
            <div className="flex items-center justify-between mb-4 flex-wrap gap-2">
              <h3 className="font-semibold text-ink text-sm">{ticker} Price Chart</h3>
              <div className="flex gap-1">
                {(['1mo','3mo','6mo','1y','2y'].map(p => (
                  <button key={p} onClick={() => setChartPeriod(p)}
                    className={clsx('px-2.5 py-1 text-xs font-medium rounded-lg transition-colors',
                      chartPeriod === p ? 'bg-primary text-white' : 'text-ink-muted hover:text-ink bg-surface-muted')}>
                    {p}
                  </button>
                )))}
              </div>
            </div>

            {(() => {
              const data = priceHistory.data
              const first = data[0]?.close ?? 0
              const last  = data[data.length - 1]?.close ?? 0
              const isUp  = last >= first
              const minC  = Math.min(...data.map(d => d.close ?? 0))
              const maxC  = Math.max(...data.map(d => d.close ?? 0))
              const pad   = (maxC - minC) * 0.05

              return (
                <>
                  <div className="flex items-baseline gap-3 mb-3">
                    <span className="text-2xl font-bold text-ink">${(last as number).toFixed(2)}</span>
                    <span className={clsx('text-sm font-semibold', isUp ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400')}>
                      {isUp ? '+' : ''}{(((last as number) - (first as number)) / (first as number) * 100).toFixed(2)}% ({chartPeriod})
                    </span>
                  </div>
                  <ResponsiveContainer width="100%" height={220}>
                    <LineChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
                      <XAxis dataKey="date"
                        tickFormatter={(d: string) => d.slice(5)}
                        tick={{ fontSize: 10, fill: 'var(--color-ink-faint)' }}
                        tickLine={false} axisLine={false}
                        interval={Math.floor(data.length / 6)} />
                      <YAxis
                        domain={[minC - pad, maxC + pad]}
                        tick={{ fontSize: 10, fill: 'var(--color-ink-faint)' }}
                        tickLine={false} axisLine={false}
                        tickFormatter={(v: number) => `$${v.toFixed(0)}`}
                        width={52} />
                      <Tooltip
                        contentStyle={{ background: 'var(--color-surface)', border: '1px solid var(--color-surface-border)', borderRadius: 8, fontSize: 12 }}
                        labelStyle={{ color: 'var(--color-ink-muted)' }}
                        formatter={(v) => [`$${Number(v).toFixed(2)}`, 'Close']} />
                      <ReferenceLine y={first as number} stroke="var(--color-ink-faint)" strokeDasharray="4 4" strokeWidth={1} />
                      <Line type="monotone" dataKey="close"
                        stroke={isUp ? '#22c55e' : '#ef4444'}
                        strokeWidth={1.5} dot={false} activeDot={{ r: 3 }} />
                    </LineChart>
                  </ResponsiveContainer>
                </>
              )
            })()}
          </div>
        )}
        {chartLoading && ticker && (
          <div className="card p-4 text-center text-ink-muted text-sm">Loading chart…</div>
        )}

        {/* Results */}
        {result && !result.error && (
          <div className="space-y-4">
            {/* Regulatory disclaimer */}
            <div className="flex items-start gap-2.5 bg-amber-50 border border-amber-200 rounded-xl px-4 py-3 dark:bg-amber-900/20 dark:border-amber-700">
              <span className="text-amber-500 text-base leading-none mt-0.5 flex-shrink-0">⚠</span>
              <p className="text-xs text-amber-800 dark:text-amber-300 leading-relaxed">
                <strong>Not investment advice.</strong> This analysis is generated by AI using publicly available market data
                and is provided for <strong>informational and research purposes only</strong>. It does not constitute a
                recommendation to buy, sell, or hold any security. Market data may be delayed up to 15 minutes.
                Always consult a qualified financial advisor before making investment decisions.
              </p>
            </div>

            {/* Final decision rating — the one thing shown up top. */}
            <DecisionSummary result={result} onRefresh={() => handleRun(true)} currency={currency} />

            {/* Analysis — factor breakdown, metrics & health (collapsed by default) */}
            {(result.factor_analysis || result.financial_health || result.rs_rating) && (
              <Section title="Analysis" subtitle="factor breakdown, metrics & financial health">
                <AnalysisDetail result={result} />
              </Section>
            )}

            {/* Final Verdict — admin-only AI judgement with price targets */}
            {isAdmin && (result.st_analysis || result.lt_analysis) && (
              <FinalVerdictCard result={result} currency={currency} />
            )}

            {/* Price history chart */}
            <StockChartPanel
              ticker={result.ticker}
              period={result.time_period}
              indicators={result.requested_indicators}
              eps={result.fundamentals?.eps}
              currency={currency}
            />

            {/* Technical detail — collapsed by default (progressive disclosure) */}
            <Section title="Technical detail" subtitle="indicators, patterns, regime & sizing">
            {/* Technical */}
            {result.technical && (
              <TechnicalPanel
                tech={result.technical}
                requested={result.requested_indicators}
                rsiPeriod={rsiPeriod}
                macdFast={macdFast}
                macdSlow={macdSlow}
                macdSig={macdSig}
                bbPeriod={bbPeriod}
                bbStd={bbStd}
                currency={currency}
              />
            )}

            {/* Technical Patterns */}
            {result.patterns && result.patterns.length > 0 && (
              <PatternsPanel patterns={result.patterns} />
            )}

            {/* Regime banner */}
            {result.regime && result.regime.regime && (() => {
              const r = result.regime
              const cls =
                r.regime === 'BULL'    ? 'bg-green-50  border-green-200  text-green-800  dark:bg-green-900/20  dark:border-green-700  dark:text-green-300'  :
                r.regime === 'BEAR'    ? 'bg-orange-50 border-orange-200 text-orange-800 dark:bg-orange-900/20 dark:border-orange-700 dark:text-orange-300' :
                r.regime === 'CRISIS'  ? 'bg-red-50    border-red-200    text-red-800    dark:bg-red-900/20    dark:border-red-700    dark:text-red-300'    :
                                         'bg-yellow-50 border-yellow-200 text-yellow-800 dark:bg-yellow-900/20 dark:border-yellow-700 dark:text-yellow-300'
              const icon = r.regime === 'BULL' ? '🟢' : r.regime === 'BEAR' ? '🟠' : r.regime === 'CRISIS' ? '🔴' : '🟡'
              return (
                <div className={`flex items-start gap-3 rounded-xl border px-4 py-3 text-sm ${cls}`}>
                  <span className="text-base leading-none mt-0.5">{icon}</span>
                  <div className="flex-1 min-w-0">
                    <span className="font-bold mr-2">Market Regime: {r.regime}</span>
                    <span className="opacity-80 text-xs">{r.description}</span>
                    <span className="ml-2 opacity-60 text-xs">
                      · Score multiplier {r.score_multiplier}×
                      {result.technical?.raw_score != null && result.technical.raw_score !== result.technical.score &&
                        ` (raw ${result.technical.raw_score.toFixed(0)} → ${result.technical.score.toFixed(0)})`}
                    </span>
                  </div>
                </div>
              )
            })()}

            {/* Position sizing */}
            {result.position_size && result.technical?.current_price && (() => {
              const ps = result.position_size
              const price = result.technical!.current_price!
              return (
                <div className="bg-surface rounded-xl border border-surface-border p-4">
                  <div className="text-sm font-semibold text-ink mb-3">Position Sizing (ATR-based, $100k portfolio)</div>
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                    {[
                      { label: 'Size',       value: `${ps.size_pct.toFixed(2)}%`, sub: `~$${ps.dollar_size.toLocaleString()}` },
                      { label: 'Shares',     value: ps.shares.toString(),         sub: `at $${price.toFixed(2)}` },
                      { label: 'Stop Loss',  value: `$${ps.stop_price.toFixed(2)}`, sub: `${ps.stop_loss_pct.toFixed(2)}% below entry` },
                      { label: 'Risk Budget',value: `$${ps.risk_budget_usd}`,     sub: `ATR ${ps.atr_pct.toFixed(2)}% of price` },
                    ].map(({ label, value, sub }) => (
                      <div key={label} className="bg-surface-muted rounded-lg p-3 text-center">
                        <div className="text-xs text-ink-faint mb-1">{label}</div>
                        <div className="font-bold text-ink text-sm">{value}</div>
                        <div className="text-xs text-ink-muted mt-0.5">{sub}</div>
                      </div>
                    ))}
                  </div>
                  <p className="text-xs text-ink-faint mt-2">Stop = 1.5 × ATR below entry · Size adjusted for score confidence and market regime</p>
                </div>
              )
            })()}
            </Section>

            {/* Analyst consensus — full width, prominent placement */}
            {result.analyst && (result.analyst.recommendation || result.analyst.target_mean) && (
              <AnalystPanel
                analyst={result.analyst}
                currentPrice={result.technical?.current_price ?? null}
                currency={currency}
              />
            )}

            {/* Fundamentals, ownership & filings — collapsed reference detail */}
            <Section title="Fundamentals, ownership & filings" subtitle="statements, holders, SEC filings, corporate actions">
            {/* Corporate Actions */}
            {result.fundamentals && (() => {
              const f = result.fundamentals!
              const isReverse = f.last_split_type === 'reverse'
              const isForward = f.last_split_type === 'forward'
              const splitLabel = f.last_split_date
                ? isForward
                  ? `${f.last_split_ratio}:1 Forward Split`
                  : `1:${f.last_split_ratio != null ? (1 / f.last_split_ratio).toFixed(0) : '?'} Reverse Split`
                : null
              return (
                <div className="bg-surface rounded-xl border border-surface-border p-4">
                  <div className="text-sm font-semibold text-ink mb-3">Corporate Actions (Past 5 Years)</div>
                  {isReverse && (
                    <div className="flex items-center gap-2 bg-red-50 dark:bg-red-900/20 border border-red-300 dark:border-red-700 rounded-lg px-3 py-2 mb-3 text-xs text-red-800 dark:text-red-300">
                      <span>⚠</span>
                      <span>Reverse split detected — often signals prior financial distress or low share price rescue</span>
                    </div>
                  )}
                  {f.upcoming_split_date && (
                    <div className="flex items-center gap-2 bg-blue-50 dark:bg-blue-900/20 border border-blue-300 dark:border-blue-700 rounded-lg px-3 py-2 mb-3 text-xs text-blue-800 dark:text-blue-300">
                      <span>✂</span>
                      <span>Stock split announced — effective {f.upcoming_split_date}</span>
                    </div>
                  )}
                  {f.last_split_date || f.upcoming_split_date ? (
                    <div className="divide-y divide-surface-border/60">
                      {f.last_split_date && (
                        <div className="flex justify-between items-center py-2">
                          <span className="text-sm text-ink-muted">Last Split</span>
                          <span className={`text-sm font-semibold ${isReverse ? 'text-red-500' : 'text-green-600'}`}>
                            {splitLabel} · {f.last_split_date}
                          </span>
                        </div>
                      )}
                      {f.upcoming_split_date && (
                        <div className="flex justify-between items-center py-2">
                          <span className="text-sm text-ink-muted">Upcoming Split</span>
                          <span className="text-sm font-semibold text-blue-600">{f.upcoming_split_date}</span>
                        </div>
                      )}
                    </div>
                  ) : (
                    <div className="flex items-center gap-2 text-sm text-green-600">
                      <span>✓</span>
                      <span>No splits in the past 5 years</span>
                    </div>
                  )}
                </div>
              )
            })()}

            {/* Volume Trend */}
            {result.technical?.vol_trend_pct != null && (() => {
              const t = result.technical!
              const signalLabel =
                t.vol_signal === 'accumulation' ? 'Institutional Buying' :
                t.vol_signal === 'distribution' ? 'Institutional Selling' :
                t.vol_signal === 'contraction'  ? 'Volume Declining' : 'Neutral'
              const signalColor =
                t.vol_signal === 'accumulation' ? 'text-green-600' :
                t.vol_signal === 'distribution' ? 'text-red-500'  :
                t.vol_signal === 'contraction'  ? 'text-amber-500' : 'text-ink-muted'
              const trendColor =
                t.vol_trend_pct! > 0 ? 'text-green-600' : 'text-red-500'
              return (
                <div className="bg-surface rounded-xl border border-surface-border p-4">
                  <div className="text-sm font-semibold text-ink mb-3">Volume Trend (30d vs Prior 30d)</div>
                  {t.vol_signal === 'accumulation' && (
                    <div className="flex items-center gap-2 bg-green-50 dark:bg-green-900/20 border border-green-300 dark:border-green-700 rounded-lg px-3 py-2 mb-3 text-xs text-green-800 dark:text-green-300">
                      <span>↑</span>
                      <span>Volume expanding on price gains — suggests institutional accumulation</span>
                    </div>
                  )}
                  {t.vol_signal === 'distribution' && (
                    <div className="flex items-center gap-2 bg-red-50 dark:bg-red-900/20 border border-red-300 dark:border-red-700 rounded-lg px-3 py-2 mb-3 text-xs text-red-800 dark:text-red-300">
                      <span>↓</span>
                      <span>Volume expanding on price weakness — suggests institutional distribution / selling</span>
                    </div>
                  )}
                  <div className="divide-y divide-surface-border/60">
                    <div className="flex justify-between items-center py-2">
                      <span className="text-sm text-ink-muted">30d Volume Change</span>
                      <span className={`text-sm font-semibold ${trendColor}`}>
                        {t.vol_trend_pct! > 0 ? '+' : ''}{t.vol_trend_pct!.toFixed(1)}%
                      </span>
                    </div>
                    <div className="flex justify-between items-center py-2">
                      <span className="text-sm text-ink-muted">Signal</span>
                      <span className={`text-sm font-semibold ${signalColor}`}>{signalLabel}</span>
                    </div>
                    {t.vol_30d_avg != null && (
                      <div className="flex justify-between items-center py-2">
                        <span className="text-sm text-ink-muted">Recent Avg (30d)</span>
                        <span className="text-sm font-semibold text-ink">
                          {t.vol_30d_avg >= 1e6 ? `${(t.vol_30d_avg / 1e6).toFixed(1)}M` : t.vol_30d_avg.toLocaleString()}
                        </span>
                      </div>
                    )}
                    {t.vol_prior_avg != null && (
                      <div className="flex justify-between items-center py-2">
                        <span className="text-sm text-ink-muted">Prior Avg (30d)</span>
                        <span className="text-sm font-semibold text-ink">
                          {t.vol_prior_avg >= 1e6 ? `${(t.vol_prior_avg / 1e6).toFixed(1)}M` : t.vol_prior_avg.toLocaleString()}
                        </span>
                      </div>
                    )}
                  </div>
                </div>
              )
            })()}

            {/* Institutional Ownership */}
            {result.institutional && (() => {
              const inst = result.institutional!
              const sig = inst.top10_signal
              return (
                <div className="bg-surface rounded-xl border border-surface-border p-4">
                  <div className="text-sm font-semibold text-ink mb-3">Institutional Ownership</div>

                  {/* Summary banner */}
                  {sig && sig !== 'mixed' && (
                    <div className={`flex items-center gap-2 rounded-lg px-3 py-2 mb-3 text-xs border ${
                      sig === 'buying'
                        ? 'bg-green-50 dark:bg-green-900/20 border-green-300 dark:border-green-700 text-green-800 dark:text-green-300'
                        : 'bg-red-50 dark:bg-red-900/20 border-red-300 dark:border-red-700 text-red-800 dark:text-red-300'
                    }`}>
                      <span>{sig === 'buying' ? '↑' : '↓'}</span>
                      <span>
                        {sig === 'buying'
                          ? `${inst.top10_buyers} of top 10 holders increased position last quarter`
                          : `${inst.top10_sellers} of top 10 holders reduced position last quarter`}
                      </span>
                    </div>
                  )}

                  {/* Stats row */}
                  <div className="divide-y divide-surface-border/60 mb-3">
                    {inst.inst_pct_held != null && (
                      <div className="flex justify-between items-center py-2">
                        <span className="text-sm text-ink-muted">Institutions Hold</span>
                        <span className="text-sm font-semibold text-ink">{(inst.inst_pct_held * 100).toFixed(1)}%</span>
                      </div>
                    )}
                    {inst.insider_pct_held != null && (
                      <div className="flex justify-between items-center py-2">
                        <span className="text-sm text-ink-muted">Insider Hold</span>
                        <span className="text-sm font-semibold text-ink">{(inst.insider_pct_held * 100).toFixed(1)}%</span>
                      </div>
                    )}
                    {inst.inst_count != null && (
                      <div className="flex justify-between items-center py-2">
                        <span className="text-sm text-ink-muted">Institution Count</span>
                        <span className="text-sm font-semibold text-ink">{inst.inst_count.toLocaleString()}</span>
                      </div>
                    )}
                    {inst.top10_buyers != null && (
                      <div className="flex justify-between items-center py-2">
                        <span className="text-sm text-ink-muted">Top 10 — Last Quarter</span>
                        <span className="text-sm font-semibold">
                          <span className="text-green-600">{inst.top10_buyers} buying</span>
                          <span className="text-ink-muted mx-1">·</span>
                          <span className="text-red-500">{inst.top10_sellers} selling</span>
                        </span>
                      </div>
                    )}
                  </div>

                  {/* Top holders table */}
                  {inst.top_holders?.length > 0 && (
                    <div className="overflow-x-auto">
                      <table className="w-full text-xs">
                        <thead>
                          <tr className="text-ink-faint border-b border-surface-border">
                            <th className="text-left py-1.5 font-medium">Holder</th>
                            <th className="text-right py-1.5 font-medium">% Held</th>
                            <th className="text-right py-1.5 font-medium">Shares</th>
                            <th className="text-right py-1.5 font-medium">Q Change</th>
                          </tr>
                        </thead>
                        <tbody>
                          {inst.top_holders.map((h, i) => (
                            <tr key={i} className="border-b border-surface-border/40 last:border-0">
                              <td className="py-1.5 text-ink-muted max-w-[160px] truncate pr-2">{h.holder}</td>
                              <td className="py-1.5 text-right text-ink">{h.pct_held != null ? `${h.pct_held.toFixed(2)}%` : '—'}</td>
                              <td className="py-1.5 text-right text-ink">
                                {h.shares != null ? (h.shares >= 1e6 ? `${(h.shares / 1e6).toFixed(1)}M` : h.shares.toLocaleString()) : '—'}
                              </td>
                              <td className={`py-1.5 text-right font-semibold ${h.pct_change == null ? 'text-ink-faint' : h.pct_change > 0 ? 'text-green-600' : h.pct_change < 0 ? 'text-red-500' : 'text-ink-muted'}`}>
                                {h.pct_change != null ? `${h.pct_change > 0 ? '+' : ''}${h.pct_change.toFixed(1)}%` : '—'}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              )
            })()}

            {/* SEC EDGAR Insider Activity */}
            {(() => {
              const summary = (result.sec_insider_summary && 'buy_count' in result.sec_insider_summary)
                ? result.sec_insider_summary : null
              const txns    = result.sec_insider_transactions ?? []
              const filings = result.sec_recent_filings ?? []
              if (!summary && txns.length === 0 && filings.length === 0) return null
              const sigLabel: Record<string, string> = {
                strong_buy: 'Strong Buy Signal', buy: 'Buy Signal',
                neutral: 'Neutral', weak_sell: 'Sell Signal', sell: 'Strong Sell Signal',
              }
              const sigColor: Record<string, string> = {
                strong_buy: 'text-green-600', buy: 'text-green-500',
                neutral: 'text-ink-muted', weak_sell: 'text-red-400', sell: 'text-red-600',
              }
              const sig = summary?.signal ?? 'neutral'
              return (
                <div className="bg-surface rounded-xl border border-surface-border p-4 space-y-4">
                  <div className="text-sm font-semibold text-ink">SEC EDGAR — Insider Activity (Form 4)</div>

                  {summary && (
                    <div className="divide-y divide-surface-border/60">
                      <div className="flex justify-between items-center py-2">
                        <span className="text-sm text-ink-muted">Signal (90d)</span>
                        <span className={`text-sm font-bold ${sigColor[sig] ?? 'text-ink-muted'}`}>{sigLabel[sig] ?? sig}</span>
                      </div>
                      <div className="flex justify-between items-center py-2">
                        <span className="text-sm text-ink-muted">Open-Market Buys</span>
                        <span className="text-sm font-semibold text-green-600">
                          {summary.buy_count} txn · {summary.buy_shares >= 1e6 ? `${(summary.buy_shares / 1e6).toFixed(2)}M` : summary.buy_shares.toLocaleString()} sh
                        </span>
                      </div>
                      <div className="flex justify-between items-center py-2">
                        <span className="text-sm text-ink-muted">Open-Market Sales</span>
                        <span className="text-sm font-semibold text-red-500">
                          {summary.sell_count} txn · {summary.sell_shares >= 1e6 ? `${(summary.sell_shares / 1e6).toFixed(2)}M` : summary.sell_shares.toLocaleString()} sh
                        </span>
                      </div>
                      <div className="flex justify-between items-center py-2">
                        <span className="text-sm text-ink-muted">Net Shares (90d)</span>
                        <span className={`text-sm font-bold ${summary.net_shares >= 0 ? 'text-green-600' : 'text-red-500'}`}>
                          {summary.net_shares >= 0 ? '+' : ''}{summary.net_shares >= 1e6 ? `${(summary.net_shares / 1e6).toFixed(2)}M` : summary.net_shares.toLocaleString()}
                        </span>
                      </div>
                    </div>
                  )}

                  {txns.length > 0 && (
                    <div>
                      <div className="text-xs font-semibold text-ink-muted uppercase tracking-wide mb-2">Recent Form 4 Transactions</div>
                      <div className="overflow-x-auto">
                        <table className="w-full text-xs">
                          <thead>
                            <tr className="text-ink-faint border-b border-surface-border">
                              <th className="text-left py-1.5 font-medium pr-2">Date</th>
                              <th className="text-left py-1.5 font-medium pr-2">Owner</th>
                              <th className="text-left py-1.5 font-medium pr-2">Role</th>
                              <th className="text-left py-1.5 font-medium pr-2">Type</th>
                              <th className="text-right py-1.5 font-medium pr-2">Shares</th>
                              <th className="text-right py-1.5 font-medium">Value</th>
                            </tr>
                          </thead>
                          <tbody>
                            {txns.slice(0, 10).map((t: SecInsiderTransaction, i: number) => (
                              <tr key={i} className="border-b border-surface-border/40 last:border-0">
                                <td className="py-1.5 text-ink-muted pr-2 whitespace-nowrap">{t.date}</td>
                                <td className="py-1.5 text-ink pr-2 max-w-[120px] truncate">{t.owner}</td>
                                <td className="py-1.5 text-ink-muted pr-2 max-w-[80px] truncate">{t.role}</td>
                                <td className={`py-1.5 font-semibold pr-2 ${t.code === 'P' ? 'text-green-600' : t.code === 'S' ? 'text-red-500' : 'text-ink-muted'}`}>
                                  {t.type}
                                </td>
                                <td className="py-1.5 text-right text-ink pr-2">
                                  {t.shares >= 1e6 ? `${(t.shares / 1e6).toFixed(2)}M` : t.shares.toLocaleString()}
                                </td>
                                <td className="py-1.5 text-right text-ink">
                                  {t.value != null ? (t.value >= 1e6 ? `$${(t.value / 1e6).toFixed(2)}M` : `$${Math.round(t.value).toLocaleString()}`) : '—'}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  )}

                  {filings.length > 0 && (
                    <div>
                      <div className="text-xs font-semibold text-ink-muted uppercase tracking-wide mb-2">Recent SEC Filings</div>
                      <div className="space-y-1.5">
                        {filings.map((f: SecRecentFiling, i: number) => (
                          <div key={i} className="flex items-center gap-3 py-1.5 border-b border-surface-border/40 last:border-0">
                            <span className="text-xs font-bold bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300 px-1.5 py-0.5 rounded">{f.form}</span>
                            <span className="text-xs text-ink-muted whitespace-nowrap">{f.date}</span>
                            {f.description && <span className="text-xs text-ink truncate">{f.description}</span>}
                            <a href={f.url} target="_blank" rel="noopener noreferrer"
                              className="ml-auto text-xs text-blue-600 hover:text-blue-800 whitespace-nowrap flex-shrink-0">
                              View ↗
                            </a>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )
            })()}

            {/* Fundamentals + AI side by side on large screens */}
            {(result.fundamentals || result.ai_analysis) && (
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                {result.fundamentals && <FundamentalsPanel fund={result.fundamentals} currency={currency} />}
                {result.ai_analysis  && <AIAnalysisPanel  text={result.ai_analysis}  />}
              </div>
            )}
            </Section>

            {/* Stock chatbot */}
            <StockChatPanel result={result} currency={currency} />
          </div>
        )}

        {/* Idle state */}
        {!isRunning && !result && !error && (
          <div className="text-center py-16 text-ink-faint">
            <div className="text-5xl mb-4">{selectedCountry ? selectedCountry.flag : '🌐'}</div>
            <div className="text-lg font-medium text-ink-muted">Enter a ticker to start analysis</div>
            <div className="text-sm mt-1">
              {selectedCountry && activeExchanges.length > 0
                ? `${selectedCountry.name} · ${activeExchanges.map(e => e.name).join(', ')} · e.g. ${activeExchanges[0].examples}`
                : 'All markets — AAPL, RELIANCE.NS, SHEL.L, 7203.T, BHP.AX'}
            </div>
          </div>
        )}

      </div>
    </div>
  )
}
