import type { FreePick, ApiPick, PickSnapshot } from '../types'

function fmtPrice(v: number | string | null | undefined): string {
  if (v == null || v === '') return '—'
  const n = Number(v)
  return isNaN(n) ? String(v) : `$${n.toFixed(2)}`
}

function fmtBig(v: number | null | undefined): string {
  if (v == null) return '—'
  if (v >= 1e12) return `$${(v / 1e12).toFixed(2)}T`
  if (v >= 1e9)  return `$${(v / 1e9).toFixed(2)}B`
  if (v >= 1e6)  return `$${(v / 1e6).toFixed(2)}M`
  return `$${v.toFixed(0)}`
}

function fmtPct(v: number | null | undefined, decimals = 1): string {
  if (v == null) return '—'
  return `${v >= 0 ? '+' : ''}${v.toFixed(decimals)}%`
}

function fmtNum(v: number | null | undefined, decimals = 2): string {
  if (v == null) return '—'
  return v.toFixed(decimals)
}

function ratingLabel(mean: number | null): string {
  if (mean == null) return '—'
  if (mean <= 1.5) return 'Strong Buy'
  if (mean <= 2.5) return 'Buy'
  if (mean <= 3.5) return 'Hold'
  if (mean <= 4.5) return 'Underperform'
  return 'Sell'
}

function ratingColor(mean: number | null): string {
  if (mean == null) return '#6b7280'
  if (mean <= 1.5) return '#16a34a'
  if (mean <= 2.5) return '#22c55e'
  if (mean <= 3.5) return '#ca8a04'
  if (mean <= 4.5) return '#ea580c'
  return '#dc2626'
}

function signalColor(signal: string): string {
  const s = signal.toLowerCase()
  if (s === 'buy')   return '#16a34a'
  if (s === 'watch') return '#2563eb'
  if (s === 'sell')  return '#dc2626'
  return '#ca8a04'
}

function row(label: string, value: string, highlight = false): string {
  return `
    <tr>
      <td style="padding:7px 12px;color:#6b7280;font-size:13px;border-bottom:1px solid #f3f4f6;white-space:nowrap">${label}</td>
      <td style="padding:7px 12px;font-weight:600;font-size:13px;border-bottom:1px solid #f3f4f6;color:${highlight ? '#1d4ed8' : '#111827'}">${value}</td>
    </tr>`
}

function section(title: string, content: string): string {
  return `
    <div style="margin-bottom:28px">
      <div style="font-size:11px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:#9ca3af;margin-bottom:8px;padding-bottom:6px;border-bottom:2px solid #e5e7eb">${title}</div>
      ${content}
    </div>`
}

function table(rows: string): string {
  return `<table style="width:100%;border-collapse:collapse">${rows}</table>`
}

function textBlock(text: string | null | undefined): string {
  if (!text) return ''
  return `<p style="font-size:13px;line-height:1.7;color:#374151;margin:0">${text}</p>`
}

function riskItem(text: string): string {
  return `<div style="display:flex;gap:8px;background:#fffbeb;border-left:3px solid #f59e0b;border-radius:0 6px 6px 0;padding:8px 12px;margin-bottom:6px;font-size:12px;color:#92400e"><span>⚠</span><span>${text}</span></div>`
}

function analystBar(mean: number | null): string {
  if (mean == null) return ''
  const pct = ((mean - 1) / 4) * 100
  const color = ratingColor(mean)
  return `
    <div style="margin-top:10px">
      <div style="display:flex;justify-content:space-between;font-size:10px;color:#9ca3af;margin-bottom:4px">
        <span>Strong Buy</span><span>Buy</span><span>Hold</span><span>Sell</span><span>Strong Sell</span>
      </div>
      <div style="height:8px;border-radius:4px;background:linear-gradient(to right,#16a34a,#22c55e,#ca8a04,#ea580c,#dc2626);position:relative">
        <div style="position:absolute;top:50%;transform:translate(-50%,-50%);width:14px;height:14px;border-radius:50%;background:white;border:3px solid ${color};box-shadow:0 1px 3px rgba(0,0,0,.3);left:${pct}%"></div>
      </div>
      <div style="text-align:center;font-size:11px;color:#6b7280;margin-top:5px">Mean: ${mean.toFixed(2)} / 5.0 — ${ratingLabel(mean)}</div>
    </div>`
}

export function generatePickReport(
  pick: FreePick | ApiPick,
  snapshot: PickSnapshot,
  sectorLabel: string,
  mode: 'free' | 'api',
): void {
  const isApi  = mode === 'api'
  const apick  = isApi ? (pick as ApiPick)  : null
  const fpick  = isApi ? null : (pick as FreePick)

  const score      = Number(pick.score)
  const signal     = pick.signal.toUpperCase()
  const sigColor   = signalColor(pick.signal)
  const confidence = isApi ? apick?.confidence_pct : fpick?.confidence
  const price      = isApi ? Number(apick?.current_price) : fpick?.current_price ?? 0
  const dayChg     = pick.day_change_pct
  const companyName = snapshot.company_name || (isApi ? apick?.company_name : null) || pick.ticker
  const now        = new Date().toLocaleString('en-US', { dateStyle: 'medium', timeStyle: 'short' })

  // Upside from snapshot or pick
  const targetMean = snapshot.target_mean
  const upsidePct  = snapshot.upside_pct ?? (isApi ? apick?.upside_pct : null)

  // Analyst rating scale label
  const recLabel = snapshot.recommendation || '—'
  const recColor = ratingColor(snapshot.recommendation_mean)

  const html = `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Stock Report — ${pick.ticker}</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0 }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #f9fafb; color: #111827; }
  @media print {
    body { background: white }
    .no-print { display: none }
    .page { box-shadow: none; margin: 0; border-radius: 0 }
  }
</style>
</head>
<body>

<div style="max-width:820px;margin:0 auto;padding:24px" class="page">

  <!-- Print button -->
  <div class="no-print" style="text-align:right;margin-bottom:16px">
    <button onclick="window.print()" style="background:#1d4ed8;color:white;border:none;padding:8px 20px;border-radius:8px;font-size:13px;cursor:pointer;font-weight:600">
      ⬇ Save as PDF / Print
    </button>
  </div>

  <!-- Header banner -->
  <div style="background:linear-gradient(135deg,#0f172a,#1e3a5f);color:white;border-radius:16px;padding:28px 32px;margin-bottom:24px">
    <div style="display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:16px">
      <div>
        <div style="font-size:36px;font-weight:900;letter-spacing:-.5px">${pick.ticker}</div>
        <div style="font-size:15px;opacity:.8;margin-top:4px">${companyName}</div>
        ${snapshot.sector ? `<div style="font-size:12px;opacity:.6;margin-top:2px">${snapshot.sector}${snapshot.industry ? ' · ' + snapshot.industry : ''}</div>` : ''}
        <div style="font-size:12px;opacity:.5;margin-top:8px">Sector: ${sectorLabel} · Generated ${now}</div>
      </div>
      <div style="text-align:right">
        <div style="display:inline-block;background:${sigColor};color:white;font-weight:800;font-size:18px;padding:8px 24px;border-radius:100px;letter-spacing:.05em">${signal}</div>
        <div style="margin-top:12px;display:flex;gap:20px;justify-content:flex-end">
          <div style="text-align:center">
            <div style="font-size:28px;font-weight:900">${score.toFixed(0)}</div>
            <div style="font-size:10px;opacity:.6;letter-spacing:.06em;text-transform:uppercase">Score</div>
          </div>
          ${confidence != null ? `
          <div style="text-align:center">
            <div style="font-size:28px;font-weight:900;color:${confidence >= 67 ? '#86efac' : confidence >= 50 ? '#fde68a' : '#fca5a5'}">${confidence}%</div>
            <div style="font-size:10px;opacity:.6;letter-spacing:.06em;text-transform:uppercase">Confidence</div>
          </div>` : ''}
          <div style="text-align:center">
            <div style="font-size:28px;font-weight:900">${fmtPrice(price)}</div>
            <div style="font-size:12px;font-weight:600;color:${dayChg >= 0 ? '#86efac' : '#fca5a5'}">${fmtPct(dayChg)}</div>
          </div>
        </div>
      </div>
    </div>
  </div>

  <div style="display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-bottom:24px">

    <!-- Selection Criteria -->
    <div style="background:white;border-radius:12px;padding:20px;border:1px solid #e5e7eb">
      ${section('Selection Criteria', table(`
        ${row('Signal', `<span style="color:${sigColor};font-weight:700">${signal}</span>`)}
        ${row('Score', `${score.toFixed(0)} / 100`)}
        ${confidence != null ? row('Confidence', `${confidence}%`) : ''}
        ${row('Day Change', `<span style="color:${dayChg >= 0 ? '#16a34a' : '#dc2626'}">${fmtPct(dayChg, 2)}</span>`)}
        ${fpick ? row('Volume Ratio', `${fpick.vol_ratio.toFixed(2)}×`) : ''}
        ${fpick ? row('52-Week Position', `${fpick.pos_52w.toFixed(1)}%`) : ''}
        ${fpick?.dividend_yield ? row('Dividend Yield', `${(fpick.dividend_yield * 100).toFixed(2)}%`) : ''}
        ${apick?.week_change_pct != null ? row('Week Change', `<span style="color:${apick.week_change_pct >= 0 ? '#16a34a' : '#dc2626'}">${fmtPct(apick.week_change_pct, 2)}</span>`) : ''}
      `))}

      ${section('Price Levels', table(`
        ${row('Current Price', fmtPrice(price))}
        ${snapshot.high_52w ? row('52-Week High', fmtPrice(snapshot.high_52w)) : ''}
        ${snapshot.low_52w  ? row('52-Week Low',  fmtPrice(snapshot.low_52w))  : ''}
        ${targetMean ? row('Analyst Target', `<span style="color:#1d4ed8">${fmtPrice(targetMean)}</span>`) : ''}
        ${upsidePct  != null ? row('Potential Upside', `<span style="color:${upsidePct >= 0 ? '#16a34a' : '#dc2626'}">${fmtPct(upsidePct, 1)}</span>`) : ''}
      `))}
    </div>

    <!-- Analyst Ratings -->
    <div style="background:white;border-radius:12px;padding:20px;border:1px solid #e5e7eb">
      ${section('Analyst Ratings', `
        <div style="display:flex;align-items:center;gap:12px;margin-bottom:12px">
          <div style="background:${recColor};color:white;font-weight:700;font-size:14px;padding:6px 16px;border-radius:100px">${recLabel}</div>
          ${snapshot.num_analysts ? `<span style="font-size:12px;color:#6b7280">${snapshot.num_analysts} analyst${snapshot.num_analysts !== 1 ? 's' : ''}</span>` : ''}
          ${upsidePct != null ? `<span style="margin-left:auto;font-weight:700;font-size:13px;color:${upsidePct >= 0 ? '#16a34a' : '#dc2626'}">${fmtPct(upsidePct, 1)} upside</span>` : ''}
        </div>
        ${analystBar(snapshot.recommendation_mean)}
        <div style="margin-top:14px">
          ${table(`
            ${snapshot.target_mean   ? row('Price Target (Mean)',   fmtPrice(snapshot.target_mean))   : ''}
            ${snapshot.target_median ? row('Price Target (Median)', fmtPrice(snapshot.target_median)) : ''}
            ${snapshot.target_high   ? row('Target High',           fmtPrice(snapshot.target_high))   : ''}
            ${snapshot.target_low    ? row('Target Low',            fmtPrice(snapshot.target_low))    : ''}
          `)}
        </div>
      `)}

      ${section('Fundamentals', table(`
        ${snapshot.market_cap    ? row('Market Cap',    fmtBig(snapshot.market_cap))  : ''}
        ${snapshot.pe_ratio      ? row('P/E (TTM)',     `${fmtNum(snapshot.pe_ratio)}×`) : ''}
        ${snapshot.forward_pe    ? row('Forward P/E',  `${fmtNum(snapshot.forward_pe)}×`) : ''}
        ${snapshot.eps           ? row('EPS (TTM)',     fmtPrice(snapshot.eps))       : ''}
        ${snapshot.revenue       ? row('Revenue',       fmtBig(snapshot.revenue))     : ''}
        ${snapshot.profit_margin ? row('Profit Margin', `${((snapshot.profit_margin) * 100).toFixed(1)}%`) : ''}
        ${snapshot.debt_to_equity ? row('Debt / Equity', fmtNum(snapshot.debt_to_equity)) : ''}
        ${snapshot.current_ratio  ? row('Current Ratio', fmtNum(snapshot.current_ratio))  : ''}
        ${snapshot.return_on_equity ? row('ROE', `${((snapshot.return_on_equity) * 100).toFixed(1)}%`) : ''}
        ${snapshot.dividend_yield && snapshot.dividend_yield > 0 ? row('Dividend Yield', `${(snapshot.dividend_yield * 100).toFixed(2)}%`) : ''}
        ${snapshot.beta          ? row('Beta',          fmtNum(snapshot.beta))        : ''}
      `))}
    </div>
  </div>

  <!-- Narrative sections (ApiPick only) -->
  ${apick ? `
  <div style="background:white;border-radius:12px;padding:20px;border:1px solid #e5e7eb;margin-bottom:20px">
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:24px">
      <div>
        ${apick.why_picked       ? section('Why Picked',         textBlock(apick.why_picked))       : ''}
        ${apick.key_catalyst     ? section('Key Catalyst',       textBlock(apick.key_catalyst))     : ''}
        ${apick.sector_tailwind  ? section('Sector Tailwind',    textBlock(apick.sector_tailwind))  : ''}
        ${apick.technical_analysis ? section('Technical Analysis', textBlock(apick.technical_analysis)) : ''}
        ${apick.why_its_cheap    ? section("Why It's Cheap",    textBlock(apick.why_its_cheap))    : ''}
      </div>
      <div>
        ${apick.business_viability ? section('Business Viability', textBlock(apick.business_viability)) : ''}
        ${apick.financial_health   ? section('Financial Health',   textBlock(apick.financial_health))   : ''}
        ${apick.analyst_sentiment  ? section('Analyst View',       textBlock(apick.analyst_sentiment))  : ''}
        ${apick.news_summary       ? section(`Latest News ${apick.news_sentiment ? '(' + apick.news_sentiment + ')' : ''}`, textBlock(apick.news_summary)) : ''}
      </div>
    </div>

    ${(apick.suggested_entry || apick.target_price || apick.stop_loss) ? `
    ${section('Trade Levels', `
      <div style="display:grid;grid-template-columns:repeat(5,1fr);border:1px solid #e5e7eb;border-radius:10px;overflow:hidden">
        ${[
          { label: 'Entry',   val: fmtPrice(apick.suggested_entry), color: '#2563eb' },
          { label: 'Target',  val: fmtPrice(apick.target_price),    color: '#16a34a' },
          { label: 'Stop',    val: fmtPrice(apick.stop_loss),       color: '#dc2626' },
          { label: 'Upside',  val: apick.upside_pct != null ? fmtPct(apick.upside_pct, 1) : '—', color: '#7c3aed' },
          { label: 'Horizon', val: apick.time_horizon ?? '—',       color: '#374151' },
        ].map((item, i) => `
          <div style="padding:12px 8px;text-align:center;${i < 4 ? 'border-right:1px solid #e5e7eb' : ''}">
            <div style="font-size:10px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:#9ca3af">${item.label}</div>
            <div style="font-size:15px;font-weight:700;margin-top:4px;color:${item.color}">${item.val}</div>
          </div>
        `).join('')}
      </div>
    `)}` : ''}

    ${apick.risk_factors && apick.risk_factors.length > 0 ? `
    ${section('Risk Factors', apick.risk_factors.map(r => riskItem(r)).join(''))}` : ''}
  </div>` : ''}

  ${fpick?.why_picked ? `
  <div style="background:white;border-radius:12px;padding:20px;border:1px solid #e5e7eb;margin-bottom:20px">
    ${section('Why Picked', textBlock(fpick.why_picked))}
  </div>` : ''}

  ${snapshot.description ? `
  <div style="background:white;border-radius:12px;padding:20px;border:1px solid #e5e7eb;margin-bottom:20px">
    ${section('About the Company', textBlock(snapshot.description + (snapshot.description.length >= 400 ? '…' : '')))}
  </div>` : ''}

  <!-- Score methodology note -->
  <div style="background:#f0f9ff;border:1px solid #bae6fd;border-radius:10px;padding:14px 18px;margin-bottom:20px;font-size:12px;color:#0369a1">
    <strong>Scoring methodology:</strong> Momentum score = price momentum 40% · volume surge 30% · 52-week position 30%.
    Confidence reflects how many scoring factors agree on the signal direction.
    Analyst ratings are sourced from Yahoo Finance consensus data.
  </div>

  <!-- Disclaimer -->
  <div style="border-top:1px solid #e5e7eb;padding-top:16px;font-size:11px;color:#9ca3af;line-height:1.6">
    <strong>⚠ Disclaimer:</strong> This report is generated for informational and research purposes only.
    It does not constitute financial advice, an offer to buy or sell securities, or a solicitation of any kind.
    Past performance is not indicative of future results. Always conduct your own due diligence and consult
    a licensed financial advisor before making investment decisions.
    <br><br>
    Generated by <strong>TradingResearch Pro</strong> · ${now}
  </div>

</div>

<script>
  // Auto-open print dialog after a brief render delay
  window.addEventListener('load', () => setTimeout(() => window.print(), 600))
</script>
</body>
</html>`

  const blob = new Blob([html], { type: 'text/html' })
  const url  = URL.createObjectURL(blob)
  const win  = window.open(url, '_blank')
  if (!win) {
    // Fallback: download as file if popup blocked
    const a = document.createElement('a')
    a.href = url
    a.download = `${pick.ticker}-report-${new Date().toISOString().slice(0, 10)}.html`
    a.click()
  }
  setTimeout(() => URL.revokeObjectURL(url), 60_000)
}
