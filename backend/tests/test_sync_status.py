"""
Non-regression tests for the shared Redis sync-status helpers (app/tasks/sync_status.py).

Extracted from what used to be near-identical private copies of these tests in
test_price_sync.py / test_macro_indicators_task.py / test_etf_holdings_task.py.
"""

import json
from unittest.mock import MagicMock, patch

from app.tasks.sync_status import get_redis, write_status


def test_get_redis_creates_client_from_broker_url():
    """get_redis() passes the broker URL to redis.Redis.from_url with decode_responses."""
    mock_client = MagicMock()
    with patch("redis.Redis.from_url", return_value=mock_client) as mock_from_url, \
         patch("app.core.config.settings") as mock_settings:
        mock_settings.celery_broker_url = "redis://localhost:6379/0"
        result = get_redis()
    mock_from_url.assert_called_once_with("redis://localhost:6379/0", decode_responses=True)
    assert result is mock_client


def test_write_status_serialises_dict_with_given_key_and_ttl():
    mock_r = MagicMock()
    status = {"status": "running", "succeeded": 0, "failed_tickers": []}
    write_status(mock_r, "pie:test:status", status, ttl_seconds=3600)
    mock_r.set.assert_called_once()
    args, kwargs = mock_r.set.call_args
    assert args[0] == "pie:test:status"
    assert json.loads(args[1]) == status
    assert kwargs.get("ex") == 3600


def test_write_status_different_keys_and_ttls():
    """Confirms the key/TTL are genuinely parameters, not hardcoded — each caller
    (prices.py: 1h, macro_indicators.py/etf_holdings.py: 1 week) supplies its own."""
    for key, ttl, payload in [
        ("pie:sync:status", 3600, {"status": "success"}),
        ("pie:macro:status", 3600 * 24 * 7, {"status": "failed"}),
    ]:
        mock_r = MagicMock()
        write_status(mock_r, key, payload, ttl_seconds=ttl)
        args, kwargs = mock_r.set.call_args
        assert args[0] == key
        assert json.loads(args[1]) == payload
        assert kwargs.get("ex") == ttl
