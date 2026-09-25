"""bol.com: watchlist items only, loaded in a headless Chromium via Playwright.

bol.com renders with JavaScript and blocks automated clients. This adapter does nothing to
hide that it is automated: when bol shows a block page or captcha it pauses for a day.

Optional dependency:
    pip install playwright
    python -m playwright install chromium

Check the parser against a page you saved from your own browser (Ctrl+S):
    python -m tracker.stores.bol saved-page.html
"""
import json
import re
import sys
import threading
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from ..config import DATA_DIR
from ..models import Snapshot, detect_game
from .base import Store, StoreBlocked

_PRODUCT_ID = re.compile(r"/p/[^/]+/(\d+)")
_PRODUCT_PATH = re.compile(r"^(/.*?/p/[^/]+/\d+)")
_LD_JSON = re.compile(r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>', re.S | re.I)
_BLOCK_MARKERS = re.compile(r"is blocked|temporarily blocked|tijdelijk geblokkeerd|captcha|access denied", re.I)
_IN_STOCK = {"instock", "limitedavailability", "onlineonly", "preorder", "presale"}


def _product_nodes(data) -> list[dict]:
    """All schema.org Product objects in a JSON-LD blob (handles lists and @graph)."""
    if isinstance(data, list):
        return [n for item in data for n in _product_nodes(item)]
    if not isinstance(data, dict):
        return []
    if "@graph" in data:
        return _product_nodes(data["@graph"])
    types = data.get("@type")
    types = types if isinstance(types, list) else [types]
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

    product = products[0]
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
    catalog = False
    min_interval_minutes = 60
    pause_hours = 24

    def __init__(self, games: list[str], delay: float):
        super().__init__(games, delay)
        self._lock = threading.Lock()  # one browser profile, one user at a time
        self._paused_until: datetime | None = None

    def configure(self, options: dict) -> None:
        self.min_interval_minutes = max(30, int(options.get("min_interval_minutes", 60)))
        self.pause_hours = int(options.get("pause_hours_when_blocked", 24))

    def scan(self) -> list[Snapshot]:
        return []

    def fetch(self, url: str) -> Snapshot | None:
        if self._paused_until and datetime.now(timezone.utc) < self._paused_until:
            raise StoreBlocked(f"paused until {self._paused_until:%Y-%m-%d %H:%M} UTC after a block")
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
            self._paused_until = datetime.now(timezone.utc) + timedelta(hours=self.pause_hours)
            raise

    def _load(self, url: str) -> tuple[str, int]:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise RuntimeError("Playwright is not installed: pip install playwright && python -m playwright install chromium")
        self._wait_for_delay()
        # A persistent profile keeps cookies (e.g. the cookie consent) between runs, like a normal browser.
        with sync_playwright() as p:
            context = p.chromium.launch_persistent_context(
                str(DATA_DIR / "bol-browser"), headless=True, locale="nl-NL",
            )
            try:
                page = context.new_page()
                response = page.goto(url, wait_until="domcontentloaded", timeout=45000)
                try:
                    page.wait_for_selector('script[type="application/ld+json"]', state="attached", timeout=10000)
                except Exception:
                    pass  # parse_product reports what is missing
                return page.content(), response.status if response else 0
            finally:
                context.close()

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
