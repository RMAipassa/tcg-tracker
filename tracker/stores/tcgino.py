"""TCGino adapter using public search and product pages."""
import re
import time
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from ..models import Snapshot, detect_game, is_sealed_product
from .base import Store

_CATALOGS = {
    "pokemon": (
        "/booster-boxes",
        "/elite-trainer-boxes",
        "/collection-boxes",
        "/tins",
        "/packs-blisters",
        "/japans-chinees-koreaans",
        "/mystery-products",
        "/cases-voordeelbundels",
        "/decks",
    ),
    "mtg": ("/magic-the-gathering",),
}


def _price(text: str) -> int | None:
    match = re.search(r"(\d[\d.]*)[,.](\d{2})", text.replace("\xa0", " "))
    return int(match.group(1).replace(".", "")) * 100 + int(match.group(2)) if match else None


class Tcgino(Store):
    name = "tcgino"
    label = "TCGino"
    domains = ("tcgino.nl",)
    base = "https://tcgino.nl"

    def __init__(self, games: list[str], delay: float):
        super().__init__(games, delay)
        self.catalog_interval_minutes = 60
        self._catalog_cache: list[Snapshot] = []
        self._catalog_scanned_at = 0.0

    def configure(self, options: dict) -> None:
        self.catalog_interval_minutes = max(15, int(options.get("catalog_interval_minutes", 60)))

    def scan(self) -> list[Snapshot]:
        if self._catalog_cache and time.monotonic() - self._catalog_scanned_at < self.catalog_interval_minutes * 60:
            return self._catalog_cache
        candidates: dict[str, tuple[str, str]] = {}
        for game, paths in _CATALOGS.items():
            if game not in self.games:
                continue
            for path in paths:
                page = 1
                while True:
                    soup = BeautifulSoup(
                        self.get(self.base + path, params={"p": page}).text,
                        "html.parser",
                    )
                    cards = soup.select("a.product-card[href]")
                    for card in cards:
                        title_node = card.select_one(".product-card-name")
                        if not title_node:
                            continue
                        title = title_node.get_text(" ", strip=True)
                        brand = card.select_one(".product-card-merk")
                        detected_game = detect_game(" ".join((title, brand.get_text(" ", strip=True) if brand else "")))
                        if detected_game in (None, game) and is_sealed_product(title):
                            candidates[card["href"]] = (title, game)
                    if len(cards) < 24:
                        break
                    page += 1
        if not candidates:
            raise ValueError("TCGino categories have no sealed product cards")
        snapshots: dict[str, Snapshot] = {}
        for url, (_, game) in candidates.items():
            snapshot = self.fetch(url)
            if snapshot:
                snapshot.game = game
                snapshots[snapshot.store_product_id] = snapshot
        self._catalog_cache = list(snapshots.values())
        self._catalog_scanned_at = time.monotonic()
        return self._catalog_cache

    def fetch(self, url: str) -> Snapshot | None:
        soup = BeautifulSoup(self.get(url).text, "html.parser")
        content = soup.select_one(".product-info")
        title = content.select_one("h1.product-info-name") if content else None
        if not content or not title:
            return None
        path = urlparse(url).path.rstrip("/")
        slug = path.rsplit("/", 1)[-1]
        if not slug:
            return None
        canonical = soup.select_one('link[rel="canonical"]')
        image = soup.select_one(".product-layout img")
        title_text = title.get_text(" ", strip=True)
        price = content.select_one(".product-info-price .price-now")
        return Snapshot(
            store=self.name,
            store_product_id=slug,
            url=canonical.get("href") if canonical else url,
            title=title_text,
            price_cents=_price(price.get_text(" ", strip=True)) if price else None,
            in_stock=bool(content.select_one(".product-info-stock.in-stock, .btn-add-cart")),
            game=detect_game(" ".join((title_text, content.get_text(" ", strip=True)))),
            image=image.get("src") if image else None,
        )
