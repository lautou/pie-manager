"""
Tests for app/tasks/celery_app.py.

Nothing in the app imports this module anymore after issue #66 step 4 (no @celery_app.task
remains anywhere — the last 2 snapshot tasks moved to PgQueuer's own cron in pgq_app.py), so
without a direct test its 4 lines would silently drop to 0% coverage. The module itself must
stay: compose.yaml's `worker` service still runs `celery -A app.tasks.celery_app worker -B`,
and Celery/Redis remain installed but idle until a later step removes them entirely.
"""
from app.tasks.celery_app import celery_app


def test_celery_app_has_no_beat_schedule():
    """Both snapshot tasks moved to PgQueuer — an empty beat_schedule means Celery Beat has
    nothing left to dispatch, rather than erroring on task names that no longer exist."""
    assert celery_app.conf.beat_schedule == {}


def test_celery_app_configured_with_json_serialization():
    assert celery_app.conf.task_serializer == "json"
    assert celery_app.conf.result_serializer == "json"
    assert celery_app.conf.accept_content == ["json"]


def test_celery_app_beat_schedule_file_written_outside_app_tree():
    """appuser (non-root, see Containerfile) never needs write access to the source tree."""
    assert celery_app.conf.beat_schedule_filename == "/tmp/celerybeat-schedule"
