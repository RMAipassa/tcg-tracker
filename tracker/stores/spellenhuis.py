"""Spellenhuis adapter using public Shopware catalog listings."""
import json
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..models import Snapshot, detect_game, is_sealed_product
from .base import Store

_CATALOGS = {
    "pokemon": "/trading-cards/pokemon/",
    "mtg": "/trading-cards/magic-kaarten/",
}


def _price(text: str) -> int | None:
    match = re.search(r"(\d[\d.]*)[,.](\d{2})", text.replace("\xa0", " "))
    return int(match.group(1).replace(".", "")) * 100 + int(match.group(2)) if match else None


class Spellenhuis(Store):
    name = "spellenhuis"
    label = "Spellenhuis"
    domains = ("spellenhuis.nl",)
    base = "https://www.spellenhuis.nl"

    def __init__(self, games: list[str], delay: float):
        super().__init__(games, max(delay, 3.2))

    def scan(self) -> list[Snapshot]:
        snapshots: dict[str, Snapshot] = {}
        for game, path in _CATALOGS.items():
            if game not in self.games:
                continue
            soup = BeautifulSoup(self.get(self.base + path).text, "html.parser")
            options_node = soup.select_one("[data-listing-options]")
            if not options_node:
                raise ValueError(f"Spellenhuis {game} listing options missing")
            options = json.loads(options_node["data-listing-options"])
            pages = max(int(node.get("value", 1)) for node in soup.select('nav.pagination-nav input[name="p"]'))
            self._add_cards(soup, game, snapshots)
            for page in range(2, pages + 1):
                page_html = self.get(options["dataUrl"], params={**options["params"], "p": page}).text
                self._add_cards(BeautifulSoup(page_html, "html.parser"), game, snapshots)
        return list(snapshots.values())

    def _add_cards(self, soup: BeautifulSoup, game: str, snapshots: dict[str, Snapshot]) -> None:
        for card in soup.select(".card.product-box.box-minimal"):
            product_id = card.select_one('input[name="product-id"]')
            title_link = card.select_one("a.product-name")
            if not product_id or not title_link:
                continue
            title = title_link.get_text(" ", strip=True)
            if not is_sealed_product(title):
                continue
            availability = card.select_one('link[itemprop="availability"]')
            status = availability.get("href", "").rstrip("/").rsplit("/", 1)[-1] if availability else ""
            image = card.select_one("img.product-image")
            snapshots[product_id["value"]] = Snapshot(
                store=self.name,
                store_product_id=product_id["value"],
                url=urljoin(self.base, title_link["href"]),
                title=title,
                price_cents=_price(card.select_one(".product-price").get_text(" ", strip=True)),
                in_stock=status in {"InStock", "LimitedAvailability", "PreOrder"},
                game=game,
                image=urljoin(self.base, image.get("src")) if image else None,
            )

    def fetch(self, url: str) -> Snapshot | None:
        soup = BeautifulSoup(self.get(url).text, "html.parser")
        title = soup.select_one('h1.product-detail-name[itemprop="name"]')
        product_data = soup.select_one('input[name="redirectParameters"]')
        if not title or not product_data:
            return None
        product_id = str(json.loads(product_data["value"])["productId"])
        price = soup.select_one('meta[itemprop="price"]')
        availability = soup.select_one('link[itemprop="availability"]')
        canonical = soup.select_one('link[rel="canonical"]')
        image = soup.find("meta", attrs={"property": "og:image"})
        title_text = title.get_text(" ", strip=True)
        status = availability.get("href", "").rstrip("/").rsplit("/", 1)[-1] if availability else ""
        return Snapshot(
            store=self.name,
            store_product_id=product_id,
            url=canonical.get("href") if canonical else url,
            title=title_text,
            price_cents=round(float(price["content"]) * 100) if price else None,
            in_stock=status in {"InStock", "LimitedAvailability", "PreOrder"},
            game=detect_game(title_text),
            image=image.get("content") if image else None,
        )
