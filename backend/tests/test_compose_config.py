"""
Tests for compose.yaml and CI workflow configuration.

These are pure unit tests — no containers needed, just YAML parsing.

Key regression: the PostgreSQL healthcheck must specify -d <dbname> to avoid
the "database pie does not exist" FATAL that occurs every ~6 s when pg_isready
connects without a database name and PostgreSQL defaults to using the username
as the database name.
"""

import re
import yaml
import pytest


import pathlib

_ROOT = pathlib.Path(__file__).parent.parent.parent


def _load_compose() -> dict:
    with open(_ROOT / "compose.yaml") as f:
        return yaml.safe_load(f)


def _load_ci_workflow() -> str:
    with open(_ROOT / ".github" / "workflows" / "ci.yml") as f:
        return f.read()


# ---------------------------------------------------------------------------
# compose.yaml — postgres healthcheck
# ---------------------------------------------------------------------------

class TestComposeHealthcheck:
    def test_postgres_healthcheck_specifies_database(self):
        """
        Regression: pg_isready without -d <dbname> tries to connect to a DB
        named after the user ('pie'), which doesn't exist, producing a FATAL
        error in the PostgreSQL logs every ~6 s.
        """
        compose = _load_compose()
        hc = compose["services"]["postgres"]["healthcheck"]["test"]
        hc_str = " ".join(hc) if isinstance(hc, list) else hc
        assert "-d" in hc_str, (
            "pg_isready must include -d <dbname> to avoid 'database pie does "
            "not exist' FATAL errors (compose.yaml postgres.healthcheck.test)"
        )

    def test_postgres_healthcheck_database_matches_env(self):
        """The -d value must reference POSTGRES_DB, not a hardcoded or wrong name."""
        compose = _load_compose()
        hc = compose["services"]["postgres"]["healthcheck"]["test"]
        hc_str = " ".join(hc) if isinstance(hc, list) else hc
        # Must contain the DB env var reference or a known correct value
        assert "pie_db" in hc_str or "POSTGRES_DB" in hc_str, (
            "pg_isready -d must use the correct database name (pie_db or "
            "${POSTGRES_DB}) not the username"
        )

    def test_postgres_healthcheck_uses_pg_isready(self):
        """Healthcheck command must use pg_isready (not psql or custom script)."""
        compose = _load_compose()
        hc = compose["services"]["postgres"]["healthcheck"]["test"]
        hc_str = " ".join(hc) if isinstance(hc, list) else hc
        assert "pg_isready" in hc_str

    def test_postgres_healthcheck_specifies_user(self):
        """pg_isready must specify -U to avoid ambiguity."""
        compose = _load_compose()
        hc = compose["services"]["postgres"]["healthcheck"]["test"]
        hc_str = " ".join(hc) if isinstance(hc, list) else hc
        assert "-U" in hc_str

    def test_backend_depends_on_postgres_without_health_condition(self):
        """Backend depends on postgres but deliberately without `condition:
        service_healthy` — that condition was found to hang podman-compose 1.6.0 /
        podman 4.9.3 in CI indefinitely right after the postgres image pull (see git
        history for the full writeup). Startup ordering safety instead relies on the
        app's own crash-and-restart resilience (`restart: unless-stopped`) plus
        HAProxy's independent active health-checking (`/api/admin/health` every 2s)
        before it ever routes real traffic to backend."""
        compose = _load_compose()
        backend_deps = compose["services"]["backend"]["depends_on"]
        assert "postgres" in backend_deps
        if isinstance(backend_deps, dict):
            assert "condition" not in backend_deps["postgres"]

    def test_pgq_worker_depends_on_backend_without_health_condition(self):
        """pgq-worker (the only background-job worker since Celery's removal, issue #66)
        depends on `backend`, also without a `condition: service_healthy` — same
        rationale as backend's own postgres dependency above: that condition is what
        hung CI, not which service it targets or how many services poll it."""
        compose = _load_compose()
        worker_deps = compose["services"]["pgq-worker"]["depends_on"]
        assert "backend" in worker_deps
        if isinstance(worker_deps, dict):
            assert "condition" not in worker_deps["backend"]


# ---------------------------------------------------------------------------
# CI workflow — postgres healthcheck
# ---------------------------------------------------------------------------

class TestCIWorkflowHealthcheck:
    def test_ci_postgres_healthcheck_specifies_database(self):
        """
        Same regression check for the CI workflow: the --health-cmd must
        pass -d <dbname> to pg_isready so GitHub Actions doesn't produce
        'database pie does not exist' errors during test setup.
        """
        ci = _load_ci_workflow()
        # Find the health-cmd line
        match = re.search(r"--health-cmd\s+(.+)", ci)
        assert match, "--health-cmd not found in ci.yml"
        health_cmd = match.group(1).strip().strip('"').strip("'")
        assert "-d" in health_cmd, (
            f"CI pg_isready must include -d <dbname>. Found: {health_cmd!r}"
        )

    def test_ci_postgres_healthcheck_database_matches_env(self):
        """CI health-cmd -d must reference the CI test database name."""
        ci = _load_ci_workflow()
        match = re.search(r"--health-cmd\s+(.+)", ci)
        assert match
        health_cmd = match.group(1)
        assert "pie_test" in health_cmd or "POSTGRES_DB" in health_cmd, (
            "CI healthcheck -d should reference the CI database (pie_test)"
        )
