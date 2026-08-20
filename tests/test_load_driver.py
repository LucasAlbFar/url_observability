from unittest.mock import AsyncMock, patch

import pytest

import worker.load_driver as load_driver


@pytest.mark.asyncio
async def test_call_endpoint_success():
    mock_response = AsyncMock()
    mock_response.status_code = 200

    with patch("httpx.AsyncClient.get", return_value=mock_response):
        await load_driver.call_endpoint("http://test")


@pytest.mark.asyncio
async def test_call_endpoint_failure():
    with patch("httpx.AsyncClient.get", side_effect=Exception("fail")):
        await load_driver.call_endpoint("http://fail")


@pytest.mark.asyncio
async def test_main_loop_once(monkeypatch):
    monkeypatch.setattr(load_driver, "URLS", ["http://test"])
    monkeypatch.setattr(load_driver, "call_endpoint", AsyncMock())

    await load_driver.main(cycles=1)


def test_urls_drive_both_services():
    """Confirm the generator hits the Go service as well as the app."""
    assert len(load_driver.URLS) == 7
    hosts = {url.split("/")[2] for url in load_driver.URLS}
    assert hosts == {"app:8002", "service-go:8003"}


def test_the_app_health_route_is_not_driven():
    """Confirm the app's own healthcheck is not duplicated here.

    Both services answer /health; only the Go one needs traffic from
    this list, since the app's compose healthcheck probes its own
    every ten seconds.
    """
    assert "http://app:8002/health" not in load_driver.URLS
    assert "http://service-go:8003/health" in load_driver.URLS
