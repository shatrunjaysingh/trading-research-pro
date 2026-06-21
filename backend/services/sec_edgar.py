"""
SEC EDGAR integration — Form 4 insider transactions and recent filing history.

Uses the free EDGAR REST API (no API key required).
Rate limit: max 10 requests/second; User-Agent header required by SEC policy.

Key endpoints used:
  Ticker → CIK map : https://www.sec.gov/files/company_tickers.json
  Company filings  : https://data.sec.gov/submissions/CIK{padded}.json
  Form 4 XML       : https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/form4.xml
"""

import logging
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

EDGAR_HEADERS  = {"User-Agent": "TradingResearchPro ssingh327@gmail.com"}
EDGAR_SUBS     = "https://data.sec.gov/submissions"
EDGAR_ARCHIVES = "https://www.sec.gov/Archives/edgar/data"
TICKERS_URL    = "https://www.sec.gov/files/company_tickers.json"

# Transaction code meanings
TXN_CODES = {
    "P": "Purchase",
    "S": "Sale",
    "A": "Award/Grant",
    "D": "Disposition",
    "F": "Tax Withholding",
    "M": "Option Exercise",
    "G": "Gift",
    "V": "Voluntary",
    "X": "Option Exercise (expired)",
    "C": "Convertible",
    "E": "Expiration",
    "H": "Expiration (in-the-money)",
    "I": "Discretionary",
    "L": "Small acq.",
    "O": "Out-of-money option",
    "U": "Tender offer",
    "W": "Inherited",
    "Z": "Trust",
}

# In-process caches
_TICKER_CIK: dict[str, str] = {}
_TICKER_CIK_AT: float = 0.0
_TICKER_CIK_TTL = 86_400   # 24 h

_FORM4_CACHE: dict[str, tuple[list, float]] = {}
_FORM4_TTL = 3_600         # 1 h


def _get(url: str, timeout: int = 8) -> Optional[dict | str]:
    try:
        import httpx
        r = httpx.get(url, headers=EDGAR_HEADERS, timeout=timeout, follow_redirects=True)
        r.raise_for_status()
        ct = r.headers.get("content-type", "")
        return r.json() if "json" in ct else r.text
    except Exception as exc:
        logger.debug("EDGAR fetch failed %s: %s", url, exc)
        return None


# ── Ticker → CIK ─────────────────────────────────────────────────────────────

def _load_cik_map() -> dict[str, str]:
    global _TICKER_CIK, _TICKER_CIK_AT
    if time.time() - _TICKER_CIK_AT < _TICKER_CIK_TTL and _TICKER_CIK:
        return _TICKER_CIK
    data = _get(TICKERS_URL)
    if isinstance(data, dict):
        _TICKER_CIK = {v["ticker"].upper(): str(v["cik_str"]).zfill(10) for v in data.values()}
        _TICKER_CIK_AT = time.time()
    return _TICKER_CIK


def get_cik(ticker: str) -> Optional[str]:
    return _load_cik_map().get(ticker.strip().upper())


# ── Form 4 XML parsing ────────────────────────────────────────────────────────

def _txt(el, path: str) -> Optional[str]:
    node = el.find(path)
    return node.text.strip() if node is not None and node.text else None


def _parse_form4(xml_text: str, filed_date: str) -> list[dict]:
    """Parse a Form 4 XML document into a list of transaction dicts."""
    transactions = []
    try:
        root = ET.fromstring(xml_text)

        # Reporting owner info
        owner_el    = root.find(".//reportingOwner")
        owner_name  = _txt(owner_el, ".//rptOwnerName")  if owner_el is not None else None
        is_director = _txt(owner_el, ".//isDirector")    if owner_el is not None else "0"
        is_officer  = _txt(owner_el, ".//isOfficer")     if owner_el is not None else "0"
        title       = _txt(owner_el, ".//officerTitle")  if owner_el is not None else None
        role = (
            title if title else
            "Director" if is_director == "1" else
            "Officer" if is_officer == "1" else
            "10% Owner"
        )

        for txn in root.findall(".//nonDerivativeTransaction"):
            code   = _txt(txn, ".//transactionCode")
            shares = _txt(txn, ".//transactionShares/value")
            price  = _txt(txn, ".//transactionPricePerShare/value")
            txn_dt = _txt(txn, ".//transactionDate/value") or filed_date

            if code not in ("P", "S", "A", "F", "M"):
                continue  # skip gifts, dispositions, etc.
            if not shares:
                continue

            transactions.append({
                "date":        txn_dt,
                "filed_date":  filed_date,
                "owner":       owner_name or "Unknown",
                "role":        role,
                "code":        code,
                "type":        TXN_CODES.get(code, code),
                "shares":      int(float(shares)),
                "price":       round(float(price), 2) if price else None,
                "value":       round(int(float(shares)) * float(price), 0) if price else None,
            })
    except Exception as exc:
        logger.debug("Form 4 parse error: %s", exc)
    return transactions


# ── Public API ────────────────────────────────────────────────────────────────

def get_insider_transactions(ticker: str, days: int = 90, max_filings: int = 10) -> list[dict]:
    """
    Return Form 4 insider transactions for a ticker from the past `days` days.
    Fetches up to `max_filings` individual XML files.
    Results cached 1 hour.
    """
    cache_key = f"{ticker.upper()}:{days}"
    if cache_key in _FORM4_CACHE:
        cached, ts = _FORM4_CACHE[cache_key]
        if time.time() - ts < _FORM4_TTL:
            return cached

    cik = get_cik(ticker)
    if not cik:
        return []

    # Fetch submissions JSON
    subs = _get(f"{EDGAR_SUBS}/CIK{cik}.json")
    if not isinstance(subs, dict):
        return []

    recent  = subs.get("filings", {}).get("recent", {})
    forms   = recent.get("form",            [])
    dates   = recent.get("filingDate",      [])
    accnums = recent.get("accessionNumber", [])

    cutoff  = (date.today() - timedelta(days=days)).isoformat()
    results: list[dict] = []
    fetched = 0

    for i, form in enumerate(forms):
        if form != "4":
            continue
        filed = dates[i] if i < len(dates) else ""
        if filed < cutoff:
            break  # newest-first — stop when outside window

        acc      = accnums[i].replace("-", "") if i < len(accnums) else ""
        cik_int  = int(cik)
        xml_url  = f"{EDGAR_ARCHIVES}/{cik_int}/{acc}/form4.xml"

        xml_text = _get(xml_url, timeout=6)
        if isinstance(xml_text, str):
            txns = _parse_form4(xml_text, filed)
            results.extend(txns)
            fetched += 1

        if fetched >= max_filings:
            break

    _FORM4_CACHE[cache_key] = (results, time.time())
    return results


def summarise_insider_transactions(transactions: list[dict]) -> dict:
    """Aggregate a list of Form 4 transactions into buy/sell signals."""
    if not transactions:
        return {}

    purchases = [t for t in transactions if t["code"] == "P"]
    sales     = [t for t in transactions if t["code"] == "S"]

    buy_shares  = sum(t["shares"] for t in purchases)
    sell_shares = sum(t["shares"] for t in sales)
    net_shares  = buy_shares - sell_shares

    signal = (
        "strong_buy"  if net_shares >  200_000 else
        "buy"         if net_shares >   20_000 else
        "sell"        if net_shares < -200_000 else
        "weak_sell"   if net_shares <  -20_000 else
        "neutral"
    )

    return {
        "buy_count":   len(purchases),
        "sell_count":  len(sales),
        "buy_shares":  buy_shares,
        "sell_shares": sell_shares,
        "net_shares":  net_shares,
        "signal":      signal,
    }


def get_recent_filings(ticker: str, forms: list[str] = None, limit: int = 5) -> list[dict]:
    """Return recent SEC filings (10-K, 10-Q, 8-K) for a ticker."""
    if forms is None:
        forms = ["10-K", "10-Q", "8-K"]

    cik = get_cik(ticker)
    if not cik:
        return []

    subs = _get(f"{EDGAR_SUBS}/CIK{cik}.json")
    if not isinstance(subs, dict):
        return []

    recent   = subs.get("filings", {}).get("recent", {})
    f_forms  = recent.get("form",        [])
    f_dates  = recent.get("filingDate",  [])
    f_desc   = recent.get("items",       [])
    f_acc    = recent.get("accessionNumber", [])

    cik_int  = int(cik)
    results  = []
    for i, form in enumerate(f_forms):
        if form not in forms:
            continue
        acc     = f_acc[i].replace("-", "") if i < len(f_acc) else ""
        results.append({
            "form":    form,
            "date":    f_dates[i] if i < len(f_dates) else "",
            "description": f_desc[i] if i < len(f_desc) else "",
            "url":     f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc}/",
        })
        if len(results) >= limit:
            break

    return results
