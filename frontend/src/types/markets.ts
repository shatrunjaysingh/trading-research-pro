export interface ExchangeConfig {
  id: string
  name: string
  fullName: string
  suffix: string
  suffixes: string[]
  examples: string
}

export interface CountryConfig {
  id: string
  name: string
  flag: string
  currency: string
  exchanges: ExchangeConfig[]
}

export const COUNTRIES: CountryConfig[] = [
  {
    id: 'US', name: 'United States', flag: '🇺🇸', currency: '$',
    exchanges: [
      { id: 'NYSE_NASDAQ', name: 'NYSE / NASDAQ', fullName: 'New York Stock Exchange & NASDAQ', suffix: '', suffixes: [], examples: 'AAPL, TSLA, NVDA, MSFT, AMZN' },
      { id: 'AMEX',        name: 'NYSE American', fullName: 'NYSE American (AMEX) — small/mid-cap',  suffix: '', suffixes: [], examples: 'SQQQ, TNA, ERX' },
    ],
  },
  {
    id: 'IN', name: 'India', flag: '🇮🇳', currency: '₹',
    exchanges: [
      { id: 'NSE', name: 'NSE', fullName: 'National Stock Exchange of India',  suffix: '.NS', suffixes: ['.NS'], examples: 'RELIANCE, TCS, INFY, WIPRO, HDFCBANK' },
      { id: 'BSE', name: 'BSE', fullName: 'Bombay Stock Exchange (Sensex)',     suffix: '.BO', suffixes: ['.BO'], examples: 'RELIANCE, TCS, INFY, WIPRO, HDFCBANK' },
    ],
  },
  {
    id: 'UK', name: 'United Kingdom', flag: '🇬🇧', currency: '£',
    exchanges: [
      { id: 'LSE', name: 'LSE', fullName: 'London Stock Exchange (Main Market)', suffix: '.L', suffixes: ['.L'], examples: 'SHEL, AZN, HSBA, BP, GSK' },
      { id: 'AIM', name: 'AIM', fullName: 'AIM — Alternative Investment Market', suffix: '.L', suffixes: ['.L'], examples: 'ASOS, BOO, ITV, ABDN' },
    ],
  },
  {
    id: 'DE', name: 'Germany', flag: '🇩🇪', currency: '€',
    exchanges: [
      { id: 'XETRA', name: 'Xetra',    fullName: 'Xetra (Deutsche Börse — primary)', suffix: '.DE', suffixes: ['.DE'], examples: 'SAP, BMW, SIE, BAYN, MBG' },
      { id: 'FSE',   name: 'Frankfurt', fullName: 'Frankfurt Stock Exchange',          suffix: '.F',  suffixes: ['.F'],  examples: 'SAP, BMW, SIE, BAYN' },
      { id: 'MUN',   name: 'Munich',    fullName: 'Börse München (Gettex)',            suffix: '.MU', suffixes: ['.MU'], examples: 'SAP, BMW, SIE, BAYN' },
      { id: 'STU',   name: 'Stuttgart', fullName: 'Börse Stuttgart (EUWAX)',           suffix: '.SG', suffixes: ['.SG'], examples: 'SAP, BMW, SIE, BAYN' },
      { id: 'BER',   name: 'Berlin',    fullName: 'Börse Berlin',                      suffix: '.BE', suffixes: ['.BE'], examples: 'SAP, BMW, SIE, BAYN' },
    ],
  },
  {
    id: 'CA', name: 'Canada', flag: '🇨🇦', currency: 'CA$',
    exchanges: [
      { id: 'TSX',  name: 'TSX',  fullName: 'Toronto Stock Exchange (large/mid-cap)',      suffix: '.TO', suffixes: ['.TO'], examples: 'SHOP, RY, TD, ENB, CNR' },
      { id: 'TSXV', name: 'TSXV', fullName: 'TSX Venture Exchange (small-cap / growth)',   suffix: '.V',  suffixes: ['.V'],  examples: 'Smaller junior/growth companies' },
      { id: 'NEO',  name: 'NEO',  fullName: 'NEO Exchange',                                suffix: '.NE', suffixes: ['.NE'], examples: 'Evolve ETFs, Purpose funds' },
    ],
  },
  {
    id: 'JP', name: 'Japan', flag: '🇯🇵', currency: '¥',
    exchanges: [
      { id: 'TSE',    name: 'TSE / JPX', fullName: 'Tokyo Stock Exchange (Prime, Standard & Growth)', suffix: '.T',  suffixes: ['.T'],  examples: '7203, 9984, 6758, 8306, 6501' },
      { id: 'NSE_JP', name: 'Nagoya',    fullName: 'Nagoya Stock Exchange',                            suffix: '.NG', suffixes: ['.NG'], examples: '7203, 9983' },
      { id: 'FSE_JP', name: 'Fukuoka',   fullName: 'Fukuoka Stock Exchange',                           suffix: '.FU', suffixes: ['.FU'], examples: 'Regional listings' },
      { id: 'SSE_JP', name: 'Sapporo',   fullName: 'Sapporo Securities Exchange',                      suffix: '.SP', suffixes: ['.SP'], examples: 'Regional listings' },
    ],
  },
  {
    id: 'AU', name: 'Australia', flag: '🇦🇺', currency: 'A$',
    exchanges: [
      { id: 'ASX',     name: 'ASX',  fullName: 'Australian Securities Exchange', suffix: '.AX', suffixes: ['.AX'], examples: 'BHP, CBA, CSL, ANZ, WBC' },
      { id: 'CBOE_AU', name: 'CBOE', fullName: 'CBOE Australia (Chi-X)',          suffix: '.AX', suffixes: ['.AX'], examples: 'Same tickers as ASX — dual-listed' },
    ],
  },
]

export function detectCountry(): CountryConfig | null {
  const tz = Intl.DateTimeFormat().resolvedOptions().timeZone ?? ''
  if (tz === 'Asia/Kolkata' || tz === 'Asia/Calcutta')              return COUNTRIES.find(c => c.id === 'IN') ?? null
  if (tz.startsWith('Europe/London') || tz === 'Europe/Dublin')     return COUNTRIES.find(c => c.id === 'UK') ?? null
  if (tz.startsWith('Europe/'))                                      return COUNTRIES.find(c => c.id === 'DE') ?? null
  if (tz.startsWith('America/Toronto') || tz.startsWith('America/Vancouver') ||
      tz.startsWith('America/Winnipeg') || tz === 'America/Halifax') return COUNTRIES.find(c => c.id === 'CA') ?? null
  if (tz.startsWith('Asia/Tokyo'))                                   return COUNTRIES.find(c => c.id === 'JP') ?? null
  if (tz.startsWith('Australia/') || tz.startsWith('Pacific/Auckland')) return COUNTRIES.find(c => c.id === 'AU') ?? null
  return null
}

export function formatTicker(raw: string, activeExchanges: ExchangeConfig[]): string {
  const t = raw.trim().toUpperCase()
  if (activeExchanges.length === 1 && activeExchanges[0].suffix) {
    const ex = activeExchanges[0]
    const alreadySuffixed = ex.suffixes.some(s => t.endsWith(s))
    return alreadySuffixed ? t : `${t}${ex.suffix}`
  }
  return t
}
