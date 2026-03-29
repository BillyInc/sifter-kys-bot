# Repository Pattern Migration Guide

## What was created

```
Backend/repositories/
  __init__.py            # Public exports
  base.py                # Abstract interfaces (ABCs)
  supabase_repos.py      # Concrete Supabase implementations
  registry.py            # Lazy-init DI registry with test overrides
```

### Interfaces defined in `base.py`

| Interface | Supabase table(s) | Used by |
|---|---|---|
| `WatchlistRepository` | `watchlist_accounts`, `watchlist_groups` | `routes/watchlist.py`, `db/watchlist_db.py` |
| `WalletWatchlistRepository` | `wallet_watchlist`, `wallet_performance_history`, `wallet_activity` | `routes/wallets.py`, `db/watchlist_db.py` |
| `NotificationRepository` | `wallet_notifications` | `db/watchlist_db.py`, `services/wallet_monitor.py` |
| `AnalysisJobRepository` | `analysis_jobs` | `routes/wallets.py` (job CRUD) |
| `UserRepository` | `users` | `routes/wallets.py` (tier lookup), `db/watchlist_db.py` |
| `UserSettingsRepository` | `user_settings` | `routes/user_settings.py` |
| `AnalysisHistoryRepository` | `user_analysis_history` | `routes/wallets.py` (history endpoints) |

## How to migrate a route

### Before (direct Supabase calls)

```python
# routes/user_settings.py
from services.supabase_client import get_supabase_client, SCHEMA_NAME

@user_settings_bp.route('/settings', methods=['GET'])
@optional_auth
def get_user_settings():
    user_id = getattr(request, 'user_id', None) or anon_user_id()
    supabase = get_supabase_client()

    result = supabase.schema(SCHEMA_NAME).table('user_settings').select('*').eq(
        'user_id', user_id
    ).limit(1).execute()

    if result.data:
        return jsonify({'success': True, 'settings': result.data[0]}), 200
    else:
        return jsonify({'success': True, 'settings': DEFAULT_SETTINGS}), 200
```

### After (repository call)

```python
# routes/user_settings.py
from repositories.registry import get_user_settings_repo

DEFAULT_SETTINGS = { ... }

@user_settings_bp.route('/settings', methods=['GET'])
@optional_auth
def get_user_settings():
    user_id = getattr(request, 'user_id', None) or anon_user_id()
    repo = get_user_settings_repo()

    settings = repo.get_settings(user_id)
    return jsonify({
        'success': True,
        'settings': settings or DEFAULT_SETTINGS,
    }), 200
```

### Migration checklist per route file

1. Import the getter from `repositories.registry`
2. Replace every `get_supabase_client()` + `.schema().table()...` chain with the matching repo method
3. Remove the `from services.supabase_client import ...` line if no longer used
4. Verify behaviour is unchanged (the repo methods replicate the exact query patterns)

## How to use in tests

### 1. Create an in-memory fake

```python
# tests/fakes.py
from repositories.base import UserSettingsRepository

class FakeUserSettingsRepo(UserSettingsRepository):
    def __init__(self):
        self._store: dict[str, dict] = {}

    def get_settings(self, user_id: str) -> dict | None:
        return self._store.get(user_id)

    def save_settings(self, user_id: str, settings: dict) -> bool:
        self._store[user_id] = settings
        return True
```

### 2. Inject it in your test

```python
# tests/test_user_settings.py
import pytest
from repositories.registry import set_user_settings_repo, reset_all
from tests.fakes import FakeUserSettingsRepo

@pytest.fixture(autouse=True)
def _clean_repos():
    yield
    reset_all()  # restore defaults after each test

def test_get_settings_returns_none_for_unknown_user(client):
    set_user_settings_repo(FakeUserSettingsRepo())
    resp = client.get('/api/user/settings')
    assert resp.json['settings']['timezone'] == 'UTC'  # default fallback
```

No Supabase SDK, no network calls, no mocking `create_client`.

## Incremental adoption plan

The repository layer sits alongside the existing `db/watchlist_db.py` without replacing it. Migrate routes one at a time:

1. **Low-risk first**: `user_settings.py` (2 endpoints, simple CRUD)
2. **Then**: `watchlist.py` (already delegates to `WatchlistDatabase`, swap the backing store)
3. **Then**: `wallets.py` job endpoints (`create_job`, `get_job`, `update_job`)
4. **Then**: `wallets.py` history endpoints
5. **Last**: Wallet watchlist + Premier League table (most complex logic)

After all routes are migrated, `db/watchlist_db.py` becomes dead code and can be removed.
