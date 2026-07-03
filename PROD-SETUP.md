# Production environment setup (KYS)

Goal: a **protected prod** separate from **dev**. Dev = what we run today. Prod = isolated.

| Layer | Dev (current) | Prod (new) |
|---|---|---|
| Supabase | `billy` `igvizqgbrxmdtyaujbxu` (shared w/ skillup, `sifter_dev`) | **`sifter-kys` `vkgfwblewragoetkikti`** (isolated, `sifter_dev` schema) |
| Deploy trigger | push to `main` | **git tag `v*`** (`deploy-prod.yml`) |
| Compute | `sifter-backend` service, port 5000 | **`sifter-backend-prod`** service, separate port, same box |
| Backend dir | `~/sifter-backend` | `~/sifter-backend-prod` |
| Frontend dir | `~/sifter-frontend` | `~/sifter-frontend-prod` |
| GH environment | `development` | **`production`** (add a required approver) |

## What Claude does in-repo
- [x] `deploy-prod.yml` — tag-triggered, `environment: production`, deploys backend+frontend to the prod service/dirs on the same box.
- [x] **KYS schema applied to the prod project** (`vkgfwblewragoetkikti`) — cloned from the live dev `sifter_dev` schema (the migration files are stubbed, so dev is the source of truth). Full parity: 59 tables, 29 sequences, 120 constraints, 165 indexes, 9 functions, 42 RLS policies, 6 triggers. No `skillup_*` pollution. (4 migrations: `kys_prod_bootstrap_01..04`.)
- [x] Fixed `_sync_helius_webhook` PUT (full webhook definition) — verified: dev webhook now subscribes the 29 cluster wallets.
- [ ] **Seed prod reference data** — the prod tables are empty. Before the bot runs in prod, seed `copy_wallets` + `copy_clusters` (`Backend/seeds/copytrade/seed_clusters_wallets.sql`) and `bot_defaults`. Users/trades come from live use.

## What you must provision (prod)
1. **GitHub `production` environment** (Settings → Environments → New) with a required reviewer, holding these secrets:
   - `ENV_FILE` — the full **prod** backend `.env` (prod Supabase URL + service key, prod DB password, ClickHouse creds, Telegram token, Helius key, `PORT=<prod port>`, etc.)
   - `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY` — prod Supabase
   - `SSH_PRIVATE_KEY`, `SERVER_HOST`, `SERVER_USER` — same box is fine
   - `SUPABASE_ACCESS_TOKEN`, `SUPABASE_DB_PASSWORD` — prod project (for migrate)
   - Environment **variable** `VITE_API_URL` = prod backend URL
2. **Prod domain(s)** + nginx server blocks: e.g. `api.sifter-kys.<domain>` → prod backend port, `app.sifter-kys.<domain>` → `~/sifter-frontend-prod`. (Dev keeps `sifter-kys.duckdns.org` / `sifter-kys-web.duckdns.org`.)
3. **Prod port** for the backend (e.g. 5001) — set `PORT` in the prod `.env`; nginx proxies the prod domain to it.
4. **Separate ClickHouse + Redis** for prod — a distinct ClickHouse database and a distinct Redis instance/DB index (so prod analytics + job queue never mix with dev).
5. **Prod Helius webhook** — register a webhook against the prod backend domain and let `sync_clusters_to_helius` subscribe the cluster wallets (after the PUT fix).

## Release flow once set up
```
# dev: normal work
git push origin main            # -> dev deploy

# prod: cut a release
git tag v1.0.0 && git push origin v1.0.0   # -> deploy-prod.yml (needs production approval)
```
