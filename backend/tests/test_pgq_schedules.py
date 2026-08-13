"""
Schedule-fidelity + timezone-behavior checks for app/tasks/pgq_app.py (issue #66 step 1 POC).

Confirmed live (2026-08-13): a real `pgq run app.tasks.pgq_app:main` process, against a real
throwaway Postgres, registered all 6 schedules correctly (`pgqueuer_schedules` table populated
with sane `next_run` values) and shut down cleanly on SIGTERM.

Also confirmed live: PgQueuer's SchedulerManager computes each schedule's next-run time by
seeding croniter with `datetime.now(timezone.utc)` (pgqueuer/core/executors.py's
`get_next()`) — cron hour/minute fields are therefore always interpreted in UTC, with no
equivalent of Celery's `timezone="Europe/Paris"` config. Setting `TZ=Europe/Paris` on a future
worker container would have zero effect on this computation (it isn't wall-clock-dependent at
all). This is a real, confirmed behavioral difference from today's Celery schedule (which
fires on Paris wall-clock time, via Celery's own timezone-aware crontab resolution) that a
later step must account for when cutting these schedules over for real — e.g. by hand-shifting
the 5 hour-specific expressions by Paris's current UTC offset, accepting a documented ±1h
drift across the two DST transitions each year.
"""

from datetime import datetime, timezone

from croniter import croniter

from app.tasks.pgq_app import (
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
]


def test_every_cron_expression_is_valid():
    for expr in ALL_CRONS:
        assert croniter.is_valid(expr), expr


def test_refresh_prices_live_fires_every_15_minutes():
    """Celery: crontab(minute="*/15")."""
    assert REFRESH_PRICES_LIVE_CRON == "*/15 * * * *"


def test_compute_daily_snapshots_restricted_to_weekdays_at_1900():
    """Celery: crontab(hour=19, minute=0, day_of_week="1-5") — Mon-Fri only. Field-by-field
    structural translation, independent of the UTC-vs-Paris question (see module docstring)."""
    minute, hour, dom, month, dow = COMPUTE_DAILY_SNAPSHOTS_CRON.split()
    assert (minute, hour, dom, month, dow) == ("0", "19", "*", "*", "1-5")


def test_compute_monthly_snapshots_fires_on_first_of_month_at_0800():
    """Celery: crontab(hour=8, minute=0, day_of_month=1)."""
    minute, hour, dom, month, dow = COMPUTE_MONTHLY_SNAPSHOTS_CRON.split()
    assert (minute, hour, dom, month, dow) == ("0", "8", "1", "*", "*")


def test_refresh_etf_holdings_restricted_to_sunday_at_0600():
    """Celery: crontab(hour=6, minute=0, day_of_week="0") — Sunday. "0"=Sunday in both
    Celery's crontab and standard/croniter day-of-week numbering, so this maps directly."""
    minute, hour, dom, month, dow = REFRESH_ETF_HOLDINGS_CRON.split()
    assert (minute, hour, dom, month, dow) == ("0", "6", "*", "*", "0")


def test_macro_indicators_and_country_performance_stay_offset_by_15_minutes():
    """Deliberately offset (see celery_app.py's comment) so both don't hit Yahoo at once."""
    assert REFRESH_MACRO_INDICATORS_CRON == "0 7 * * *"
    assert REFRESH_COUNTRY_PERFORMANCE_CRON == "15 7 * * *"


def test_pgqueuer_scheduler_computes_next_run_in_utc_not_local_time():
    """Reproduces pgqueuer's own SchedulerManager.get_next() computation directly, seeded
    with a known reference time, to guard against this UTC-only behavior silently changing in
    a future pgqueuer version bump — confirmed live against a real `pgq run` process (see
    module docstring) that '0 19 * * 1-5', evaluated from 2026-08-13 17:49 UTC (a Thursday,
    with the host's local zone at Europe/Madrid CEST/UTC+2 that day), resolves to 19:00 UTC
    the same day — not 17:00 UTC (which 19:00 CEST would be), and not local wall time either.
    If this test ever fails, PgQueuer's scheduler has changed and the timezone-handling plan
    for the real cutover (a later step) needs revisiting before relying on it."""
    reference_utc = datetime(2026, 8, 13, 17, 49, 20, tzinfo=timezone.utc)
    next_run = datetime.fromtimestamp(
        croniter(COMPUTE_DAILY_SNAPSHOTS_CRON, start_time=reference_utc).get_next(),
        timezone.utc,
    )
    assert next_run == datetime(2026, 8, 13, 19, 0, 0, tzinfo=timezone.utc)
