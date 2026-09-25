import re

from ..models import Snapshot
from .base import Store

# Bescards runs on Shopify and tags products like "game:pokemon" and "product:sealed".
_TAG_GAMES = {"game:pokemon": "pokemon", "game:magic": "mtg", "game:naruto": "naruto"}
_EXCLUDED_TAGS = {"category:accessoires", "category:funko-pop", "product:single"}


def _game(tags: set[str]) -> str | None:
    return next((g for t, g in _TAG_GAMES.items() if t in tags), None)


class Bescards(Store):
    name = "bescards"
    label = "Bescards"
    domains = ("bescards.com", "bescards.nl")
    base = "https://www.bescards.com"

    def scan(self) -> list[Snapshot]:
        snapshots = []
        page = 1
        while True:
            products = self.get(f"{self.base}/products.json", params={"limit": 250, "page": page}).json()["products"]
            for product in products:
                tags = set(product["tags"])
                game = _game(tags)
                if game in self.games and "product:sealed" in tags and not tags & _EXCLUDED_TAGS:
                    variants = product["variants"]
                    available = [v for v in variants if v["available"]]
                    prices = [round(float(v["price"]) * 100) for v in (available or variants)]
                    images = product.get("images") or []
                    snapshots.append(Snapshot(
                        store=self.name,
                        store_product_id=str(product["id"]),
                        url=f"{self.base}/products/{product['handle']}",
                        title=product["title"],
                        price_cents=min(prices) if prices else None,
                        in_stock=bool(available),
                        game=game,
                        image=images[0]["src"] if images else None,
                    ))
            if len(products) < 250:
                return snapshots
            page += 1

    def fetch(self, url: str) -> Snapshot | None:
        match = re.search(r"/products/([^/?#]+)", url)
        if not match:
            return None
        # The storefront ".js" endpoint includes availability (".json" does not).
        product = self.get(f"{self.base}/products/{match.group(1)}.js").json()
        variants = product["variants"]
        available = [v for v in variants if v["available"]]
        prices = [v["price"] for v in (available or variants)]
        image = product.get("featured_image")
        return Snapshot(
            store=self.name,
            store_product_id=str(product["id"]),
            url=f"{self.base}/products/{product['handle']}",
            title=product["title"],
            price_cents=min(prices) if prices else None,
            in_stock=bool(available),
            game=_game(set(product["tags"])),
            image=f"https:{image}" if image and image.startswith("//") else image,
        )
