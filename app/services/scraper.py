import asyncio
import ipaddress
import json
import logging
import re
import socket
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from urllib.parse import urlparse

import httpx
import idna
from bs4 import BeautifulSoup

from app.core.config import settings

logger = logging.getLogger("root")
logging.getLogger("httpx").setLevel(logging.WARNING)

COMMON_SELECTORS = [
    ".product_price_current",
    ".js-current-price",
    ".price--current",
    ".price__value",
    ".product-price",
]
PRICE_QUANTUM = Decimal("0.01")


class UnsafeScraperURLError(ValueError):
    """Raised when a scraper target violates the URL security policy."""


class ScraperResponseError(RuntimeError):
    """Raised when a scraper response violates resource limits."""


@dataclass(frozen=True, slots=True)
class ValidatedTarget:
    url: str
    hostname: str


def _normalize_hostname(hostname: str) -> str:

    normalized = hostname.removesuffix(".")

    if not normalized:
        raise UnsafeScraperURLError("Invalid scraper hostname")

    try:
        ipaddress.ip_address(normalized)

    except ValueError:
        pass

    else:
        raise UnsafeScraperURLError("IP addresses are not allowed")

    try:
        normalized = idna.encode(
            normalized,
            uts46=True,
            std3_rules=True,
        ).decode("ascii")

    except idna.IDNAError as exc:
        raise UnsafeScraperURLError("Invalid scraper hostname") from exc

    return normalized.lower()


def _is_allowed_hostname(hostname: str) -> bool:

    for allowed_domain in settings.SCRAPER_ALLOWED_DOMAINS:
        normalized_allowed = _normalize_hostname(allowed_domain)

        if hostname == normalized_allowed:
            return True

        if hostname.endswith(f".{normalized_allowed}"):
            return True

    return False


def _validate_target_url(url: str) -> ValidatedTarget:

    if len(url) > settings.SCRAPER_MAX_URL_LENGTH:
        raise UnsafeScraperURLError("Scraper URL is too long")
    try:
        parsed = urlparse(url)
        port = parsed.port
    except ValueError as exc:
        raise UnsafeScraperURLError("Invalid scraper URL ") from exc

    if parsed.fragment:
        raise UnsafeScraperURLError("URL fragments are not allowed")

    if parsed.scheme != "https":
        raise UnsafeScraperURLError("Only  HTTPS URLs are allowed")

    if not parsed.hostname:
        raise UnsafeScraperURLError("Scraper URL must contain a hostname")

    if parsed.username is not None or parsed.password is not None:
        raise UnsafeScraperURLError("Credentials in scraper URLs are not allowed")

    if port is not None:
        raise UnsafeScraperURLError("Explicit ports are not allowed")

    hostname = _normalize_hostname(parsed.hostname)

    if not _is_allowed_hostname(hostname):
        raise UnsafeScraperURLError("Scraper hostname is not allowed")

    return ValidatedTarget(url=url, hostname=hostname)


async def validate_scraper_url(url: str) -> ValidatedTarget:

    target = _validate_target_url(url)
    loop = asyncio.get_running_loop()

    try:
        address_info = await loop.getaddrinfo(
            target.hostname,
            None,
            family=socket.AF_UNSPEC,
            type=socket.SOCK_STREAM,
        )

    except OSError as exc:
        raise UnsafeScraperURLError("Scraper hostname could not be resolved") from exc
    addresses = {entry[4][0] for entry in address_info}

    if not addresses:
        raise UnsafeScraperURLError("Scraper hostname did not resolve to any address")

    for address in addresses:
        try:
            ip = ipaddress.ip_address(address)

        except ValueError as exc:
            raise UnsafeScraperURLError(
                "Scraper hostname resolved to an invalid address"
            ) from exc

        if not ip.is_global:
            raise UnsafeScraperURLError(
                "Scraper hostname resolved to a non-global address"
            )

        if (
            isinstance(ip, ipaddress.IPv6Address)
            and ip.ipv4_mapped is not None
            and not ip.ipv4_mapped.is_global
        ):
            raise UnsafeScraperURLError(
                "Scraper hostname resolved to a non-global mapped address"
            )

    return target


async def _read_limited_response(response: httpx.Response) -> bytes:
    content_type = response.headers.get("content-type", "")
    media_type = content_type.split(";", 1)[0].strip().lower()
    if media_type not in {"text/html", "application/xhtml+xml"}:
        raise ScraperResponseError("Scraper response is not HTML")

    content_length = response.headers.get("content-length")
    if content_length is not None:
        try:
            declared_size = int(content_length)

        except ValueError as exc:
            raise ScraperResponseError(
                "Scraper response has an invalid Content-Length"
            ) from exc

        if declared_size < 0:
            raise ScraperResponseError("Scraper response has an invalid Content-Length")

        if declared_size > settings.SCRAPER_MAX_RESPONSE_BYTES:
            raise ScraperResponseError("Scraper response exceeds the maximum size")

    body = bytearray()

    async for chunk in response.aiter_bytes():
        if len(body) + len(chunk) > settings.SCRAPER_MAX_RESPONSE_BYTES:
            raise ScraperResponseError("Scraper response exceeds the maximum size")

        body.extend(chunk)

    return bytes(body)


def _parse_decimal_price(value: object) -> Decimal | None:
    try:
        price = Decimal(str(value))

        if not price.is_finite() or price <= 0:
            return None

        return price.quantize(PRICE_QUANTUM, rounding=ROUND_HALF_UP)

    except (InvalidOperation, TypeError, ValueError):
        return None


def _extract_price(html: bytes) -> Decimal | None:

    soup = BeautifulSoup(html, "lxml")

    scripts = soup.find_all("script", type="application/ld+json")

    for script in scripts:
        try:
            data = json.loads(script.string or "")

        except (json.JSONDecodeError, TypeError):
            continue

        products = data if isinstance(data, list) else [data]

        for product in products:
            if not isinstance(product, dict):
                continue

            if product.get("@type") != "Product":
                continue

            offers = product.get("offers")

            offers_list = offers if isinstance(offers, list) else [offers]

            for offer in offers_list:
                if not isinstance(offer, dict):
                    continue

                price = _parse_decimal_price(offer.get("price"))

                if price is not None:
                    return price

    price_meta = soup.find("meta", property="product:price:amount")

    if price_meta:
        content = price_meta.get("content")

        price = _parse_decimal_price(content)

        if price is not None:
            return price

    price_element = soup.select_one(", ".join(COMMON_SELECTORS))

    if price_element:
        raw_text = price_element.get_text(strip=True)

        cleaned_text = re.sub(
            r"[^\d.]",
            "",
            raw_text.replace(",", "."),
        )

        if cleaned_text and len(cleaned_text) < 10:
            return _parse_decimal_price(cleaned_text)

    return None


async def get_current_price(url: str) -> Decimal | None:

    target = await validate_scraper_url(url)

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "uk-UA,uk;q=0.9,en-US;q=0.8,en;q=0.7",
    }

    timeout = httpx.Timeout(
        connect=3.0,
        read=7.0,
        write=7.0,
        pool=3.0,
    )

    limits = httpx.Limits(
        max_connections=20,
        max_keepalive_connections=10,
    )

    try:
        async with httpx.AsyncClient(
            headers=headers,
            timeout=timeout,
            limits=limits,
            follow_redirects=False,
            trust_env=False,
        ) as client:
            async with client.stream("GET", target.url) as response:
                response.raise_for_status()

                body = await _read_limited_response(response)
        price = await asyncio.to_thread(_extract_price, body)
    except (httpx.HTTPError, ScraperResponseError) as exc:
        logger.warning(
            "Scraping failed for host=%s error=%s",
            target.hostname,
            type(exc).__name__,
        )
        return None

    if price is None:
        logger.warning(
            "Price was not found for host=%s",
            target.hostname,
        )

    return price
