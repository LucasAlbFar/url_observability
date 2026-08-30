"""Structural checks on the provisioned Grafana files.

These assert each dashboard JSON parses, carries the fields Grafana
needs to load it, and declares the things it depends on rather than
relying on Grafana to supply them at load time: panel types, panel
ids, grid positions, datasource references and the service variable.
They are still not a review of the dashboards — nothing here proves a
query returns data or that a series was drawn on screen, and only a
browser can answer that.
"""

import itertools
import json

import pytest
import yaml

DASHBOARD_BIND = "./grafana/dashboards"
PROVIDER_CONFIG = "grafana/provisioning/dashboards/dashboard.yml"
DATASOURCE_CONFIG = "grafana/provisioning/datasources/datasource.yaml"
PROMETHEUS_CONFIG = "prometheus.yml"
COMPOSE_CONFIG = "docker-compose.yml"
JOB_LABEL = "prometheus.io/job"
# The two synthetic metrics that count a scrape, and the reason they
# have to be read as a pair. `scrape_samples_scraped` counts what the
# target emitted, *before* metric relabeling; the other counts what
# survived it. With the drop rules working, the first keeps climbing
# while the second sits still — so a panel reading the first alone
# draws a working guard as a broken one.
SAMPLES_SCRAPED = "scrape_samples_scraped"
SAMPLES_STORED = "scrape_samples_post_metric_relabeling"


@pytest.fixture(scope="session")
def dashboard_files(repo_root):
    """Return every provisioned dashboard JSON file."""
    directory = repo_root / "grafana" / "dashboards"
    paths = sorted(directory.glob("*.json"))
    assert paths, directory
    return paths


def test_every_dashboard_file_parses_as_json(dashboard_files):
    """Confirm no dashboard file is malformed."""
    for path in dashboard_files:
        json.loads(path.read_text())


def test_every_dashboard_carries_its_loading_fields(dashboard_files):
    """Confirm each dashboard has the fields Grafana loads it by."""
    for path in dashboard_files:
        dashboard = json.loads(path.read_text())
        assert dashboard.get("uid"), path.name
        assert dashboard.get("title"), path.name
        assert dashboard.get("panels"), path.name


def test_every_provisioning_file_parses_as_yaml(repo_root):
    """Confirm the datasource and provider files are readable."""
    directory = repo_root / "grafana" / "provisioning"
    paths = sorted(directory.rglob("*.y*ml"))
    assert paths, directory
    for path in paths:
        assert yaml.safe_load(path.read_text()), path.name


def test_every_datasource_declares_a_uid(repo_root):
    """Confirm no datasource lets Grafana generate its uid.

    A datasource without a `uid` still resolves, because Grafana
    invents one and dashboards may reference it by name instead. The
    invented value is not reproducible across volumes, so a dashboard
    pinned to it would break on a fresh one.
    """
    config = yaml.safe_load((repo_root / DATASOURCE_CONFIG).read_text())
    for datasource in config["datasources"]:
        assert datasource.get("uid"), datasource["name"]


def iter_panels(dashboard):
    """Yield every panel, including those nested inside a row.

    A collapsed row carries its children in its own `panels` key, so a
    flat loop over the top-level list silently skips them.
    """
    for panel in dashboard.get("panels", []):
        yield panel
        yield from panel.get("panels", [])


@pytest.fixture(scope="session")
def dashboards(dashboard_files):
    """Return each dashboard as a (name, parsed) pair."""
    return [(path.name, json.loads(path.read_text())) for path in dashboard_files]


@pytest.fixture(scope="session")
def datasource_uids(repo_root):
    """Return the uids the datasource provisioning file declares."""
    config = yaml.safe_load((repo_root / DATASOURCE_CONFIG).read_text())
    return {datasource["uid"] for datasource in config["datasources"]}


def test_no_panel_uses_the_retired_graph_type(dashboards):
    """Confirm no panel depends on the load-time schema migration.

    A `graph` panel still draws, because Grafana rewrites the type in
    the browser before resolving the plugin. The plugin itself is gone
    from the image, so the file describes something the image cannot
    render on its own.
    """
    for name, dashboard in dashboards:
        for panel in iter_panels(dashboard):
            assert panel["type"] != "graph", (name, panel.get("title"))


def test_every_panel_declares_a_unique_id(dashboards):
    """Confirm the file assigns panel ids instead of Grafana."""
    for name, dashboard in dashboards:
        ids = [panel.get("id") for panel in iter_panels(dashboard)]
        assert all(panel_id is not None for panel_id in ids), name
        assert len(ids) == len(set(ids)), (name, ids)


def test_ref_ids_are_unique_within_each_panel(dashboards):
    """Confirm no panel gives two of its targets the same refId.

    Across panels a refId may repeat; inside one it addresses a query,
    and a duplicate makes one of them unaddressable.
    """
    for name, dashboard in dashboards:
        for panel in iter_panels(dashboard):
            refs = [target["refId"] for target in panel.get("targets", [])]
            assert len(refs) == len(set(refs)), (name, panel.get("title"), refs)


def test_no_two_panels_share_grid_space(dashboards):
    """Confirm the file determines the layout, not Grafana.

    Grafana resolves a collision by stacking the panels, so this never
    looks broken on screen — which is why nothing catches it without
    an assertion.
    """
    for name, dashboard in dashboards:
        groups = [dashboard["panels"]]
        groups += [
            panel["panels"] for panel in dashboard["panels"] if panel.get("panels")
        ]
        for group in groups:
            check_no_overlap(name, group)


def check_no_overlap(name, panels):
    """Assert no two panels in one layout group overlap.

    Groups are compared separately: a collapsed row holds its children
    in its own list, and their coordinates only mean anything next to
    each other.
    """
    rects = [
        (
            panel["gridPos"]["x"],
            panel["gridPos"]["y"],
            panel["gridPos"]["x"] + panel["gridPos"]["w"],
            panel["gridPos"]["y"] + panel["gridPos"]["h"],
            panel.get("title"),
        )
        for panel in panels
    ]
    for left, right in itertools.combinations(rects, 2):
        apart = (
            left[2] <= right[0]
            or right[2] <= left[0]
            or left[3] <= right[1]
            or right[3] <= left[1]
        )
        assert apart, (name, left[4], right[4])


def test_every_query_references_a_declared_datasource_uid(dashboards, datasource_uids):
    """Confirm nothing reaches the datasource by name or by default.

    A reference by name is the legacy form, and a panel with no
    datasource at all inherits the org default — which works only for
    as long as there is exactly one.
    """
    for name, dashboard in dashboards:
        for panel in iter_panels(dashboard):
            if panel["type"] == "row":
                continue
            holders = [panel] + panel.get("targets", [])
            for holder in holders:
                datasource = holder.get("datasource")
                assert isinstance(datasource, dict), (name, panel.get("title"))
                assert datasource.get("uid") in datasource_uids, datasource


def test_every_dashboard_declares_the_service_variable(dashboards):
    """Confirm each dashboard can be filtered down to one service."""
    for name, dashboard in dashboards:
        variables = dashboard["templating"]["list"]
        assert any(variable["name"] == "job" for variable in variables), name


@pytest.fixture(scope="session")
def scrape_job_names(compose_labels):
    """Return the values the `job` label actually takes.

    The source is docker-compose.yml, not prometheus.yml. Under label
    discovery the only `job_name` in prometheus.yml names the discovery
    mechanism, so reading it left this guard forbidding a string no
    query would ever contain — green, and covering nothing. The values
    a query could name are the `prometheus.io/job` labels the services
    declare. Should a static job return, its `job_name` has to be
    unioned into this set, for the same reason.

    Read from the file rather than listed here, so a service that joins
    the scrape is covered without touching this test. The reading is
    the shared `compose_labels` fixture, which normalises both forms a
    compose label block can take — a local reader that handled only the
    mapping form would drop a list-shaped service out of this set, and
    the guard would stop rejecting that service's name.
    """
    names = {
        labels[JOB_LABEL] for labels in compose_labels.values() if JOB_LABEL in labels
    }
    assert names, COMPOSE_CONFIG
    return names


def queries(dashboard):
    """Yield every PromQL string the dashboard sends to Prometheus."""
    for panel in iter_panels(dashboard):
        for target in panel.get("targets", []):
            yield target["expr"]
    for variable in dashboard.get("templating", {}).get("list", []):
        query = variable.get("query")
        # Grafana writes a Prometheus query variable as a string or, once
        # it has been edited in the UI, as an object holding the same text
        # under its own "query" key. Reading only the first form would let
        # this test pass over the second without looking at it.
        if isinstance(query, dict):
            query = query.get("query")
        for text in (query, variable.get("definition")):
            if isinstance(text, str):
                yield text


def test_no_query_names_a_scrape_job(dashboards, scrape_job_names):
    """Confirm the dashboard separates services without naming any.

    A panel written against a literal job name works, and keeps
    working, while quietly making the file specific to the services
    that exist today. The label to select on is the one the service
    happens to carry; which service that is belongs to the `job`
    variable.
    """
    for name, dashboard in dashboards:
        for query in queries(dashboard):
            for job in scrape_job_names:
                assert job not in query, (name, job, query)


def test_datasource_time_interval_matches_the_scrape_interval(repo_root):
    """Confirm Grafana is told how often Prometheus actually scrapes.

    `$__rate_interval` is derived from this value, not from
    prometheus.yml, and Grafana falls back to its own 15s default when
    the datasource stays quiet — which silently floors every rate
    window in every dashboard at 60s.
    """
    datasources = yaml.safe_load((repo_root / DATASOURCE_CONFIG).read_text())
    prometheus = yaml.safe_load((repo_root / PROMETHEUS_CONFIG).read_text())
    scrape = prometheus["global"]["scrape_interval"]
    for datasource in datasources["datasources"]:
        declared = datasource.get("jsonData", {}).get("timeInterval")
        assert declared == scrape, (datasource["name"], declared, scrape)


def test_provider_path_matches_the_compose_mount(repo_root):
    """Confirm the provider reads the directory compose mounts."""
    config = yaml.safe_load((repo_root / PROVIDER_CONFIG).read_text())
    compose_path = repo_root / "docker-compose.yml"
    compose = yaml.safe_load(compose_path.read_text())
    grafana = compose["services"]["grafana"]
    targets = [
        mount.split(":")[1]
        for mount in grafana["volumes"]
        if mount.split(":")[0] == DASHBOARD_BIND
    ]
    assert targets == [config["providers"][0]["options"]["path"]]


def test_the_sample_ceiling_drawn_matches_the_one_enforced(dashboards, repo_root):
    """Confirm the threshold line is the limit Prometheus applies.

    The ceiling now exists in two files: enforced in prometheus.yml and
    drawn in the dashboard. Two copies of a number drift, and this one
    drifts silently — the panel keeps drawing a line, at the wrong
    height, and the graph says a target is safe while Prometheus is
    refusing it.

    Scoped to the panels that plot the stored-sample count. A threshold
    anywhere else — a red at 5 on the error-rate panel — is an ordinary
    one and has nothing to do with this limit, and reading it here
    fails the suite with a message pointing at prometheus.yml.
    """
    limit = yaml.safe_load((repo_root / PROMETHEUS_CONFIG).read_text())
    enforced = limit["global"]["sample_limit"]
    checked = 0
    for name, dashboard in dashboards:
        for panel in iter_panels(dashboard):
            plotted = [target["expr"] for target in panel.get("targets", [])]
            if not any(SAMPLES_STORED in expr for expr in plotted):
                continue
            steps = (
                panel.get("fieldConfig", {})
                .get("defaults", {})
                .get("thresholds", {})
                .get("steps", [])
            )
            for step in steps:
                if step.get("value") is None:
                    continue
                checked += 1
                assert step["value"] == enforced, (name, panel["title"], step)
    assert checked, "no threshold drawn against the sample ceiling"


def test_the_pre_relabel_sample_count_is_never_drawn_alone(dashboards):
    """Confirm a panel reading what a target emits also reads what is kept.

    Measured while building the guard: with the drop rules in place the
    noisy target reported 350 samples scraped and 0 stored. A panel on
    the first number alone shows a line climbing without bound and
    invites the reader to conclude the guard failed, when the gap
    between the two is precisely the guard working.
    """
    checked = 0
    for name, dashboard in dashboards:
        for query in queries(dashboard):
            if SAMPLES_SCRAPED not in query:
                continue
            checked += 1
            assert SAMPLES_STORED in query, (name, query)
    assert checked, f"no panel reads {SAMPLES_SCRAPED}"


def test_a_panel_reads_what_each_target_stores(dashboards):
    """Confirm the row that makes the guard visible exists at all.

    Without this the two tests above are satisfied by a dashboard that
    draws no cardinality panel whatsoever, which is the state this
    ticket set out to leave behind.
    """
    drawn = [
        query
        for _, dashboard in dashboards
        for query in queries(dashboard)
        if SAMPLES_STORED in query
    ]
    assert drawn
