"""Structural checks on the trace path's two configuration files.

The shape tests/test_prometheus_config.py has — the files parse and
carry the fields the stack depends on — plus what is new here: values
that have to agree *across* files. A bind address, a port and a mount
path each answer to something declared somewhere else, and none of
them complains when it stops agreeing. A loopback bind refuses every
sender in this stack and logs nothing; a metrics port that drifts from
`prometheus.io/port` is a target sitting at `up=0`.

Whether either binary would accept its file is not asked here. The CI
infra job runs the Collector's `validate` and Tempo's `-config.verify`
for that.
"""

import pytest
import yaml

COLLECTOR_SERVICE = "otel-collector"
TEMPO_SERVICE = "tempo"
TEMPO_VOLUME = "tempo_data"
PORT_LABEL = "prometheus.io/port"
# An endpoint bound to one of these accepts nothing from another
# container, which is every sender and every scraper in this stack.
LOOPBACK = ("localhost", "127.0.0.1", "::1", "")


@pytest.fixture(scope="session")
def collector_config(repo_root):
    """Parse otel-collector-config.yaml."""
    return yaml.safe_load((repo_root / "otel-collector-config.yaml").read_text())


@pytest.fixture(scope="session")
def tempo_config(repo_root):
    """Parse tempo.yaml."""
    return yaml.safe_load((repo_root / "tempo.yaml").read_text())


def host_and_port(endpoint):
    """Split a `host:port` endpoint, port as an int."""
    host, _, port = str(endpoint).rpartition(":")
    return host, int(port)


def label_port(compose_labels, service):
    """Return the port a service tells Prometheus to scrape."""
    return int(compose_labels[service][PORT_LABEL])


def mount_target(compose, service, volume):
    """Return where a named volume is mounted, or None."""
    for entry in compose["services"][service].get("volumes", []):
        source, _, rest = entry.partition(":")
        if source == volume:
            return rest.partition(":")[0]
    return None


def test_the_collector_receives_otlp_off_loopback(collector_config):
    """Confirm the receiver accepts connections from other containers."""
    protocols = collector_config["receivers"]["otlp"]["protocols"]
    assert protocols
    for name, protocol in protocols.items():
        host, _ = host_and_port(protocol["endpoint"])
        assert host not in LOOPBACK, name


def test_the_collector_sends_traces_to_the_trace_store(
    collector_config, tempo_config, compose
):
    """Confirm the traces pipeline ends at the port Tempo listens on.

    Both halves matter. A host that is not a compose service resolves
    to nothing, and a port Tempo does not listen on is refused — in
    either case the spans are dropped after a retry queue fills, which
    is a log line in the Collector and an empty Explore everywhere else.
    """
    pipeline = collector_config["service"]["pipelines"]["traces"]
    exporters = [collector_config["exporters"][name] for name in pipeline["exporters"]]
    assert exporters
    receiver = tempo_config["distributor"]["receivers"]["otlp"]["protocols"]["grpc"]
    _, listening = host_and_port(receiver["endpoint"])
    for exporter in exporters:
        host, port = host_and_port(exporter["endpoint"])
        assert host in compose["services"], host
        assert port == listening, exporter["endpoint"]


def test_the_collector_publishes_its_metrics_where_prometheus_looks(
    collector_config, compose_labels
):
    """Confirm the Collector's own telemetry is reachable and declared.

    The default is `localhost:8888`, which is a refused connection from
    the Prometheus container. Declaring the reader is what makes the
    target answer, and the port has to be the one the label advertises.
    """
    readers = collector_config["service"]["telemetry"]["metrics"]["readers"]
    assert readers
    exposed = set()
    for reader in readers:
        exporter = reader["pull"]["exporter"]["prometheus"]
        assert exporter["host"] not in LOOPBACK, exporter
        exposed.add(int(exporter["port"]))
    assert label_port(compose_labels, COLLECTOR_SERVICE) in exposed, exposed


def test_the_trace_store_receives_otlp_off_loopback(tempo_config):
    """Confirm Tempo accepts what the Collector sends.

    Its default receiver binds loopback, so the section exists for this
    one line rather than for tuning.
    """
    protocols = tempo_config["distributor"]["receivers"]["otlp"]["protocols"]
    assert protocols
    for name, protocol in protocols.items():
        host, _ = host_and_port(protocol["endpoint"])
        assert host not in LOOPBACK, name


def test_the_trace_store_serves_metrics_where_prometheus_looks(
    tempo_config, compose_labels
):
    """Confirm Tempo's HTTP port is the one its label advertises."""
    assert tempo_config["server"]["http_listen_port"] == label_port(
        compose_labels, TEMPO_SERVICE
    )


def test_the_trace_store_writes_inside_its_named_volume(tempo_config, compose):
    """Confirm every path Tempo writes to survives a `down`.

    A path outside the mount is written to the container layer, and the
    only symptom is traces recorded before a restart being gone after
    it — with the stack otherwise working.
    """
    target = mount_target(compose, TEMPO_SERVICE, TEMPO_VOLUME)
    assert target, TEMPO_VOLUME
    trace = tempo_config["storage"]["trace"]
    assert trace["backend"] == "local", trace["backend"]
    for path in (trace["local"]["path"], trace["wal"]["path"]):
        assert path.startswith(f"{target}/"), path
