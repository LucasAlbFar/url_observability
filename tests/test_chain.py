"""The route that crosses every service.

The next hop is mocked rather than reached: the address resolves on the
compose network only, and what this asserts is this service's half of
the contract — it wraps what it received, and reports a downstream
failure as one instead of as its own.
"""

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
