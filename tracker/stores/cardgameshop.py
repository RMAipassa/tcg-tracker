"""CardGameShop adapter using public server-rendered category listings."""
import math
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..models import Snapshot, detect_game, is_sealed_product
from .base import Store

_CATALOGS = {
    "pokemon": "/nl/categorieen/pokemon",
    "mtg": "/nl/categorieen/magic-the-gathering",
    "naruto": "/nl/categorieen/naruto",
}


def _price(text: str) -> int | None:
    match = re.search(r"(\d[\d.]*)[,.](\d{2})", text.replace("\xa0", " "))
    return int(match.group(1).replace(".", "")) * 100 + int(match.group(2)) if match else None


def _product_id(node) -> str | None:
    if not node:
        return None
    match = re.search(r"(?:addProduct|addToFavourites)\((\d+)", node.get("onclick", ""))
    return match.group(1) if match else None


class CardGameShop(Store):
    name = "cardgameshop"
    label = "CardGameShop"
    domains = ("cardgameshop.be",)
    base = "https://www.cardgameshop.be"

    def scan(self) -> list[Snapshot]:
        snapshots: dict[str, Snapshot] = {}
        for game, path in _CATALOGS.items():
            if game not in self.games:
                continue
            page = 1
            pages = 1
            while page <= pages:
                soup = BeautifulSoup(
                    self.get(self.base + path, params={"limit": 72, "page": page}).text,
                    "html.parser",
                )
                cards = soup.select(".card.product")
                if not cards:
                    raise ValueError(f"CardGameShop {game} page {page} has no product cards")
                info = soup.select_one(".pagination-settings .info")
                total_match = re.search(r"van\s+(\d+)", info.get_text(" ", strip=True), re.I) if info else None
                pages = math.ceil(int(total_match.group(1)) / 72) if total_match else page
                for card in cards:
                    title_link = card.select_one("h3 a[href]")
                    action = card.select_one("[onclick*=addProduct], [onclick*=addToFavourites]")
                    product_id = _product_id(action)
                    if not title_link or not product_id:
                        continue
                    title = title_link.get_text(" ", strip=True)
                    if not is_sealed_product(title):
                        continue
                    image = card.select_one(".card-header img")
                    price = card.select_one(".card-footer .price")
                    snapshots[product_id] = Snapshot(
                        store=self.name,
                        store_product_id=product_id,
                        url=urljoin(self.base, title_link["href"]),
                        title=title,
                        price_cents=_price(price.get_text(" ", strip=True)) if price else None,
                        in_stock=bool(card.select_one(".btn-add-to-order")),
                        game=game,
                        image=image.get("data-src") or image.get("src") if image else None,
                    )
                page += 1
        return list(snapshots.values())

    def fetch(self, url: str) -> Snapshot | None:
        soup = BeautifulSoup(self.get(url).text, "html.parser")
        content = soup.select_one(".product-content")
        title = soup.select_one("h1.title")
        if not content or not title:
            return None
        action = content.select_one("[onclick*=addProduct], [onclick*=addToFavourites]")
        product_id = _product_id(action)
        if not product_id:
            return None
        price = content.select_one(".product-information .price-wrapper .price")
        image = content.select_one(".image-wrapper img")
        canonical = soup.select_one('link[rel="canonical"]')
        title_text = title.get_text(" ", strip=True)
        return Snapshot(
            store=self.name,
            store_product_id=product_id,
            url=canonical.get("href") if canonical else url,
            title=title_text,
            price_cents=_price(price.get_text(" ", strip=True)) if price else None,
            in_stock=bool(content.select_one(".order-product-favourites-wrapper.in-stock")),
            game=detect_game(title_text),
            image=image.get("data-src") or image.get("src") if image else None,
        )
