"""Test fixtures."""

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app


@pytest.fixture
def test_settings():
    """Create test settings."""
    return settings


@pytest.fixture
def client():
    """Create test client."""
    return TestClient(app)
