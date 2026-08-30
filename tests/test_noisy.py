"""Checks on the deliberately badly behaved service.

What is asserted is that it misbehaves: the paths are raw and their
number grows. A service that stopped doing either would leave the
cardinality guard with nothing to fire against, and every test of the
guard would pass by finding no problem.
"""

import re
import threading
import urllib.error
import urllib.request

import pytest
import yaml

from noisy import raw_path_emitter
from noisy.raw_path_emitter import FIRST, STEP, create_server

RAW_PATH = re.compile(r'handler="/users/\d+"')


@pytest.fixture
def origin():
    """Serve on an OS-chosen port, so a running stack is never hit."""
    server = create_server(port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    server.server_close()


def scrape(origin, path="/metrics"):
    """Return the status and body of one request."""
    request = urllib.request.Request(origin + path)
    try:
        with urllib.request.urlopen(request) as response:
            return response.status, response.read().decode()
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode()


def samples(body):
    """Return the sample lines, without the HELP and TYPE comments."""
    return [line for line in body.splitlines() if not line.startswith("#")]


def test_metrics_are_served_in_the_exposition_format(origin):
    status, body = scrape(origin)

    assert status == 200
    assert body.startswith("# HELP http_requests_total")
    assert "# TYPE http_requests_total counter" in body


def test_every_path_is_raw(origin):
    """Confirm no id is collapsed into a template.

    This is the whole point of the service: a `/users/{id}` here would
    make it as well behaved as the other three and leave the guard
    untested.
    """
    _, body = scrape(origin)
    lines = samples(body)

    assert lines
    assert all(RAW_PATH.search(line) for line in lines)
    assert "{id}" not in body


def test_each_scrape_reports_more_paths_than_the_last(origin):
    """Confirm the series count is a ramp, not a step.

    A fixed set of raw paths trips a ceiling once and then sits still,
    which is not the failure being guarded against: what exhausts a
    Prometheus is a count that keeps climbing.
    """
    _, first = scrape(origin)
    _, second = scrape(origin)

    assert len(samples(first)) == FIRST
    assert len(samples(second)) == FIRST + STEP


def test_the_ramp_levels_off_at_the_ceiling():
    """Confirm the ramp has a top.

    Left climbing, the body crosses Prometheus's body_size_limit in a
    couple of hours and the scrape fails outright — both Cardinality
    panels then read zero for this target, which is what a guard that
    stopped working looks like. The demo has to end in a plateau, not
    in an outage.
    """
    metrics = raw_path_emitter.RawPathMetrics(first=2, step=2, ceiling=5)

    counts = [len(samples(metrics.render())) for _ in range(5)]

    assert counts == [2, 4, 5, 5, 5]


def test_the_plateau_fits_inside_the_scrape_body_limit(repo_root):
    """Confirm the ceiling was chosen against the limit that bounds it.

    The two numbers live in different files, and raising this one
    without reading the other is precisely how the plateau turns back
    into the outage the ceiling was added to prevent.
    """
    config = yaml.safe_load((repo_root / "prometheus.yml").read_text())
    limit = config["global"]["body_size_limit"]
    assert limit.endswith("MB"), limit
    allowed = int(limit[: -len("MB")]) * 1024 * 1024

    body = raw_path_emitter.RawPathMetrics(first=raw_path_emitter.CEILING).render()

    assert len(body.encode()) < allowed


def test_an_unknown_path_answers_404(origin):
    status, _ = scrape(origin, "/health")

    assert status == 404
