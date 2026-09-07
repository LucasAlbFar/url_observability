"""Test main route."""


def test_main_route(client):
    """Confirm that main root is working."""
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {"message": "Hello, FastAPI!"}


# Written before the instrumentation was retired, because nothing else
# asserted this endpoint existed: the app's HTTP metrics left with the
# library that produced them, and `/metrics` had to stay behind for the
# process and runtime collectors the resource panels read.
def test_metrics_is_served(client):
    """Confirm /metrics answers directly, without a redirect.

    `follow_redirects=False` is the whole assertion: mounting an ASGI app
    at this path answers 307 and sends the scrape to /metrics/, which a
    redirect-following client reports as a clean 200.
    """
    response = client.get("/metrics", follow_redirects=False)
    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]


def test_metrics_carries_the_process_collectors(client):
    """Confirm what the dashboard's resource panels read is still there.

    The two names are the ones the *CPU by service* and *Resident
    memory* panels query, so an exposition that lost them is a pair of
    empty panels rather than a failure anywhere.
    """
    body = client.get("/metrics").text
    for name in ("process_cpu_seconds_total", "process_resident_memory_bytes"):
        assert f"{name} " in body or f"{name}{{" in body, name


def test_metrics_carries_no_http_request_series(client):
    """Confirm the retired convention is gone rather than merely unused.

    `handler`/`status` was one of the three this feature replaces with
    the labels derived from the spans. Leaving the library in place but
    unused would keep publishing it.
    """
    client.get("/health")
    body = client.get("/metrics").text
    assert "http_requests_total" not in body
    assert "http_request_duration_seconds" not in body
