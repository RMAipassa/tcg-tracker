import re
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from ..models import Snapshot, detect_game, is_sealed_product
from .base import Store


class CardCorner(Store):
    name = "cardcorner"
    label = "CardCorner"
    domains = ("card-corner.de",)
    base = "https://www.card-corner.de"
    catalog_interval_minutes = 60
    categories = {
        "pokemon": ("/Pokemon-Display", "/Pokemon-Box", "/Pokemon-Booster", "/pokemon-mystery-box"),
        "mtg": (
            "/mtg-play-booster",
            "/mtg-collector-booster",
            "/mtg-commander-decks",
            "/Theme-Decks",
            "/Scene-Boxen",
            "/Beginner-Boxen",
        ),
        "naruto": ("/naruto-mythos-displays", "/naruto-mythos-boxen"),
    }

    def __init__(self, games: list[str], delay: float):
        super().__init__(games, delay)
        self._latest: list[Snapshot] = []

    def scan(self) -> list[Snapshot]:
        cached = self._cached_catalog()
        if cached is not None:
            return cached
        snapshots: dict[str, Snapshot] = {}
        for game, paths in self.categories.items():
            if game not in self.games:
                continue
            for path in paths:
                first = BeautifulSoup(self.get(self.base + path).text, "html.parser")
                page_numbers = [
                    int(match.group(1))
                    for link in first.select('a[href]')
                    if (match := re.search(r"_s(\d+)(?:\?|$)", link.get("href", "")))
                ]
                pages = max(page_numbers, default=1)
                for page in range(1, pages + 1):
                    soup = first if page == 1 else BeautifulSoup(
                        self.get(f"{self.base}{path}_s{page}").text,
                        "html.parser",
                    )
                    for card in soup.select(".productbox"):
                        title_link = card.select_one(".productbox-title a[href]")
                        product_id = card.select_one('input[name="a"][value]')
                        price = card.select_one('[itemprop="price"][content]')
                        if not title_link or not product_id:
                            continue
                        title = title_link.get_text(" ", strip=True)
                        if not is_sealed_product(title):
                            continue
                        image = card.select_one('[itemprop="image"][content]')
                        button = card.select_one(".basket-details-add-to-cart")
                        snapshots[product_id["value"]] = Snapshot(
                            store=self.name,
                            store_product_id=product_id["value"],
                            url=title_link["href"],
                            title=title,
                            price_cents=round(float(price["content"]) * 100) if price else None,
                            in_stock=bool(button and not button.has_attr("disabled")),
                            game=game,
                            image=image["content"] if image else None,
                        )
        self._latest = self._remember_catalog(list(snapshots.values()))
        return self._latest

    def fetch(self, url: str) -> Snapshot | None:
        target = urlparse(url).path.rstrip("/")
        cached = next((item for item in self._latest if urlparse(item.url).path.rstrip("/") == target), None)
        if cached:
            return cached
        soup = BeautifulSoup(self.get(url).text, "html.parser")
        title_node = soup.select_one("h1")
        product_id = soup.select_one('form#buy_form input[name="a"][value]')
        price = soup.select_one('[itemprop="price"][content]')
        availability = soup.select_one('[itemprop="availability"][href]')
        image = soup.select_one('[itemprop="image"][content]')
        if not title_node or not product_id:
            return None
        title = title_node.get_text(" ", strip=True)
        return Snapshot(
            store=self.name,
            store_product_id=product_id["value"],
            url=url,
            title=title,
            price_cents=round(float(price["content"]) * 100) if price else None,
            in_stock=bool(availability and availability["href"].rstrip("/").endswith("/InStock")),
            game=detect_game(title + " " + url),
            image=image["content"] if image else None,
        )
