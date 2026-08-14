from celery import Celery

from app.core.config import settings

celery_app = Celery(
    "pie",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Europe/Paris",
    enable_utc=True,
    # Written outside /app so the non-root container user (see backend/Containerfile,
    # issue #17) never needs write access to the application source tree.
    beat_schedule_filename="/tmp/celerybeat-schedule",
    # issue #66 step 4: both scheduled snapshot tasks moved to PgQueuer's own cron (see
    # app/tasks/pgq_app.py) — app/tasks/snapshots.py no longer has any @celery_app.task at
    # all, so there's nothing left for Celery Beat to dispatch. Celery/Redis/the `worker`
    # container stay installed but idle; full removal is a later step.
    beat_schedule={},
)
