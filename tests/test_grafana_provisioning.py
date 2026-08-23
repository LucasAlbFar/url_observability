"""Structural checks on the provisioned Grafana files.

These assert each dashboard JSON parses and carries the fields
Grafana needs to load it, and that the dashboard provider points at
the path the compose file mounts. They are not a review of the
dashboards themselves — nothing here looks at a query, a panel type
or a panel's position on the grid.
"""

import json

import pytest
import yaml

DASHBOARD_BIND = "./grafana/dashboards"
PROVIDER_CONFIG = "grafana/provisioning/dashboards/dashboard.yml"
DATASOURCE_CONFIG = "grafana/provisioning/datasources/datasource.yaml"


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
