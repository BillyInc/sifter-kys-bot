# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Sifter KYS is a full-stack Solana token analytics platform featuring Twitter caller analysis, professional wallet pump detection, real-time wallet activity monitoring, Telegram alerts, referral/points gamification, and Elite 100 leaderboards.

## Commands

### Development
```bash
# Start both backend and frontend
./start-dev.sh
# Backend: http://localhost:5000
# Frontend: http://localhost:5173

# Or start separately:
cd Backend && make run          # Flask dev server
cd frontend && pnpm run dev     # Vite dev server
```

### Backend (in Backend/ — uses uv)
```bash
uv sync               # Install dependencies (creates .venv)
uv run python app.py   # Development server (port 5000)
uv run pytest          # Run tests

# Or via Makefile:
make install          # uv sync
make run              # Dev server (port 5000)
make run-prod         # Production with Gunicorn
make lint             # flake8 + pyright
make test             # pytest
make format           # black
```

### Frontend (in frontend/)
```bash
pnpm install          # Install dependencies
pnpm run dev          # Vite dev server (port 5173)
pnpm run build        # Production build
```

### Workers & Scheduling
```bash
# Celery worker (production scheduled jobs)
celery -A celery_app worker --loglevel=info
celery -A celery_app beat --loglevel=info

# System cron alternative
python cron_jobs.py daily|weekly|four_week|refresh_ath
```

## Architecture

### Backend (Python Flask)
- **Entry**: `Backend/app.py` - Flask app factory with blueprints, APScheduler for in-process cron
- **Routes**: `Backend/routes/` - API endpoints
  - `analyze.py` - Token analysis and pump detection
  - `wallets.py` - Wallet monitoring, PnL, health scoring, Elite 100, discovery
  - `watchlist.py` - Watchlist CRUD operations
  - `telegram.py` - Telegram bot integration
  - `auth.py` - User signup with referral code support
  - `referral_points_routes.py` - Referral codes, points, leaderboards, streaks
  - `token_routes.py` - Token search and info (proxies SolanaTracker)
  - `user_settings.py` - User preferences CRUD
  - `support.py` - Support ticket submission
  - `whop_webhook.py` - Whop payment webhook handler (subscription lifecycle)
- **Services**: `Backend/services/` - Core business logic
  - `wallet_analyzer.py` - 6-step professional wallet analysis (60% timing, 30% profit, 10% overall scoring)
  - `wallet_monitor.py` - Real-time background wallet monitoring
  - `telegram_notifier.py` - Telegram notifications
  - `token_analyzer.py` - Twitter caller analysis
  - `watchlist_manager.py` - Premier League-style watchlist ranking (zones, form, degradation alerts)
  - `watchlist_stats_updater.py` - Scheduled stats refresh and reranking orchestration
  - `elite_100_manager.py` - Elite 100 and Community Top 100 cross-user leaderboards
  - `referral_points_manager.py` - Referral codes, commissions, points, streaks, tiers
  - `worker_tasks.py` - RQ-based 3-phase parallel analysis pipeline
- **Scheduling**: Three coexisting systems (use one per deployment):
  - `celery_app.py` + `Backend/services/tasks.py` - Celery Beat for production scheduled jobs
  - `app.py` APScheduler - In-process scheduler for single-process deployments
  - `cron_jobs.py` - System cron entry point
- **Auth**: `Backend/auth.py` - JWT authentication with `@require_auth` and `@optional_auth` decorators
- **Config**: `Backend/config.py` - Centralized configuration with rate limits

### Frontend (React 19 + Vite)
- **Entry**: `frontend/src/App.jsx` - Main app with slide-out panel navigation
- **Contexts**: `frontend/src/contexts/`
  - `AuthContext.jsx` - Supabase authentication state
  - `WalletContext.jsx` - Solana wallet adapter integration
- **Panels**: `frontend/src/components/panels/` - Slide-out panel system
  - `SlideOutPanel.jsx` - Base animated panel wrapper (slide-in with backdrop blur)
  - `AnalyzePanel.jsx` - Token analysis UI
  - `TrendingPanel.jsx` - Trending runners display
  - `DiscoveryPanel.jsx` - Auto wallet discovery with configurable filters
  - `WatchlistPanel.jsx` - Watchlist with expandable wallet cards
  - `PremiumElite100Panel.jsx` - Elite 100 leaderboard (premium-gated, CSV export)
  - `Top100CommunityPanel.jsx` - Community most-added wallets
  - `QuickAddWalletPanel.jsx` - Quick wallet add form
  - `ProfilePanel.jsx` - Profile hub with sub-panel routing (Settings, Telegram, Dashboard, Referrals)
  - `SettingsSubPanel.jsx` - User settings form
  - `ReferralDashboardSubPanel.jsx` - Referral stats, points, streak, leaderboard rank
  - `MyDashboardPanel.jsx` - User stats with skeleton loading and in-memory cache
  - `HelpSupportPanel.jsx` - Support ticket submission
- **Dashboard**: `frontend/src/components/dashboard/DashboardHome.jsx` - Landing screen with quick action grid
- **Key Components**:
  - `WatchlistExpandedCard.jsx` - Expandable wallet card (zones, form dots, two-step delete)
  - `WalletLeagueTable.jsx` - Wallet ranking table
  - `WalletActivityMonitor.jsx` - Real-time activity display
  - `TelegramSettings.jsx` - Telegram connection UI
  - `NetworkGraph.jsx` - D3 visualization

### Data Layer Architecture

**Supabase PostgreSQL** (schema: `sifter_dev`) - Primary persistent storage:
- `users` - User accounts and profiles (includes `subscription_tier`)
- `watchlist_accounts` - Twitter account watchlists
- `wallet_watchlist` - Wallet watchlists with alert settings
- `wallet_notifications` - User notifications
- `telegram_users` - Telegram connection mapping
- `wallet_performance_history` - Historical position tracking
- `wallet_activity` - Real-time wallet trade events
- `wallet_monitor_status` - Monitor health tracking
- `referral_codes` - User referral codes with click/signup/conversion counters
- `referrals` - Referral relationships (referrer/referee, status, commissions)
- `referral_earnings` - Individual commission payment records
- `user_points` - Points balance, streak, tier, level per user
- `point_transactions` - Audit log of all point awards
- `elite_100_cache` - Cached Elite 100 and Community Top 100 results (1hr TTL)
- `user_settings` - User preferences (timezone, theme, alert settings)
- `support_tickets` - User support ticket submissions
- `analysis_jobs` - Async analysis job status tracking (phase, progress, results)
- **Schema file**: `Backend/supabase_schema.sql`
- **Client**: `Backend/services/supabase_client.py`
- **DB Layer**: `Backend/db/watchlist_db.py`

**DuckDB** - Analytics caching (local):
- `wallet_token_cache` - Wallet-to-token mappings
- `wallet_runner_cache` - Wallet runner hit stats
- `token_runner_cache` - Token runner data

**Redis** - Job queue, scheduling, and caching:
- RQ job queue for async analysis (3-phase parallel pipeline)
- Celery broker and result backend for scheduled jobs
- Job results caching (1hr TTL with `job_result:{job_id}` keys)
- Custom config: `Backend/redis.conf` (2GB max memory, LRU eviction, AOF persistence)

### ClickHouse Analytics Pipeline

ClickHouse is the analytical computation layer. Supabase remains source of truth for user data. Redis caches results for API reads. ClickHouse is never queried directly from API handlers.

**Data flow:** SolanaTracker -> Celery tasks -> ClickHouse -> (MV auto-aggregates) -> Redis cache -> API response

**Tables** (database: `kys`, all ReplacingMergeTree — INSERT only, never UPDATE):
- `token_scans` — one row per token per scan event
- `wallet_token_stats` — one row per wallet per token (MV fires on INSERT)
- `wallet_aggregate_stats` — auto-maintained by `mv_wallet_aggregate` materialized view
- `wallet_weekly_snapshots` — Sunday point-in-time snapshots
- `leaderboard_results` — cached leaderboard output

**Key rules:**
- Always use `SELECT ... FINAL` to read deduplicated rows
- All ClickHouse writes happen inside Celery tasks, never in API handlers
- Use `ch.insert()` for bulk inserts (not `ch.execute()` with VALUES)
- Schema init: `python scripts/init_clickhouse.py`
- Schema DDL: `Backend/services/clickhouse_schema.py`
- Client: `Backend/services/clickhouse_client.py`

**Celery Beat Schedule:**
- Token discovery: every 5 min (`tasks/token_discovery.py`)
- Wallet qualification: on-demand per token (`tasks/wallet_qualification.py`)
- Daily stats sync (CH -> Supabase): 3am UTC
- Weekly rerank + Elite 100: Sunday 4am UTC
- 4-week degradation: 1st & 29th of month 5am UTC

### External APIs
- Twitter (Tweepy) - Social data
- Birdeye - Token metrics, historical trades
- SolanaTracker - Wallet data, transactions, token search
- Telegram Bot - User notifications
- Whop - Payment/subscription webhooks

## Environment Variables

Backend `.env`:
```
SUPABASE_URL=
SUPABASE_SERVICE_KEY=
TWITTER_BEARER_TOKEN=
BIRDEYE_API_KEY=
SOLANATRACKER_API_KEY=
TELEGRAM_BOT_TOKEN=
CLICKHOUSE_HOST=
CLICKHOUSE_PORT=8443
CLICKHOUSE_USER=default
CLICKHOUSE_PASSWORD=
CLICKHOUSE_DATABASE=kys
WHOP_WEBHOOK_SECRET=
PORT=5000
```

Frontend `.env`:
```
VITE_SUPABASE_URL=
VITE_SUPABASE_ANON_KEY=
VITE_API_URL=http://localhost:5000
VITE_WALLETCONNECT_PROJECT_ID=
```

## Key Business Logic

### Watchlist League System (`watchlist_manager.py`)
- Position scoring: 40% 7d ROI + 30% 7d runners + 20% win rate + 10% consistency
- Zones: Elite / midtable / monitoring / relegation (scales with watchlist size)
- Runners threshold: 5x+ price multiplier
- Degradation alerts: 6 types with yellow/orange/red severity levels
- W/D/L form tracking over last 5 trades

### Subscription Tiers (via Whop)
- `free` / `pro` / `elite` - managed via webhook events
- Points multipliers: free 1x, pro 2x, elite 3x

### Referral System (`referral_points_manager.py`)
- Commission: 30% first month, 5% recurring (up to 5 years)
- Points with daily caps per action type
- Daily streak tracking with weekly/monthly bonus awards

## Rate Limiting

Configured in `Backend/config.py` (currently disabled in production):
- `/api/analyze`: 5/hour, 20/day
- `/api/wallets`: 5/hour
- `/api/watchlist` (writes): 30/hour
- Default: 50/hour, 200/day

## Skills

Load these skills when working on this codebase:

### Backend (Python Flask)
- `python-patterns` - Python development principles, async patterns, type hints
- `python-testing-patterns` - pytest fixtures, mocking, TDD
- `api-designer` - REST API design, error handling, versioning

### Frontend (React 19 + Vite)
- `react-dev` - React 19, hooks, Server Components, TypeScript patterns
- `javascript-mastery` - ES6+, async/await, functional patterns
- `modern-javascript-patterns` - Modern JS best practices

### Database (Supabase PostgreSQL)
- `supabase-postgres-best-practices` - Postgres optimization, queries, schema design
- `nextjs-supabase-auth` - Supabase Auth patterns (applies to any framework)
- `database-schema-designer` - Schema design, migrations, indexing

### Quality & Security
- `senior-qa` - Testing strategies, E2E testing, coverage analysis
- `senior-security` - Application security, auth patterns, OWASP compliance

### Workflow
- `git-workflow` - Git commits, branches, pull requests

### DevOps & CI/CD
- `devops-engineer` - CI/CD pipelines, containerization, infrastructure as code
- `ci-cd-pipeline-builder` - GitHub Actions, Vercel, deployment workflows
- `docker-expert` - Docker, multi-stage builds, container security
- `linux-server-expert` - Linux server admin, Nginx, systemd, firewall
