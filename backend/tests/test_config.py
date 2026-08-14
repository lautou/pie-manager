"""
Tests for app/core/config.py — Settings class and singleton instance.

These tests document the expected defaults and verify the configuration
structure. They run without a database (pure Python/Pydantic).
"""

from app.core.config import Settings, settings


# ---------------------------------------------------------------------------
# Singleton instance
# ---------------------------------------------------------------------------

def test_settings_is_settings_instance():
    """The module-level `settings` is an instance of Settings."""
    assert isinstance(settings, Settings)


def test_settings_singleton_identity():
    """Importing settings twice gives the same object."""
    from app.core.config import settings as s2
    assert settings is s2


# ---------------------------------------------------------------------------
# Default values — document and protect against accidental changes
# ---------------------------------------------------------------------------

def test_default_database_url_is_postgresql(monkeypatch):
    # Clear DATABASE_URL so we read the hardcoded default, not the CI test DB.
    monkeypatch.delenv("DATABASE_URL", raising=False)
    s = Settings()
    assert s.database_url.startswith("postgresql+asyncpg://")
    assert "pie_db" in s.database_url


def test_default_debug_is_false():
    s = Settings()
    assert s.debug is False


# ---------------------------------------------------------------------------
# Environment variable override
# ---------------------------------------------------------------------------

def test_env_override_database_url(monkeypatch):
    """DATABASE_URL env var overrides the default."""
    custom = "postgresql+asyncpg://user:pass@myhost:5432/mydb"
    monkeypatch.setenv("DATABASE_URL", custom)
    s = Settings()
    assert s.database_url == custom


def test_env_override_debug_false(monkeypatch):
    """DEBUG=false disables debug mode."""
    monkeypatch.setenv("DEBUG", "false")
    s = Settings()
    assert s.debug is False


def test_extra_env_vars_are_ignored(monkeypatch):
    """extra='ignore' means unknown env vars don't raise an error."""
    monkeypatch.setenv("COMPLETELY_UNKNOWN_VAR_XYZ", "some_value")
    # Should not raise
    s = Settings()
    assert isinstance(s, Settings)
