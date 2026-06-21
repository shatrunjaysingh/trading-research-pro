# TradingResearch Pro — Research & Analysis Reference

**Last updated:** 2026-06-20  
**Applies to:** `research.py`, `backend/services/stock_analyzer.py`, `sentiment.py`, `backend/services/regime_detector.py`

---

## Table of Contents

1. [Overview — Two Analysis Paths](#1-overview)
2. [Market Regime Detection](#2-market-regime-detection)
3. [Technical Indicators](#3-technical-indicators)
4. [Fundamental Factors](#4-fundamental-factors)
5. [Sentiment Factors](#5-sentiment-factors)
6. [Insider & Institutional Data](#6-insider--institutional-data)
7. [Analyst Consensus](#7-analyst-consensus)
8. [Earnings Calendar Awareness](#8-earnings-calendar-awareness)
9. [Composite Scoring (Research — Free Mode)](#9-composite-scoring-research--free-mode)
10. [AI Prompts](#10-ai-prompts)

---

## 1. Overview

The app has two distinct analysis paths that share some data sources but serve different purposes:

| Feature | Path | Mode | Purpose |
|---|---|---|---|
| **Research** | `research.py` | Free (yfinance) or API (Claude) | Rank a universe of assets by opportunity score, generate daily picks |
| **Stock Analysis** | `backend/services/stock_analyzer.py` | Always uses Claude | Deep single-stock analysis with AI narrative |

Both paths use the same technical indicator math. Since the recent update, Research computes and displays the same named indicators (RSI, MACD, Bollinger, SMA, VWAP, ATR) that Stock Analysis shows.

---

## 2. Market Regime Detection

**File:** `backend/services/regime_detector.py`  
**Data sources:** VIX (`^VIX`), SPY — fetched daily, cached 1 hour  
**Used by:** Both Research scoring and Stock Analysis AI prompt

The regime classifier sets a **score multiplier** applied to every asset's composite score.

| Regime | Condition | Multiplier | Effect |
|---|---|---|---|
| **BULL** | VIX ≤ 18 AND SPY > SMA50 by >1% AND > SMA200 by >5% | 1.10× | Scores boosted 10% |
| **NEUTRAL** | Default (mixed signals) | 1.00× | No adjustment |
| **BEAR** | VIX ≥ 25 OR (SPY < SMA50 by 3% AND < SMA200 by 5%) | 0.75× | Scores dampened 25% |
| **CRISIS** | VIX ≥ 35 OR (VIX ≥ 28 AND deep drawdown) | 0.60× | Scores dampened 40% |

The regime also informs the AI narrative in Stock Analysis ("favour tight stops in this environment").

---

## 3. Technical Indicators

### 3a. Research (Free Mode) — `research.py`

Computed inside `_score_asset()` from 3-month daily OHLCV history fetched via yfinance. All values are included in the research output and shown in the email HTML under each pick.

| Indicator | Parameters | Notes |
|---|---|---|
| **RSI** | Period: 14 | < 30 = oversold (green), > 70 = overbought (red) |
| **MACD** | Fast: 12, Slow: 26, Signal: 9 | Line, signal line, histogram |
| **SMA 20** | 20-day simple moving average | Short-term trend |
| **SMA 50** | 50-day simple moving average | Medium-term trend; 🟢 if price above, 🔴 below |
| **SMA 200** | 200-day simple moving average | Long-term trend; `null` if < 200 days of history |
| **Bollinger Bands** | Period: 20, Std dev: 2× | Upper, lower, mid band |
| **VWAP** | Across full 3-month window | Volume-Weighted Average Price; 🟢 if price above |
| **ATR** | Period: 14 | Average True Range; shown as % of price (volatility proxy) |

These same indicators are also **injected into the Claude API prompt** via `_build_technical_context()` so the AI has the quantitative data to reason from when doing deep research.

### 3b. Stock Analysis — `backend/services/stock_analyzer.py`

Computed from user-selected time period (1d/1w/1m/3m/6m/1y) and interval. All parameters are user-configurable from the UI.

| Indicator | Default Parameters | User-configurable |
|---|---|---|
| **RSI** | Period: 14 | Yes — RSI period |
| **MACD** | Fast: 12, Slow: 26, Signal: 9 | Yes — all three periods |
| **SMA 20** | 20-day | No (fixed) |
| **SMA 50** | 50-day | No (fixed) |
| **SMA 200** | 200-day | No (fixed) |
| **Bollinger Bands** | Period: 20, Std: 2.0 | Yes — period and std multiplier |
| **VWAP** | Full selected period | No (always computed) |
| **ATR** | Period: 14 | No (fixed) |

#### Technical Signal Score (Stock Analysis)

The Stock Analysis service also derives a signal and score from the indicators:

| Indicator | Bullish condition | Score impact |
|---|---|---|
| RSI < 30 (oversold) | Yes | +15 |
| RSI < 45 | Yes | +7 |
| RSI > 70 (overbought) | No | −15 |
| RSI > 55 | No | −5 |
| MACD > Signal line | Yes | +10 |
| MACD < Signal line | No | −10 |
| Price > SMA 50 | Yes | +8 |
| Price < SMA 50 | No | −8 |
| Price > SMA 200 | Yes | +7 |
| Price < SMA 200 | No | −7 |
| Day change > 0 | Proportional | ±up to 10 |
| Volume ratio > 1.5× | Yes | +5 |
| Price < Bollinger Lower | Oversold bounce | Vote only |
| Price > Bollinger Upper | Overbought reversal | Vote only |
| Price > VWAP | Yes | +6 |
| Price < VWAP | No | −4 |

**Final signal:** BUY (score ≥ 65) / WATCH (52–64) / HOLD (38–51) / SELL (< 38)  
**Confidence:** % of active indicator votes aligned with the final signal direction

---

## 4. Fundamental Factors

### 4a. Research Scoring

Fetched from `yfinance Ticker.info` for each asset.

| Factor | Field | How used in scoring |
|---|---|---|
| Forward EPS | `forwardEps` vs `trailingEps` | EPS growth sub-score |
| Earnings Growth | `earningsGrowth` | Fallback if EPS not available |
| Revenue Growth | `revenueGrowth` | Part of earnings quality score |
| EPS Surprise | Latest from `earnings_history` | Beat(+) / miss(−) vs analyst estimate |
| Short % of Float | `shortPercentOfFloat` | Short squeeze or bearish signal |
| Short Ratio | `shortRatio` | Days to cover |
| Sector | `sector` | Used for sector ETF relative strength |

**Earnings quality sub-score (0–100):**  
`50% × EPS beat/miss + 30% × EPS growth + 20% × revenue growth`

**Short interest sub-score:**
- > 15% short + price rising → squeeze setup (score 70–92) 🔥
- > 30% short + price falling → confirmed short thesis (score 22)
- > 20% short, no direction → headwind (score 40)

### 4b. Stock Analysis Fundamentals

| Field | Description |
|---|---|
| Company name, sector, industry | Identity |
| Market cap | Size classification |
| P/E ratio (trailing & forward) | Valuation |
| EPS (trailing & forward) | Earnings power |
| EPS growth (fwd vs trailing) | Growth trajectory |
| EPS surprise (last quarter) | Beat / miss vs consensus |
| Revenue & revenue growth (YoY) | Top-line momentum |
| Profit margin | Profitability |
| Debt-to-equity | Balance sheet risk |
| Current ratio | Liquidity |
| Return on equity (ROE) | Capital efficiency |
| Dividend yield | Income |
| Beta | Market correlation / volatility |
| Short % of float + short ratio | Short interest |

---

## 5. Sentiment Factors

**File:** `sentiment.py`  
**Cache:** 30 minutes in-process  
**Used by:** Research scoring (5% weight) and injected into API research prompts

### Sources

| Source | Type | API | What it provides |
|---|---|---|---|
| **StockTwits** | Per-ticker | Public, no key | Bullish/bearish message counts (last 30 msgs) |
| **CNN Fear & Greed** | Macro (stocks) | Public, no key | Score 0–100; cached per session |
| **Alternative.me Crypto F&G** | Macro (crypto) | Public, no key | Score 0–100; used for crypto assets only |
| **Reddit** | Per-ticker | OAuth (optional) | Post count + bull/bear keyword ratio across WSB, stocks, investing, StockMarket, pennystocks, cryptocurrency |

Reddit is only active when `REDDIT_CLIENT_ID` and `REDDIT_CLIENT_SECRET` are set in `.env`.

### Sentiment Score Blending

| Data available | Formula |
|---|---|
| StockTwits + Fear&Greed + Reddit | 50% ST + 35% F&G + 15% Reddit |
| StockTwits + Fear&Greed (no Reddit) | 60% ST + 40% F&G |
| Fear&Greed only | 100% F&G |

**Output labels:** Bullish (≥65) / Leaning Bullish (55–64) / Neutral (45–54) / Leaning Bearish (35–44) / Bearish (<35)

---

## 6. Insider & Institutional Data

**Source:** yfinance `Ticker.insider_transactions` (SEC Form 4) + `Ticker.major_holders`  
**Lookback:** Last 90 days  
**Weight in composite:** 5%  
**Asset types:** Stocks only (skipped for crypto)

### Insider Transaction Score (0–100)

| Net shares bought (last 90 days) | Score | Interpretation |
|---|---|---|
| > 100,000 | 85 | Strong insider buying signal |
| 20,001 – 100,000 | 70 | Moderate buying |
| 1 – 20,000 | 58 | Slight buying |
| 0 (neutral) | 50 | No notable activity |
| −1 to −50,000 | 42 | Slight selling |
| −50,001 to −200,000 | 33 | Moderate selling |
| < −200,000 | 22 | Heavy selling — red flag |

"Automatic" sales (Rule 10b5-1 plans) are excluded from the sell count.

### Institutional Ownership Bonus

| Institutional ownership | Score bonus |
|---|---|
| > 75% | +8 points |
| 50%–75% | +4 points |
| < 50% | No adjustment |

High institutional ownership confirms that professional investors have conviction in the stock.

---

## 7. Analyst Consensus

**Source:** yfinance `Ticker.info`  
**Fields:** `targetMeanPrice`, `recommendationMean` (1=Strong Buy → 5=Sell), `numberOfAnalystOpinions`  
**Weight in composite:** 10%  
**Minimum analysts for score activation:** 2

### Analyst Score Calculation (0–100)

```
price_score    = clamp(50 + analyst_upside_pct × 1.5,  0, 100)
rec_score      = clamp(100 − (recommendationMean − 1) × 22.5, 0, 100)
reliability    = min(num_analysts / 8, 1.0)
analyst_score  = (price_score × 0.5 + rec_score × 0.5) × reliability
               + 50 × (1 − reliability)
```

The `reliability` factor scales from 0 to 1 as analyst count goes from 0 to 8+, so a single analyst opinion doesn't dominate the score.

### Recommendation Scale

| recommendationMean | Label | rec_score |
|---|---|---|
| 1.0 | Strong Buy | 100 |
| 1.5 | Buy | 88.75 |
| 2.0 | Buy | 77.5 |
| 2.5 | Hold | 66.25 |
| 3.0 | Hold | 55 |
| 3.5 | Underperform | 33.75 |
| 4.0 | Underperform | 22.5 |
| 5.0 | Sell | 0 |

---

## 8. Earnings Calendar Awareness

**Source:** yfinance `Ticker.calendar`  
**Lookback:** Next 7 days  
**Applied as:** Score penalty after composite is computed

Stocks with imminent earnings are flagged and penalised because the outcome is binary and unpredictable — holding into earnings is a speculation, not an analysis-based trade.

| Days to earnings | Score penalty | Display |
|---|---|---|
| 0–1 day | −15 points | ⚠ Earnings tomorrow |
| 2–3 days | −10 points | ⚠ Earnings in X days |
| 4–7 days | −5 points | ⚠ Earnings this week |
| > 7 days | 0 | (no flag) |

The penalty is applied **after** the regime multiplier: `score = composite × regime_multiplier − earnings_penalty`

---

## 9. Composite Scoring (Research — Free Mode)

**Function:** `_score_asset()` in `research.py`  
**Scale:** 0–100  
**Signal thresholds:** BUY ≥ 65 / WATCH 45–64 / HOLD < 45

### Sub-scores (all normalised to 0–100)

| Sub-score | Formula |
|---|---|
| mom_1d | `day_change_pct × 5 + 50` |
| mom_1w | `week_change_pct × 3 + 50` |
| mom_1m | `month_change_pct × 2 + 50` |
| mom_3m | `qtr_change_pct × 1.5 + 50` |
| vol_scr | `min(vol_ratio × 40, 100)` |
| pos_scr | `52w_position × 100` (0 = at 52w low, 100 = at 52w high) |
| rs_spy | `(qtr_change − SPY_3m) × 2 + 50` |
| rs_sector | `(qtr_change − sector_ETF_3m) × 2 + 50` |
| earn_qual_scr | `EPS_beat×0.5 + EPS_growth×0.3 + rev_growth×0.2` |
| short_scr | See squeeze / bearish / headwind logic above |
| sent_scr | From `sentiment.py` (0–100) |
| analyst_score | See Section 7 |
| insider_score | See Section 6 |

### Composite Weights

| Factor | Weight |
|---|---|
| 3-month momentum | 18% |
| 1-month momentum | 14% |
| 1-week momentum | 9% |
| 1-day change | 2% |
| Volume surge | 9% |
| Relative strength vs SPY | 7% |
| Relative strength vs sector ETF | 7% |
| 52-week position | 3% |
| Earnings quality | 7% |
| Short interest / squeeze | 4% |
| Social sentiment | 5% |
| **Analyst consensus + price target** | **10%** |
| **Insider / institutional signal** | **5%** |
| **Total** | **100%** |

### Confidence Score

Percentage of sub-scores above 50 (i.e. how many factors agree the asset is above average):  
`confidence = count(sub_score > 50) / total_sub_scores × 100`

---

## 10. AI Prompts

### 10a. Research — Simple Dual-Category Prompt (`SYSTEM_PROMPT`)

Used in `run_api()` for the "All Stocks + Penny Stocks" report mode.

```
You are a quantitative trading analyst. Research a given universe
of stocks and cryptocurrencies using live market data and news, then rank them by
short-term opportunity score for today.

IMPORTANT QUALITY BAR: Only include picks where you have 90%+ confidence in the
opportunity. Prefer returning fewer than 5 picks over including a low-conviction one.
Return EXACTLY 5 picks (or fewer if not enough qualify at 90%+ confidence).

For each asset, research ALL of the following:
1. Price momentum, volume vs 30-day average, and today's % change.
2. News sentiment from the last 48 hours.
3. Analyst consensus: current buy/hold/sell ratings and mean price target.
4. Earnings calendar: flag any earnings within the next 7 days (high event risk).
5. Insider activity: any notable Form 4 insider purchases or sales in the last 30 days.
6. Institutional ownership: is it rising or falling (13F signals)?
7. Technical signals and upcoming catalysts (earnings, macro events, sector rotation).

Penalise stocks reporting earnings within 3 days — reduce confidence accordingly.
Treat recent insider buying as a strong positive signal; heavy selling as a red flag.

Respond ONLY with a JSON object:
{
  "date": "YYYY-MM-DD",
  "market_summary": "2-3 sentence market overview",
  "top_picks": [
    {
      "rank": 1,
      "ticker": "NVDA",
      "asset_type": "stock",
      "current_price": 135.42,
      "day_change_pct": 2.3,
      "score": 92,
      "confidence_pct": 94,
      "signal": "BUY",
      "reasoning": "...",
      "key_catalyst": "...",
      "analyst_sentiment": "e.g. '18 Buy, 5 Hold, 0 Sell — consensus target $240'",
      "insider_activity": "e.g. 'CEO bought 50,000 shares on 2026-06-10' or 'No notable activity'",
      "earnings_warning": "e.g. 'Reports 2026-06-22 — hold until after' or null",
      "suggested_entry": 134.00,
      "target_price": 160.00,
      "stop_loss": 125.00,
      "time_horizon": "2-4 weeks",
      "risk_note": "..."
    }
  ],
  "avoid_today": ["TICKER1"],
  "avoid_reason": "brief explanation"
}
Signal: BUY | HOLD | WATCH. Score: 0-100 (only include if score >= 90). Rank by score descending.
```

---

### 10b. Research — Penny / Cheap Stock Prompt (`CHEAP_STOCK_SYSTEM_PROMPT`)

Used in `run_api()` for penny stocks (price < $5).

```
You are a small-cap stock analyst specialising in
low-price, high-potential equities (under $5). Your job is to identify stocks that
are currently cheap but have strong future growth potential — NOT just momentum plays.

IMPORTANT QUALITY BAR: Only include picks where you have 90%+ confidence in the
opportunity. Prefer returning fewer than 5 picks over including a low-conviction one.
Return EXACTLY 5 picks (or fewer if not enough qualify at 90%+ confidence).

For each stock consider:
- Business model: is the company solving a real problem with a viable path to profitability?
- Catalysts: upcoming earnings, product launches, FDA approvals, contracts, partnerships
- Financial health: debt levels, cash runway, recent revenue trend (growing or shrinking?)
- News sentiment: any recent positive developments in the last 7 days?
- Insider/institutional activity: any notable buying?
- Risk: why is it cheap? Is the risk temporary (sector downturn, short-term loss) or structural (dying business)?

Only recommend stocks where the upside potential clearly outweighs the risk.
Avoid pure penny-stock pumps, companies with no revenue, or stocks in terminal decline.

JSON output includes: score, confidence_pct, signal, reasoning, key_catalyst,
suggested_entry, target_price, time_horizon, risk_note
```

---

### 10c. Research — Sector Deep Research Prompt (`DEEP_RESEARCH_PROMPT_TEMPLATE`)

Used in `run_sector_api()` for sector-by-sector analysis (Technology, Pharma, Energy, etc.).

```
You are a senior equity research analyst at a top-tier investment fund.
Conduct rigorous, data-driven research on the {sector} assets provided.

SECTOR FOCUS
{sector_guidance}   ← tailored per sector (see below)

RESEARCH PROCESS — execute ALL steps via web search:
1. Fetch live price, today's % change, volume vs 30-day average, and 52-week range.
2. Search news from the last 7 days for each ticker.
3. Check analyst ratings and mean price target changes in the last 30 days.
4. Identify upcoming catalysts in the next 60-90 days: earnings, product launches,
   FDA decisions, analyst days, regulatory filings, macro events.
5. Review latest earnings: EPS beat/miss, revenue growth, guidance, margin trend.
6. Assess balance sheet: cash vs debt, free cash flow, any concerns.
7. Check insider transactions (SEC Form 4) in the last 30 days — note any significant
   purchases or sales by executives or directors.
8. Note institutional ownership trend — rising or falling.
9. Flag any stock with earnings within 7 days — high event risk; reduce confidence.

QUALITY BAR:
- Score 0-100. Confidence 0-100%. Only include if BOTH >= 90%.
- Return UP TO {top_n} picks. Fewer is better than including a weak pick.

JSON output includes per pick:
  rank, ticker, company_name, current_price, day_change_pct, week_change_pct,
  score, confidence_pct, signal, why_picked, technical_analysis,
  fundamental_snapshot, key_catalyst, sector_tailwind, analyst_sentiment,
  insider_activity, earnings_warning, news_summary, news_sentiment,
  suggested_entry, target_price, stop_loss, upside_pct, time_horizon, risk_factors[]
```

**Sector guidance injected per sector:**

| Sector | Key focus areas |
|---|---|
| Technology | AI/ML adoption, semiconductor demand, cloud ARR growth, software innovation, competitive moats, valuation vs growth |
| Pharma & Biotech | FDA calendar (next 90 days), Phase 2/3 trials, patent cliffs, pipeline value, M&A activity, drug pricing |
| Healthcare | Insurance reimbursement, hospital utilization, medical device innovation, Medicare/Medicaid policy, managed care margins |
| Finance | Net interest margin, loan growth vs credit losses, capital adequacy, fee income, Fed rate trajectory |
| Energy | Crude/nat-gas futures, production guidance, refining spreads, capex discipline, OPEC+ decisions, energy transition |
| Consumer | Consumer confidence, same-store sales, gross margin recovery, inventory normalization, e-commerce, brand strength |
| Industrials | Order backlog, defense budget, infrastructure spending, supply chain, pricing power, international exposure |
| Crypto | On-chain metrics, institutional inflows, regulatory developments, network upgrades, DeFi activity |

---

### 10d. Research — Penny Stocks Deep Research Prompt (`PENNY_DEEP_RESEARCH_PROMPT_TEMPLATE`)

Used in `run_sector_api()` for the Penny sector.

```
You are a small-cap and penny stock specialist.
Research the provided stocks (all priced under ${max_price}) for high-conviction
recovery or growth plays.

KEY QUESTIONS FOR EACH STOCK:
- Why is it cheap? Temporary headwind or structural decline?
- Is the business viable? Real revenue, path to profitability, defensible niche?
- What catalyst could re-rate it? FDA approval, contract win, earnings surprise?
- Financial runway: months of cash, revenue trajectory, debt burden.
- Market interest: insider buying, institutional accumulation, short interest (squeeze)?

AVOID: pure pump plays, zero-revenue shells, companies in terminal decline, fraudulent operators.

QUALITY BAR: Score >= 90 AND confidence >= 90%. Return UP TO {top_n} picks.

JSON output includes per pick:
  rank, ticker, company_name, current_price, score, confidence_pct, signal,
  why_picked, why_its_cheap, business_viability, key_catalyst, financial_health,
  technical_analysis, news_summary, suggested_entry, target_price, stop_loss,
  upside_pct, time_horizon, risk_factors[]
```

---

### 10e. Stock Analysis — AI Narrative Prompt

Used in `_ai_analysis()` in `backend/services/stock_analyzer.py`.  
Model: `claude-sonnet-4-6` (max 600 tokens — concise, actionable)

```
You are a professional equity analyst. Analyze {ticker} ({company}) based on the
following data and provide a concise, actionable analysis.

TECHNICAL DATA:
- Current Price: ${price}
- Day Change: {day_change_pct}%
- RSI (14): {rsi}
- MACD: {macd}
- 50-day SMA: {sma50}
- 200-day SMA: {sma200}
- VWAP: ${vwap}  (above/below — bullish/bearish intraday)
- ATR (14): ${atr} ({atr_pct}% of price)
- Momentum Score: {score}/100
- Signal: {signal}

FUNDAMENTAL DATA:
- Sector: {sector}
- P/E Ratio: {pe}
- Beta: {beta}
- Profit Margin: {profit_margin}%
- Revenue Growth (YoY): {rev_growth}%
- EPS (forward vs trailing): ${trailing} → ${forward} ({growth}% expected)
- EPS Surprise (last quarter): {eps_surprise}% vs estimate
- Short Interest: {short_pct}% of float ({short_ratio} days to cover)

ANALYST DATA:
- Consensus: {recommendation} ({num_analysts} analysts)
- Price Target (mean): ${target_mean} ({upside}% upside)
- Target Range: ${target_low} – ${target_high}

MARKET REGIME:
- Regime: {regime} (VIX={vix})
- SPY vs SMA50: {vs_sma50}% / vs SMA200: {vs_sma200}%
- Score multiplier: {multiplier}× — {regime_advice}

Provide a structured analysis with:
1. Summary (2-3 sentences on current situation and market regime context)
2. Technical Outlook (what the indicators tell us, including VWAP position)
3. Analyst Consensus (how analyst targets compare to current price)
4. Key Risks (2-3 bullet points)
5. Trade Setup (entry zone, target, stop-loss = 1.5× ATR below entry, size for regime)

Keep it concise and actionable. No fluff.
```

---

## Appendix — Data Sources Summary

| Data | Source | API key required | Refresh cadence |
|---|---|---|---|
| Price, OHLCV, fundamentals | yfinance (Yahoo Finance) | No | Per request |
| Earnings calendar | yfinance `Ticker.calendar` | No | Per request |
| Analyst targets & consensus | yfinance `Ticker.info` | No | Per request |
| Insider transactions (Form 4) | yfinance `Ticker.insider_transactions` | No | Per request |
| Institutional holders | yfinance `Ticker.major_holders` | No | Per request |
| StockTwits sentiment | StockTwits public API | No | 30 min cache |
| CNN Fear & Greed | CNN dataviz API | No | 30 min cache |
| Crypto Fear & Greed | Alternative.me API | No | 30 min cache |
| Reddit mentions | Reddit OAuth API | Yes (optional) | Per request |
| Market regime (VIX/SPY) | yfinance | No | 1 hour cache |
| Deep research + news | Claude Opus 4.8 + web_search | ANTHROPIC_API_KEY | Per run |
| Stock Analysis AI narrative | Claude Sonnet 4.6 | ANTHROPIC_API_KEY | Per request |

---

*This document is auto-generated from the codebase. Re-generate after significant changes to `research.py`, `stock_analyzer.py`, or `sentiment.py`.*
