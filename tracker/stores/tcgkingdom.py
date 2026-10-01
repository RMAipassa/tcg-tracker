from urllib.parse import urlparse

from bs4 import BeautifulSoup

from ..models import Snapshot, is_sealed_product
from .base import Store


class TcgKingdom(Store):
    name = "tcgkingdom"
    label = "TCG Kingdom"
    domains = ("tcgkingdom.nl",)
    base = "https://www.tcgkingdom.nl"
    categories = {
        "pokemon": "/c-7536048/pokemon/",
        "mtg": "/c-7626093/magic-the-gathering/",
        "naruto": "/c-7813514/naruto/",
    }
    catalog_interval_minutes = 60

    def __init__(self, games: list[str], delay: float):
        super().__init__(games, max(delay, 5))

    def scan(self) -> list[Snapshot]:
        cached = self._cached_catalog()
        if cached is not None:
            return cached
        snapshots: dict[str, Snapshot] = {}
        for game, path in self.categories.items():
            if game not in self.games:
                continue
            soup = BeautifulSoup(self.get(self.base + path).text, "html.parser")
            for card in soup.select("ul.products > li[id^=article_]"):
                title_link = card.select_one("a.title[href]")
                if not title_link:
                    continue
                title = title_link.get_text(" ", strip=True)
                if not is_sealed_product(title):
                    continue
                image = card.select_one("a.image img[src]")
                price = card.select_one("[data-value]")
                product_id = card["id"].removeprefix("article_")
                snapshots[product_id] = Snapshot(
                    store=self.name,
                    store_product_id=product_id,
                    url=title_link["href"],
                    title=title,
                    price_cents=round(float(price["data-value"]) * 100) if price else None,
                    in_stock=bool(card.select_one("form.addToCartForm")),
                    game=game,
                    image=image["src"] if image else None,
                )
        return self._remember_catalog(list(snapshots.values()))

    def fetch(self, url: str) -> Snapshot | None:
        target = urlparse(url).path.rstrip("/")
        return next(
            (item for item in self.scan() if urlparse(item.url).path.rstrip("/") == target),
            None,
        )
