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
