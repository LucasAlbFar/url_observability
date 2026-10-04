"""Test the route that fails on purpose."""

import logging

from fastapi.testclient import TestClient

from app.main import app
from tests.test_main import caplog_for


def test_fail_is_answered_and_logged():
    """Confirm the route reaches the unhandled-exception handler.

    A client of its own: Starlette re-raises after the handler answers,
    and the default client turns that into a test failure. What the
    route exists for is the 500 and the line, so both are asserted.
    """
    client = TestClient(app, raise_server_exceptions=False)

    with caplog_for("app.main") as records:
        response = client.get("/fail")

    assert response.status_code == 500
    assert response.text == "Internal Server Error"
    assert records and records[0].levelno == logging.ERROR
    assert getattr(records[0], "url.path") == "/fail"
