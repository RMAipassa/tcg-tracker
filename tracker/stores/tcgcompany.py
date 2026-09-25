import html
import re

from ..models import Snapshot, detect_game, looks_sealed
from .base import Store

# TCG Company runs on WooCommerce; its public Store API lists products with categories.
# Top-level category id per game; products sit in subcategories (e.g. "pokemon-booster-box").
_GAME_ROOTS = {15: "pokemon", 287: "mtg", 305: "naruto"}
# Singles and bulk, excluded server side so a scan stays within the API rate limit (20 req/min).
_SINGLES_CATEGORIES = "31,75"
_EXCLUDED_SLUGS = {"accessoires", "merchandise", "funko-pop", "knuffels", "playmat", "acrylic-display-cases", "lego"}


class TcgCompany(Store):
    name = "tcgcompany"
    label = "TCG Company"
    domains = ("tcgcompany.nl",)
    api = "https://tcgcompany.nl/wp-json/wc/store/v1/products"

    def scan(self) -> list[Snapshot]:
        category_games = self._category_games()
        snapshots = []
        page = 1
        while True:
            response = self.get(self.api, params={
                "category": _SINGLES_CATEGORIES, "category_operator": "not_in", "per_page": 100, "page": page,
            })
            for product in response.json():
                game = self._game(product, category_games)
                slugs = {c["slug"] for c in product["categories"]}
                if game in self.games and not slugs & _EXCLUDED_SLUGS and looks_sealed(html.unescape(product["name"])):
                    snapshots.append(self._snapshot(product, game))
            if page >= int(response.headers.get("X-WP-TotalPages", 1)):
                return snapshots
            page += 1

    def fetch(self, url: str) -> Snapshot | None:
        match = re.search(r"tcgcompany\.nl/(?:product/)?([^/?#]+)", url)
        if not match:
            return None
        products = self.get(self.api, params={"slug": match.group(1)}).json()
        if not products:
            return None
        return self._snapshot(products[0], self._game(products[0], self._category_games()))

    def _category_games(self) -> dict[int, str]:
        """Maps every category id to the game of its top-level ancestor."""
        parents: dict[int, int] = {}
        page = 1
        while True:
            response = self.get(f"{self.api}/categories", params={"per_page": 100, "page": page})
            categories = response.json()
            parents.update({c["id"]: c["parent"] for c in categories})
            if len(categories) < 100:
                break
            page += 1
        games = {}
        for category_id in parents:
            root, hops = category_id, 0
            while parents.get(root) and hops < 10:
                root, hops = parents[root], hops + 1
            if root in _GAME_ROOTS:
                games[category_id] = _GAME_ROOTS[root]
        return games

    @staticmethod
    def _game(product: dict, category_games: dict[int, str]) -> str | None:
        for category in product["categories"]:
            if category["id"] in category_games:
                return category_games[category["id"]]
        return detect_game(html.unescape(product["name"]))

    def _snapshot(self, product: dict, game: str | None) -> Snapshot:
        prices = product["prices"]
        price = int(prices["price"]) if prices.get("price") and int(prices["price"]) > 0 else None
        if price is not None and prices.get("currency_minor_unit", 2) != 2:
            price = round(price * 10 ** (2 - prices["currency_minor_unit"]))
        images = product.get("images") or []
        return Snapshot(
            store=self.name,
            store_product_id=str(product["id"]),
            url=product["permalink"],
            title=html.unescape(product["name"]),
            price_cents=price,
            in_stock=bool(product["is_in_stock"]),
            game=game,
            image=images[0]["src"] if images else None,
        )
