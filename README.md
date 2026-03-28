# Sifter KYS

A full-stack Solana token analytics platform featuring Twitter caller analysis, professional wallet pump detection, real-time wallet activity monitoring, Elite 100 leaderboards, and Telegram alerts.

## Quick Start

```bash
# Start both backend and frontend
./start-dev.sh

# Backend: http://localhost:5000
# Frontend: http://localhost:5173
```

### Backend (Python/Flask — uses uv)

```bash
cd Backend
uv sync              # Install dependencies (creates .venv)
uv run python app.py # Dev server on :5000
uv run pytest        # Run tests
```

### Frontend (React 19/Vite)

```bash
cd frontend
pnpm install && pnpm run dev   # Dev server on :5173
pnpm run build                 # Production build
```

## Deployment

Both backend and frontend deploy automatically on push to `main` via GitHub Actions.

- **Backend** (`deploy-backend.yml`) — rsyncs to server, installs deps with `uv sync`, restarts systemd services
- **Frontend** (`deploy-frontend.yml`) — builds with pnpm, rsyncs `dist/` to server, served by nginx

### Production URLs

| Service | URL |
|---------|-----|
| Backend API | https://sifter-kys.duckdns.org |
| Frontend | https://sifter-kys-web.duckdns.org |

### GitHub Secrets Required

Configure these in your repository settings under **Settings > Secrets and variables > Actions**:

| Secret | Description |
|--------|-------------|
| `SSH_PRIVATE_KEY` | SSH private key for server access |
| `SERVER_HOST` | Server hostname/IP address |
| `SERVER_USER` | SSH username for deployment |
| `ENV_FILE` | Full contents of Backend `.env` file |
| `VITE_SUPABASE_URL` | Supabase project URL |
| `VITE_SUPABASE_ANON_KEY` | Supabase anon/public key |

Optional variables (Settings > Variables > Actions):

| Variable | Description | Default |
|----------|-------------|---------|
| `VITE_API_URL` | Backend API URL | `https://sifter-kys.duckdns.org` |

### Server Prerequisites

- Ubuntu with nginx and certbot installed
- DuckDNS subdomains (`sifter-kys`, `sifter-kys-web`) pointed to server IP
- Redis running locally for Celery/caching
- uv installed automatically on first deploy

## Architecture

See [CLAUDE.md](./CLAUDE.md) for detailed architecture, commands, and development docs.

**Stack:**
- Backend: Flask, Celery/Redis, Supabase PostgreSQL, ClickHouse, DuckDB
- Frontend: React 19, Vite, Tailwind, Zustand, Sonner
- Deploy: GitHub Actions, rsync, nginx, systemd, Let's Encrypt
