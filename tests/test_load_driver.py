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


def test_urls_drive_every_service_in_the_load_profile(driven_services):
    """Confirm the generator hits every service that comes up with it.

    Derived from the compose file rather than counted here: a service
    that joins the scrape and is never called draws the flat line its
    own healthcheck produces, and nothing says why. A hand-written
    count would have to be edited by whoever adds the next service,
    which is the moment the check is worth the least.

    The set is the scraped services **in the load profile**, not every
    scraped service. Those were the same set until a service joined the
    scrape to be observed misbehaving and stayed out of the load
    profile on purpose; equality against the wider set then reports a
    deliberate absence as a missing URL.
    """
    driven = {
        f"{name}:{labels['prometheus.io/port']}"
        for name, labels in driven_services.items()
    }
    assert driven
    hosts = {url.split("/")[2] for url in load_driver.URLS}
    assert hosts == driven


def test_the_app_health_route_is_not_driven():
    """Confirm the app's own healthcheck is not duplicated here.

    All three services answer /health; only the other two need traffic
    from this list, since the app's compose healthcheck probes its own
    every ten seconds.
    """
    assert "http://app:8002/health" not in load_driver.URLS
    assert "http://service-go:8003/health" in load_driver.URLS
    assert "http://service-node:8004/health" in load_driver.URLS
