"""Test fixtures."""

from pathlib import Path

import pytest
import yaml
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


@pytest.fixture(scope="session")
def compose_labels(repo_root):
    """Return each compose service's labels, keyed by service name.

    Shared because two modules read them: the scrape contract in
    test_compose_config.py, and the dashboard's genericity guard in
    test_grafana_provisioning.py, which forbids these job values in a
    query. One reader normalising and the other not is how the guard
    would quietly stop covering a service.

    Compose accepts labels as a mapping or as a `key=value` list, and
    reading only the mapping form makes a list-shaped block look like a
    service with no labels — both readers would then pass by finding
    nothing to check.
    """
    compose = yaml.safe_load((repo_root / "docker-compose.yml").read_text())
    labels = {}
    for name, service in compose["services"].items():
        declared = service.get("labels", {})
        if isinstance(declared, list):
            declared = dict(entry.split("=", 1) for entry in declared)
        labels[name] = declared
    return labels
