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
- [x] **Seeded prod reference data** — copied live dev rows: `copy_clusters` (12, incl. 3 bot clusters = 9-wallet engine), `copy_wallets` (124), `bot_defaults` (v1, bear-calibrated). Users/trades come from live use. (Migrations `kys_prod_seed_01..02`.)

## What you must provision (prod)
1. **GitHub `production` environment** (Settings → Environments → New) with a required reviewer, holding these secrets. GitHub environment secrets are per-environment, so copy the values in even when identical to dev.
   - **Same values as dev** (just deploys to a separate folder): `SSH_PRIVATE_KEY`, `SERVER_HOST`, `SERVER_USER` — same box.
   - **Prod-specific** (must differ from dev):
     - `ENV_FILE` — the full **prod** backend `.env` (prod Supabase URL + service key for `vkgfw…`, prod ClickHouse creds, Telegram token, Helius key, `PORT=<prod port, e.g. 5001>`, etc.)
     - `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY` — prod Supabase (`vkgfw…`)
     - `SUPABASE_ACCESS_TOKEN`, `SUPABASE_DB_PASSWORD` — prod project (if you later add a prod migrate step)
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
