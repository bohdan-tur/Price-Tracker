import asyncio
import socket

import httpx
import pytest

from app.core.config import settings
from app.services.scraper import (
    ScraperResponseError,
    UnsafeScraperURLError,
    _read_limited_response,
    get_current_price,
    validate_scraper_url,
)


@pytest.fixture
async def public_dns(monkeypatch):
    async def fake_getaddrinfo(*args, **kwargs):
        return [
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                socket.IPPROTO_TCP,
                "",
                ("8.8.8.8", 0),
            )
        ]

    loop = asyncio.get_running_loop()
    monkeypatch.setattr(loop, "getaddrinfo", fake_getaddrinfo)


async def test_get_current_price_success(httpx_mock, public_dns):
    fake_html = """
    <html>
        <body>
            <span class="price__value">1500.00</span>
        </body>
    </html>
    """

    httpx_mock.add_response(
        url="https://rozetka.com.ua/fake_item/",
        text=fake_html,
        status_code=200,
        headers={"Content-Type": "text/html; charset=utf-8"},
    )

    price = await get_current_price("https://rozetka.com.ua/fake_item/")

    assert price == 1500.0


async def test_get_current_price_not_found(httpx_mock, public_dns):
    httpx_mock.add_response(
        url="https://rozetka.com.ua/fake_item/",
        text="<html><body><h1>Product not found</h1></body></html>",
        headers={"Content-Type": "text/html; charset=utf-8"},
    )

    price = await get_current_price("https://rozetka.com.ua/fake_item/")

    assert price is None


async def test_get_current_price_network_error(httpx_mock, public_dns):
    httpx_mock.add_exception(
        httpx.ReadTimeout("Connection timeout"),
        url="https://rozetka.com.ua/fake_item/",
    )

    price = await get_current_price("https://rozetka.com.ua/fake_item/")

    assert price is None


@pytest.mark.parametrize(
    "url",
    [
        "http://rozetka.com.ua/product",
        "https://user:password@rozetka.com.ua/product",
        "https://rozetka.com.ua:8443/product",
        "https://rozetka.com.ua/product#reviews",
        "https://rozetka.com.ua.evil.example/product",
        "https://127.0.0.1/product",
    ],
)
async def test_validate_scraper_url_rejects_unsafe_url_structure(url):
    with pytest.raises(UnsafeScraperURLError):
        await validate_scraper_url(url)


async def test_validate_scraper_url_rejects_too_long_url():
    url = "https://rozetka.com.ua/" + "a" * settings.SCRAPER_MAX_URL_LENGTH

    with pytest.raises(UnsafeScraperURLError, match="too long"):
        await validate_scraper_url(url)


@pytest.mark.parametrize(
    "addresses",
    [
        ["127.0.0.1"],
        ["::1"],
        ["10.0.0.1"],
        ["169.254.1.1"],
        ["::ffff:127.0.0.1"],
        ["8.8.8.8", "127.0.0.1"],
    ],
)
async def test_validate_scraper_url_rejects_non_global_dns(monkeypatch, addresses):
    async def fake_getaddrinfo(*args, **kwargs):
        return [
            (
                socket.AF_INET6 if ":" in address else socket.AF_INET,
                socket.SOCK_STREAM,
                socket.IPPROTO_TCP,
                "",
                (address, 0),
            )
            for address in addresses
        ]

    loop = asyncio.get_running_loop()
    monkeypatch.setattr(loop, "getaddrinfo", fake_getaddrinfo)

    with pytest.raises(UnsafeScraperURLError, match="non-global"):
        await validate_scraper_url("https://rozetka.com.ua/product")


async def test_validate_scraper_url_rejects_dns_failure(monkeypatch):
    async def fake_getaddrinfo(*args, **kwargs):
        raise socket.gaierror("DNS failure")

    loop = asyncio.get_running_loop()
    monkeypatch.setattr(loop, "getaddrinfo", fake_getaddrinfo)

    with pytest.raises(UnsafeScraperURLError, match="could not be resolved"):
        await validate_scraper_url("https://rozetka.com.ua/product")


async def test_read_limited_response_rejects_non_html():
    response = httpx.Response(
        status_code=200,
        headers={"Content-Type": "application/pdf"},
        content=b"fake PDF",
    )

    with pytest.raises(ScraperResponseError, match="not HTML"):
        await _read_limited_response(response)


async def test_read_limited_response_rejects_large_content_length():
    response = httpx.Response(
        status_code=200,
        headers={
            "Content-Type": "text/html",
            "Content-Length": str(settings.SCRAPER_MAX_RESPONSE_BYTES + 1),
        },
        content=b"small body",
    )

    with pytest.raises(ScraperResponseError, match="maximum size"):
        await _read_limited_response(response)


async def test_read_limited_response_rejects_large_stream():
    class OversizedStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"a" * settings.SCRAPER_MAX_RESPONSE_BYTES
            yield b"b"

    response = httpx.Response(
        status_code=200,
        headers={"Content-Type": "text/html"},
        stream=OversizedStream(),
    )

    with pytest.raises(ScraperResponseError, match="maximum size"):
        await _read_limited_response(response)


async def test_get_current_price_does_not_follow_redirect(
    httpx_mock,
    public_dns,
    caplog,
):
    url = "https://rozetka.com.ua/product?token=secret-value"

    httpx_mock.add_response(
        url=url,
        status_code=302,
        headers={"Location": "http://127.0.0.1/admin"},
    )

    price = await get_current_price(url)

    assert price is None
    assert len(httpx_mock.get_requests()) == 1
    assert str(httpx_mock.get_requests()[0].url) == url
    assert "secret-value" not in caplog.text
