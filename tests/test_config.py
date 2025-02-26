"""Test app configs."""

from app.core.config import Settings


def test_config_defaults():
    """Check default settings."""
    settings = Settings()
    assert settings.APP_NAME == "FastAPI Throughput API's Project"
    assert settings.DEBUG is True


def test_config_env_file(monkeypatch):
    """Mock settings."""
    monkeypatch.setenv("APP_NAME", "Mock Name FastAPI Project")
    monkeypatch.setenv("DEBUG", "False")
    settings = Settings()
    assert settings.APP_NAME == "Mock Name FastAPI Project"
    assert settings.DEBUG is False
