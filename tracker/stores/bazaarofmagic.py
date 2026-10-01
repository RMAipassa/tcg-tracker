import html
import json
import math
import re
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from ..models import Snapshot, looks_sealed
from .base import Store
from .generic import _html_price


class BazaarOfMagic(Store):
    name = "bazaarofmagic"
    label = "Bazaar of Magic"
    domains = ("bazaarofmagic.eu",)
    base = "https://www.bazaarofmagic.eu"
    catalog_interval_minutes = 60
    categories = {
        "pokemon": (
            "/en-WW/c/pokemon-boosters/1000401",
            "/en-WW/c/pokemon-booster-blisters/1000402",
            "/en-WW/c/pokemon-decks/1000403",
            "/en-WW/c/pokemon-tins/1000404",
            "/en-WW/c/pokemon-trainer-boxes/1000405",
            "/en-WW/c/pokemon-special-boxes/1000406",
            "/en-WW/c/pokemon-sets/1000904",
        ),
        "mtg": (
            "/en-WW/c/magic-packs/1000107",
            "/en-WW/c/magic-decks/1000131",
        ),
    }

    def scan(self) -> list[Snapshot]:
        cached = self._cached_catalog()
        if cached is not None:
            return cached
        snapshots: dict[str, Snapshot] = {}
        for game, paths in self.categories.items():
            if game not in self.games:
                continue
            for path in paths:
                first = BeautifulSoup(
                    self.get(self.base + path, params={"page": 1, "items": 144}).text,
                    "html.parser",
                )
                pagination = first.select_one(".product-list .pagination")
                total_match = re.search(r"\bof\s+([\d,]+)", pagination.get_text(" ", strip=True) if pagination else "")
                pages = math.ceil(int(total_match.group(1).replace(",", "")) / 144) if total_match else 1
                for page in range(1, pages + 1):
                    soup = first if page == 1 else BeautifulSoup(
                        self.get(self.base + path, params={"page": page, "items": 144}).text,
                        "html.parser",
                    )
                    for card in soup.select(".products"):
                        title_link = card.select_one("a.header[href]")
                        product_id = card.select_one("[data-id]")
                        if not title_link or not product_id:
                            continue
                        title = title_link.get_text(" ", strip=True)
                        if not looks_sealed(title):
                            continue
                        prices = card.select(".price-display .nowrap")
                        image = card.select_one(".thumb img[src]")
                        snapshots[product_id["data-id"]] = Snapshot(
                            store=self.name,
                            store_product_id=product_id["data-id"],
                            url=title_link["href"],
                            title=title,
                            price_cents=_html_price(prices[-1].get_text(" ", strip=True)) if prices else None,
                            in_stock=bool(card.select_one(".cart.buy")),
                            game=game,
                            image=image["src"] if image else None,
                        )
        return self._remember_catalog(list(snapshots.values()))

    def fetch(self, url: str) -> Snapshot | None:
        soup = BeautifulSoup(self.get(url).text, "html.parser")
        for node in soup.find_all("script", type="application/ld+json"):
            try:
                product = json.loads(node.get_text())
            except json.JSONDecodeError:
                continue
            if product.get("@type") != "Product":
                continue
            offers = product.get("offers") or {}
            if isinstance(offers, list):
                offers = offers[0] if offers else {}
            images = product.get("image") or []
            image = images[0] if isinstance(images, list) and images else images if isinstance(images, str) else None
            title = html.unescape(product.get("name", "")).strip()
            price = offers.get("price")
            availability = str(offers.get("availability") or "")
            product_id = str(product.get("sku") or urlparse(url).path.rstrip("/").rsplit("/", 1)[-1])
            metadata = " ".join((title, str(product.get("brand") or ""), str(product.get("category") or "")))
            game = "pokemon" if re.search(r"pok[eé]mon", metadata, re.I) else "mtg" if re.search(r"magic", metadata, re.I) else None
            return Snapshot(
                store=self.name,
                store_product_id=product_id,
                url=product.get("url") or url,
                title=title,
                price_cents=round(float(price) * 100) if price is not None else None,
                in_stock=availability.rstrip("/").endswith("/InStock"),
                game=game,
                image=image,
            )
        return None
