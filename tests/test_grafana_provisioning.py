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
        rects = [
            (
                panel["gridPos"]["x"],
                panel["gridPos"]["y"],
                panel["gridPos"]["x"] + panel["gridPos"]["w"],
                panel["gridPos"]["y"] + panel["gridPos"]["h"],
                panel.get("title"),
            )
            for panel in dashboard["panels"]
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
def scrape_job_names(repo_root):
    """Return the job names prometheus.yml declares.

    Read from the file rather than listed here, so a service added to
    the scrape configuration is covered without touching this test.
    `prometheus_config` is not reused: it lives in the module that
    tests prometheus.yml and is not visible from here.
    """
    config = yaml.safe_load((repo_root / PROMETHEUS_CONFIG).read_text())
    names = {job["job_name"] for job in config["scrape_configs"]}
    assert names, PROMETHEUS_CONFIG
    return names


def queries(dashboard):
    """Yield every PromQL string the dashboard sends to Prometheus."""
    for panel in iter_panels(dashboard):
        for target in panel.get("targets", []):
            yield target["expr"]
    for variable in dashboard.get("templating", {}).get("list", []):
        if "query" in variable:
            yield variable["query"]


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
