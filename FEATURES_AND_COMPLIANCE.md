# TradingResearch Pro — Features & Regulatory Compliance

**Version:** 1.0  
**Stack:** FastAPI (Python) · React (TypeScript) · PostgreSQL · Claude AI  
**Last updated:** 2026-06-14

---

## Table of Contents

1. [Application Overview](#1-application-overview)
2. [Feature Catalogue](#2-feature-catalogue)
   - 2.1 Authentication & Access Control
   - 2.2 Market Overview
   - 2.3 Research Dashboard
   - 2.4 Stock Analysis
   - 2.5 Caching & Performance
   - 2.6 Market Preferences
   - 2.7 Reporting & Export
   - 2.8 Administration
3. [Regulatory Compliance](#3-regulatory-compliance)
   - 3.1 Consent Management
   - 3.2 Investment Disclaimers
   - 3.3 AI Content Labelling
   - 3.4 Risk Classification
   - 3.5 Stale Data Warnings
   - 3.6 Immutable Audit Log
   - 3.7 Data Portability (GDPR Art.20)
   - 3.8 Right to Erasure (GDPR Art.17)
4. [Regulatory Framework Mapping](#4-regulatory-framework-mapping)
5. [Data Architecture](#5-data-architecture)
6. [Known Limitations & Roadmap](#6-known-limitations--roadmap)

---

## 1. Application Overview

TradingResearch Pro is a multi-market, AI-assisted investment research platform for individual and institutional users. It combines real-time market data (via Yahoo Finance), quantitative screening, technical analysis, and large-language-model narrative synthesis (via Claude AI) to produce stock research outputs across seven global markets.

The platform is **not a broker-dealer** and does **not execute trades**. All outputs are research and information only.

| Property | Detail |
|---|---|
| Primary data source | Yahoo Finance (yfinance) — ~15 min delay during market hours |
| AI model | Anthropic Claude (latest Sonnet) |
| Supported markets | United States · India · United Kingdom · Germany · Canada · Japan · Australia |
| Deployment target | AWS (Docker + RDS PostgreSQL) |
| Authentication | JWT (Bearer tokens) + bcrypt password hashing |
| Database | PostgreSQL 15+ |

---

## 2. Feature Catalogue

### 2.1 Authentication & Access Control

| Feature | Description |
|---|---|
| **User registration** | Email + username + password with strength validation (min 8 chars, upper, lower, digit, special). Consent checkbox mandatory. |
| **JWT login** | Stateless bearer-token auth; tokens signed with HS256. Sessions tracked in `sessions` table for audit trail. |
| **Role-based access** | Four roles: `admin`, `analyst`, `trader`, `viewer`. Permissions enforced at every API endpoint. |
| **License tiers** | Three tiers: `free`, `professional`, `enterprise`. Controls available modes, sectors, pick limits, email/export/admin capabilities. |
| **Must-change-password** | Admin can require password reset on next login. |
| **Forced logout** | Session invalidation on logout; admin can invalidate any session. |
| **Audit log** | Every login, logout, analysis request, profile change, data export, and account deletion is recorded. |
| **Change password** | Users can change their own password with current-password verification. |
| **Multi-device sessions** | JWT is stateless; login works across any device. Preferences sync via backend. |

### 2.2 Market Overview

The Market Overview page shows live market data for the user's selected market region.

| Feature | Description |
|---|---|
| **Major indices** | Country-specific benchmark indices displayed as cards with 52-week range bars. |
| **Sector performance** | Sector ETF/proxy bar chart, sorted by daily performance. |
| **Commodities & bonds** | Gold, silver, crude oil, 20Y Treasury, US Dollar (always shown regardless of market selection). |
| **Crypto** | BTC, ETH, SOL, BNB (always global). |
| **60-second auto-refresh** | Data refreshes automatically. |
| **Market status** | Live open/closed indicator using correct timezone for each market. |
| **Stale data warning** | Amber banner if data is >15 minutes old during market hours. |
| **Multi-market support** | Separate index and sector symbols per country (see table below). |

**Market-specific index symbols:**

| Country | Indices |
|---|---|
| United States | S&P 500 (^GSPC) · NASDAQ (^IXIC) · Dow Jones (^DJI) · Russell 2000 (^RUT) · VIX (^VIX) |
| India | Nifty 50 (^NSEI) · Sensex (^BSESN) · Nifty Bank (^NSEBANK) · Nifty IT (^CNXIT) |
| Japan | Nikkei 225 (^N225) · TOPIX (^TOPX) |
| Australia | ASX 200 (^AXJO) · All Ordinaries (^AORD) |
| United Kingdom | FTSE 100 (^FTSE) · FTSE 250 (^FTMC) |
| Germany | DAX 40 (^GDAXI) · MDAX (^MDAXI) |
| Canada | S&P/TSX Composite (^GSPTSE) |

### 2.3 Research Dashboard

Scans entire market sectors for top stock picks using quantitative scoring and optional AI narrative enrichment.

| Feature | Description |
|---|---|
| **Free Scan mode** | Instant quantitative screen using yfinance metrics (price momentum, volume, 52-week position, dividend yield). No AI token usage. |
| **Deep Research mode** | Each top pick is sent to Claude AI for narrative analysis covering catalyst, technicals, fundamentals, and analyst sentiment. Licensed tiers only. |
| **Sector selection** | Technology · Pharma · Healthcare · Finance · Energy · Consumer · Industrials · Crypto · Penny stocks. Admin can restrict per license. |
| **Top-N picks** | Configurable 1–10 picks per sector. Max enforced by license tier. |
| **Max price filter** | Exclude stocks above a set price threshold. |
| **Dividend filter** | Restrict results to dividend-paying stocks only. |
| **Confidence filter** | Minimum AI confidence threshold for Deep Research mode. |
| **Expandable row details** | Each pick expands inline to show full metrics without leaving the table. |
| **Email report** | Send research results by email (licensed tiers only). |
| **PDF download** | Export the full research session as a PDF with all metrics, AI analysis, and analyst ratings. |
| **Real-time progress** | Server-Sent Events (SSE) stream progress messages during Deep Research. |
| **Tabbed sector navigation** | Results grouped by sector with tab navigation; auto-selects first tab. |

### 2.4 Stock Analysis

Deep per-ticker analysis combining technical indicators, fundamental data, AI narrative, and analyst consensus.

| Feature | Description |
|---|---|
| **Any global ticker** | Accepts any symbol supported by Yahoo Finance. Exchange suffix auto-appended based on market selection. |
| **Market/exchange selection** | 7 countries × multiple exchanges. Auto-detects home market from browser timezone on first visit. |
| **Technical indicators** | RSI · MACD · SMA (20/50/200) · Bollinger Bands · Volume Analysis. Each with configurable parameters. |
| **Configurable periods** | 1 day · 1 week · 1 month · 3 months · 6 months · 1 year. |
| **MACD presets** | Standard (12/26/9) · Fast (8/17/9) · Slow (21/55/13). |
| **Momentum score** | 0–100 composite score combining all selected indicators. |
| **Confidence rating** | 0–100% signal conviction metric. |
| **Signal classification** | BUY · WATCH · HOLD · SELL. |
| **Risk classification** | LOW · MEDIUM · HIGH · UNKNOWN — derived from beta, day change, and RSI. |
| **Price history chart** | Candlestick / OHLCV chart with overlay SMA lines and volume bars. PE ratio timeline. |
| **Fundamentals panel** | Market cap · P/E · Forward P/E · EPS · Revenue · Profit margin · Debt/equity · Current ratio · ROE · Dividend yield · Beta. |
| **Analyst consensus** | Recommendation distribution · Mean/median/high/low price targets · Upside %. |
| **AI narrative** | Claude-generated analysis covering market context, technical setup, fundamental health, risks, and catalyst. |
| **News summary** | AI-synthesised headline sentiment. |
| **Peer comparison** | Side-by-side metrics vs. sector peers. |
| **Tooltip explanations** | Every indicator and metric has a plain-English info tooltip. |
| **Force refresh** | Bypass cache and request fresh data on demand. |
| **Stale data badge** | Cache age shown; amber warning when >15 minutes old. |

### 2.5 Caching & Performance

| Feature | Description |
|---|---|
| **Two-tier cache** | L1: in-process Python dict (max 100 entries, LRU eviction). L2: PostgreSQL `analysis_cache` table. |
| **Deterministic cache key** | SHA-256 of all analysis parameters (ticker, mode, period, all indicator settings). |
| **TTL by mode & hours** | API mode: 4h during market hours, 12h after close. Free mode: 2h / 6h. |
| **Cache hit SSE** | Cached results stream instantly via SSE without spawning an executor thread. |
| **Cache stats endpoint** | Admin-only `GET /api/v1/analysis/cache/stats` shows hit counts and top tickers. |
| **Cache invalidation** | Admin-only `DELETE /api/v1/analysis/cache` accepts optional `?ticker=&mode=` filters. |
| **Hit tracking** | `hit_count` and `last_hit_at` tracked per cache entry for analytics. |

### 2.6 Market Preferences

| Feature | Description |
|---|---|
| **Global market state** | Zustand store shared across Stock Analysis, Market Overview, and Research Dashboard pages. |
| **Country selection** | 7 countries available: US · India · UK · Germany · Canada · Japan · Australia. Default: "All Markets". |
| **Exchange multi-select** | When a country is selected, all its exchanges are selected by default. User can deselect individual exchanges. |
| **Suffix auto-append** | When exactly one exchange is selected, its suffix (e.g. `.NS`, `.L`, `.T`) is automatically appended to tickers. |
| **Browser timezone detection** | On first visit, the app detects home timezone and pre-selects the relevant market. |
| **localStorage persistence** | Preferences saved locally for immediate load on next visit. |
| **Backend persistence** | Preferences synced to the `users.preferences` JSONB column via `PUT /api/v1/profile/preferences`. |
| **Cross-device sync** | On login, preferences are fetched from the backend and applied, overriding localStorage. |
| **Currency propagation** | Selected country's currency symbol (₹, £, €, ¥, A$, CA$) flows through all price displays. |

### 2.7 Reporting & Export

| Feature | Description |
|---|---|
| **PDF download** | Per-pick report PDF with technicals, fundamentals, analyst ratings, and AI analysis. Available on licensed tiers. |
| **Email delivery** | Research session emailed to the user's registered address. Licensed tiers only. |
| **GDPR data export** | Full personal data export (profile, preferences, activity log) as a timestamped JSON file. Available to all users. |

### 2.8 Administration

| Feature | Description |
|---|---|
| **Admin panel** | Manage users, licenses, and view system audit logs. Admin role only. |
| **User management** | Create, activate, deactivate users; assign roles and licenses. |
| **License management** | Create and configure license tiers; set allowed modes, sectors, pick limits, and feature flags. |
| **System audit log** | Full audit trail of all user actions across the platform. Immutable at the database level. |
| **Cache management** | View cache statistics and selectively invalidate entries. |

---

## 3. Regulatory Compliance

### 3.1 Consent Management

**Regulation:** GDPR Art.7, DPDP Act 2023 (India) S.6, CCPA

**Implementation:**

- The registration form requires explicit tick of a consent checkbox before the "Create Account" button is enabled.
- Checkbox text: *"I understand that TradingResearch Pro provides AI-generated research for informational purposes only and does not constitute investment advice. I will not make investment decisions based solely on this platform. I agree to the Terms of Use and Privacy Policy."*
- The backend independently validates `consent == True` and rejects registration if absent (HTTP 400).
- `consent_at` timestamp (UTC) is stored on the `users` table row.
- Consent is never assumed or implied by continued use — it is a hard gate at account creation.

**Audit trail:** `consent_at` column preserved on the user record even after GDPR erasure (timestamp only, no PII).

---

### 3.2 Investment Disclaimers

**Regulation:** SEC Rule 206(4)-1, FCA COBS 4, SEBI Research Analyst Regulations 2014, MiFID II Art.24

**Implementation:**

| Location | Disclaimer |
|---|---|
| **Registration page** | In-consent-text: "does not constitute investment advice" |
| **Stock Analysis — result header** | Amber banner: "Not investment advice. AI-generated research for informational and research purposes only. Market data may be delayed up to 15 minutes. Consult a qualified financial advisor." |
| **AI Analysis panel footer** | Inline: "This AI-generated analysis is for informational purposes only and does not constitute investment advice. Past performance is not indicative of future results." |
| **Research Dashboard** | Compact amber banner: "Research only — not investment advice. AI-generated picks are for informational purposes. Data may be delayed." |
| **Market Overview footer** | "Not investment advice" appended to data attribution line. |
| **Auth page footer** | "Research only · Not financial advice" |

**Note:** These disclaimers appear unconditionally on every page containing market data or analysis output. They cannot be dismissed or hidden by the user.

---

### 3.3 AI Content Labelling

**Regulation:** EU AI Act Art.50, SEC AI disclosure guidance (2024), FCA PS24/1

**Implementation:**

Every AI-generated analysis block displays two persistent badges:

- **"Generated by Claude"** — identifies the AI system and model family.
- **"Not reviewed by a licensed analyst"** — explicitly states the content has not been reviewed, checked, or endorsed by a qualified financial professional.

A footer line below every AI analysis block repeats the disclaimer and references that past performance is not indicative of future results.

**Rationale:** Regulators increasingly require AI-generated financial content to be clearly distinguishable from human-authored research. These labels ensure users cannot be misled into treating AI output as professional advice.

---

### 3.4 Risk Classification

**Regulation:** MiFID II product governance (Art.9), SEBI Categorization Circular, FCA PROD

**Implementation:**

Every stock analysis result is classified into one of four risk levels, computed automatically from available data:

| Level | Criteria |
|---|---|
| **HIGH** | Beta > 1.5 OR \|daily change\| > 5% OR RSI < 20 OR RSI > 80 |
| **MEDIUM** | Default when data is present but HIGH/LOW criteria not met |
| **LOW** | Beta < 0.7 AND \|daily change\| < 2% AND RSI between 35–65 |
| **UNKNOWN** | Insufficient data to calculate (no beta, RSI, or price change available) |

The risk badge is displayed prominently alongside the signal pill (BUY/WATCH/HOLD/SELL) in the result banner so it is the first thing a user sees before reading any analysis.

**Limitation:** This is a simplified quantitative risk proxy. It does not substitute for a full MiFID II suitability assessment, which would also incorporate the investor's risk profile.

---

### 3.5 Stale Data Warnings

**Regulation:** MiFID II Art.24(5) (fair, clear, not misleading), FCA COBS 4.2, SEBI RA Regulations S.14

**Implementation:**

| Location | Trigger | Warning |
|---|---|---|
| **Stock Analysis — cached result** | `cache_age_seconds > 900` (15 min) | Amber badge: "Data may be stale (Xm old)" with Refresh link |
| **Market Overview** | `Date.now() - dataUpdatedAt > 900s` AND market is open | Full amber banner: "Market data is over 15 minutes old during market hours — prices may not reflect current conditions." |

**Market delay disclosure:** The footer of every Market Overview page permanently displays "~15 min delay during market hours" regardless of cache freshness.

---

### 3.6 Immutable Audit Log

**Regulation:** SEC Rule 17a-4, MiFID II Art.16(6), FCA SYSC 9, SEBI LODR S.15

**Implementation:**

A PostgreSQL database trigger (`trg_audit_no_delete`) raises a compliance exception on any `DELETE` statement targeting the `audit_log` table:

```
audit_log is immutable for regulatory compliance (SEC 17a-4 / MiFID II Art.16).
Contact your DPO to action a lawful erasure request.
```

The trigger fires `BEFORE DELETE FOR EACH ROW` and cannot be bypassed by application-layer code. Only a database superuser can drop the trigger.

**What is logged:**

| Event | Logged fields |
|---|---|
| Login / Logout | `user_id`, `username`, `action`, `timestamp` |
| Stock analysis request | `ticker`, `mode`, `period`, `indicators` |
| Research session run | `mode`, `sectors`, `top_n`, `filters` |
| Profile update | Field changed |
| Password change | Action only (no passwords stored) |
| Data export | Action + timestamp |
| Account deletion request | Action + timestamp |
| Admin user changes | Target user, action |
| Cache management | Scope of invalidation |

**Retention:** Audit log entries are never deleted. Usernames are anonymised on GDPR erasure (see §3.8) but timestamps and actions are permanently retained.

---

### 3.7 Data Portability (GDPR Art.20)

**Regulation:** GDPR Art.20, UK GDPR Art.20, DPDP Act 2023 S.11

**Implementation:**

Any authenticated user can download a complete export of all personal data held by the platform:

- **Endpoint:** `GET /api/v1/profile/export`
- **Frontend:** "Export My Data (JSON)" button in Profile → Data & Privacy section
- **Format:** Machine-readable JSON with a top-level `export_generated_at` ISO-8601 timestamp

**Export contents:**

```json
{
  "export_generated_at": "2026-06-14T10:00:00Z",
  "profile": {
    "id", "email", "username", "full_name", "role",
    "created_at", "last_login", "consent_at", "preferences"
  },
  "activity_log": [
    { "action": "...", "details": "...", "created_at": "..." }
  ],
  "note": "Exported under GDPR Article 20 — Right to Data Portability"
}
```

The export action is itself logged to the audit trail.

---

### 3.8 Right to Erasure (GDPR Art.17)

**Regulation:** GDPR Art.17, UK GDPR Art.17, DPDP Act 2023 S.13

**Implementation:**

Users can request account deletion from Profile → Data & Privacy → Delete Account. The flow requires:

1. User clicks "Delete My Account".
2. User enters their current password.
3. User confirms intent by reviewing a description of what will happen.
4. Backend verifies the password and executes erasure.

**What happens on erasure (pseudonymisation, not hard delete):**

| Field | Action |
|---|---|
| `email` | Replaced with `deleted_{id}@deleted.invalid` |
| `username` | Replaced with `deleted_{id}` |
| `full_name` | Replaced with `Deleted User` |
| `password_hash` | Cleared |
| `preferences` | Reset to `{}` |
| `is_active` | Set to `FALSE` |
| `deleted_at` | Set to current UTC timestamp |
| `audit_log.username` | Set to `NULL` (action/timestamp retained) |
| Sessions | All sessions invalidated |

**Why pseudonymisation and not deletion:**  
Financial regulations (SEC 17a-4, MiFID II Art.16) require activity records to be retained for 7 years. Hard-deleting audit log entries would violate these obligations. Pseudonymisation removes PII while preserving the compliance record — this approach is explicitly permitted under GDPR Recital 26 when re-identification is not reasonably possible.

The deletion action is logged before the anonymisation executes, creating a permanent record that an erasure was performed.

---

## 4. Regulatory Framework Mapping

| Regulation | Jurisdiction | Addressed by |
|---|---|---|
| **SEC Rule 17a-4** (record retention) | United States | §3.6 Immutable audit log |
| **SEC Rule 206(4)-1** (investment adviser marketing) | United States | §3.2 Disclaimers |
| **FINRA Rule 2210** (communications) | United States | §3.2 Disclaimers, §3.3 AI labelling |
| **MiFID II Art.16** (record keeping) | EU / UK | §3.6 Immutable audit log |
| **MiFID II Art.24** (fair, clear, not misleading) | EU / UK | §3.2 Disclaimers, §3.5 Stale data |
| **MiFID II Art.9** (product governance) | EU / UK | §3.4 Risk classification |
| **EU AI Act Art.50** (AI transparency) | EU | §3.3 AI content labelling |
| **GDPR Art.7** (consent) | EU / UK | §3.1 Consent at registration |
| **GDPR Art.17** (right to erasure) | EU / UK | §3.8 Account deletion |
| **GDPR Art.20** (data portability) | EU / UK | §3.7 Data export |
| **FCA COBS 4** (communicating with clients) | United Kingdom | §3.2 Disclaimers |
| **FCA PS24/1** (AI in financial services) | United Kingdom | §3.3 AI labelling |
| **SEBI RA Regulations 2014** | India | §3.2 Disclaimers |
| **SEBI LODR S.15** (record keeping) | India | §3.6 Immutable audit log |
| **DPDP Act 2023 S.6** (consent) | India | §3.1 Consent at registration |
| **DPDP Act 2023 S.11** (data portability) | India | §3.7 Data export |
| **DPDP Act 2023 S.13** (right to erasure) | India | §3.8 Account deletion |
| **CCPA** (consumer privacy) | California, USA | §3.1 Consent, §3.7 Export, §3.8 Erasure |

---

## 5. Data Architecture

### PostgreSQL Tables

| Table | Purpose | Retention |
|---|---|---|
| `users` | User accounts, roles, license links, preferences, consent timestamp | Indefinite (pseudonymised on erasure) |
| `licenses` | License tier configurations | Indefinite |
| `sessions` | JWT session tokens | Cleared on logout / erasure |
| `audit_log` | Immutable activity record | **Permanent** (cannot be deleted) |
| `analysis_cache` | Cached AI analysis results | TTL-based (4–12 hours) |

### Personal Data Held

| Data point | Category | Legal basis |
|---|---|---|
| Email address | Contact PII | Contract performance |
| Username | Pseudonym | Contract performance |
| Full name | Identity PII | Contract performance |
| Password hash (bcrypt) | Security credential | Contract performance |
| `consent_at` timestamp | Consent record | Legal obligation |
| Market preferences (JSONB) | Behavioural | Legitimate interests |
| Activity log entries | Usage | Legal obligation (financial regulations) |
| IP address (audit log) | Technical PII | Legitimate interests / security |

---

## 6. Known Limitations & Roadmap

### Current Limitations

| Area | Limitation |
|---|---|
| **Research analyst registration** | The platform is not registered as a Research Analyst with SEBI. Operating in India with paying users may require RA registration. |
| **KYC / AML** | No identity verification or accredited investor checks are implemented. High-risk market content (leveraged ETFs, penny stocks) is unrestricted within license tiers. |
| **Suitability assessment** | No investor risk profile collected. MiFID II requires suitability checks before providing personalised recommendations. |
| **Data residency** | User data is stored in a single AWS region. Indian users' data may need to remain in India under DPDP Act rules once data localisation requirements take effect. |
| **SOC 2** | No formal SOC 2 audit has been conducted. |
| **Terms of Use / Privacy Policy** | Referenced in the consent checkbox but not yet drafted as standalone legal documents. |

### Compliance Roadmap

| Priority | Item | Regulation |
|---|---|---|
| High | Draft Terms of Use and Privacy Policy | GDPR, CCPA, DPDP |
| High | KYC identity verification at registration | AML / Financial Services |
| High | Accredited investor / suitability check | MiFID II, SEBI |
| Medium | Concurrent session limits | Licensing / credential sharing |
| Medium | IP whitelisting for institutional clients | Enterprise security |
| Medium | Data residency (India AWS region) | DPDP Act 2023 |
| Medium | Sanctions screening (OFAC / EU / UN) | AML |
| Low | SOC 2 Type II audit | Enterprise procurement |
| Low | Penetration testing schedule | Security best practice |
| Low | Business continuity / DR plan | Operational resilience |

---

*This document describes features and compliance controls as implemented. It does not constitute legal advice. Consult qualified legal counsel before operating in regulated financial services jurisdictions.*
