# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Sifter KYS is a full-stack Solana token analytics platform featuring Twitter caller analysis, professional wallet pump detection, real-time wallet activity monitoring, and Telegram alerts.

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

### Backend (in Backend/)
```bash
make install          # Setup virtualenv and install dependencies
make run              # Development server (port 5000)
make run-prod         # Production with Gunicorn
make lint             # Run flake8 + pyright
make test             # Run pytest
make pm2-start        # Start with PM2 process manager
make pm2-logs         # View PM2 logs
```

### Frontend (in frontend/)
```bash
pnpm install          # Install dependencies
pnpm run dev          # Vite dev server (port 5173)
pnpm run build        # Production build
```

## Architecture

### Backend (Python Flask)
- **Entry**: `Backend/app.py` - Flask app factory with blueprints
- **Routes**: `Backend/routes/` - API endpoints
  - `analyze.py` - Token analysis and pump detection
  - `wallets.py` - Wallet monitoring, PnL, health scoring
  - `watchlist.py` - Watchlist CRUD operations
  - `telegram.py` - Telegram bot integration
- **Services**: `Backend/services/` - Core business logic
  - `wallet_analyzer.py` - 6-step professional wallet analysis (60% timing, 30% profit, 10% overall scoring)
  - `wallet_monitor.py` - Real-time background wallet monitoring
  - `telegram_notifier.py` - Telegram notifications
  - `token_analyzer.py` - Twitter caller analysis
- **Auth**: `Backend/auth.py` - JWT authentication with `@require_auth` and `@optional_auth` decorators
- **Config**: `Backend/config.py` - Centralized configuration with rate limits

### Frontend (React 19 + Vite)
- **Entry**: `frontend/src/App.jsx` - Main app with dual modes (Twitter/Wallet)
- **Contexts**: `frontend/src/contexts/`
  - `AuthContext.jsx` - Supabase authentication state
  - `WalletContext.jsx` - Solana wallet adapter integration
- **Key Components**:
  - `WalletLeagueTable.jsx` - Wallet ranking table
  - `WalletActivityMonitor.jsx` - Real-time activity display
  - `TelegramSettings.jsx` - Telegram connection UI
  - `NetworkGraph.jsx` - D3 visualization

### Data Layer Architecture

**Supabase PostgreSQL** (schema: `sifter_dev`) - Primary persistent storage:
- `users` - User accounts and profiles
- `watchlist_accounts` - Twitter account watchlists
- `wallet_watchlist` - Wallet watchlists with alert settings
- `wallet_notifications` - User notifications
- `telegram_users` - Telegram connection mapping
- `wallet_performance_history` - Historical position tracking
- `wallet_activity` - Real-time wallet trade events
- `wallet_monitor_status` - Monitor health tracking
- **Schema file**: `Backend/supabase_schema.sql`
- **Client**: `Backend/services/supabase_client.py`
- **DB Layer**: `Backend/db/watchlist_db.py`

**DuckDB** - Analytics caching (local):
- `wallet_token_cache` - Wallet-to-token mappings
- `wallet_runner_cache` - Wallet runner hit stats
- `token_runner_cache` - Token runner data

**Redis** - Job queue and caching:
- RQ job queue for async analysis
- Job results caching
- Rate limiting storage

### External APIs
- Twitter (Tweepy) - Social data
- Birdeye - Token metrics, historical trades
- SolanaTracker - Wallet data, transactions
- Telegram Bot - User notifications

## Environment Variables

Backend `.env`:
```
SUPABASE_URL=
SUPABASE_SERVICE_KEY=
TWITTER_BEARER_TOKEN=
BIRDEYE_API_KEY=
SOLANATRACKER_API_KEY=
TELEGRAM_BOT_TOKEN=
PORT=5000
```

Frontend `.env`:
```
VITE_SUPABASE_URL=
VITE_SUPABASE_ANON_KEY=
VITE_API_URL=http://localhost:5000
VITE_WALLETCONNECT_PROJECT_ID=
```

## Rate Limiting

Configured in `Backend/config.py`:
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
