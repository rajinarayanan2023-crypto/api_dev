"""A plain in-process TTL cache — no Redis, no external service. This app
runs as a single instance with a handful of users, so a per-process dict is
enough; it resets on deploy/restart, which is fine for data this cheap to
recompute.
"""
import time


class TTLCache:
    def __init__(self, ttl_seconds: float):
        self.ttl_seconds = ttl_seconds
        self._store: dict[str, tuple[float, object]] = {}

    def get(self, key: str):
        entry = self._store.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if time.monotonic() > expires_at:
            del self._store[key]
            return None
        return value

    def set(self, key: str, value) -> None:
        self._store[key] = (time.monotonic() + self.ttl_seconds, value)

    def invalidate(self, key: str) -> None:
        self._store.pop(key, None)

    def keys(self) -> list[str]:
        return list(self._store.keys())


# 5 minutes: fuel entries/expenses/rates don't change every second, but a
# fresh edit should still show up reasonably promptly (the invalidation
# hooks below make this the ceiling, not the typical wait).
dashboard_cache = TTLCache(ttl_seconds=300)

_DASHBOARD_PREFIX = "dashboard:"


def dashboard_cache_key(month: str) -> str:
    return _DASHBOARD_PREFIX + month


def invalidate_dashboard_month(month: str) -> None:
    dashboard_cache.invalidate(dashboard_cache_key(month))


# A commission-rate revision with a given effective_from can change the
# applicable rate for every month from there forward (until the next
# revision supersedes it again), not just the one month it lands in — so a
# rate write invalidates that month and every later cached month, not a
# blanket clear of the whole cache (which would also drop unrelated,
# still-valid months).
def invalidate_dashboard_from_month(month: str) -> None:
    for key in dashboard_cache.keys():
        if key.startswith(_DASHBOARD_PREFIX) and key[len(_DASHBOARD_PREFIX):] >= month:
            dashboard_cache.invalidate(key)
