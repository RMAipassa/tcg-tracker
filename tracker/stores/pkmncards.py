from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from ..models import Snapshot, is_sealed_product
from .base import Store, StoreBlocked


class PkmnCards(Store):
    name = "pkmncards"
    label = "PKMNCards"
    domains = ("pkmncards.nl",)
    base = "https://pkmncards.nl"
    catalog_interval_minutes = 60
    category_paths = (
        "/c/pre-orders",
        "/c/sealed-cases",
        "/c/pokemon-tcg",
        "/c/pokemon-tcg-japans",
        "/c/pokemon-tcg-chinees",
    )

    def __init__(self, games: list[str], delay: float):
        super().__init__(games, delay)
        self._latest: list[Snapshot] = []

    def scan(self) -> list[Snapshot]:
        cached = self._cached_catalog()
        if cached is not None:
            return cached
        snapshots: dict[str, Snapshot] = {}
        if "pokemon" not in self.games:
            return []
        for path in self.category_paths:
            page = self.get(self.base + path).text
            if "you are now in line" in page.lower():
                raise StoreBlocked("PKMNCards waiting room")
            soup = BeautifulSoup(page, "html.parser")
            for card in soup.select(".product-item"):
                title_node = card.select_one(".product-item-title")
                link = card.select_one("a.product-item-link[href]")
                offer = card.select_one('[itemprop="offers"]')
                if not title_node or not link or not offer:
                    continue
                title = title_node.get_text(" ", strip=True)
                if not is_sealed_product(title):
                    continue
                url = urljoin(self.base, link["href"])
                product_id = urlparse(url).path.rstrip("/")
                price = offer.select_one('[itemprop="price"][content]')
                availability = offer.select_one('[itemprop="availability"][href]')
                image = card.select_one('[itemprop="image"][content]')
                snapshots[product_id] = Snapshot(
                    store=self.name,
                    store_product_id=product_id,
                    url=url,
                    title=title,
                    price_cents=round(float(price["content"]) * 100) if price else None,
                    in_stock=bool(availability and availability["href"].rstrip("/").endswith("/InStock")),
                    game="pokemon",
                    image=urljoin(self.base, image["content"]) if image else None,
                )
        self._latest = self._remember_catalog(list(snapshots.values()))
        return self._latest

    def fetch(self, url: str) -> Snapshot | None:
        target = urlparse(url).path.rstrip("/")
        snapshots = self._latest or self.scan()
        return next((snapshot for snapshot in snapshots if urlparse(snapshot.url).path.rstrip("/") == target), None)
