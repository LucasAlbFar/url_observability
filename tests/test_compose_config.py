"""Structural checks on docker-compose.yml.

These parse the compose file and assert the invariants the stack
hardening introduced: pinned tags, named volumes, profiles,
healthchecks, the storage path and the labels a service scrapes by.
Nothing here starts a container,
so they say nothing about whether the stack actually comes up.
"""

import re

import pytest
import yaml

PINNED_TAG = re.compile(r"^v?\d+\.\d+\.\d+$")
FROM_IMAGE = re.compile(r"^FROM\s+(\S+)", re.MULTILINE)
# The base image name that marks a Dockerfile as Go-built.
GO_BASE = "golang"
GO_MODULE_FILES = ("go.mod", "go.sum")
NAMED_VOLUMES = {"prometheus_data", "grafana_data"}
EXPECTED_MOUNTS = {
    "prometheus": "prometheus_data:/prometheus",
    "grafana": "grafana_data:/var/lib/grafana",
}
STORAGE_FLAGS = ("--storage.tsdb.path",)
CONTINUATION = re.compile(r"\\\s*\n\s*")
COMMENT = re.compile(r"^\s*#.*$", re.MULTILINE)
SEPARATORS = re.compile(r"&&|\|\||;")
# One entry per ecosystem the repo installs from, with the separator
# that pins a version in it. `npm ci` matches too and names no package:
# it installs the lockfile, which is the pin.
INSTALL_COMMANDS = (
    (re.compile(r"\bpip\d?\s+install\b([^\n]*)"), "=="),
    (re.compile(r"\bnpm\s+(?:install|add|i|ci)\b([^\n]*)"), "@"),
)
REQUIREMENT_FLAGS = ("-r", "--requirement")
# `pip install --upgrade pip` is bootstrapping the installer, not
# declaring a dependency, so it is the one name allowed to float.
UNPINNED_ALLOWED = {"pip"}
# What has to follow the separator for a reference to count as pinned:
# a version, not a tag or a range. `latest`, `^5.0.0` and `~1.2` fail.
EXACT_VERSION = re.compile(r"^v?\d+(\.\d+)*$")
NODE_BASE = "node"
NODE_MODULE_FILES = ("package.json", "package-lock.json")
NPM_CI = re.compile(r"\bnpm\s+ci\b")
# The scrape contract: a service joins by declaring these, and nothing
# else. The path label is optional and defaults to /metrics.
SCRAPE_LABEL = "prometheus.io/scrape"
JOB_LABEL = "prometheus.io/job"
PORT_LABEL = "prometheus.io/port"
DOCKER_SOCKET = "/var/run/docker.sock"


@pytest.fixture(scope="session")
def compose(repo_root):
    """Parse docker-compose.yml."""
    return yaml.safe_load((repo_root / "docker-compose.yml").read_text())


@pytest.fixture(scope="session")
def dockerfiles(repo_root):
    """Every Dockerfile in the repo, found rather than listed.

    Discovery is the point: a Dockerfile a later feature adds
    inherits both pinning rules instead of quietly escaping them.

    Installed dependencies are not this repo's to pin, and `rglob` does
    not read .gitignore — so `node_modules`, which exists on a
    developer's machine after `npm ci` and never in CI, is skipped.
    """
    found = [
        path
        for path in sorted(repo_root.rglob("Dockerfile"))
        if "node_modules" not in path.parts
    ]
    assert found
    return found


def assert_pinned(image):
    """Fail unless the image reference carries an exact version tag."""
    assert ":" in image, image
    assert PINNED_TAG.match(image.rsplit(":", 1)[1]), image


def instructions(text):
    """Return a Dockerfile's instructions, with the prose removed.

    Every reader below greps for a command, and a comment explaining
    that command reads exactly like it: prose about `npm install` was
    parsed as an install, and prose about `npm ci` satisfied the
    assertion that the image installs through it. Both are gone once
    the comments are.
    """
    return COMMENT.sub("", text)


def named_packages(arguments):
    """Yield the package names in one install command's arguments.

    A requirements flag takes the next token with it, and only those
    two: skipping the whole command instead — which is what this did
    until now — let `pip install -r base.txt gunicorn` install an
    unpinned package and pass green.
    """
    tokens = iter(arguments.split())
    for token in tokens:
        if token in REQUIREMENT_FLAGS:
            next(tokens, None)
            continue
        if token.startswith("-"):
            continue
        yield token


def installed_packages(text):
    """Yield each package a Dockerfile installs, with the separator
    that would pin it.

    This reads **pip and npm**. A Dockerfile built in another language
    names no packages here, so it passes
    test_every_dockerfile_pins_what_it_installs vacuously. That is
    accepted rather than overlooked: for a Go image what replaces the
    guarantee is `go.sum`, a cryptographic hash per module and a
    stricter pin than `==`, asserted present and non-empty by
    test_every_go_dockerfile_commits_its_module_checksums. Teaching
    this parser to read Go would be a second, weaker verifier of what
    `go.sum` already guarantees. For Node the same role is played by
    `package-lock.json` and `npm ci`, asserted by
    test_every_node_dockerfile_commits_its_lockfile.

    Line continuations are joined first, then commands are split on
    the shell separators, so one `RUN` chaining several installs is
    read as several. An install driven by a requirements file or by a
    lockfile names no packages here — the file it points at carries
    the pins.
    """
    joined = CONTINUATION.sub(" ", instructions(text))
    for segment in SEPARATORS.split(joined):
        for pattern, separator in INSTALL_COMMANDS:
            for match in pattern.finditer(segment):
                for package in named_packages(match.group(1)):
                    yield package, separator


def is_pinned(package, separator):
    """Report whether the reference names an exact version.

    The leading `@` of a scoped npm package is dropped first, so
    `@scope/name` reads as unpinned and `@scope/name@1.2.3` as pinned.
    What follows the separator has to look like a version: `@` alone
    would accept `express@latest` and `express@^5.0.0`, which pin
    nothing and would leave this test weaker than the claim made for
    it.
    """
    name, found, version = package.lstrip("@").partition(separator)
    return bool(found) and bool(EXACT_VERSION.match(version))


def scraped_services(compose_labels):
    """Yield each service that opted into the scrape, with its labels.

    The labels come from the shared `compose_labels` fixture, which is
    also what the dashboard's genericity guard reads: one reader
    normalising the label block and the other not is how that guard
    would quietly stop covering a service.
    """
    for name, labels in compose_labels.items():
        if labels.get(SCRAPE_LABEL) == "true":
            yield name, labels


def socket_mounts(service):
    """Yield each Docker socket mount a service declares, read-only first.

    Compose accepts a volume as a short string or as a long mapping.
    Reading only the string form raises on the other, which is a loud
    failure but the wrong one.
    """
    for volume in service.get("volumes", []):
        if isinstance(volume, str):
            source, _, rest = volume.partition(":")
            if source == DOCKER_SOCKET:
                yield rest.endswith(":ro")
        elif volume.get("source") == DOCKER_SOCKET:
            yield bool(volume.get("read_only"))


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
    """Confirm every built image pins its base to a patch release.

    Multi-stage counts: the matcher returns one reference per FROM,
    so a build stage cannot float while the final stage is pinned.
    """
    for path in dockerfiles:
        references = FROM_IMAGE.findall(path.read_text())
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
        for package, separator in installed_packages(path.read_text()):
            if package in UNPINNED_ALLOWED:
                continue
            assert is_pinned(
                package, separator
            ), f"{path.parent.name}/{path.name}: {package}"


def test_every_go_dockerfile_commits_its_module_checksums(dockerfiles):
    """Confirm a Go image pins dependencies where Go pins them.

    The pip test above cannot see a Go build, so this is what stands
    in for it: `go.sum` carries a hash per module, but only if it is
    committed rather than resolved at build time. A `go install
    pkg@latest` would escape both tests, which is why the image
    resolves through `go mod download`.
    """
    checked = 0
    for path in dockerfiles:
        references = FROM_IMAGE.findall(path.read_text())
        if not any(ref.startswith(GO_BASE) for ref in references):
            continue
        checked += 1
        for name in GO_MODULE_FILES:
            module_file = path.parent / name
            assert module_file.is_file(), f"{path.parent.name}: {name}"
            assert module_file.read_text().strip(), f"{path.parent.name}: {name}"
    # Without this the test passes by finding nothing to check, which
    # is the exact failure mode it exists to close.
    assert checked, "no Go Dockerfile found"


def test_every_node_dockerfile_commits_its_lockfile(dockerfiles):
    """Confirm a Node image pins dependencies where npm pins them.

    The parser above sees a `npm ci` naming no package and has nothing
    to check, which is correct rather than a gap: `npm ci` installs
    exactly `package-lock.json` and fails when the lockfile and the
    manifest have drifted apart. That is the guarantee, so this
    asserts the two files are committed and that the image installs
    through `npm ci` — a plain `npm install` would resolve versions at
    build time and escape both.
    """
    checked = 0
    for path in dockerfiles:
        text = path.read_text()
        if not any(ref.startswith(NODE_BASE) for ref in FROM_IMAGE.findall(text)):
            continue
        checked += 1
        assert NPM_CI.search(
            instructions(text)
        ), f"{path.parent.name}: installs without npm ci"
        for name in NODE_MODULE_FILES:
            module_file = path.parent / name
            assert module_file.is_file(), f"{path.parent.name}: {name}"
            assert module_file.read_text().strip(), f"{path.parent.name}: {name}"
    # Without this the test passes by finding nothing to check, which
    # is the exact failure mode it exists to close.
    assert checked, "no Node Dockerfile found"


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


def serving_services(compose):
    """Yield each service that answers requests, by the port it opens.

    The rule replaces a hand-written tuple. Listing the services meant
    that a new one was covered only if whoever added it also edited the
    list, and the test would have gone on passing if they did not —
    which is exactly how a third service could have arrived with no
    readiness probe and nothing to say so.

    Publishing a port is what separates the two kinds of service here:
    the load generator opens none, calls the others and answers
    nobody, so there is nothing to probe.
    """
    for name, service in compose["services"].items():
        if service.get("ports"):
            yield name


def test_serving_services_declare_a_healthcheck(compose):
    """Confirm every container that answers requests reports readiness."""
    checked = 0
    for name in serving_services(compose):
        checked += 1
        assert "healthcheck" in compose["services"][name], name
    # Without this the test passes by finding nothing to check, which
    # is the failure mode the tuple it replaced could not have.
    assert checked, "no serving service found"


def test_loadgen_waits_for_every_service_it_drives(compose, compose_labels):
    """Confirm the generator races none of the services it hits.

    Derived, like the healthcheck rule above and for the same reason:
    the tuple this replaced named two services, so the third could —
    and did — reach `depends_on` with nothing asserting it, and
    deleting it again would leave the test green while the generator
    hammers a service that has not reported ready.
    """
    depends_on = compose["services"]["loadgen"]["depends_on"]
    driven = [name for name, _ in scraped_services(compose_labels)]
    assert driven
    for name in driven:
        assert depends_on[name]["condition"] == "service_healthy", name


def test_prometheus_command_sets_the_storage_path(compose):
    """Confirm the TSDB is pointed at the mounted named volume.

    Retention is no longer a flag: it lives in prometheus.yml, and
    tests/test_prometheus_config.py asserts it there.
    """
    command = compose["services"]["prometheus"]["command"]
    flags = {argument.split("=", 1)[0] for argument in command}
    for flag in STORAGE_FLAGS:
        assert flag in flags, flag


def test_scraped_services_declare_a_job_and_a_port(compose_labels):
    """Confirm an opted-in service carries the rest of the contract.

    A `replace` rule *deletes* the label it targets when the value is
    empty, so a service opting in without `prometheus.io/job` does not
    fall back to anything — it would be scraped carrying no `job` at
    all. `prometheus.yml` drops such a container rather than storing
    it under a broken identity; this is where the omission is reported
    as the mistake it is, instead of as a service that silently never
    appears.
    """
    checked = 0
    for name, labels in scraped_services(compose_labels):
        checked += 1
        assert labels.get(JOB_LABEL), name
        assert labels.get(PORT_LABEL), name
    assert checked, "no service opted into the scrape"


def test_scrape_job_labels_are_unique(compose_labels):
    """Confirm no two services claim the same `job` label.

    This is where the invariant behind test_scrape_job_names_are_unique
    now lives. With a single discovery job, job names in prometheus.yml
    can no longer collide; the collision moved to the labels, and
    Prometheus still folds the second service's series under the first
    one's label without complaining.
    """
    # A service missing the label belongs to the completeness test
    # above; counting it here would report two such services as a
    # collision with each other.
    jobs = [
        labels[JOB_LABEL]
        for _, labels in scraped_services(compose_labels)
        if JOB_LABEL in labels
    ]
    assert len(jobs) == len(set(jobs)), jobs


def test_prometheus_reads_the_docker_socket_unprivileged(compose):
    """Confirm discovery has its socket, and does not take it as root.

    `user: root` would also read the socket and is a one-way door:
    prometheus_data belongs to `nobody`, and files written as root are
    not readable again after a revert. `group_add` is what makes a
    660 root:docker socket readable without that.

    `:ro` is asserted as the declared minimum, not as a boundary: it
    protects the file node and not the API, and whoever reads that
    socket enumerates every container on the host either way.
    """
    service = compose["services"]["prometheus"]
    read_only = list(socket_mounts(service))
    assert read_only, service["volumes"]
    assert all(read_only), service["volumes"]
    assert service.get("group_add"), service.get("group_add")
    assert "user" not in service
