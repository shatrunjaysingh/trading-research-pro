export type Role = 'admin' | 'analyst' | 'trader' | 'viewer'
export type LicenseTier = 'free' | 'professional' | 'enterprise'
export type ResearchMode = 'free' | 'api'

export interface User {
  id: number
  email: string
  username: string
  full_name: string | null
  role: Role
  is_active: boolean
  license_id: number | null
  license_tier: LicenseTier | null
  license_name: string | null
  allowed_modes: ResearchMode[] | null
  allowed_sectors: string[] | 'all' | null
  max_picks: number | null
  can_email: boolean | null
  can_export: boolean | null
  can_admin: boolean | null
  must_change_pwd: boolean
  created_at: string | null
  last_login: string | null
}

export interface License {
  id: number
  name: string
  tier: LicenseTier
  max_users: number
  allowed_modes: string
  allowed_sectors: string
  max_picks: number
  can_email: boolean
  can_export: boolean
  can_admin: boolean
  expires_at: string | null
  is_active: boolean
  created_at: string | null
  user_count: number
}

export interface AuditEntry {
  id: number
  user_id: number | null
  username: string | null
  action: string | null
  details: string | null
  ip_address: string | null
  created_at: string | null
}

export interface ResearchConfig {
  available_modes: ResearchMode[]
  available_sectors: string[]
  max_picks: number
  default_top_n: number
  sector_labels: Record<string, string>
}

export interface FreePick {
  ticker: string
  type: string
  current_price: number
  day_change_pct: number
  vol_ratio: number
  pos_52w: number
  score: number
  signal: string
  confidence?: number
  dividend_yield?: number | null
  why_picked?: string
  // Technical indicators
  rsi?: number | null
  macd?: number | null
  macd_signal?: number | null
  macd_hist?: number | null
  sma20?: number | null
  sma50?: number | null
  sma200?: number | null
  bb_upper?: number | null
  bb_lower?: number | null
  bb_mid?: number | null
  vwap?: number | null
  atr?: number | null
  atr_pct?: number | null
  // Momentum returns
  qtr_change_pct?: number | null
  month_change_pct?: number | null
  week_change_pct?: number | null
  // Analyst consensus
  analyst_target?: number | null
  analyst_upside_pct?: number | null
  analyst_consensus?: string | null
  num_analysts?: number | null
  analyst_ratings?: AnalystRating[]
  // Insider / institutional
  insider_net_shares?: number | null
  inst_pct_held?: number | null
  inst_top_holders?: { holder: string; pct_held: number | null; pct_change: number | null }[]
  inst_top10_buyers?: number | null
  inst_top10_sellers?: number | null
  inst_top10_signal?: string | null
  // Earnings
  earnings_flag?: string | null
  earnings_days_out?: number | null
  earnings_penalty?: number | null
  // Corporate actions
  last_split_date?: string | null
  last_split_ratio?: number | null
  last_split_type?: string | null
  upcoming_split_date?: string | null
  split_score_adj?: number | null
  // Volume trend
  vol_30d_avg?: number | null
  vol_prior_avg?: number | null
  vol_trend_pct?: number | null
  vol_signal?: string | null
  // SEC EDGAR insider data
  sec_insider_summary?: SecInsiderSummary | null
  sec_recent_filings?: SecRecentFiling[]
}

export interface PriceBar {
  date: string
  open: number | null
  high: number | null
  low: number | null
  close: number | null
  volume: number
}

export interface StockHistory {
  ticker: string
  period: string
  interval: string
  bars: PriceBar[]
}

export interface ApiPick {
  rank: number
  ticker: string
  company_name?: string
  current_price: number | string
  day_change_pct: number
  week_change_pct?: number
  score: number | string
  confidence_pct?: number
  signal: string
  why_picked?: string
  key_catalyst?: string
  sector_tailwind?: string
  technical_analysis?: string
  fundamental_snapshot?: string
  analyst_sentiment?: string
  news_summary?: string
  news_sentiment?: string
  suggested_entry?: number | string
  target_price?: number | string
  stop_loss?: number | string
  upside_pct?: number
  time_horizon?: string
  risk_factors?: string[]
  why_its_cheap?: string
  business_viability?: string
  financial_health?: string
}

export interface ApiSectionData {
  date?: string
  market_summary?: string
  avoid_today?: string[]
  avoid_reason?: string
  top_picks: ApiPick[]
}

export type SectionData = FreePick[] | ApiSectionData

export interface Section {
  label: string
  mode: ResearchMode
  sector: string
  data: SectionData
}

export type SSEEvent =
  | { type: 'progress'; message: string }
  | { type: 'section';  section: Section }
  | { type: 'done' }
  | { type: 'error';   message: string }

// ── Market Overview ───────────────────────────────────────────────────────────

export interface MarketTicker {
  symbol: string
  name: string
  category: 'index' | 'sector' | 'commodity' | 'crypto'
  price: number | null
  change: number | null
  change_pct: number | null
  prev_close: number | null
  open: number | null
  day_high: number | null
  day_low: number | null
  high_52w: number | null
  low_52w: number | null
  pos_52w: number | null
}

export interface MarketOverview {
  as_of: string
  market_open: boolean
  indices: MarketTicker[]
  sectors: MarketTicker[]
  commodities: MarketTicker[]
  crypto: MarketTicker[]
}

// ── Stock Analysis ────────────────────────────────────────────────────────────

export interface PickSnapshot {
  ticker: string
  company_name: string | null
  sector: string | null
  industry: string | null
  website: string | null
  description: string | null
  current_price: number | null
  high_52w: number | null
  low_52w: number | null
  market_cap: number | null
  pe_ratio: number | null
  forward_pe: number | null
  eps: number | null
  revenue: number | null
  profit_margin: number | null
  debt_to_equity: number | null
  current_ratio: number | null
  return_on_equity: number | null
  dividend_yield: number | null
  beta: number | null
  recommendation: string | null
  recommendation_key: string | null
  recommendation_mean: number | null
  num_analysts: number | null
  target_mean: number | null
  target_median: number | null
  target_high: number | null
  target_low: number | null
  upside_pct: number | null
}

export interface StockAnalysisRequest {
  ticker: string
  mode: 'free' | 'api'
  time_period: '1d' | '1w' | '1m' | '3m' | '6m' | '1y'
  indicators: IndicatorKey[]
  include_news: boolean
  include_fundamentals: boolean
  include_peers: boolean
  // Indicator calculation parameters
  rsi_period?: number
  bb_period?: number
  bb_std?: number
  macd_fast?: number
  macd_slow?: number
  macd_signal_period?: number
  force_refresh?: boolean
}

export type IndicatorKey = 'rsi' | 'macd' | 'sma20' | 'sma50' | 'sma200' | 'bollinger' | 'volume'

export interface TechnicalSnapshot {
  current_price: number | null
  prev_close: number | null
  day_change_pct: number | null
  week_change_pct: number | null
  month_change_pct: number | null
  high_52w: number | null
  low_52w: number | null
  pos_52w_pct: number | null
  avg_volume: number | null
  last_volume: number | null
  vol_ratio: number | null
  vol_30d_avg?: number | null
  vol_prior_avg?: number | null
  vol_trend_pct?: number | null
  vol_signal?: string | null
  rsi: number | null
  macd: number | null
  macd_signal: number | null
  macd_hist: number | null
  sma20: number | null
  sma50: number | null
  sma200: number | null
  bb_upper: number | null
  bb_lower: number | null
  bb_mid: number | null
  vwap: number | null
  atr: number | null
  atr_pct: number | null
  signal: string
  score: number
  raw_score?: number
  regime_multiplier?: number
  confidence: number
}

export interface FundamentalSnapshot {
  company_name: string | null
  sector: string | null
  industry: string | null
  market_cap: number | null
  pe_ratio: number | null
  forward_pe: number | null
  eps: number | null
  forward_eps: number | null
  eps_growth: number | null
  revenue: number | null
  revenue_growth: number | null
  profit_margin: number | null
  debt_to_equity: number | null
  current_ratio: number | null
  return_on_equity: number | null
  dividend_yield: number | null
  beta: number | null
  short_pct_float: number | null
  short_ratio: number | null
  eps_surprise_pct: number | null
  last_split_date?: string | null
  last_split_ratio?: number | null
  last_split_type?: string | null
  upcoming_split_date?: string | null
}

export interface PositionSize {
  size_pct: number
  dollar_size: number
  shares: number
  stop_price: number
  stop_loss_pct: number
  atr_pct: number
  risk_budget_usd: number
}

export interface MarketRegime {
  regime: string
  vix: number
  spy_price: number
  spy_vs_sma50: number
  spy_vs_sma200: number
  score_multiplier: number
  color: string
  description: string
  updated_at: string
}

export interface LiveQuote {
  ticker: string
  price: number | null
  change_pct: number | null
  volume: number | null
  vwap: number | null
  open: number | null
  high: number | null
  low: number | null
}

export interface AnalystRating {
  date: string
  firm: string
  to_grade: string
  from_grade: string | null
  action: string   // up | down | main | init | reit
}

export interface AnalystSnapshot {
  recommendation: string | null
  recommendation_key: string | null
  recommendation_mean: number | null   // 1 = Strong Buy … 5 = Strong Sell
  num_analysts: number | null
  target_mean: number | null
  target_median: number | null
  target_high: number | null
  target_low: number | null
  upside_pct: number | null
  ratings?: AnalystRating[]
}

export interface SecInsiderTransaction {
  date: string
  filed_date: string
  owner: string
  role: string
  code: string
  type: string
  shares: number
  price: number | null
  value: number | null
}

export interface SecInsiderSummary {
  buy_count: number
  sell_count: number
  buy_shares: number
  sell_shares: number
  net_shares: number
  signal: 'strong_buy' | 'buy' | 'neutral' | 'weak_sell' | 'sell'
}

export interface SecRecentFiling {
  form: string
  date: string
  description: string
  url: string
}

export interface InstitutionalHolder {
  holder: string
  shares: number | null
  pct_held: number | null
  value: number | null
  pct_change: number | null
  date: string | null
}

export interface InstitutionalSnapshot {
  inst_pct_held: number | null
  inst_float_pct: number | null
  inst_count: number | null
  insider_pct_held: number | null
  top_holders: InstitutionalHolder[]
  top10_buyers: number | null
  top10_sellers: number | null
  top10_signal: 'buying' | 'selling' | 'mixed' | null
}

export interface StockAnalysisResult {
  ticker: string
  company_name: string | null
  mode: string
  time_period: string
  technical: TechnicalSnapshot | null
  fundamentals: FundamentalSnapshot | null
  analyst: AnalystSnapshot | null
  institutional: InstitutionalSnapshot | null
  sec_insider_transactions?: SecInsiderTransaction[]
  sec_insider_summary?: SecInsiderSummary | null
  sec_recent_filings?: SecRecentFiling[]
  ai_analysis: string | null
  news_summary: string | null
  peer_comparison: Record<string, unknown>[] | null
  requested_indicators: string[]
  error: string | null
  cached?: boolean
  cached_at?: string | null
  cache_age_seconds?: number | null
  position_size?: PositionSize | null
  regime?: MarketRegime | null
}

export type StockSSEEvent =
  | { type: 'progress'; message: string }
  | { type: 'result';   data: StockAnalysisResult }
  | { type: 'done' }
  | { type: 'error';    message: string }
