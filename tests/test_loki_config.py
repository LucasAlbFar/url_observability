"""Structural checks on loki.yaml.

The shape tests/test_collector_config.py has: the file parses, carries
the fields the stack depends on, and agrees with what is declared
about it elsewhere. A listen port that drifts from
`prometheus.io/port` is a target sitting at `up=0`; a storage path
outside the named volume is a log store that loses everything on a
`down`, with nothing saying so until someone looks.

Whether Loki would accept the file is not asked here — the CI infra
job runs `-verify-config` for that.
"""

import pytest
import yaml

LOKI_CONFIG = "loki.yaml"
LOKI_SERVICE = "loki"
LOKI_VOLUME = "loki_data"
PORT_LABEL = "prometheus.io/port"
# v13 on tsdb is the schema that carries structured metadata, which is
# where the trace id goes. On an older schema it would have to become a
# label, and a label per trace id is a stream per request.
METADATA_SCHEMA = "v13"
METADATA_STORE = "tsdb"
# What a stream may be keyed by, and nothing else. `service.instance.id`
# is the reason this is written down rather than left to the default:
# the Python SDK sets it to a UUID per process, Loki indexes it by
# default, and the app would open a stream on every restart.
INDEXED_ATTRIBUTES = {"service.name", "log.severity"}
INDEX_ACTION = "index_label"


@pytest.fixture(scope="session")
def loki_config(repo_root):
    """Parse loki.yaml."""
    return yaml.safe_load((repo_root / LOKI_CONFIG).read_text())


def mount_target(compose, service, volume):
    """Return where a named volume is mounted, or None."""
    for entry in compose["services"][service].get("volumes", []):
        source, _, rest = entry.partition(":")
        if source == volume:
            return rest.partition(":")[0]
    return None


def test_the_store_listens_on_the_port_the_scrape_label_names(
    loki_config, compose_labels
):
    """Confirm the label points at the port Loki actually serves.

    One port carries both here — the queries Grafana runs and the
    /metrics Prometheus pulls — so a drift costs the target and the
    datasource at once.
    """
    declared = int(compose_labels[LOKI_SERVICE][PORT_LABEL])
    assert loki_config["server"]["http_listen_port"] == declared


def test_the_store_writes_inside_the_named_volume(loki_config, compose):
    """Confirm nothing Loki keeps is written outside the mount."""
    target = mount_target(compose, LOKI_SERVICE, LOKI_VOLUME)
    assert target
    common = loki_config["common"]
    paths = [common["path_prefix"], *common["storage"]["filesystem"].values()]
    for path in paths:
        assert path == target or path.startswith(f"{target}/"), path


def test_the_store_takes_no_tenant(loki_config):
    """Confirm ingestion needs no tenant header.

    With auth on, every write and every query carries `X-Scope-OrgID`
    — one more thing to declare in the Collector and in the datasource,
    for a stack with a single tenant.
    """
    assert loki_config["auth_enabled"] is False


def test_the_schema_carries_structured_metadata(loki_config):
    """Confirm the trace id has somewhere to go that is not a label."""
    configs = loki_config["schema_config"]["configs"]
    assert configs
    for entry in configs:
        assert entry["schema"] == METADATA_SCHEMA, entry
        assert entry["store"] == METADATA_STORE, entry


def resource_attribute_rules(loki_config):
    """Return the OTLP resource-attribute config, or None."""
    otlp = loki_config.get("limits_config", {}).get("otlp_config", {})
    return otlp.get("resource_attributes")


def test_only_two_attributes_become_a_stream_label(loki_config):
    """Confirm the indexed set is the decided one, not Loki's default.

    Every label combination is a stream with an index of its own, so
    this is the cardinality guard for the log store — the limits in
    prometheus.yml do not reach it.
    """
    rules = resource_attribute_rules(loki_config)
    assert rules, "the indexed attribute set is left to the default"
    indexed = {
        attribute
        for entry in rules.get("attributes_config", [])
        if entry.get("action") == INDEX_ACTION
        for attribute in entry.get("attributes", [])
    }
    assert indexed == INDEXED_ATTRIBUTES, sorted(indexed)


def test_the_defaults_are_turned_off_rather_than_added_to(loki_config):
    """Confirm the list above replaces Loki's four, not extends them.

    Without this the guard reads as correct and does nothing: the
    default set is merged in, `service.instance.id` keeps its index,
    and the app opens a stream on every restart with no rule looking
    wrong.
    """
    rules = resource_attribute_rules(loki_config)
    assert rules.get("ignore_defaults") is True, rules
