"""TCGShop adapter using Ecwid's public storefront catalog API."""
from urllib.parse import urlparse

from ..models import Snapshot, detect_game, is_sealed_product
from .base import Store

_GAME_SEARCHES = {"pokemon": "Pokémon", "mtg": "Magic the Gathering", "naruto": "naruto"}
_URL_PARAMS = {
    "urlType": "CLEAN_URL",
    "baseUrl": "/products",
    "canonicalBaseUrl": "https://tcgshop.nl/products",
    "isCleanUrls": True,
    "isCanonicalUrlsEnabled": True,
    "isSlugsWithoutIds": True,
    "isTrailingSlash": False,
}


class TcgShop(Store):
    name = "tcgshop"
    label = "TCGShop"
    domains = ("tcgshop.nl",)
    base = "https://tcgshop.nl"
    api = "https://eu-fra2-storefront-api.ecwid.com/storefront/api/v1/111329799"

    def scan(self) -> list[Snapshot]:
        snapshots: dict[str, Snapshot] = {}
        for game, keyword in _GAME_SEARCHES.items():
            if game not in self.games:
                continue
            offset = 0
            total = 1
            while offset < total:
                data = self.post(
                    self.api + "/catalog/search",
                    json={
                        "isFuzzySearchEnabled": False,
                        "productFiltersValue": {"keyword": keyword},
                        "pagination": {"offset": offset, "limit": 60},
                        "urlParams": _URL_PARAMS,
                        "lang": "nl",
                    },
                ).json()
                total = int(data["totalProductsCount"])
                for product in data["products"]:
                    title = product["name"].strip()
                    if is_sealed_product(title):
                        snapshot = self._snapshot(product, game)
                        snapshots[snapshot.store_product_id] = snapshot
                offset += 60
        return list(snapshots.values())

    def fetch(self, url: str) -> Snapshot | None:
        slug = urlparse(url).path.strip("/").rsplit("/", 1)[-1]
        if not slug:
            return None
        route = self.post(self.api + "/catalog/slug", json={"slug": slug}).json()
        if route.get("type") != "product":
            return None
        product = self.post(
            self.api + "/catalog/product",
            json={
                "lang": "nl",
                "productIdentifier": {"type": "PUBLISHED", "productId": route["entityId"]},
                "urlParams": _URL_PARAMS,
            },
        ).json()
        return self._snapshot(product, detect_game(product["name"]))

    def _snapshot(self, product: dict, game: str | None) -> Snapshot:
        options = product["defaultOptionsOverrides"]
        prices = options["pricesOverrides"]
        variation = options["variationOverrides"]
        media = variation.get("mediaItems") or variation.get("productGridMediaItems") or []
        main_image = next((item for item in media if item.get("isMain")), media[0] if media else {})
        url = product.get("seo", {}).get("canonicalUrl") or product.get("urls", {}).get("directPageUrl")
        if url and url.startswith("/"):
            url = self.base + url
        product_id = str(product["identifier"]["productId"])
        price = prices.get("basePriceWithModifiersDiscountAndTaxes", prices.get("basePrice"))
        return Snapshot(
            store=self.name,
            store_product_id=product_id,
            url=url or f"{self.base}/products/{product['slugs']['forRouteWithoutId']}",
            title=product["name"].strip(),
            price_cents=round(float(price) * 100) if price is not None else None,
            in_stock=not variation.get("isSoldOut", False),
            game=game,
            image=main_image.get("imageOriginalUrl") or main_image.get("image800pxUrl"),
        )
