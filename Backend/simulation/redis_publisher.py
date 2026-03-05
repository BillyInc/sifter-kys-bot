"""
simulation/redis_publisher.py
──────────────────────────────────────────────────────────────────
Drop this into your simulation folder.
Call publish_day_state(state_dict) from simulation_harness.py
after each day step to push data to Flask → Three.js.

Usage in simulation_harness.py:
    from redis_publisher import SimulationPublisher
    publisher = SimulationPublisher()

    # inside your day loop:
    publisher.publish_day_state({
        'status':       'running',
        'mode':         'simulation',
        'day':          current_day,
        'total_days':   30,
        'market_state': market_state,
        'agents':       agent_states,   # list of agent dicts
        'stats':        stats_dict,
        'events':       recent_events,
        'monte_carlo':  mc_result,      # None until MC runs
    })
"""

import json
import os
import time
import requests
from redis import Redis


class SimulationPublisher:
    """
    Publishes simulation state to Redis so Flask can serve it to Three.js.
    Falls back to HTTP POST if Redis is not directly accessible.
    """

    def __init__(self,
                 redis_url: str = None,
                 flask_url: str = 'http://localhost:5000'):
        self.flask_url = flask_url
        self.redis_url = redis_url or os.environ.get('REDIS_URL', 'redis://localhost:6379')
        self._redis = self._connect_redis()

    def _connect_redis(self):
        try:
            r = Redis.from_url(self.redis_url, decode_responses=True, socket_timeout=2)
            r.ping()
            print('[PUBLISHER] ✅ Redis connected — publishing directly')
            return r
        except Exception:
            print('[PUBLISHER] ⚠️  Redis unavailable — will use HTTP POST to Flask')
            return None

    def publish_day_state(self, state: dict):
        """
        Push the current simulation day state so Three.js can read it.
        Tries Redis first (fast), falls back to Flask HTTP POST.
        """
        state['timestamp'] = time.time()
        payload = json.dumps(state)

        if self._redis:
            try:
                self._redis.setex('abm:current_state', 300, payload)
                return True
            except Exception as e:
                print(f'[PUBLISHER] Redis write failed: {e} — trying HTTP')

        # HTTP fallback
        try:
            requests.post(
                f'{self.flask_url}/api/abm/state',
                json=state,
                timeout=2
            )
            return True
        except Exception as e:
            print(f'[PUBLISHER] HTTP POST failed: {e}')
            return False

    def publish_monte_carlo_result(self, results: dict):
        """Call this when Monte Carlo finishes to update the MC badge in Three.js."""
        try:
            raw = self._redis.get('abm:current_state') if self._redis else None
            if raw:
                state = json.loads(raw)
                state['monte_carlo'] = results
                self.publish_day_state(state)
        except Exception as e:
            print(f'[PUBLISHER] MC publish failed: {e}')

    def publish_complete(self, final_stats: dict):
        """Mark simulation as complete."""
        try:
            raw = self._redis.get('abm:current_state') if self._redis else None
            if raw:
                state = json.loads(raw)
                state['status'] = 'complete'
                state['final_stats'] = final_stats
                self.publish_day_state(state)
        except Exception as e:
            print(f'[PUBLISHER] Complete publish failed: {e}')

    def reset(self):
        """Clear simulation state."""
        if self._redis:
            self._redis.delete('abm:current_state')
            self._redis.delete('abm:mode')