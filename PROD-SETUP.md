# Production environment setup (KYS)

Goal: a **protected prod** separate from **dev**. Dev = what we run today. Prod = isolated.

| Layer | Dev (current) | Prod (new) |
|---|---|---|
| Supabase | `billy` `igvizqgbrxmdtyaujbxu` (shared w/ skillup, `sifter_dev`) | **`sifter-kys` `vkgfwblewragoetkikti`** (isolated, `sifter_dev` schema) |
| Deploy trigger | push to `main` | **git tag `v*`** (`deploy-prod.yml`) |
| Compute | `sifter-backend` service, port 5000 | **`sifter-backend-prod`** service, **port 5001**, same box |
| Backend domain | `sifter-kys.duckdns.org` | **`sifter-kys-prod.duckdns.org`** → :5001 |
| Frontend domain | `sifter-kys-web.duckdns.org` | **`sifter-kys-web-prod.duckdns.org`** |
| Backend dir | `~/sifter-backend` | `~/sifter-backend-prod` |
| Frontend dir | `~/sifter-frontend` | `~/sifter-frontend-prod` |
| GH environment | `development` | **`production`** (add a required approver) |

**Port collision fix:** the systemd unit hardcodes `--bind 0.0.0.0:5000`; `deploy-prod.yml` rewrites it to `:5001` for the prod service so it never clashes with dev on the same box. nginx for both prod domains (backend proxy → :5001, frontend static) is auto-created + certbot-SSL'd on first prod deploy.

**duckdns:** create the two prod subdomains `sifter-kys-prod` and `sifter-kys-web-prod` and point them at the server IP (same box) before the first tag deploy, so certbot can issue certs.

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
     - Environment **variable** `VITE_API_URL` = `https://sifter-kys-prod.duckdns.org` ✅ (already set)
2. **duckdns subdomains** — create `sifter-kys-prod` (backend) and `sifter-kys-web-prod` (frontend) pointing at the server IP. nginx + certbot are auto-configured by `deploy-prod.yml` on first deploy; the backend binds :5001 (dev stays :5000).
3. **Separate ClickHouse + Redis** for prod — a distinct ClickHouse database and a distinct Redis instance/DB index (put these in the prod `ENV_FILE`) so prod analytics + job queue never mix with dev.
4. **Prod Helius webhook** — register a webhook against `https://sifter-kys-prod.duckdns.org/api/webhooks/helius` and let `sync_clusters_to_helius` subscribe the cluster wallets (PUT fix is in).

## Release flow once set up
```
# dev: normal work
git push origin main            # -> dev deploy

# prod: cut a release
git tag v1.0.0 && git push origin v1.0.0   # -> deploy-prod.yml (needs production approval)
```
