-- Telegram connection tokens for the /start <token> deep-link account-linking flow.
--
-- The backend (routes/telegram.py, services/telegram_notifier.py,
-- repositories/supabase_repos.py) has referenced sifter_dev.telegram_connection_tokens
-- for a while, but the table was never committed to the schema. This migration
-- adds it. Idempotent — safe to run against prod (CREATE ... IF NOT EXISTS).

CREATE TABLE IF NOT EXISTS sifter_dev.telegram_connection_tokens (
    id BIGSERIAL PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES sifter_dev.users(user_id) ON DELETE CASCADE,
    token TEXT NOT NULL UNIQUE,
    used BOOLEAN NOT NULL DEFAULT FALSE,
    expires_at TIMESTAMPTZ NOT NULL,
    telegram_id BIGINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_telegram_conn_tokens_token
ON sifter_dev.telegram_connection_tokens(token);

CREATE INDEX IF NOT EXISTS idx_telegram_conn_tokens_user_unused
ON sifter_dev.telegram_connection_tokens(user_id) WHERE used = FALSE;

ALTER TABLE sifter_dev.telegram_connection_tokens ENABLE ROW LEVEL SECURITY;
-- Server-side only (service_role bypasses RLS); tokens are sensitive so no
-- anon/authenticated policies are granted.
