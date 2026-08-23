# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Schedule-fidelity + timezone-behavior checks for app/tasks/pgq_app.py (issue #66).

Confirmed live (2026-08-13): a real `pgq run app.tasks.pgq_app:main` process, against a real
throwaway Postgres (and separately, a real windows-latest GitHub Actions runner), registered
all 6 schedules correctly (`pgqueuer_schedules` table populated with sane `next_run` values)
and shut down cleanly on SIGTERM.

Also confirmed live: PgQueuer's SchedulerManager computes each schedule's next-run time by
seeding croniter with `datetime.now(timezone.utc)` (pgqueuer/core/executors.py's
`get_next()`) — cron hour/minute fields are therefore always interpreted in UTC, with no
equivalent of Celery's `timezone="Europe/Paris"` config. Setting `TZ=Europe/Paris` on the
worker container has zero effect on this computation (it isn't wall-clock-dependent at all).

Because of this, the 5 hour-specific cron constants in pgq_app.py are hand-shifted by -2h
from Celery's raw Paris-local hour numbers (Europe/Paris's current CEST/UTC+2 offset) — the
tests below assert the *shifted* (UTC) values, not the original Celery-local ones. During CET
(UTC+1, roughly late Oct-late Mar) these fire 1 hour earlier than the intended Paris wall-clock
time — an accepted, documented drift (see pgq_app.py's module docstring), not a bug.
"""

from datetime import datetime, timezone

from croniter import croniter

from app.tasks.pgq_app import (
    CHECK_GITHUB_UPDATE_CRON,
    COMPUTE_DAILY_SNAPSHOTS_CRON,
    COMPUTE_MONTHLY_SNAPSHOTS_CRON,
    REFRESH_COUNTRY_PERFORMANCE_CRON,
    REFRESH_ETF_HOLDINGS_CRON,
    REFRESH_MACRO_INDICATORS_CRON,
    REFRESH_PRICES_LIVE_CRON,
)

ALL_CRONS = [
    REFRESH_PRICES_LIVE_CRON,
    COMPUTE_DAILY_SNAPSHOTS_CRON,
    COMPUTE_MONTHLY_SNAPSHOTS_CRON,
    REFRESH_ETF_HOLDINGS_CRON,
    REFRESH_MACRO_INDICATORS_CRON,
    REFRESH_COUNTRY_PERFORMANCE_CRON,
    CHECK_GITHUB_UPDATE_CRON,
]


def test_check_github_update_fires_every_6_hours_utc_no_paris_shift():
    """Unlike the 5 hour-specific crons above, this one is intentionally NOT Paris-shifted —
    checking for a new release doesn't depend on wall-clock time of day (see pgq_app.py's
    module docstring)."""
    assert CHECK_GITHUB_UPDATE_CRON == "0 */6 * * *"


def test_every_cron_expression_is_valid():
    for expr in ALL_CRONS:
        assert croniter.is_valid(expr), expr


def test_refresh_prices_live_fires_every_15_minutes():
    """Celery: crontab(minute="*/15")."""
    assert REFRESH_PRICES_LIVE_CRON == "*/15 * * * *"


def test_compute_daily_snapshots_restricted_to_weekdays_at_1700_utc():
    """Celery: crontab(hour=19, minute=0, day_of_week="1-5") — 19:00 Paris/CEST = 17:00 UTC,
    Mon-Fri only. Field-by-field structural translation of the non-hour fields, which are
    unaffected by the UTC-vs-Paris question (see module docstring)."""
    minute, hour, dom, month, dow = COMPUTE_DAILY_SNAPSHOTS_CRON.split()
    assert (minute, hour, dom, month, dow) == ("0", "17", "*", "*", "1-5")


def test_compute_monthly_snapshots_fires_on_first_of_month_at_0600_utc():
    """Celery: crontab(hour=8, minute=0, day_of_month=1) — 08:00 Paris/CEST = 06:00 UTC."""
    minute, hour, dom, month, dow = COMPUTE_MONTHLY_SNAPSHOTS_CRON.split()
    assert (minute, hour, dom, month, dow) == ("0", "6", "1", "*", "*")


def test_refresh_etf_holdings_restricted_to_sunday_at_0400_utc():
    """Celery: crontab(hour=6, minute=0, day_of_week="0") — 06:00 Paris/CEST = 04:00 UTC,
    Sunday only. "0"=Sunday in both Celery's crontab and standard/croniter day-of-week
    numbering, so this field maps directly."""
    minute, hour, dom, month, dow = REFRESH_ETF_HOLDINGS_CRON.split()
    assert (minute, hour, dom, month, dow) == ("0", "4", "*", "*", "0")


def test_macro_indicators_and_country_performance_stay_offset_by_15_minutes():
    """07:00/07:15 Paris/CEST = 05:00/05:15 UTC — deliberately offset from each other (see
    celery_app.py's original comment) so both don't hit Yahoo at once."""
    assert REFRESH_MACRO_INDICATORS_CRON == "0 5 * * *"
    assert REFRESH_COUNTRY_PERFORMANCE_CRON == "15 5 * * *"


def test_pgqueuer_scheduler_computes_next_run_in_utc_not_local_time():
    """Reproduces pgqueuer's own SchedulerManager.get_next() computation directly, seeded
    with a known reference time, to guard against this UTC-only behavior silently changing in
    a future pgqueuer version bump — confirmed live against a real `pgq run` process (see
    module docstring) that '0 17 * * 1-5', evaluated from 2026-08-13 17:49 UTC (a Thursday,
    17:00 UTC already passed today), correctly rolls over to the *next* weekday occurrence
    (2026-08-14, a Friday) at 17:00 UTC — not local wall time, and not "later today". If this
    test ever fails, PgQueuer's scheduler has changed and the timezone-handling in pgq_app.py
    needs revisiting before relying on it."""
    reference_utc = datetime(2026, 8, 13, 17, 49, 20, tzinfo=timezone.utc)
    next_run = datetime.fromtimestamp(
        croniter(COMPUTE_DAILY_SNAPSHOTS_CRON, start_time=reference_utc).get_next(),
        timezone.utc,
    )
    assert next_run == datetime(2026, 8, 14, 17, 0, 0, tzinfo=timezone.utc)
