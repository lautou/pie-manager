# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Tests for app/utils/datetime_utils.py — the shared naive-UTC-to-unambiguous-ISO8601 helper
(issue #72: sync badges displayed UTC time as if it were local, off by the browser's UTC offset).
"""
from datetime import datetime, timezone

from app.utils.datetime_utils import to_utc_iso


def test_to_utc_iso_returns_none_for_none():
    assert to_utc_iso(None) is None


def test_to_utc_iso_attaches_utc_offset_to_a_naive_datetime():
    naive = datetime(2026, 8, 14, 15, 36, 32, 239968)
    assert to_utc_iso(naive) == "2026-08-14T15:36:32.239968+00:00"


def test_to_utc_iso_leaves_an_already_aware_datetime_unchanged():
    aware = datetime(2026, 8, 14, 15, 36, 32, tzinfo=timezone.utc)
    assert to_utc_iso(aware) == aware.isoformat()
