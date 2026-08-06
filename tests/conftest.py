"""Test fixtures."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app


@pytest.fixture(scope="session")
def repo_root():
    """Return the repository root directory."""
    return Path(__file__).resolve().parent.parent


@pytest.fixture
def test_settings():
    """Create test settings."""
    return settings


@pytest.fixture
def client():
    """Create test client."""
    return TestClient(app)
