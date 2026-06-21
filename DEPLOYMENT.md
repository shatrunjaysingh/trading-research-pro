# TradingResearch Pro — Deployment & Reference Guide

Last updated: 2026-06-13

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Repository Layout](#2-repository-layout)
3. [Environment Variables](#3-environment-variables)
4. [Database Details](#4-database-details)
5. [Users Created](#5-users-created)
6. [License Tiers](#6-license-tiers)
7. [Running Locally (Dev)](#7-running-locally-dev)
8. [Running with Docker Compose](#8-running-with-docker-compose)
9. [API Endpoints](#9-api-endpoints)
10. [Frontend Pages](#10-frontend-pages)
11. [RBAC — Roles & Permissions](#11-rbac--roles--permissions)
12. [AWS Deployment Path](#12-aws-deployment-path)
13. [Troubleshooting](#13-troubleshooting)

---

## 1. Architecture Overview

```
┌─────────────────────────────────────────────────────┐
│                     Browser                         │
│          React 18 + TypeScript + Vite               │
│              http://localhost:5173 (dev)            │
│              http://localhost:3000  (Docker)        │
└───────────────────────┬─────────────────────────────┘
                        │ /api/v1/*  (proxied)
┌───────────────────────▼─────────────────────────────┐
│              FastAPI (Python 3.12+)                 │
│              http://localhost:8000                  │
│   JWT auth · SSE streaming · RBAC middleware        │
└───────────────────────┬─────────────────────────────┘
                        │ psycopg2
┌───────────────────────▼─────────────────────────────┐
│           PostgreSQL 16 (Docker)                    │
│           localhost:5433  →  container:5432         │
│           DB: trading_research                      │
└─────────────────────────────────────────────────────┘
```

**Stack:**

| Layer | Technology |
|---|---|
| Frontend | React 18, TypeScript, Vite, TailwindCSS, TanStack Query v5, Zustand, React Router v6 |
| Backend | FastAPI, Pydantic v2, python-jose (JWT HS256), SSE streaming |
| Database | PostgreSQL 16 (Alpine Docker image) |
| AI Engine | Anthropic Claude (claude-sonnet-4-6) via `anthropic` SDK |
| Market Data | yfinance |
| Auth | JWT (24h expiry), bcrypt password hashing, session invalidation via `sid` claim |

---

## 2. Repository Layout

```
trading-agent/
├── app.py                  # Legacy Streamlit UI (still functional)
├── research.py             # Core research engine (yfinance + Claude)
├── database.py             # PostgreSQL connection pool + all DB functions
├── auth.py                 # Password hashing, session management, RBAC helpers
├── config.yaml             # Asset universe, sector config, email settings
├── .env                    # Secrets (not committed to git)
├── docker-compose.yml      # 4 services: db, backend, frontend, pgadmin
│
├── backend/
│   ├── main.py             # FastAPI app entry point
│   ├── config.py           # pydantic-settings (reads .env)
│   ├── auth_middleware.py  # JWT bearer extraction, get_current_user
│   ├── routers/
│   │   ├── auth.py         # /api/v1/auth/*
│   │   ├── research.py     # /api/v1/research/*
│   │   ├── analysis.py     # /api/v1/analysis/stock  (individual stock)
│   │   ├── admin.py        # /api/v1/admin/*
│   │   └── profile.py      # /api/v1/profile/*
│   ├── schemas/
│   │   ├── auth.py         # UserOut, LoginRequest, TokenResponse
│   │   ├── admin.py        # CreateUserRequest, LicenseOut, AuditLogOut
│   │   ├── research.py     # ResearchRequest, ResearchConfigOut
│   │   └── analysis.py     # StockAnalysisRequest, StockAnalysisResult
│   └── services/
│       ├── jwt.py              # create_access_token, decode_access_token
│       ├── research_runner.py  # Async SSE wrapper for run_research()
│       └── stock_analyzer.py   # Single-stock deep analysis + AI narrative
│
└── frontend/
    ├── src/
    │   ├── App.tsx                    # Router + AuthGuard + AdminGuard
    │   ├── pages/
    │   │   ├── AuthPage.tsx           # Login / Register
    │   │   ├── ResearchDashboard.tsx  # Sector research runner
    │   │   ├── StockAnalysisPage.tsx  # Individual stock analysis
    │   │   ├── AdminPanel.tsx         # User/license management
    │   │   └── ProfilePage.tsx        # Account settings
    │   ├── api/                # Fetch wrappers (auth, research, analysis, admin, profile)
    │   ├── store/auth.ts       # Zustand auth store (persists token to localStorage)
    │   ├── types/index.ts      # All TypeScript interfaces
    │   └── components/         # Sidebar, PickCard, SectorSection, ui/*
    ├── vite.config.ts          # Proxies /api → http://localhost:8000
    ├── nginx.conf              # Production proxy config (Docker)
    └── Dockerfile              # Multi-stage: node builder → nginx
```

---

## 3. Environment Variables

File: `/Users/shatrunjaysingh/trading-agent/.env`

```env
# Database
DATABASE_URL=postgresql://trading_user:trading_pass@localhost:5433/trading_research
DB_HOST=localhost
DB_PORT=5433
DB_NAME=trading_research
DB_USER=trading_user
DB_PASSWORD=trading_pass

# Email (Gmail App Password — NOT your account password)
EMAIL_SENDER=your_gmail@gmail.com
EMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx
```

**Additional runtime variables** (set in shell or docker-compose.yml):

| Variable | Default | Notes |
|---|---|---|
| `SECRET_KEY` | `change-me-in-production` | JWT signing secret — **change before production** |
| `ANTHROPIC_API_KEY` | _(empty)_ | Required for AI/api research mode and AI stock analysis |
| `CORS_ORIGINS` | `["http://localhost:5173","http://localhost:3000"]` | Allowed frontend origins |

---

## 4. Database Details

| Setting | Value |
|---|---|
| Engine | PostgreSQL 16 (Alpine) |
| Database name | `trading_research` |
| Username | `trading_user` |
| Password | `trading_pass` |
| Host (local dev) | `localhost` |
| Port (local dev) | **5433** (Docker maps host:5433 → container:5432) |
| Host (Docker internal) | `db` (Docker service name) |
| Port (Docker internal) | `5432` |
| Current size | ~8 MB |
| Data volume | `postgres_data` (Docker named volume, persists across restarts) |

**Connection strings:**

```
# Local dev / scripts
postgresql://trading_user:trading_pass@localhost:5433/trading_research

# Inside Docker network (backend service → db service)
postgresql://trading_user:trading_pass@db:5432/trading_research
```

**Tables:**

| Table | Purpose |
|---|---|
| `users` | All user accounts (email, hashed password, role, license_id, active flag) |
| `licenses` | License tier definitions (modes, sectors, limits, feature flags) |
| `sessions` | Active JWT sessions (sid → user_id mapping, used for logout invalidation) |
| `audit_log` | Every user action recorded with actor, action, details, IP, timestamp |

**Connect via psql:**

```bash
psql "postgresql://trading_user:trading_pass@localhost:5433/trading_research"
```

**pgAdmin (optional GUI):**

```bash
docker compose --profile tools up pgadmin -d
# Open: http://localhost:5050
# pgAdmin login:  admin@tradingresearch.com / Admin123!
# Add server:     host=db  port=5432  user=trading_user  pass=trading_pass
```

---

## 5. Users Created

### System User (auto-seeded on first `init_db` run)

| ID | Email | Username | Password | Role | License |
|---|---|---|---|---|---|
| 1 | admin@tradingresearch.com | admin | **Admin123!** | admin | Enterprise |

### Test Users (created manually)

| ID | Email | Username | Role | License |
|---|---|---|---|---|
| 3 | analyst@test.com | testanalyst | analyst | Professional |
| 4 | trader@test.com | testtrader | trader | Free Tier |
| 5 | viewer@test.com | testviewer | viewer | Free Tier |

> ID 2 was skipped during seeding — this is normal, caused by a sequence increment on a failed insert.

**Password policy:** Minimum 8 characters, must contain at least one uppercase letter, one lowercase letter, and one digit.

**Reset a password from Admin Panel:**
Admin Panel → Users tab → click "Reset Password" next to the user.

**Reset a password via CLI:**
```bash
cd /Users/shatrunjaysingh/trading-agent
DATABASE_URL="postgresql://trading_user:trading_pass@localhost:5433/trading_research" \
python3 -c "from database import change_password; change_password(3, 'NewPassword1!'); print('done')"
```

---

## 6. License Tiers

| ID | Name | Tier | Max Users | Modes | Sectors | Max Picks | Email | Export | Admin |
|---|---|---|---|---|---|---|---|---|---|
| 1 | Free Tier | free | 1 | free | technology, consumer | 3 | No | No | No |
| 2 | Professional | professional | 5 | free, api | all | 10 | Yes | Yes | No |
| 3 | Enterprise | enterprise | unlimited | free, api | all | 10 | Yes | Yes | Yes |

Assign a license to a user via Admin Panel → Users → Edit, or via CLI:

```bash
DATABASE_URL="postgresql://trading_user:trading_pass@localhost:5433/trading_research" \
python3 -c "from database import update_user; update_user(3, license_id=2); print('done')"
```

---

## 7. Running Locally (Dev)

### Prerequisites
- Python 3.12+
- Node.js 20+
- Docker Desktop (for the PostgreSQL container)

### Step 1 — Start the database

```bash
cd /Users/shatrunjaysingh/trading-agent
docker compose up db -d
# Wait ~5 seconds for Postgres to be ready
```

### Step 2 — Install Python dependencies (first time only)

```bash
pip3 install --break-system-packages fastapi "uvicorn[standard]" pydantic pydantic-settings \
  "python-jose[cryptography]" "passlib[bcrypt]" psycopg2-binary yfinance anthropic \
  pyyaml pytz requests
```

### Step 3 — Start the backend

```bash
cd /Users/shatrunjaysingh/trading-agent
DATABASE_URL="postgresql://trading_user:trading_pass@localhost:5433/trading_research" \
python3 -m uvicorn backend.main:app --port 8000 --reload
```

### Step 4 — Start the frontend

```bash
cd /Users/shatrunjaysingh/trading-agent/frontend
npm install        # first time only
npm run dev
```

### Access

| Service | URL |
|---|---|
| Frontend (React) | http://localhost:5173 |
| Backend API | http://localhost:8000 |
| API Docs (Swagger) | http://localhost:8000/docs |
| API Health | http://localhost:8000/health |

---

## 8. Running with Docker Compose

### Build and start all services

```bash
cd /Users/shatrunjaysingh/trading-agent

# Edit .env to set ANTHROPIC_API_KEY, EMAIL_*, and a strong SECRET_KEY
docker compose up --build -d
```

### Services

| Service | Container | Host Port | Purpose |
|---|---|---|---|
| `db` | trading_db | **5433** | PostgreSQL 16 |
| `backend` | trading_backend | **8000** | FastAPI |
| `frontend` | trading_frontend | **3000** | React via nginx |
| `pgadmin` | trading_pgadmin | **5050** | DB admin GUI (use `--profile tools`) |

### Useful commands

```bash
# Logs
docker compose logs -f backend
docker compose logs -f frontend

# Restart a service
docker compose restart backend

# Stop all
docker compose down

# Stop and wipe database volume
docker compose down -v

# Start with pgAdmin
docker compose --profile tools up -d

# Shell into backend container
docker exec -it trading_backend bash

# Shell into database
docker exec -it trading_db psql -U trading_user -d trading_research
```

### URLs (Docker mode)

| Service | URL |
|---|---|
| Frontend | http://localhost:3000 |
| Backend API | http://localhost:8000 |
| pgAdmin | http://localhost:5050 |

---

## 9. API Endpoints

Base URL: `http://localhost:8000/api/v1`

All protected endpoints require: `Authorization: Bearer <jwt_token>`

### Auth

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/auth/login` | Public | Email + password → JWT token |
| POST | `/auth/register` | Public | Create account → JWT token |
| POST | `/auth/logout` | Required | Invalidate current session |
| GET | `/auth/me` | Required | Current user profile |

### Research

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/research/config` | Required | Available modes, sectors, max_picks for current user |
| POST | `/research/run` | Required | Stream SSE research across selected sectors |

**`/research/run` body:**
```json
{
  "mode": "free",
  "selected_sectors": ["technology", "finance"],
  "top_n": 5,
  "max_price": null,
  "send_email": false
}
```

### Stock Analysis

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/analysis/stock` | Required | Stream SSE deep analysis for a single ticker |

**`/analysis/stock` body:**
```json
{
  "ticker": "AAPL",
  "mode": "free",
  "time_period": "3m",
  "indicators": ["rsi", "macd", "sma50", "sma200", "volume"],
  "include_news": true,
  "include_fundamentals": true,
  "include_peers": false
}
```

Valid `time_period`: `1d` `1w` `1m` `3m` `6m` `1y`

Valid `indicators`: `rsi` `macd` `sma20` `sma50` `sma200` `bollinger` `volume`

### Admin _(admin role required)_

| Method | Path | Description |
|---|---|---|
| GET | `/admin/users` | List all users with license fields |
| POST | `/admin/users` | Create a new user |
| PATCH | `/admin/users/{id}` | Update user fields |
| POST | `/admin/users/{id}/activate` | Activate a user |
| POST | `/admin/users/{id}/deactivate` | Deactivate a user |
| POST | `/admin/users/{id}/reset-password` | Reset a user's password |
| GET | `/admin/licenses` | List all licenses |
| POST | `/admin/licenses` | Create a license |
| PATCH | `/admin/licenses/{id}` | Update a license |
| POST | `/admin/licenses/{id}/deactivate` | Deactivate a license |
| GET | `/admin/audit` | Audit log (supports `?limit=200&user_id=3`) |

### Profile

| Method | Path | Description |
|---|---|---|
| GET | `/profile` | Get own profile |
| PATCH | `/profile` | Update name / username |
| POST | `/profile/change-password` | Change own password |
| GET | `/profile/audit` | Own audit history |

---

## 10. Frontend Pages

| URL | Page | Access |
|---|---|---|
| `/login` | Login / Register | Public |
| `/research` | Sector Research Dashboard | All authenticated users |
| `/stocks` | Individual Stock Analysis | All authenticated users |
| `/admin` | Admin Panel (users, licenses, audit log) | Admin role only |
| `/profile` | Profile & password change | All authenticated users |

---

## 11. RBAC — Roles & Permissions

### Role capabilities

| Permission | admin | analyst | trader | viewer |
|---|---|---|---|---|
| Run research | Yes | Yes | Yes | Yes |
| Run stock analysis | Yes | Yes | Yes | Yes |
| Send email report | License | License | No | No |
| Export results | License | License | No | No |
| Access admin panel | Yes | No | No | No |

### License feature matrix

| Feature | Free | Professional | Enterprise |
|---|---|---|---|
| Research modes | free only | free + api | free + api |
| Sectors available | technology, consumer | all 9 | all 9 |
| Max picks | 3 | 10 | 10 |
| Email delivery | No | Yes | Yes |
| Export | No | Yes | Yes |
| Admin panel access | No | No | Yes |

### All 9 sectors

`technology` · `pharma` · `healthcare` · `finance` · `energy` · `consumer` · `industrials` · `crypto` · `penny`

---

## 12. AWS Deployment Path

### Recommended architecture

```
Route 53 → ALB (HTTPS 443) → ECS Fargate cluster
                                  ├── backend task  (port 8000)
                                  └── frontend task (port 80)
                                           ↓
                                  RDS PostgreSQL 16 (db.t3.micro+)
```

### Steps

**1. Push images to ECR:**
```bash
aws ecr create-repository --repository-name trading-backend
aws ecr create-repository --repository-name trading-frontend
docker build -t trading-backend -f backend/Dockerfile .
docker build -t trading-frontend ./frontend
# tag and push to your ECR URIs
```

**2. Create RDS instance:**
- Engine: PostgreSQL 16
- DB name: `trading_research`, User: `trading_user`
- Security group: allow port 5432 from ECS task SG only

**3. ECS task environment variables:**
- `DATABASE_URL` — RDS endpoint (use port 5432 internally)
- `SECRET_KEY` — strong random string (use Secrets Manager)
- `ANTHROPIC_API_KEY` — from Secrets Manager
- `EMAIL_SENDER` / `EMAIL_APP_PASSWORD` — from Secrets Manager
- `CORS_ORIGINS` — your production frontend domain

**4. DB init:** FastAPI lifespan runs `init_db()` automatically on startup — no manual step needed.

**5. ALB listener rules:** Forward `/api/*` to backend target group, `/*` to frontend target group.

---

## 13. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Backend: `role "trading_user" does not exist` | `.env` not loaded; backend reads OS env | Start uvicorn with explicit `DATABASE_URL=... python3 -m uvicorn ...` |
| Port 5432 conflict | Local Postgres occupies 5432 | Docker DB uses host port **5433** — ensure connection string says `:5433` |
| `admin/users` returns HTTP 500 | (Fixed) Was missing license LEFT JOIN | Now uses `get_all_users_with_licenses()` in auth_middleware.py |
| `/research/config` returns empty modes/sectors | User row missing license fields | Fixed — `_get_user_with_license()` does LEFT JOIN on every auth call |
| Frontend blank / white screen | Vite not running or wrong port | Run `npm run dev` in `frontend/`; ensure backend on 8000 |
| SSE stream cuts off behind nginx | Proxy buffering enabled | `proxy_buffering off` is set in nginx.conf; also set `X-Accel-Buffering: no` header |
| `anthropic` not installed | Missing Python package | `pip3 install anthropic --break-system-packages` |
| Email fails to send | Wrong Gmail credential | Use a Gmail **App Password** (16-char), not account password; requires 2FA enabled |
| `SyntaxError` in app.py | Nested f-string escape chars | Fixed — `app.py` compiles clean on Python 3.12+ |

### Quick health check commands

```bash
# Backend health
curl http://localhost:8000/health

# Get admin token
curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@tradingresearch.com","password":"Admin123!"}' | python3 -m json.tool

# List users (replace TOKEN)
curl -s -H "Authorization: Bearer TOKEN" \
  http://localhost:8000/api/v1/admin/users | python3 -m json.tool

# Quick stock analysis test
curl -s -X POST http://localhost:8000/api/v1/analysis/stock \
  -H "Authorization: Bearer TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"ticker":"AAPL","mode":"free","time_period":"1m","indicators":["rsi","sma50"],"include_fundamentals":true,"include_news":false,"include_peers":false}'
```


 "admin@tradingresearch.com:Admin123!" "analyst@test.com:Analyst123!" "trader@test.com:Trader123!" "viewer@test.com:Viewer123!

  Login credentials:

  ┌───────────────────────────┬─────────────┬─────────────────────┐
  │           Email           │  Password   │        Role         │
  ├───────────────────────────┼─────────────┼─────────────────────┤
  │ admin@tradingresearch.com │ Admin123!   │ Admin (full access) │
  ├───────────────────────────┼─────────────┼─────────────────────┤
  │ analyst@test.com          │ Analyst123! │ Analyst             │
  ├───────────────────────────┼─────────────┼─────────────────────┤
  │ trader@test.com           │ Trader123!  │ Trader              │
  ├───────────────────────────┼─────────────┼─────────────────────┤
  │ viewer@test.com           │ Viewer123!  │ Viewer              │
  └───────────────────────────┴─────────────┴───────────────────
