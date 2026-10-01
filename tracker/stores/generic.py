"""Configuration-driven adapters for public ecommerce catalogs."""
import html
import json
import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from ..models import Snapshot, detect_game, is_sealed_product, looks_sealed
from .base import Store

_SHOPIFY_EXCLUDED_TAGS = {
    "accessory", "accessories", "accessoire", "accessoires", "single", "singles",
    "product:single", "category:accessoires", "merchandise",
}
_OTHER_GAME = re.compile(
    r"lorcana|one piece|riftbound|yu-?gi-?oh|dragon ball|gundam|star wars|flesh and blood|digimon|"
    r"union arena|altered|final fantasy tcg|weiss schwarz|grand archive",
    re.I,
)


def _html_price(text: str) -> int | None:
    match = re.search(r"(\d[\d.]*)[,.](\d{2})", text.replace("\xa0", " "))
    return int(match.group(1).replace(".", "")) * 100 + int(match.group(2)) if match else None


class ConfiguredStore(Store):
    def __init__(self, name: str, options: dict, games: list[str], delay: float):
        super().__init__(games, float(options.get("request_delay_seconds", delay)))
        self.name = name
        self.label = options.get("label") or name.replace("_", " ").title()
        self.base = options["base_url"].rstrip("/")
        host = (urlparse(self.base).hostname or "").removeprefix("www.")
        self.domains = tuple(options.get("domains") or [host])
        self.default_game = options.get("default_game")
        self.catalog_interval_minutes = int(options.get("catalog_interval_minutes", 0))
        timeout = float(options.get("timeout_seconds", 30))
        self.client.timeout = timeout

    def _game(self, metadata: str, forced_game: str | None = None) -> str | None:
        game = forced_game or detect_game(metadata)
        if game is None and self.default_game and not _OTHER_GAME.search(metadata):
            return self.default_game
        return game

class ShopifyStore(ConfiguredStore):
    platform = "shopify"

    def __init__(self, name: str, options: dict, games: list[str], delay: float):
        super().__init__(name, options, games, delay)
        self.collections = options.get("collections", {})
        self.include_all_products = options.get("include_all_products", True)

    @staticmethod
    def _tags(product: dict) -> set[str]:
        tags = product.get("tags") or []
        if isinstance(tags, str):
            tags = tags.split(",")
        return {str(tag).strip().lower() for tag in tags}

    def _details(self, product: dict, forced_game: str | None = None) -> tuple[str | None, bool]:
        title = html.unescape(product.get("title", "")).strip()
        tags = self._tags(product)
        metadata = " ".join((title, str(product.get("product_type") or ""), " ".join(tags)))
        game = self._game(metadata, forced_game)
        explicitly_sealed = any(tag == "sealed" or tag.endswith(":sealed") for tag in tags)
        sealed = looks_sealed(title) and not tags.intersection(_SHOPIFY_EXCLUDED_TAGS) and (
            explicitly_sealed or is_sealed_product(title)
        )
        return game, sealed

    def scan(self) -> list[Snapshot]:
        cached = self._cached_catalog()
        if cached is not None:
            return cached
        snapshots: dict[str, Snapshot] = {}
        feeds = [(f"{self.base}/products.json", None)] if self.include_all_products else []
        for game, configured_handles in self.collections.items():
            if game not in self.games:
                continue
            handles = configured_handles if isinstance(configured_handles, list) else [configured_handles]
            feeds.extend((f"{self.base}/collections/{handle}/products.json", game) for handle in handles)
        if not feeds:
            raise ValueError(f"{self.label} has no configured Shopify feeds")
        for url, forced_game in feeds:
            page = 1
            while True:
                products = self.get(url, params={"limit": 250, "page": page}).json()["products"]
                for product in products:
                    game, sealed = self._details(product, forced_game)
                    if game in self.games and sealed:
                        snapshots[str(product["id"])] = self._snapshot(product, game, prices_are_cents=False)
                if len(products) < 250:
                    break
                page += 1
        return self._remember_catalog(list(snapshots.values()))

    def fetch(self, url: str) -> Snapshot | None:
        match = re.search(r"/products/([^/?#]+)", url)
        if not match:
            return None
        product = self.get(f"{self.base}/products/{match.group(1)}.js").json()
        game, _ = self._details(product)
        return self._snapshot(product, game, prices_are_cents=True)

    def _snapshot(self, product: dict, game: str | None, prices_are_cents: bool) -> Snapshot:
        variants = product.get("variants") or []
        available = [variant for variant in variants if variant.get("available")]
        raw_prices = [variant.get("price") for variant in (available or variants) if variant.get("price") not in (None, "")]
        prices = [int(price) if prices_are_cents else round(float(price) * 100) for price in raw_prices]
        images = product.get("images") or []
        first_image = images[0] if images else product.get("featured_image")
        image = first_image.get("src") if isinstance(first_image, dict) else first_image
        if image and image.startswith("//"):
            image = "https:" + image
        handle = product["handle"]
        return Snapshot(
            store=self.name,
            store_product_id=str(product["id"]),
            url=f"{self.base}/products/{handle}",
            title=html.unescape(product.get("title", "")).strip(),
            price_cents=min(prices) if prices else None,
            in_stock=bool(available),
            game=game,
            image=image,
        )


class WooCommerceStore(ConfiguredStore):
    platform = "woocommerce"
    fields = "id,name,permalink,prices,is_in_stock,images,categories,tags"

    def __init__(self, name: str, options: dict, games: list[str], delay: float):
        super().__init__(name, options, games, delay)
        self.api = options.get("api_url", f"{self.base}/wp-json/wc/store/v1/products").rstrip("/")
        self.per_page = max(1, min(int(options.get("per_page", 100)), 100))
        self.categories = options.get("categories", {})

    def _details(self, product: dict, forced_game: str | None = None) -> tuple[str | None, bool]:
        title = html.unescape(product.get("name", "")).strip()
        categories = product.get("categories") or []
        tags = product.get("tags") or []
        metadata = " ".join(
            [title]
            + [str(item.get("name") or item.get("slug") or "") for item in categories + tags]
        )
        return self._game(metadata, forced_game), is_sealed_product(title)

    def scan(self) -> list[Snapshot]:
        cached = self._cached_catalog()
        if cached is not None:
            return cached
        feeds: list[tuple[dict, str | None]] = []
        for game, configured_ids in self.categories.items():
            if game not in self.games:
                continue
            category_ids = configured_ids if isinstance(configured_ids, list) else [configured_ids]
            feeds.append(({"category": ",".join(str(category_id) for category_id in category_ids)}, game))
        if not feeds:
            feeds = [({}, None)]

        snapshots: dict[str, Snapshot] = {}
        for extra_params, forced_game in feeds:
            page = 1
            while True:
                params = {"per_page": self.per_page, "page": page, "_fields": self.fields, **extra_params}
                response = self.get(self.api, params=params)
                products = response.json()
                for product in products:
                    game, sealed = self._details(product, forced_game)
                    if game in self.games and sealed:
                        snapshots[str(product["id"])] = self._snapshot(product, game)
                if page >= int(response.headers.get("X-WP-TotalPages", 1)):
                    break
                page += 1
        return self._remember_catalog(list(snapshots.values()))

    def fetch(self, url: str) -> Snapshot | None:
        path = urlparse(url).path.rstrip("/")
        slug = path.rsplit("/", 1)[-1]
        if not slug:
            return None
        products = self.get(self.api, params={"slug": slug, "_fields": self.fields}).json()
        if not products:
            return None
        game, _ = self._details(products[0])
        return self._snapshot(products[0], game)

    def _snapshot(self, product: dict, game: str | None) -> Snapshot:
        prices = product.get("prices") or {}
        raw_price = prices.get("price")
        price = int(raw_price) if raw_price and int(raw_price) > 0 else None
        minor_unit = prices.get("currency_minor_unit", 2)
        if price is not None and minor_unit != 2:
            price = round(price * 10 ** (2 - minor_unit))
        images = product.get("images") or []
        return Snapshot(
            store=self.name,
            store_product_id=str(product["id"]),
            url=product["permalink"],
            title=html.unescape(product.get("name", "")).strip(),
            price_cents=price,
            in_stock=bool(product.get("is_in_stock")),
            game=game,
            image=images[0].get("src") if images else None,
        )


class MagentoStore(ConfiguredStore):
    platform = "magento"

    def __init__(self, name: str, options: dict, games: list[str], delay: float):
        super().__init__(name, options, games, delay)
        self.api = options.get("api_url", f"{self.base}/graphql")
        self.categories = options.get("categories", {})
        store_view = options.get("store_view")
        if store_view:
            self.client.headers["Store"] = store_view

    def _query(self, query: str) -> dict:
        payload = self.get(self.api, params={"query": query}).json()
        if payload.get("errors"):
            message = payload["errors"][0].get("message", "unknown error")
            raise ValueError(f"{self.label} GraphQL error: {message}")
        return payload["data"]

    def scan(self) -> list[Snapshot]:
        if not self.categories:
            raise ValueError(f"{self.label} has no configured Magento categories")
        snapshots: dict[str, Snapshot] = {}
        for game, configured_ids in self.categories.items():
            if game not in self.games:
                continue
            category_ids = configured_ids if isinstance(configured_ids, list) else [configured_ids]
            quoted_ids = ", ".join(json.dumps(str(category_id)) for category_id in category_ids)
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
                        items {{
                          id name url_key url_suffix stock_status
                          small_image {{ url }}
                          price_range {{ minimum_price {{ final_price {{ value currency }} }} }}
                        }}
                      }}
                    }}
                """)["products"]
                for product in products["items"]:
                    title = html.unescape(product["name"]).strip()
                    if is_sealed_product(title):
                        snapshots[str(product["id"])] = self._snapshot(product, game)
                if page >= products["page_info"]["total_pages"]:
                    break
                page += 1
        return list(snapshots.values())

    def fetch(self, url: str) -> Snapshot | None:
        path = urlparse(url).path.strip("/")
        if not path:
            return None
        product = self._query(f"""
            query {{
              route(url: {json.dumps(path)}) {{
                type
                ... on ProductInterface {{
                  id name url_key url_suffix stock_status
                  small_image {{ url }}
                  price_range {{ minimum_price {{ final_price {{ value currency }} }} }}
                }}
              }}
            }}
        """)["route"]
        if not product or product.get("type") != "PRODUCT":
            return None
        return self._snapshot(product, self._game(product["name"]))

    def _snapshot(self, product: dict, game: str | None) -> Snapshot:
        final_price = product.get("price_range", {}).get("minimum_price", {}).get("final_price", {})
        value = final_price.get("value")
        image = product.get("small_image") or {}
        suffix = product.get("url_suffix") or ""
        return Snapshot(
            store=self.name,
            store_product_id=str(product["id"]),
            url=f"{self.base}/{product['url_key']}{suffix}",
            title=html.unescape(product["name"]).strip(),
            price_cents=round(float(value) * 100) if value is not None else None,
            in_stock=product.get("stock_status") == "IN_STOCK",
            game=game,
            image=image.get("url"),
        )


class JouwWebStore(ConfiguredStore):
    platform = "jouwweb"

    def __init__(self, name: str, options: dict, games: list[str], delay: float):
        super().__init__(name, options, games, delay)
        paths = options.get("catalog_paths") or [options.get("catalog_path", "/")]
        self.catalog_paths = [path if path.startswith("/") else "/" + path for path in paths]

    def scan(self) -> list[Snapshot]:
        snapshots: dict[str, Snapshot] = {}
        for path in self.catalog_paths:
            catalog_url = self.base + path
            first_page = self.get(catalog_url).text
            soup = BeautifulSoup(first_page, "html.parser")
            gallery = soup.select_one(".jw-product-gallery[data-jw-element-id]")
            if not gallery:
                raise ValueError(f"{self.label} product gallery missing at {path}")
            pagination = soup.select_one(".jw-pagination[data-page-total]")
            pages = int(pagination["data-page-total"]) if pagination else 1
            element_id = gallery["data-jw-element-id"]
            for page in range(pages):
                if page:
                    page_html = self.get(
                        catalog_url,
                        params={f"ep[{element_id}][page]": page, f"ep[{element_id}][sort]": "manual"},
                    ).text
                    soup = BeautifulSoup(page_html, "html.parser")
                for card in soup.select(".product-gallery__content.js-product-container[data-webshop-product]"):
                    product = json.loads(html.unescape(card["data-webshop-product"]))
                    title = product["title"].strip()
                    game = self._game(title)
                    if game in self.games and is_sealed_product(title):
                        price = card.select_one(".product-price")
                        snapshots[str(product["id"])] = Snapshot(
                            store=self.name,
                            store_product_id=str(product["id"]),
                            url=urljoin(self.base, product["url"]),
                            title=title,
                            price_cents=_html_price(price.get_text(" ", strip=True)) if price else None,
                            in_stock=any(
                                float(variant.get("stock") or 0) > 0 for variant in product.get("variants", [])
                            ),
                            game=game,
                            image=(product.get("image") or {}).get("url"),
                        )
        return list(snapshots.values())

    def fetch(self, url: str) -> Snapshot | None:
        soup = BeautifulSoup(self.get(url).text, "html.parser")
        card = soup.select_one(".product-page.js-product-container[data-webshop-product]")
        if not card:
            return None
        product = json.loads(html.unescape(card["data-webshop-product"]))
        price = soup.select_one('meta[itemprop="price"]')
        availability = soup.select_one('meta[itemprop="availability"]')
        canonical = soup.select_one('link[rel="canonical"]')
        image = product.get("image") or {}
        title = product["title"].strip()
        return Snapshot(
            store=self.name,
            store_product_id=str(product["id"]),
            url=canonical.get("href") if canonical else url,
            title=title,
            price_cents=round(float(price["content"]) * 100) if price else None,
            in_stock=bool(availability and availability["content"].rstrip("/").endswith("/InStock")),
            game=self._game(title),
            image=image.get("url"),
        )


class OdooStore(ConfiguredStore):
    platform = "odoo"

    def __init__(self, name: str, options: dict, games: list[str], delay: float):
        super().__init__(name, options, games, delay)
        self.categories = options.get("categories", {})

    def _category_url(self, category: str | int) -> str:
        value = str(category)
        path = value if value.startswith("/") else f"/shop/category/{value}"
        return urljoin(self.base + "/", path.lstrip("/"))

    @staticmethod
    def _product_id(card) -> str | None:
        node = card.select_one(".o_add_wishlist[data-product-template-id], input[name=product_template_id]")
        if not node:
            return None
        return node.get("data-product-template-id") or node.get("value")

    def _add_cards(self, soup: BeautifulSoup, game: str, snapshots: dict[str, Snapshot]) -> None:
        for card in soup.select(".oe_product"):
            title_link = card.select_one(".o_wsale_products_item_title a[href]")
            product_id = self._product_id(card)
            if not title_link or not product_id:
                continue
            title = title_link.get_text(" ", strip=True)
            if not is_sealed_product(title):
                continue
            image = card.select_one(".oe_product_image img")
            snapshots[product_id] = Snapshot(
                store=self.name,
                store_product_id=product_id,
                url=urljoin(self.base, title_link["href"]),
                title=title,
                price_cents=_html_price(card.select_one(".product_price").get_text(" ", strip=True)),
                in_stock=bool(card.select_one(".o_wsale_product_btn_primary")),
                game=game,
                image=urljoin(self.base, image.get("src")) if image else None,
            )

    def scan(self) -> list[Snapshot]:
        if not self.categories:
            raise ValueError(f"{self.label} has no configured Odoo categories")
        snapshots: dict[str, Snapshot] = {}
        for game, category in self.categories.items():
            if game not in self.games:
                continue
            url = self._category_url(category)
            seen_pages = set()
            while url and url not in seen_pages:
                seen_pages.add(url)
                soup = BeautifulSoup(self.get(url).text, "html.parser")
                if not soup.select_one(".oe_product"):
                    raise ValueError(f"{self.label} {game} category has no product cards")
                self._add_cards(soup, game, snapshots)
                next_link = soup.select_one("li.o_pager_next:not(.disabled) a[href], a.o_pager_next[href]")
                url = urljoin(self.base, next_link["href"]) if next_link else None
        return list(snapshots.values())

    def fetch(self, url: str) -> Snapshot | None:
        soup = BeautifulSoup(self.get(url).text, "html.parser")
        title = soup.select_one("h1")
        product_id = soup.select_one("input[name=product_template_id]")
        if not title or not product_id:
            return None
        title_text = title.get_text(" ", strip=True)
        price = soup.select_one(".oe_price")
        image = soup.select_one("img.product_detail_img")
        canonical = soup.select_one('link[rel="canonical"]')
        in_stock = bool(soup.select_one("#add_to_cart:not(.disabled)"))

        # Odoo's detail button can remain visible for store-only items. The
        # category card is the authoritative signal for online availability.
        parts = urlparse(url).path.strip("/").split("/")
        shop_index = parts.index("shop") if "shop" in parts else -1
        if len(parts) > shop_index + 2 and shop_index >= 0 and parts[shop_index + 1] != "category":
            category_soup = BeautifulSoup(
                self.get(f"{self.base}/shop/category/{parts[shop_index + 1]}").text,
                "html.parser",
            )
            matching_card = next(
                (card for card in category_soup.select(".oe_product") if self._product_id(card) == product_id["value"]),
                None,
            )
            if matching_card:
                in_stock = bool(matching_card.select_one(".o_wsale_product_btn_primary"))

        return Snapshot(
            store=self.name,
            store_product_id=product_id["value"],
            url=canonical.get("href") if canonical else url,
            title=title_text,
            price_cents=_html_price(price.get_text(" ", strip=True)) if price else None,
            in_stock=in_stock,
            game=self._game(title_text),
            image=urljoin(self.base, image.get("src")) if image else None,
        )
