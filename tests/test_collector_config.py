"""Structural checks on the telemetry path's two configuration files.

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

from urllib.parse import urlparse

import pytest
import yaml

COLLECTOR_SERVICE = "otel-collector"
TEMPO_SERVICE = "tempo"
TEMPO_VOLUME = "tempo_data"
PORT_LABEL = "prometheus.io/port"
OTLP_ENDPOINT = "OTEL_EXPORTER_OTLP_ENDPOINT"
OTLP_PROTOCOL = "OTEL_EXPORTER_OTLP_PROTOCOL"
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


def pipelines(collector_config, kind):
    """Yield (name, pipeline) for every pipeline of one signal.

    Read by prefix rather than by name: a pipeline of a given signal is
    either `traces` or `traces/<something>`, and a test that named them
    would stop seeing the next one added.
    """
    for name, pipeline in collector_config["service"]["pipelines"].items():
        if name == kind or name.startswith(f"{kind}/"):
            yield name, pipeline


def published_exporters(collector_config, compose_labels):
    """Return the exporters bound to the port the scrape label names.

    The crossing that decides whether the Collector is a target at all.
    """
    wanted = label_port(compose_labels, COLLECTOR_SERVICE)
    found = {}
    for name, exporter in collector_config["exporters"].items():
        endpoint = exporter.get("endpoint", "")
        host, _, port = str(endpoint).rpartition(":")
        if port.isdigit() and int(port) == wanted and host not in LOOPBACK:
            found[name] = exporter
    return found


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
    """Confirm something answers on the port the label advertises.

    A port that drifts from `prometheus.io/port` is a target sitting at
    `up=0`. Found by endpoint rather than by name: the name is what a
    rewrite may change, the port is what Prometheus depends on.
    """
    exporters = published_exporters(collector_config, compose_labels)
    assert exporters, label_port(compose_labels, COLLECTOR_SERVICE)
    served = {
        name
        for _, pipeline in pipelines(collector_config, "metrics")
        for name in pipeline["exporters"]
    }
    assert set(exporters) <= served, (sorted(exporters), sorted(served))


def test_the_collectors_own_telemetry_reaches_that_same_port(
    collector_config, compose_labels
):
    """Confirm the Collector did not fall out of its own dashboard.

    One port per container means the internal reader is loopback-only
    and reaches Prometheus through a receiver that scrapes it back. Drop
    that receiver and the Collector still exports and still boots clean,
    reporting nothing about itself.
    """
    readers = collector_config["service"]["telemetry"]["metrics"]["readers"]
    assert readers
    internal = {
        int(reader["pull"]["exporter"]["prometheus"]["port"]) for reader in readers
    }
    scraped = {
        host_and_port(target)[1]
        for receiver in collector_config["receivers"].values()
        for scrape in receiver.get("config", {}).get("scrape_configs", [])
        for static in scrape.get("static_configs", [])
        for target in static["targets"]
    }
    assert internal <= scraped, (sorted(internal), sorted(scraped))

    reading = {
        name
        for name, receiver in collector_config["receivers"].items()
        if receiver.get("config", {}).get("scrape_configs")
    }
    published = set(published_exporters(collector_config, compose_labels))
    for _, pipeline in pipelines(collector_config, "metrics"):
        if reading & set(pipeline["receivers"]):
            assert published & set(pipeline["exporters"]), pipeline
            break
    else:
        raise AssertionError("no metrics pipeline reads the internal telemetry")


def test_the_internal_scrape_does_not_republish_a_second_target(collector_config):
    """Confirm the self-scrape's own `up` and `scrape_*` are dropped.

    Republished, they make Prometheus read two targets for one
    container. The drop has to be a filter: the receiver adds them
    outside the reach of `metric_relabel_configs`.
    """
    reading = {
        name
        for name, receiver in collector_config["receivers"].items()
        if receiver.get("config", {}).get("scrape_configs")
    }
    assert reading, "nothing scrapes the internal telemetry"
    filters = {
        name
        for name in collector_config["processors"]
        if name.split("/")[0] == "filter"
    }
    for name, pipeline in pipelines(collector_config, "metrics"):
        if not reading & set(pipeline["receivers"]):
            continue
        standing = filters & set(pipeline.get("processors", []))
        assert standing, (name, pipeline)
        for processor in standing:
            dropped = collector_config["processors"][processor]["metrics"]["metric"]
            assert any("up" in condition for condition in dropped), dropped
            assert any("scrape_" in condition for condition in dropped), dropped


def test_the_request_metrics_are_derived_from_the_spans(
    collector_config, compose_labels
):
    """Confirm the connector sits between the two signals.

    A traces pipeline has to feed it and a metrics pipeline has to carry
    what it emits. Either half missing validates, boots, and produces no
    request metric at all.
    """
    connectors = set(collector_config["connectors"])
    assert connectors
    fed = {
        name
        for _, pipeline in pipelines(collector_config, "traces")
        for name in pipeline["exporters"]
    }
    assert connectors <= fed, (sorted(connectors), sorted(fed))

    published = set(published_exporters(collector_config, compose_labels))
    for _, pipeline in pipelines(collector_config, "metrics"):
        if connectors & set(pipeline["receivers"]):
            assert published & set(pipeline["exporters"]), pipeline
            break
    else:
        raise AssertionError("no metrics pipeline reads the connector")


def test_only_server_spans_are_counted(collector_config):
    """Confirm the filter guards the connector and nothing else.

    Missing, every /chain hop is counted twice and throughput comes out
    multiplied. On the trace store's branch the same filter would decide
    what Tempo holds.
    """
    connectors = set(collector_config["connectors"])
    filters = {
        name
        for name in collector_config["processors"]
        if name.split("/")[0] == "filter"
    }
    assert filters, "no filter processor declared"
    for name, pipeline in pipelines(collector_config, "traces"):
        counted = bool(connectors & set(pipeline["exporters"]))
        filtered = bool(filters & set(pipeline.get("processors", [])))
        assert counted == filtered, (name, pipeline)


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


def test_the_traced_services_send_where_the_collector_listens(
    collector_config, compose, compose_environments
):
    """Confirm each sender's endpoint is a receiver the Collector has.

    The crossing nothing else checks, and the quietest of them all:
    move either side and every test in this file still passes, both
    binaries still accept their configuration, the Collector still
    boots clean, and the spans go nowhere with no error anywhere.

    The protocol decides which receiver to check against — `grpc` on
    4317, anything else on the http one — because the two ports are
    declared in the same block and picking the wrong one is exactly the
    mistake this asserts against.
    """
    protocols = collector_config["receivers"]["otlp"]["protocols"]
    listening = {
        name: host_and_port(protocol["endpoint"])[1]
        for name, protocol in protocols.items()
    }
    checked = 0
    for name, declared in compose_environments.items():
        endpoint = declared.get(OTLP_ENDPOINT)
        if not endpoint:
            continue
        checked += 1
        parsed = urlparse(endpoint)
        assert parsed.hostname in compose["services"], (name, endpoint)
        protocol = declared.get(OTLP_PROTOCOL, "")
        expected = "grpc" if protocol.startswith("grpc") else "http"
        assert expected in listening, (name, protocol, sorted(listening))
        assert parsed.port == listening[expected], (name, endpoint, listening)
    assert checked, "no service exports OTLP"
