"""Structural checks on docker-compose.yml.

These parse the compose file and assert the invariants the stack
hardening introduced: pinned tags, named volumes, profiles,
healthchecks and bounded retention. Nothing here starts a container,
so they say nothing about whether the stack actually comes up.
"""

import re

import pytest
import yaml

PINNED_TAG = re.compile(r"^v?\d+\.\d+\.\d+$")
CORE_SERVICES = ("app", "prometheus", "grafana")
NAMED_VOLUMES = {"prometheus_data", "grafana_data"}
EXPECTED_MOUNTS = {
    "prometheus": "prometheus_data:/prometheus",
    "grafana": "grafana_data:/var/lib/grafana",
}
RETENTION_FLAGS = (
    "--storage.tsdb.path",
    "--storage.tsdb.retention.time",
    "--storage.tsdb.retention.size",
)


@pytest.fixture(scope="session")
def compose(repo_root):
    """Parse docker-compose.yml."""
    return yaml.safe_load((repo_root / "docker-compose.yml").read_text())


def assert_pinned(image):
    """Fail unless the image reference carries an exact version tag."""
    assert ":" in image, image
    assert PINNED_TAG.match(image.rsplit(":", 1)[1]), image


def test_compose_carries_no_obsolete_version_key(compose):
    """Confirm the key current Compose ignores with a warning is gone."""
    assert "version" not in compose


def test_every_compose_image_is_pinned(compose):
    """Confirm no pulled image tracks a floating tag."""
    images = [
        service["image"]
        for service in compose["services"].values()
        if "image" in service
    ]
    assert images
    for image in images:
        assert_pinned(image)


def test_every_dockerfile_base_image_is_pinned(repo_root):
    """Confirm both built images pin their base to a patch release."""
    dockerfiles = (
        repo_root / "Dockerfile",
        repo_root / "worker" / "Dockerfile",
    )
    for path in dockerfiles:
        pattern = re.compile(r"^FROM\s+(\S+)", re.MULTILINE)
        references = pattern.findall(path.read_text())
        assert references, path
        for reference in references:
            assert_pinned(reference)


def test_named_volumes_are_declared(compose):
    """Confirm both databases have a named volume to live in."""
    assert set(compose["volumes"]) == NAMED_VOLUMES


def test_named_volumes_are_mounted(compose):
    """Confirm each named volume reaches the service that needs it."""
    for service, mount in EXPECTED_MOUNTS.items():
        assert mount in compose["services"][service]["volumes"], service


def test_every_service_declares_a_profile(compose):
    """Confirm no service is left outside the profile grouping."""
    for name, service in compose["services"].items():
        assert service.get("profiles"), name


def test_core_services_declare_a_healthcheck(compose):
    """Confirm the three serving containers report their readiness."""
    for name in CORE_SERVICES:
        assert "healthcheck" in compose["services"][name], name


def test_loadgen_waits_for_a_healthy_app(compose):
    """Confirm the generator no longer races the app it hits."""
    depends_on = compose["services"]["loadgen"]["depends_on"]
    assert depends_on["app"]["condition"] == "service_healthy"


def test_prometheus_command_bounds_storage(compose):
    """Confirm the storage path and both retention limits are set."""
    command = compose["services"]["prometheus"]["command"]
    flags = {argument.split("=", 1)[0] for argument in command}
    for flag in RETENTION_FLAGS:
        assert flag in flags, flag
