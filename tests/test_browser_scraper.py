from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from playwright.async_api import Error as PlaywrightError

from app.core.config import settings
from app.services import browser_scraper
from app.services.browser_scraper import BrowserScraperError, fetch_rendered_html

URL = "https://www.sinsay.com/ua/uk/product"
RENDERED_HTML = (
    '<script type="application/ld+json">'
    '{"@type":"Product","offers":{"price":"109.00"}}'
    "</script>"
)


@pytest.fixture
def playwright_mocks(monkeypatch):
    response = SimpleNamespace(ok=True, status=200)

    locator = MagicMock()
    locator.first = SimpleNamespace(wait_for=AsyncMock())
    locator.evaluate_all = AsyncMock(return_value=RENDERED_HTML)

    page = MagicMock()
    page.goto = AsyncMock(return_value=response)
    page.locator = MagicMock(return_value=locator)

    browser = MagicMock()
    browser.new_page = AsyncMock(return_value=page)
    browser.close = AsyncMock()

    chromium = MagicMock()
    chromium.launch = AsyncMock(return_value=browser)
    playwright = SimpleNamespace(chromium=chromium)

    manager = MagicMock()
    manager.__aenter__ = AsyncMock(return_value=playwright)
    manager.__aexit__ = AsyncMock(return_value=None)

    monkeypatch.setattr(browser_scraper, "async_playwright", lambda: manager)

    return SimpleNamespace(
        browser=browser,
        locator=locator,
        page=page,
    )


async def test_fetch_rendered_html_returns_json_ld(playwright_mocks):
    html = await fetch_rendered_html(URL)

    assert html == RENDERED_HTML.encode("utf-8")
    playwright_mocks.page.goto.assert_awaited_once_with(
        URL,
        wait_until="domcontentloaded",
        timeout=settings.BROWSER_SCRAPING_TIMEOUT_SECONDS * 1000,
    )
    playwright_mocks.locator.first.wait_for.assert_awaited_once_with(
        state="attached",
        timeout=settings.BROWSER_SCRAPING_TIMEOUT_SECONDS * 1000,
    )
    playwright_mocks.browser.close.assert_awaited_once()


async def test_fetch_rendered_html_wraps_playwright_error(playwright_mocks):
    playwright_mocks.page.goto.side_effect = PlaywrightError("navigation failed")

    with pytest.raises(BrowserScraperError, match="Browser scraping failed") as exc:
        await fetch_rendered_html(URL)

    assert isinstance(exc.value.__cause__, PlaywrightError)
    playwright_mocks.browser.close.assert_awaited_once()


async def test_fetch_rendered_html_rejects_large_result(
    monkeypatch,
    playwright_mocks,
):
    monkeypatch.setattr(settings, "SCRAPER_MAX_RESPONSE_BYTES", 1)

    with pytest.raises(BrowserScraperError, match="exceeds the maximum size"):
        await fetch_rendered_html(URL)

    playwright_mocks.browser.close.assert_awaited_once()
