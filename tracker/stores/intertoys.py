import json
import re
from urllib.parse import urlparse

from ..models import Snapshot, detect_game, looks_sealed
from .base import Store

# Intertoys renders pages with Next.js; product data is embedded in __NEXT_DATA__.
# Only the first 36 products of a category are server-rendered, so the catalog scan
# covers the newest/top listings; watchlist URLs work for any product.
_CATEGORY_PAGES = ["/spellen/trading-cards/ruilkaarten"]
_NEXT_DATA = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)


def _fallback(page_html: str) -> dict:
    match = _NEXT_DATA.search(page_html)
    if not match:
        raise ValueError("Intertoys page has no __NEXT_DATA__ (layout changed?)")
    return json.loads(match.group(1))["props"]["pageProps"]["fallback"]


def _offer_price(prices: list[dict]) -> int | None:
    for price in prices:
        if price.get("usage") == "Offer" and price.get("value"):
            return round(float(price["value"]) * 100)
    return None


class Intertoys(Store):
    name = "intertoys"
    label = "Intertoys"
    domains = ("intertoys.nl",)
    base = "https://www.intertoys.nl"

    def scan(self) -> list[Snapshot]:
        snapshots = []
        for path in _CATEGORY_PAGES:
            fallback = _fallback(self.get(self.base + path).text)
            listing = next(v for k, v in fallback.items() if "findProductsByCategory" in k)
            for product in listing["contents"]:
                game = detect_game(product["name"])
                if game in self.games and looks_sealed(product["name"]):
                    snapshots.append(self._snapshot(product, product["buyable"] == "true", game))
        return snapshots

    def fetch(self, url: str) -> Snapshot | None:
        fallback = _fallback(self.get(self.base + urlparse(url).path).text)
        product = next((v["product"] for k, v in fallback.items() if k.endswith('"PRODUCT",') and isinstance(v, dict) and "product" in v), None)
        if not product:
            return None
        # "buyable" is whether it can be ordered online; inventory can be positive while it is not
        # (e.g. before release or store-only), which is not worth an alert.
        in_stock = product.get("buyable") == "true"
        inventory = next((v for k, v in fallback.items() if '"INVENTORY"' in k), None)
        if in_stock and inventory and inventory.get("InventoryAvailability"):
            in_stock = any(i.get("inventoryStatus") in ("Available", "Allocated") for i in inventory["InventoryAvailability"])
        return self._snapshot(product, in_stock, detect_game(product["name"]))

    def _snapshot(self, product: dict, in_stock: bool, game: str | None) -> Snapshot:
        image = product.get("thumbnail") or product.get("fullImage")
        return Snapshot(
            store=self.name,
            store_product_id=str(product["partNumber"]),
            url=self.base + product["seo"]["href"],
            title=product["name"],
            price_cents=_offer_price(product.get("price", [])),
            in_stock=in_stock,
            game=game,
            image=f"https://image.intertoys.nl{image.replace('/hclstore/', '/wcsstore/')}" if image and image.startswith("/") else image,
        )
