from celery import Celery
from celery.schedules import crontab

from app.core.config import settings

celery_app = Celery(
    "pie",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.tasks.prices", "app.tasks.snapshots", "app.tasks.etf_holdings", "app.tasks.macro_indicators"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Europe/Paris",
    enable_utc=True,
    beat_schedule={
        # Live price refresh every 15 min — parallel httpx calls, regularMarketPrice
        "refresh-prices-live": {
            "task": "app.tasks.prices.refresh_prices_live",
            "schedule": crontab(minute="*/15"),
        },
        # Compute daily snapshots every weekday at 19:00
        "compute-daily-snapshots": {
            "task": "app.tasks.snapshots.compute_daily_snapshots_all_users",
            "schedule": crontab(hour=19, minute=0, day_of_week="1-5"),
        },
        # Compute monthly snapshots on the 1st of each month at 08:00
        "compute-monthly-snapshots": {
            "task": "app.tasks.snapshots.compute_monthly_snapshots_all_users",
            "schedule": crontab(hour=8, minute=0, day_of_month=1),
        },
        # Refresh ETF top-10 holdings/sector weightings weekly (composition doesn't move daily)
        "refresh-etf-holdings": {
            "task": "app.tasks.etf_holdings.refresh_etf_holdings",
            "schedule": crontab(hour=6, minute=0, day_of_week="0"),
        },
        # Refresh macro indicators (SP500/oil, US10Y/gold) once a day
        "refresh-macro-indicators": {
            "task": "app.tasks.macro_indicators.refresh_macro_indicators",
            "schedule": crontab(hour=7, minute=0),
        },
    },
)
