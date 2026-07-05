# Production environment setup (KYS)

Goal: a **protected prod** separate from **dev**. Dev = what we run today. Prod = isolated.

| Layer | Dev (current) | Prod (new) |
|---|---|---|
| Supabase | `billy` `igvizqgbrxmdtyaujbxu` (shared w/ skillup, `sifter_dev`) | **`sifter-kys` `vkgfwblewragoetkikti`** (isolated, `sifter_dev` schema) |
| Deploy trigger | push to `main` | **git tag `v*`** (`deploy-prod.yml`) |
| Compute | `sifter-backend` service, port 5000 | **`sifter-backend-prod`** service, **port 5001**, same box |
| Backend domain | `sifter-kys.duckdns.org` (dev, for now) | **`api.kys.levelup.com.ng`** → :5001 |
| Frontend domain | `sifter-kys-web.duckdns.org` (dev, for now) | **`kys.levelup.com.ng`** |
| Backend dir | `~/sifter-backend` | `~/sifter-backend-prod` |
| Frontend dir | `~/sifter-frontend` | `~/sifter-frontend-prod` |
| GH environment | `development` | **`production`** (add a required approver) |

**Prod services:** `deploy-prod.yml` enables + starts the full prod stack — `sifter-backend-prod` (:5001), `celery-worker-prod`, `celery-beat-prod` (scheduler → runs `sync_clusters_to_helius` + the beat schedule), `celery-alerts-worker-prod`, `wallet-monitor-prod`. (RQ analysis workers use a server-side `rq-worker@` template, not managed by this workflow.)

**⚠️ Prod MUST use a separate Redis** (distinct instance or DB index in the prod `ENV_FILE`). Both dev and prod run `celery-beat`; if they share a broker they double-fire every scheduled task (incl. the Helius sync). Separate Redis = isolated schedulers.

**Port collision fix:** the systemd unit hardcodes `--bind 0.0.0.0:5000`; `deploy-prod.yml` rewrites it to `:5001` for the prod service so it never clashes with dev on the same box. nginx for both prod domains (backend proxy → :5001, frontend static) is auto-created + certbot-SSL'd on first prod deploy.

**DNS:** create two A records under `levelup.com.ng` — `api.kys` and `kys` — both pointing at the server IP (same box) before the first tag deploy, so certbot can issue certs. (Naming follows the shared-domain scheme: `[api.]<app>[.dev].levelup.com.ng`; KYS dev migrates off duckdns later.)

## What Claude does in-repo
- [x] `deploy-prod.yml` — tag-triggered, `environment: production`, deploys backend+frontend to the prod service/dirs on the same box.
- [x] **KYS schema applied to the prod project** (`vkgfwblewragoetkikti`) — cloned from the live dev `sifter_dev` schema (the migration files are stubbed, so dev is the source of truth). Full parity: 59 tables, 29 sequences, 120 constraints, 165 indexes, 9 functions, 42 RLS policies, 6 triggers. No `skillup_*` pollution. (4 migrations: `kys_prod_bootstrap_01..04`.)
- [x] Fixed `_sync_helius_webhook` PUT (full webhook definition) — verified: dev webhook now subscribes the 29 cluster wallets.
- [x] **Seeded prod reference data** — copied live dev rows: `copy_clusters` (12, incl. 3 bot clusters = 9-wallet engine), `copy_wallets` (124), `bot_defaults` (v1, bear-calibrated). Users/trades come from live use. (Migrations `kys_prod_seed_01..02`.)

## What you must provision (prod)
1. **GitHub `production` environment** (Settings → Environments → New) with a required reviewer, holding these secrets. GitHub environment secrets are per-environment, so copy the values in even when identical to dev.
   - **Same values as dev** (just deploys to a separate folder): `SSH_PRIVATE_KEY`, `SERVER_HOST`, `SERVER_USER` — same box.
   - **Prod-specific** (must differ from dev):
     - `ENV_FILE` — the full **prod** backend `.env` (prod Supabase URL + service key for `vkgfw…`, prod ClickHouse creds, Telegram token, Helius key, `PORT=<prod port, e.g. 5001>`, etc.)
     - `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY` — prod Supabase (`vkgfw…`)
     - `SUPABASE_ACCESS_TOKEN`, `SUPABASE_DB_PASSWORD` — prod project (if you later add a prod migrate step)
     - Environment **variable** `VITE_API_URL` = `https://api.kys.levelup.com.ng` ✅ (already set)
2. **DNS A records** — `api.kys.levelup.com.ng` (backend) and `kys.levelup.com.ng` (frontend) → server IP. nginx + certbot are auto-configured by `deploy-prod.yml` on first deploy; the backend binds :5001 (dev stays :5000).
3. **Separate ClickHouse + Redis** for prod — a distinct ClickHouse database and a distinct Redis instance/DB index (put these in the prod `ENV_FILE`) so prod analytics + job queue never mix with dev.
4. **Prod Helius webhook** — register a webhook against `https://api.kys.levelup.com.ng/api/webhooks/helius` and let `sync_clusters_to_helius` subscribe the cluster wallets (PUT fix is in).

## Prod `ENV_FILE` contents (the `production` secret)

Copy dev's `.env`, then change the marked lines. Every Redis consumer reads a single
`REDIS_URL`, so appending `/1` isolates prod onto **DB index 1** (dev is DB 0).

```dotenv
# ── PROD-SPECIFIC (must differ from dev) ──
SUPABASE_URL=https://vkgfwblewragoetkikti.supabase.co      # prod project (isolated)
SUPABASE_SERVICE_KEY=<prod project service_role key>       # Supabase dashboard → API
SUPABASE_DB_PASSWORD=<prod project db password>            # only needed if you add a prod migrate step
SUPABASE_ACCESS_TOKEN=<same account PAT as dev is fine>

REDIS_URL=redis://localhost:6379/1                         # ← separate DB index (dev=0, prod=1)
RATELIMIT_STORAGE_URI=redis://localhost:6379/1             # match REDIS_URL

CLICKHOUSE_DATABASE=sifter-kys-prod                        # create this DB in ClickHouse (dev=sifter-kys)
WEBHOOK_URL=https://api.kys.levelup.com.ng/api/webhooks/helius   # prod Helius receiver
PORT=5001                                                  # gunicorn already binds :5001 via systemd

# ── DECISIONS (isolate for safety) ──
TELEGRAM_BOT_TOKEN=<SEPARATE prod bot>                     # a bot has ONE webhook; reusing dev's breaks one of them
TELEGRAM_BOT_USERNAME=<prod bot @username, no @>          # used to build the connect deep-link
TELEGRAM_SECRET_TOKEN=<new random for prod webhook>
HELIUS_WEBHOOK_SECRET=<new random; set as the prod webhook authHeader>
WALLET_ENCRYPTION_SECRET=<NEW random for prod>            # do NOT reuse dev's — isolates prod bot-wallet keys

# ── SAME AS DEV (copy values) ──
TELEGRAM_ADMIN_CHAT_IDS=…   TELEGRAM_OPERATOR_CHAT_IDS=…   TELEGRAM_OPERATOR_USER_IDS=…
BIRDEYE_API_KEY=…   SOLANATRACKER_API_KEY=…   TWITTER_BEARER_TOKEN=…   HELIUS_API_KEY=…
CLICKHOUSE_HOST=…   CLICKHOUSE_PORT=…   CLICKHOUSE_USER=…   CLICKHOUSE_PASSWORD=…   CLICKHOUSE_SECURE=…
SMTP_HOST=…   SMTP_PORT=…   SMTP_USERNAME=…   SMTP_PASSWORD=…   SMTP_FROM_EMAIL=…   FROM_EMAIL=…
RESEND_API_KEY=…   ADMIN_EMAIL=…   PAPER_TRADER_EMAIL_TO=…
UPSTASH_REDIS_REST_URL=…   UPSTASH_REDIS_REST_TOKEN=…      # reuse, or a separate Upstash DB for full isolation
WORKER_MODE=…
```

Notes:
- **ClickHouse:** create the `sifter-kys-prod` database on the same CH instance (`python scripts/init_clickhouse.py` with `CLICKHOUSE_DATABASE=sifter-kys-prod`) — same host/creds, separate data.
- **Redis:** one instance, DB 0 (dev) vs DB 1 (prod). Because both run `celery-beat`, this separation is what stops double-firing.
- **Telegram (prod bot):** create a new bot in BotFather (`/newbot`) → put its token in `TELEGRAM_BOT_TOKEN` and its `@username` (without `@`) in `TELEGRAM_BOT_USERNAME`. After the first prod deploy, point its webhook at prod:
  `TELEGRAM_SECRET_TOKEN=… WEBHOOK_URL=https://api.kys.levelup.com.ng uv run python scripts/setup_telegram_webhook.py` (or let the app's startup register it). Set operator/admin IDs the same as dev unless you want different prod operators.

## Release flow once set up
```
# dev: normal work
git push origin main            # -> dev deploy

# prod: cut a release
git tag v1.0.0 && git push origin v1.0.0   # -> deploy-prod.yml (needs production approval)
```
