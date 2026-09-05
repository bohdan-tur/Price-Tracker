from playwright.async_api import Error as PlaywrightError
from playwright.async_api import async_playwright

from app.core.config import settings


class BrowserScraperError(RuntimeError):
    """Raised when a page cannot be rendered safely with Playwright."""


async def fetch_rendered_html(url: str) -> bytes:
    timeout_ms = settings.BROWSER_SCRAPING_TIMEOUT_SECONDS * 1000

    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)

            try:
                page = await browser.new_page()

                response = await page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=timeout_ms,
                )

                if response is None or not response.ok:
                    status = response.status if response else "unknown"
                    raise BrowserScraperError(
                        f"Browser returned an unsuccessful status: {status}"
                    )

                json_ld_scripts = page.locator('script[type="application/ld+json"]')
                await json_ld_scripts.first.wait_for(
                    state="attached",
                    timeout=timeout_ms,
                )
                rendered_html = await json_ld_scripts.evaluate_all(
                    """
                    elements => elements
                        .map(element => element.outerHTML)
                        .join("")
                    """
                )
                html = rendered_html.encode("utf-8")
            finally:
                await browser.close()

    except PlaywrightError as exc:
        raise BrowserScraperError("Browser scraping failed") from exc

    if len(html) > settings.SCRAPER_MAX_RESPONSE_BYTES:
        raise BrowserScraperError("Rendered HTML exceeds the maximum size")

    return html
