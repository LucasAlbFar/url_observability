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
# The opt-in half of the scrape contract, and the profile that decides
# whether the load generator calls a service. Being scraped and being
# driven are different questions, and reading one for the other is the
# bug the `driven_services` fixture below exists to stop repeating.
SCRAPE_LABEL = "prometheus.io/scrape"
LOAD_PROFILE = "load"


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
def compose(repo_root):
    """Parse docker-compose.yml.

    Here rather than in one test module because three fixtures below
    and two modules read it. Parsing it twice risks nothing on its own;
    what it costs is that a reader wanting profiles alongside labels
    has to re-open the file, which is how `driven_services` came to be
    derived from the wrong set in the first place.
    """
    return yaml.safe_load((repo_root / "docker-compose.yml").read_text())


@pytest.fixture(scope="session")
def compose_labels(compose):
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
    labels = {}
    for name, service in compose["services"].items():
        declared = service.get("labels", {})
        if isinstance(declared, list):
            declared = dict(entry.split("=", 1) for entry in declared)
        labels[name] = declared
    return labels


@pytest.fixture(scope="session")
def pinned_images(repo_root, compose):
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
    references = [
        service["image"]
        for service in compose["services"].values()
        if "image" in service
    ]
    dockerfiles = [
        path
        for path in sorted(repo_root.rglob("Dockerfile"))
        # An installed dependency shipping its own Dockerfile is not this
        # stack's to pin, and `rglob` does not read .gitignore. Both
        # documents tell a developer to run `npm ci` locally, so the
        # directory exists on their machine and not in CI — the shape of
        # failure that is hardest to reproduce.
        if "node_modules" not in path.parts
    ]
    assert dockerfiles
    for path in dockerfiles:
        references.extend(FROM_IMAGE.findall(path.read_text()))
    assert references
    pinned = {}
    for reference in references:
        # A stage reference (`FROM builder`) carries no tag; asserting
        # says which file to look at, where unpacking would raise a
        # ValueError naming nothing.
        assert ":" in reference, reference
        repository, tag = reference.rsplit(":", 1)
        pinned.setdefault(repository, set()).add(tag)
    return pinned


@pytest.fixture(scope="session")
def driven_services(compose, compose_labels):
    """Return the services the load generator calls, with their labels.

    Scraped **and** in the load profile. Both halves are needed and
    neither alone is right: the generator drives nothing that is not
    observed, and a service outside the load profile does not come up
    when the generator does, so waiting on it or calling it is a
    contradiction rather than an omission.

    Two tests derived this from the scrape label alone, which held only
    while every scraped service happened to be in the load profile. A
    service that opts into the scrape to be measured misbehaving — and
    is deliberately left out of the load profile so it costs nothing in
    normal operation — failed both, and the failure named the new
    service rather than the derivation.
    """
    return {
        name: labels
        for name, labels in compose_labels.items()
        if labels.get(SCRAPE_LABEL) == "true"
        and LOAD_PROFILE in compose["services"][name].get("profiles", [])
    }
