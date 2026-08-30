"""Structural checks on prometheus.yml.

These assert the file parses and carries the fields the stack depends
on: the scrape configuration and the retention bounds that used to be
compose flags. Whether a target answers, and whether Prometheus
itself would accept the file, is not tested here — the CI infra job
runs `promtool check config` for the semantics.
"""

import re

import pytest
import yaml

SCRAPE_META = "__meta_docker_container_label_prometheus_io_scrape"
PROJECT_FILTER = "com.docker.compose.project"
# The labels a service can put a URL path in. Hand-written, and this is
# the one place in this ticket where that is the honest answer: the set
# comes from three instrumentation libraries, not from any file in this
# repo, so there is nothing to derive it from. `handler` is the FastAPI
# instrumentator's, `route` the Node service's; the Go service exports
# no path label. A fourth convention needs a fourth entry here and a
# third rule in prometheus.yml — the cost of three live conventions,
# owed to the feature that unifies them.
PATH_LABELS = ("handler", "route")
# The ceiling and the label limits. Every one fails the whole scrape
# for the target that trips it, so each has to be present and each has
# to be a positive number — a zero or a missing key is not a loose
# limit, it is no limit.
SCRAPE_LIMITS = (
    "sample_limit",
    "label_limit",
    "label_name_length_limit",
    "label_value_length_limit",
    "target_limit",
    "body_size_limit",
)
# Naming a target is what a drop rule must not do. It works, it is
# easier to write, and it puts the list of services back into a file
# that discovery emptied of service names.
TARGET_LABELS = ("job", "instance")
# Values a well-behaved service in this stack really reports, and
# values a badly behaved one does. The regex is what a mistake would
# live in, so it is exercised against both rather than merely asserted
# to exist.
RAW_VALUES = (
    "/users/1",
    "/users/42/posts",
    "/orders/9c8f1a2b-3d4e-4f50-8a1b-2c3d4e5f6071",
)
LABELLED_VALUES = (
    "/health",
    "/load/io-bound",
    "/load/cpu-bound",
    "/load/memory-spike",
    "/load/stress/{seconds}",
    "/metrics",
    "/api/v1/users",
    "none",
    "unmatched",
)


@pytest.fixture(scope="session")
def prometheus_config(repo_root):
    """Parse prometheus.yml."""
    return yaml.safe_load((repo_root / "prometheus.yml").read_text())


def test_a_global_scrape_interval_is_set(prometheus_config):
    """Confirm scraping is not left to the Prometheus default."""
    assert prometheus_config["global"]["scrape_interval"]


def test_at_least_one_scrape_job_exists(prometheus_config):
    """Confirm the file would actually collect something."""
    assert prometheus_config["scrape_configs"]


def test_every_scrape_job_names_itself(prometheus_config):
    """Confirm each job carries the label its series are keyed by."""
    for job in prometheus_config["scrape_configs"]:
        assert job.get("job_name"), job


def test_scrape_job_names_are_unique(prometheus_config):
    """Confirm no two jobs claim the same `job` label.

    Prometheus accepts a duplicated job_name, so promtool does not
    catch this: the second job's series simply land under the first
    one's label, which is the only thing separating two services that
    export the same metric names.
    """
    names = [job["job_name"] for job in prometheus_config["scrape_configs"]]
    assert len(names) == len(set(names)), names


def test_storage_retention_is_bounded(prometheus_config):
    """Confirm the TSDB is capped in both time and size.

    Presence only: promtool rejects a malformed duration or size, so
    the CI infra job validates the values with the real parser.
    """
    retention = prometheus_config["storage"]["tsdb"]["retention"]
    assert retention["time"]
    assert retention["size"]


def _sd_configs(job):
    """Return the discovery blocks a job declares, by any mechanism."""
    return [key for key in job if key.endswith("_sd_configs") and job[key]]


def test_every_scrape_job_has_a_target(prometheus_config):
    """Confirm no job is configured to scrape nothing.

    Under discovery "does this job scrape anything" stops having a
    static answer: the addresses arrive from the Docker socket at
    runtime and are not in this file. So the test asks for a source of
    targets — a `static_configs` carrying addresses, or any
    `*_sd_configs` block — rather than for a list of addresses.
    """
    for job in prometheus_config["scrape_configs"]:
        targets = [
            target
            for static in job.get("static_configs", [])
            for target in static.get("targets", [])
        ]
        assert targets or _sd_configs(job), job["job_name"]


def test_discovery_is_opt_in(prometheus_config):
    """Confirm a discovery job keeps only the containers that asked.

    Without a `keep`, discovery means scraping every container that
    starts — Prometheus and Grafana included — which is the cardinality
    door a later feature exists to close, left open early.
    """
    for job in prometheus_config["scrape_configs"]:
        if not _sd_configs(job):
            continue
        # The source label matters as much as the action: a `keep` on
        # some other label would satisfy a looser assertion while
        # leaving this door open.
        keeps = [
            rule
            for rule in job.get("relabel_configs", [])
            if rule.get("action") == "keep"
            and SCRAPE_META in rule.get("source_labels", [])
        ]
        assert keeps, job["job_name"]


def test_discovery_is_scoped_to_this_project(prometheus_config, repo_root):
    """Confirm discovery cannot reach another stack's containers.

    The socket enumerates every container on the host, and
    `prometheus.io/scrape` is a convention other stacks use too, so the
    opt-in alone does not scope it. A foreign container would join with
    an address rebuilt from its own compose service name, which does
    not resolve on this network: a permanently down target, and a
    foreign value in the `job` dropdown.

    The expected value is compose's default project name, the
    directory name. That coupling is deliberate — a mismatch means
    discovery silently returns nothing, and the container still reports
    healthy while every panel goes empty.
    """
    expected = f"{PROJECT_FILTER}={repo_root.name}"
    for job in prometheus_config["scrape_configs"]:
        for key in _sd_configs(job):
            for config in job[key]:
                values = [
                    value
                    for entry in config.get("filters", [])
                    if entry.get("name") == "label"
                    for value in entry.get("values", [])
                ]
                assert expected in values, job["job_name"]


def drop_rules(prometheus_config):
    """Yield every metric_relabel rule that discards a series."""
    for job in prometheus_config["scrape_configs"]:
        for rule in job.get("metric_relabel_configs", []):
            if rule.get("action") == "drop":
                yield job["job_name"], rule


def test_a_drop_rule_covers_every_path_carrying_label(prometheus_config):
    """Confirm no convention is left without a guard.

    There is no wildcard over label values in Prometheus:
    `source_labels` names labels explicitly, and labeldrop/labelkeep
    match label names rather than their values. So one rule per
    path-carrying label is the only shape available, and a convention
    missing from the list is a service the first layer never sees.
    """
    covered = {
        label
        for _, rule in drop_rules(prometheus_config)
        for label in rule.get("source_labels", [])
    }
    assert covered, "no drop rule declared"
    for label in PATH_LABELS:
        assert label in covered, label


def test_no_drop_rule_selects_on_a_target_label(prometheus_config):
    """Confirm the guard is generic rather than a list of services.

    A rule keyed on `job` would work and would undo what discovery
    bought: prometheus.yml stops naming services, and the moment one
    rule names one, the next reader adds the second.
    """
    checked = 0
    for name, rule in drop_rules(prometheus_config):
        checked += 1
        for label in rule.get("source_labels", []):
            assert label not in TARGET_LABELS, f"{name}: {label}"
    assert checked, "no drop rule declared"


def test_a_drop_rule_discards_raw_paths_and_keeps_labelled_ones(prometheus_config):
    """Confirm the regex does what the rule claims.

    Prometheus anchors a relabel regex at both ends, so `fullmatch` is
    what reproduces it here. Both directions matter and the second
    matters more: a regex that drops everything also drops every raw
    path, and would pass a test that only checked the first.
    """
    checked = 0
    for name, rule in drop_rules(prometheus_config):
        checked += 1
        pattern = re.compile(rule["regex"])
        for value in RAW_VALUES:
            assert pattern.fullmatch(value), f"{name}: kept {value}"
        for value in LABELLED_VALUES:
            assert not pattern.fullmatch(value), f"{name}: dropped {value}"
    assert checked, "no drop rule declared"


def test_every_scrape_limit_is_declared_and_positive(prometheus_config):
    """Confirm the backstop exists and bounds something.

    Presence and sign only: whether `4MB` parses as a size is
    promtool's question, and the CI infra job asks it. What cannot be
    asked there is whether a limit was quietly dropped from this file,
    since a config with no limits at all is perfectly valid.
    """
    limits = prometheus_config["global"]
    for name in SCRAPE_LIMITS:
        assert name in limits, name
        value = limits[name]
        assert value, name
        if isinstance(value, int):
            assert value > 0, name


def test_no_scrape_limit_is_declared_on_a_single_job(prometheus_config):
    """Confirm the limits are global rather than per job.

    There is one job today, which is exactly when writing a limit on it
    looks equivalent to writing it in `global:` and is not: the next
    job added inherits the global block and inherits nothing from its
    neighbour. The failure would be a new job scraping with no ceiling
    at all, and nothing here or in promtool would say so.
    """
    for job in prometheus_config["scrape_configs"]:
        for name in SCRAPE_LIMITS:
            assert name not in job, f"{job['job_name']}: {name}"
