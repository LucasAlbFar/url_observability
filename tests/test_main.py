"""Test main route."""

import asyncio
import logging
from contextlib import contextmanager

from starlette.requests import Request

from app.main import app, log_unhandled_exception


@contextmanager
def caplog_for(name):
    """Collect the records one logger emits, then put it back.

    `caplog` reaches this through the root logger, which the SDK also
    attaches to in the container — capturing on the named logger keeps
    the test about this module.
    """
    collected = []

    class Collector(logging.Handler):
        def emit(self, record):
            collected.append(record)

    logger = logging.getLogger(name)
    handler = Collector()
    logger.addHandler(handler)
    try:
        yield collected
    finally:
        logger.removeHandler(handler)


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


def test_unhandled_exceptions_are_logged_and_still_answered():
    """Confirm the line is added without changing the response.

    Two halves, because neither proves the other. Calling the handler
    says what it does — a record, and the same plain 500 Starlette
    sends with no handler registered. Reading the app's handler table
    says Starlette will call it, which is what a direct call cannot.
    """
    request = Request({"type": "http", "method": "GET", "path": "/boom", "headers": []})
    try:
        raise RuntimeError("boom")
    except RuntimeError as error:
        with caplog_for("app.main") as records:
            response = asyncio.run(log_unhandled_exception(request, error))

    assert response.status_code == 500
    assert response.body == b"Internal Server Error"
    assert records and records[0].levelno == logging.ERROR
    assert records[0].exc_info is not None
    assert getattr(records[0], "url.path") == "/boom"
    assert app.exception_handlers[Exception] is log_unhandled_exception
