from pydantic import BaseModel


class ResearchRequest(BaseModel):
    mode: str = "free"
    selected_sectors: list[str] = []
    top_n: int = 5
    max_price: float | None = None
    send_email: bool = False
    dividend_only: bool = False
    min_market_cap: int = 10_000_000


class ResearchConfigOut(BaseModel):
    available_modes: list[str]
    available_sectors: list[str]
    max_picks: int
    default_top_n: int
    sector_labels: dict[str, str]
