"""
Shared Redis-backed sync-status helpers, used by every Celery refresh task (prices,
macro_indicators, etf_holdings, country_performance) to report progress to the frontend.

Extracted from what used to be near-identical private copies in each task module — only the
Redis key and TTL ever differed between them.
"""

import json


def get_redis():
    import redis as redis_lib
    from app.core.config import settings
    return redis_lib.Redis.from_url(settings.celery_broker_url, decode_responses=True)


def write_status(r, key: str, status: dict, ttl_seconds: int) -> None:
    r.set(key, json.dumps(status), ex=ttl_seconds)
