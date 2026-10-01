"""MediaMarkt NL adapter for its server-rendered Pokemon card category."""
import html
import json
import re
from urllib.parse import urlparse

from ..models import Snapshot, detect_game, looks_sealed
from .base import Store

_JSON_LD = re.compile(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', re.S)
_PAGE_COUNT = re.compile(r'"paging":\{[^{}]*"pageCount":(\d+)')
_PRODUCT_ID = re.compile(r"-(\d+)\.html$")


def _json_ld(page_html: str, type_: str) -> dict:
    for raw in _JSON_LD.findall(page_html):
        data = json.loads(html.unescape(raw))
        if data.get("@type") == type_:
            return data
    raise ValueError(f"MediaMarkt page has no {type_} JSON-LD")


def _cached_bool(page_html: str, product_id: str, feature: str, field: str) -> bool:
    marker = f'"{feature}:Media:nl:{product_id}":'
    start = page_html.find(marker)
    if start < 0:
        raise ValueError(f"MediaMarkt product {product_id} has no {feature}")
    match = re.search(rf'"{field}":(true|false)', page_html[start:start + 5000])
    if not match:
        raise ValueError(f"MediaMarkt product {product_id} has no {field}")
    return match.group(1) == "true"


class MediaMarkt(Store):
    name = "mediamarkt"
    label = "MediaMarkt NL"
    domains = ("mediamarkt.nl",)
    base = "https://www.mediamarkt.nl"
    category = base + "/nl/category/pokemon-kaarten-2071.html"

    def scan(self) -> list[Snapshot]:
        snapshots: dict[str, Snapshot] = {}
        page = 1
        pages = 1
        while page <= pages:
            page_html = self.get(self.category, params={"page": page} if page > 1 else None).text
            if page == 1:
                match = _PAGE_COUNT.search(page_html)
                if not match:
                    raise ValueError("MediaMarkt page has no catalog page count")
                pages = int(match.group(1))
            listing = _json_ld(page_html, "ItemList")
            for entry in listing.get("itemListElement", []):
                product = entry["item"]
                product_id = self._product_id(product["url"])
                if _cached_bool(page_html, product_id, "CofrCoreFeature", "isProductOfTypeMarketplace"):
                    continue
                title = product["name"].strip()
                game = detect_game(title)
                # This category is curated to Pokemon cards, so abbreviated product names such as
                # "BO" and "3BB" only need the merchandise/accessory exclusions.
                if game in self.games and looks_sealed(title):
                    in_stock = _cached_bool(
                        page_html, product_id, "CofrOnlineStatusFeature", "isAvailableAndBuyable"
                    )
                    snapshots[product_id] = self._snapshot(product, product_id, in_stock, game)
            page += 1
        return list(snapshots.values())

    def fetch(self, url: str) -> Snapshot | None:
        page_html = self.get(url).text
        action = _json_ld(page_html, "BuyAction")
        product = action.get("object") or {}
        if not product.get("sku"):
            return None
        offers = product.get("offers") or {}
        if isinstance(offers, list):
            offers = offers[0] if offers else {}
        images = product.get("image") or []
        image = images[0] if isinstance(images, list) and images else images if isinstance(images, str) else None
        item = {
            "name": product.get("name", ""),
            "url": product.get("url") or url,
            "image": image,
            "offers": offers,
        }
        availability = offers.get("availability", "")
        return self._snapshot(
            item,
            str(product["sku"]),
            availability.rstrip("/").endswith("/InStock"),
            detect_game(item["name"]),
        )

    @staticmethod
    def _product_id(url: str) -> str:
        match = _PRODUCT_ID.search(urlparse(url).path)
        if not match:
            raise ValueError(f"MediaMarkt product URL has no id: {url}")
        return match.group(1)

    def _snapshot(self, product: dict, product_id: str, in_stock: bool, game: str | None) -> Snapshot:
        offers = product.get("offers") or {}
        price = offers.get("price")
        return Snapshot(
            store=self.name,
            store_product_id=product_id,
            url=product["url"],
            title=product["name"].strip(),
            price_cents=round(float(price) * 100) if price is not None else None,
            in_stock=in_stock,
            game=game,
            image=product.get("image"),
        )
