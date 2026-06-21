from pydantic import BaseModel, Field


class StockAnalysisRequest(BaseModel):
    ticker: str = Field(..., min_length=1, max_length=10)
    mode: str = "free"
    time_period: str = "3m"
    indicators: list[str] = Field(default_factory=lambda: ["rsi", "macd", "sma50", "sma200", "volume"])
    include_news: bool = True
    include_fundamentals: bool = True
    include_peers: bool = False
    # Indicator calculation parameters
    rsi_period: int = Field(default=14, ge=2, le=50)
    bb_period: int = Field(default=20, ge=5, le=200)
    bb_std: float = Field(default=2.0, ge=0.5, le=4.0)
    macd_fast: int = Field(default=12, ge=2, le=50)
    macd_slow: int = Field(default=26, ge=5, le=200)
    macd_signal_period: int = Field(default=9, ge=2, le=50)
    force_refresh: bool = False


class TechnicalSnapshot(BaseModel):
    current_price: float | None = None
    prev_close: float | None = None
    day_change_pct: float | None = None
    week_change_pct: float | None = None
    month_change_pct: float | None = None
    high_52w: float | None = None
    low_52w: float | None = None
    pos_52w_pct: float | None = None
    avg_volume: float | None = None
    last_volume: float | None = None
    vol_ratio: float | None = None
    rsi: float | None = None
    macd: float | None = None
    macd_signal: float | None = None
    macd_hist: float | None = None
    sma20: float | None = None
    sma50: float | None = None
    sma200: float | None = None
    bb_upper: float | None = None
    bb_lower: float | None = None
    bb_mid: float | None = None
    signal: str = "hold"
    score: float = 50.0
    confidence: float = 50.0


class FundamentalSnapshot(BaseModel):
    company_name: str | None = None
    sector: str | None = None
    industry: str | None = None
    market_cap: float | None = None
    pe_ratio: float | None = None
    forward_pe: float | None = None
    eps: float | None = None
    revenue: float | None = None
    profit_margin: float | None = None
    debt_to_equity: float | None = None
    current_ratio: float | None = None
    return_on_equity: float | None = None
    dividend_yield: float | None = None
    beta: float | None = None


class AnalystSnapshot(BaseModel):
    recommendation: str | None = None        # "Buy", "Strong Buy", "Hold", etc.
    recommendation_key: str | None = None    # raw yf key: "buy", "strong_buy", etc.
    recommendation_mean: float | None = None  # 1.0 (Strong Buy) → 5.0 (Strong Sell)
    num_analysts: int | None = None
    target_mean: float | None = None
    target_median: float | None = None
    target_high: float | None = None
    target_low: float | None = None
    upside_pct: float | None = None          # (target_mean - current) / current * 100


class StockAnalysisResult(BaseModel):
    ticker: str
    company_name: str | None = None
    mode: str
    time_period: str
    technical: TechnicalSnapshot | None = None
    fundamentals: FundamentalSnapshot | None = None
    analyst: AnalystSnapshot | None = None
    ai_analysis: str | None = None
    news_summary: str | None = None
    peer_comparison: list[dict] | None = None
    requested_indicators: list[str] = []
    error: str | None = None
