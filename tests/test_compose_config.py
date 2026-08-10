"""Structural checks on docker-compose.yml.

These parse the compose file and assert the invariants the stack
hardening introduced: pinned tags, named volumes, profiles,
healthchecks and the storage path. Nothing here starts a container,
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
STORAGE_FLAGS = ("--storage.tsdb.path",)
CONTINUATION = re.compile(r"\\\s*\n\s*")
SEPARATORS = re.compile(r"&&|\|\||;")
PIP_INSTALL = re.compile(r"\bpip\d?\s+install\b([^\n]*)")
REQUIREMENT_FLAGS = ("-r", "--requirement")
# `pip install --upgrade pip` is bootstrapping the installer, not
# declaring a dependency, so it is the one name allowed to float.
UNPINNED_ALLOWED = {"pip"}


@pytest.fixture(scope="session")
def compose(repo_root):
    """Parse docker-compose.yml."""
    return yaml.safe_load((repo_root / "docker-compose.yml").read_text())


@pytest.fixture(scope="session")
def dockerfiles(repo_root):
    """Every Dockerfile in the repo, found rather than listed.

    Discovery is the point: a Dockerfile a later feature adds
    inherits both pinning rules instead of quietly escaping them.
    """
    found = sorted(repo_root.rglob("Dockerfile"))
    assert found
    return found


def assert_pinned(image):
    """Fail unless the image reference carries an exact version tag."""
    assert ":" in image, image
    assert PINNED_TAG.match(image.rsplit(":", 1)[1]), image


def installed_packages(text):
    """Yield each package name a `pip install` in a Dockerfile names.

    Line continuations are joined first, then commands are split on
    the shell separators, so one `RUN` chaining several installs is
    read as several. An install driven by a requirements file names
    no packages here — the file it points at carries the pins.
    """
    joined = CONTINUATION.sub(" ", text)
    for segment in SEPARATORS.split(joined):
        for match in PIP_INSTALL.finditer(segment):
            tokens = match.group(1).split()
            if any(t.split("=")[0] in REQUIREMENT_FLAGS for t in tokens):
                continue
            for token in tokens:
                if not token.startswith("-"):
                    yield token


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


def test_every_dockerfile_base_image_is_pinned(dockerfiles):
    """Confirm both built images pin their base to a patch release."""
    for path in dockerfiles:
        pattern = re.compile(r"^FROM\s+(\S+)", re.MULTILINE)
        references = pattern.findall(path.read_text())
        assert references, path
        for reference in references:
            assert_pinned(reference)


def test_every_dockerfile_pins_what_it_installs(dockerfiles):
    """Confirm no image is built from a floating pip install.

    The base image being pinned is not enough for a reproducible
    build: an unpinned `pip install` changes the image the next time
    upstream releases, without anyone asking for it.
    """
    for path in dockerfiles:
        for package in installed_packages(path.read_text()):
            if package in UNPINNED_ALLOWED:
                continue
            assert "==" in package, f"{path.name}: {package}"


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


def test_prometheus_command_sets_the_storage_path(compose):
    """Confirm the TSDB is pointed at the mounted named volume.

    Retention is no longer a flag: it lives in prometheus.yml, and
    tests/test_prometheus_config.py asserts it there.
    """
    command = compose["services"]["prometheus"]["command"]
    flags = {argument.split("=", 1)[0] for argument in command}
    for flag in STORAGE_FLAGS:
        assert flag in flags, flag
