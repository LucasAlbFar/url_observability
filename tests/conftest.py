"""Test fixtures."""

import re
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app

# The base image reference of a stage, one match per FROM. Shared with
# tests/test_compose_config.py, which asserts every one of them is
# pinned; here they are read for the tag itself.
FROM_IMAGE = re.compile(r"^FROM\s+(\S+)", re.MULTILINE)


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


@pytest.fixture(scope="session")
def pinned_images(repo_root):
    """Map each pinned repository to every tag the stack gives it.

    Both sources, because a repository pinned in only one of them is
    still quoted in prose that can go stale: `image:` in the compose
    file for what is pulled, and every `FROM` for what is built here.
    Reading the compose file alone left three base images — the app's,
    the load generator's, the Go service's two stages — outside the
    drift check entirely, which is what this fixture exists to close.

    A set of tags rather than one, because two files can name the same
    repository: `Dockerfile` and `worker/Dockerfile` both pin `python`.
    Collapsing them into one mapping would let the last file read win
    and hide the disagreement, which is the drift itself.
    """
    compose = yaml.safe_load((repo_root / "docker-compose.yml").read_text())
    references = [
        service["image"]
        for service in compose["services"].values()
        if "image" in service
    ]
    dockerfiles = sorted(repo_root.rglob("Dockerfile"))
    assert dockerfiles
    for path in dockerfiles:
        references.extend(FROM_IMAGE.findall(path.read_text()))
    assert references
    pinned = {}
    for reference in references:
        repository, tag = reference.rsplit(":", 1)
        pinned.setdefault(repository, set()).add(tag)
    return pinned
