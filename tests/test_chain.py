"""The route that crosses every service.

The next hop is mocked rather than reached: the address resolves on the
compose network only, and what this asserts is this service's half of
the contract — it wraps what it received, and reports a downstream
failure as one instead of as its own.
"""

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from app.api.endpoints.chain import NEXT


def test_chain_returns_what_the_next_service_answered(client):
    """Confirm the crossing is reported whole, hop by hop."""
    answered = {"service": "service-go", "next": {"service": "service-node"}}
    downstream = MagicMock()
    downstream.json.return_value = answered

    with patch("httpx.AsyncClient.get", AsyncMock(return_value=downstream)):
        response = client.get("/chain")

    assert response.status_code == 200
    assert response.json() == {"service": "fastapi-app", "next": answered}


def test_chain_reports_a_downstream_failure_as_a_gateway_error(client):
    """Confirm a neighbour being down is not read as this service failing.

    502 rather than 500, and the address in the body: the load
    generator prints the status it got, so the difference is what says
    which of three services to go and look at.
    """
    with patch(
        "httpx.AsyncClient.get", AsyncMock(side_effect=httpx.ConnectError("refused"))
    ):
        response = client.get("/chain")

    assert response.status_code == 502
    assert NEXT in response.json()["detail"]


def test_chain_logs_which_neighbour_failed(client, caplog):
    """Confirm the failure leaves a line saying what the status cannot.

    The derived request metric counts that a 502 happened; only this
    says which address refused and with what. The trace id is not
    asserted here — nothing in a test process opens a span, and the SDK
    is what attaches it in the container.
    """
    with patch(
        "httpx.AsyncClient.get", AsyncMock(side_effect=httpx.ConnectError("refused"))
    ):
        with caplog.at_level(logging.ERROR, logger="app.api.endpoints.chain"):
            client.get("/chain")

    records = [r for r in caplog.records if r.name == "app.api.endpoints.chain"]
    assert records, caplog.records
    record = records[0]
    assert record.levelno == logging.ERROR
    assert getattr(record, "server.address") == NEXT
    assert getattr(record, "error.type") == "ConnectError"
