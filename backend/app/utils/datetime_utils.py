# SPDX-License-Identifier: AGPL-3.0-or-later
from datetime import datetime, timezone


def to_utc_iso(dt: datetime | None) -> str | None:
    """Serialize a datetime as an unambiguous ISO 8601 string with an explicit UTC offset.

    Every `DateTime` column in this app stores UTC wall-clock time without a timezone
    marker (asyncpg rejects binding a timezone-aware value against a naive column — see
    app/tasks/job_runs.py's `_finish_run`). Plain `.isoformat()` on such a naive value
    produces a string with no offset (e.g. "2026-08-14T15:36:32"), which JavaScript's
    `Date` constructor then parses as *local* time instead of UTC — silently off by
    whatever the browser's UTC offset happens to be. Assuming naive input is UTC and
    attaching that offset explicitly before serializing fixes this at the source.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()
