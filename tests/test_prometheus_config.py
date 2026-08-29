"""Structural checks on prometheus.yml.

These assert the file parses and carries the fields the stack depends
on: the scrape configuration and the retention bounds that used to be
compose flags. Whether a target answers, and whether Prometheus
itself would accept the file, is not tested here — the CI infra job
runs `promtool check config` for the semantics.
"""

import pytest
import yaml

SCRAPE_META = "__meta_docker_container_label_prometheus_io_scrape"
PROJECT_FILTER = "com.docker.compose.project"


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
