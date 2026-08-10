"""Structural checks on prometheus.yml.

These assert the file parses and carries the fields the stack depends
on: the scrape configuration and the retention bounds that used to be
compose flags. Whether a target answers, and whether Prometheus
itself would accept the file, is not tested here — the CI infra job
runs `promtool check config` for the semantics.
"""

import pytest
import yaml


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


def test_storage_retention_is_bounded(prometheus_config):
    """Confirm the TSDB is capped in both time and size.

    Presence only: promtool rejects a malformed duration or size, so
    the CI infra job validates the values with the real parser.
    """
    retention = prometheus_config["storage"]["tsdb"]["retention"]
    assert retention["time"]
    assert retention["size"]


def test_every_scrape_job_has_a_target(prometheus_config):
    """Confirm no job is configured to scrape nothing."""
    for job in prometheus_config["scrape_configs"]:
        targets = [
            target
            for static in job.get("static_configs", [])
            for target in static.get("targets", [])
        ]
        assert targets, job["job_name"]
