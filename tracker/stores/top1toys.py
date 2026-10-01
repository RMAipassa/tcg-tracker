"""Top1Toys catalog adapter using its public Magento GraphQL endpoint."""
import json
from urllib.parse import urlparse

from ..models import Snapshot, detect_game, is_sealed_product
from .base import Store

_FIELDS = """
id
name
url_key
stock_status
small_image { url }
price_range { minimum_price { final_price { value currency } } }
"""


class Top1Toys(Store):
    name = "top1toys"
    label = "Top1Toys"
    domains = ("top1toys.nl",)
    base = "https://www.top1toys.nl"
    api = base + "/graphql"
    # TCG categories currently contain no sealed products, which is a valid API result.
    allow_empty_catalog = True

    def __init__(self, games: list[str], delay: float):
        super().__init__(games, delay)
        # The endpoint rejects Chrome's full UA but serves its public schema to a generic browser UA.
        self.client.headers.update({"User-Agent": "Mozilla/5.0", "Store": "top1toys_nl"})

    def _query(self, query: str) -> dict:
        payload = self.get(self.api, params={"query": query}).json()
        if payload.get("errors"):
            message = payload["errors"][0].get("message", "unknown error")
            raise ValueError(f"Top1Toys GraphQL error: {message}")
        return payload["data"]

    def scan(self) -> list[Snapshot]:
        categories = self._query("""
            query {
              categoryList(filters: { name: { match: "Pokemon" } }) {
                id name url_path
              }
            }
        """)["categoryList"]
        category_ids = [
            str(category["id"])
            for category in categories
            if "tcg" in category["name"].lower() or category.get("url_path") == "asmodee/pokemon"
        ]
        if not category_ids:
            raise ValueError("Top1Toys returned no Pokemon TCG categories")

        quoted_ids = ", ".join(f'"{category_id}"' for category_id in category_ids)
        snapshots: dict[str, Snapshot] = {}
        page = 1
        while True:
            products = self._query(f"""
                query {{
                  products(
                    filter: {{ category_id: {{ in: [{quoted_ids}] }} }}
                    pageSize: 100
                    currentPage: {page}
                  ) {{
                    page_info {{ total_pages }}
                    items {{ {_FIELDS} }}
                  }}
                }}
            """)["products"]
            for product in products["items"]:
                game = detect_game(product["name"])
                if game in self.games and is_sealed_product(product["name"]):
                    snapshots[str(product["id"])] = self._snapshot(product, game)
            if page >= products["page_info"]["total_pages"]:
                return list(snapshots.values())
            page += 1

    def fetch(self, url: str) -> Snapshot | None:
        slug = urlparse(url).path.strip("/").rsplit("/", 1)[-1].removesuffix(".html")
        if not slug:
            return None
        data = self._query(f"""
            query {{
              products(filter: {{ url_key: {{ eq: {json.dumps(slug)} }} }}, pageSize: 1) {{
                items {{ {_FIELDS} }}
              }}
            }}
        """)
        products = data["products"]["items"]
        if not products:
            return None
        return self._snapshot(products[0], detect_game(products[0]["name"]))

    def _snapshot(self, product: dict, game: str | None) -> Snapshot:
        final_price = product.get("price_range", {}).get("minimum_price", {}).get("final_price", {})
        value = final_price.get("value")
        image = product.get("small_image") or {}
        return Snapshot(
            store=self.name,
            store_product_id=str(product["id"]),
            url=f"{self.base}/{product['url_key']}",
            title=product["name"].strip(),
            price_cents=round(float(value) * 100) if value is not None else None,
            in_stock=product.get("stock_status") == "IN_STOCK",
            game=game,
            image=image.get("url"),
        )
