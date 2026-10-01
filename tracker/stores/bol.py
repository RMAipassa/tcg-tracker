"""bol.com: Pokemon catalog and watchlist items, loaded via Playwright.

bol.com renders with JavaScript and blocks automated clients. The browser omits the standard
webdriver signal; when bol shows a block page or captcha the adapter pauses for a day.

Install dependencies and Chromium:
    powershell -ExecutionPolicy Bypass -File ./install.ps1

Check the parser against a page you saved from your own browser (Ctrl+S):
    python -m tracker.stores.bol saved-page.html
"""
import json
import os
import re
import sys
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

from ..config import DATA_DIR
from ..models import Snapshot, detect_game, is_sealed_product
from .base import Store, StoreBlocked

_CATALOG_URL = "https://www.bol.com/nl/nl/l/pokemon-kaarten/55042/"
_PRODUCT_ID = re.compile(r"/p/[^/]+/(\d+)")
_PRODUCT_PATH = re.compile(r"^(/.*?/p/[^/]+/\d+)")
_LD_JSON = re.compile(r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>', re.S | re.I)
_BLOCK_MARKERS = re.compile(r"is blocked|temporarily blocked|tijdelijk geblokkeerd|captcha|access denied", re.I)
_IN_STOCK = {"instock", "limitedavailability", "onlineonly", "preorder", "presale"}
_LISTING_SCRIPT = r"""() => {
    const products = new Map();
    for (const link of document.querySelectorAll('a[href*="/p/"]')) {
        const title = link.textContent.trim();
        const match = link.pathname.match(/\/p\/[^/]+\/(\d+)/);
        if (!title || link.search || !match || products.has(match[1])) continue;

        let card = link.parentElement;
        while (card && card !== document.body) {
            if (card.querySelector("img") && card.innerText.includes("Prijsinformatie en bestellen")) break;
            card = card.parentElement;
        }
        if (!card || card === document.body) continue;

        const priceLabel = Array.from(card.querySelectorAll("span")).find(
            span => span.textContent.startsWith("De prijs van dit product is")
        );
        const priceMatch = priceLabel && priceLabel.textContent.match(/([\d.]+)\D+euro(?:\D+(\d{1,2})\D+cent)?/i);
        const euros = priceMatch ? Number(priceMatch[1].replace(/\./g, "")) : null;
        const priceCents = euros === null ? null : euros * 100 + Number(priceMatch[2] || 0);
        const image = card.querySelector("img");
        const imageCandidates = image ? [
            image.currentSrc,
            image.getAttribute("data-src"),
            image.getAttribute("data-lazy-src"),
            image.getAttribute("src"),
            ...Array.from(image.getAttribute("srcset")?.matchAll(/(?:^|,)\s*(\S+)/g) || [], match => match[1]),
        ] : [];
        products.set(match[1], {
            id: match[1],
            url: `${location.origin}${link.pathname}`,
            title,
            price_cents: priceCents,
            in_stock: priceCents !== null && !/niet leverbaar/i.test(card.innerText),
            image: imageCandidates.find(src => src && !src.startsWith("data:")) || null,
        });
    }

    const pages = [1];
    for (const link of document.querySelectorAll('a[href*="page="]')) {
        const page = Number(new URL(link.href).searchParams.get("page"));
        if (Number.isInteger(page)) pages.push(page);
    }
    return {products: Array.from(products.values()), pages: Math.max(...pages)};
}"""


def _product_nodes(data) -> list[dict]:
    """All schema.org Product objects in a JSON-LD blob."""
    if isinstance(data, list):
        return [n for item in data for n in _product_nodes(item)]
    if not isinstance(data, dict):
        return []
    if "@graph" in data:
        return _product_nodes(data["@graph"])
    types = data.get("@type")
    types = types if isinstance(types, list) else [types]
    if "ProductGroup" in types:
        variants = _product_nodes(data.get("hasVariant", []))
        return variants or [data]
    return [data] if "Product" in types else []


def parse_product(html: str, url: str) -> Snapshot:
    match = _PRODUCT_ID.search(url)
    if not match:
        raise ValueError(f"Not a bol.com product URL: {url}")
    products = []
    for block in _LD_JSON.findall(html):
        try:
            products += _product_nodes(json.loads(block))
        except json.JSONDecodeError:
            continue
    if not products:
        if _BLOCK_MARKERS.search(html[:20000]):
            raise StoreBlocked("block page or captcha instead of the product page")
        raise ValueError("No product data found on the page (layout changed?)")

    product = next((item for item in products if str(item.get("productID")) == match.group(1)), products[0])
    offers = product.get("offers") or {}
    offers = offers[0] if isinstance(offers, list) and offers else offers
    price = offers.get("price", offers.get("lowPrice"))
    availability = str(offers.get("availability", "")).rsplit("/", 1)[-1].lower()
    image = product.get("image")
    image = image[0] if isinstance(image, list) and image else image
    if isinstance(image, dict):
        image = image.get("url")
    name = product.get("name", "").strip()
    return Snapshot(
        store="bol",
        store_product_id=match.group(1),
        url=url,
        title=name,
        price_cents=round(float(price) * 100) if price not in (None, "") else None,
        in_stock=availability in _IN_STOCK,
        game=detect_game(name),
        image=image,
    )


class Bol(Store):
    name = "bol"
    label = "bol.com"
    domains = ("bol.com",)
    catalog = True
    min_interval_minutes = 60
    catalog_interval_minutes = 60
    catalog_pages = 0
    pause_hours = 24

    def __init__(self, games: list[str], delay: float):
        super().__init__(games, delay)
        self._lock = threading.Lock()  # one browser profile, one user at a time
        self._catalog_paused_until: datetime | None = None
        self._fetch_paused_until: datetime | None = None
        self._catalog_scanned_at: datetime | None = None
        self._catalog_cache: list[Snapshot] = []

    def configure(self, options: dict) -> None:
        self.catalog = "pokemon" in self.games
        self.min_interval_minutes = max(30, int(options.get("min_interval_minutes", 60)))
        self.catalog_interval_minutes = max(30, int(options.get("catalog_interval_minutes", 60)))
        self.catalog_pages = max(0, int(options.get("catalog_pages", 0)))
        self.pause_hours = int(options.get("pause_hours_when_blocked", 24))

    def scan(self) -> list[Snapshot]:
        self._raise_if_paused(self._catalog_paused_until)
        current = datetime.now(timezone.utc)
        if self._catalog_scanned_at and current - self._catalog_scanned_at < timedelta(minutes=self.catalog_interval_minutes):
            return list(self._catalog_cache)

        try:
            with self._lock, self._browser_context() as context:
                page = context.pages[0] if context.pages else context.new_page()
                snapshots: dict[str, Snapshot] = {}
                page_number = 1
                last_page = 1
                while page_number <= last_page and (not self.catalog_pages or page_number <= self.catalog_pages):
                    self._wait_for_delay()
                    url = _CATALOG_URL if page_number == 1 else f"{_CATALOG_URL}?page={page_number}"
                    status = self._navigate(page, url, 'a[href*="/p/"]')
                    if status in (403, 429):
                        raise StoreBlocked(f"HTTP {status} on catalog page {page_number}")
                    listing = page.evaluate(_LISTING_SCRIPT)
                    if not listing["products"]:
                        if _BLOCK_MARKERS.search(page.content()[:20000]):
                            raise StoreBlocked(f"block page or captcha on catalog page {page_number}")
                        # Client-side rendering occasionally produces a blank page during a long catalog pass.
                        self._wait_for_delay()
                        status = self._navigate(page, url, 'a[href*="/p/"]')
                        if status in (403, 429):
                            raise StoreBlocked(f"HTTP {status} on catalog page {page_number}")
                        listing = page.evaluate(_LISTING_SCRIPT)
                        if not listing["products"]:
                            raise ValueError(f"No products found on catalog page {page_number} after retry")
                    for product in listing["products"]:
                        title = product["title"]
                        if detect_game(title) == "pokemon" and is_sealed_product(title):
                            snapshots[product["id"]] = Snapshot(
                                store=self.name,
                                store_product_id=product["id"],
                                url=product["url"],
                                title=title,
                                price_cents=product["price_cents"],
                                in_stock=product["in_stock"],
                                game="pokemon",
                                image=product["image"],
                            )
                    last_page = listing["pages"]
                    page_number += 1
        except StoreBlocked:
            self._catalog_paused_until = datetime.now(timezone.utc) + timedelta(hours=self.pause_hours)
            raise

        self._catalog_cache = list(snapshots.values())
        self._catalog_scanned_at = current
        return list(self._catalog_cache)

    def fetch(self, url: str) -> Snapshot | None:
        self._raise_if_paused(self._fetch_paused_until)
        path = _PRODUCT_PATH.match(urlparse(url).path)
        if not path:
            raise ValueError(f"Not a bol.com product URL: {url}")
        clean = f"https://www.bol.com{path.group(1)}/"
        with self._lock:
            html, status = self._load(clean)
        try:
            if status in (403, 429):
                raise StoreBlocked(f"HTTP {status}")
            return parse_product(html, clean)
        except StoreBlocked:
            self._fetch_paused_until = datetime.now(timezone.utc) + timedelta(hours=self.pause_hours)
            raise

    @contextmanager
    def _browser_context(self):
        local_browsers = DATA_DIR / "playwright"
        has_local_chromium = any(path.is_dir() for path in local_browsers.glob("chromium-*"))
        if has_local_chromium:
            os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(local_browsers))

        browser_channel = None
        if sys.platform == "win32" and not has_local_chromium:
            locations = (
                ("chrome", "ProgramFiles", "Google/Chrome/Application/chrome.exe"),
                ("chrome", "ProgramFiles(x86)", "Google/Chrome/Application/chrome.exe"),
                ("chrome", "LocalAppData", "Google/Chrome/Application/chrome.exe"),
                ("msedge", "ProgramFiles", "Microsoft/Edge/Application/msedge.exe"),
                ("msedge", "ProgramFiles(x86)", "Microsoft/Edge/Application/msedge.exe"),
                ("msedge", "LocalAppData", "Microsoft/Edge/Application/msedge.exe"),
            )
            browser_channel = next((channel for channel, root, path in locations
                                    if os.environ.get(root) and (Path(os.environ[root]) / path).is_file()), None)
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise RuntimeError("Playwright is not installed: run install.ps1")
        # A persistent profile keeps cookies (e.g. the cookie consent) between runs, like a normal browser.
        with sync_playwright() as p:
            context = p.chromium.launch_persistent_context(
                str(DATA_DIR / "bol-browser"),
                headless=True,
                locale="nl-NL",
                service_workers="block",
                args=[
                    "--disable-background-networking",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-component-update",
                    "--disable-default-apps",
                    "--disable-extensions",
                    "--disable-gpu",
                    "--disable-sync",
                    "--metrics-recording-only",
                    "--mute-audio",
                    "--no-first-run",
                ],
                channel=browser_channel,
            )
            try:
                # Product URLs remain in the DOM, so loading their binary assets is unnecessary.
                context.route(
                    "**/*",
                    lambda route, request: route.abort()
                    if request.resource_type in {"image", "media", "font"}
                    else route.continue_(),
                )
                # Run before site scripts in every page and frame.
                context.add_init_script("delete Object.getPrototypeOf(navigator).webdriver")
                yield context
            finally:
                context.close()

    def _load(self, url: str) -> tuple[str, int]:
        self._wait_for_delay()
        with self._browser_context() as context:
            page = context.pages[0] if context.pages else context.new_page()
            status = self._navigate(page, url, 'script[type="application/ld+json"]')
            return page.content(), status

    @staticmethod
    def _navigate(page, url: str, selector: str) -> int:
        response = page.goto(url, wait_until="domcontentloaded", timeout=45000)
        try:
            page.wait_for_selector(selector, state="attached", timeout=10000)
        except Exception:
            pass  # the parser reports missing content or a block page
        return response.status if response else 0

    @staticmethod
    def _raise_if_paused(paused_until: datetime | None) -> None:
        if paused_until and datetime.now(timezone.utc) < paused_until:
            raise StoreBlocked(f"paused until {paused_until:%Y-%m-%d %H:%M} UTC after a block")

    def _wait_for_delay(self) -> None:
        import time

        wait = self.delay - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait)
        self._last_request = time.monotonic()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: python -m tracker.stores.bol <saved-page.html>")
    page_html = open(sys.argv[1], encoding="utf-8", errors="replace").read()
    canonical = re.search(r'<link[^>]+rel="canonical"[^>]+href="([^"]+)"', page_html)
    print(parse_product(page_html, canonical.group(1) if canonical else "https://www.bol.com/nl/nl/p/x/0/"))
