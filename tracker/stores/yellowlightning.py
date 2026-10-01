"""Yellow Lightning Cards adapter using public WooCommerce storefront pages."""
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..models import Snapshot, detect_game, is_sealed_product
from .base import Store

_OTHER_GAME = re.compile(
    r"one piece|lorcana|magic:? the gathering|\bmtg\b|yu-?gi-?oh|dragon ball|digimon|riftbound|"
    r"tamagotchi|panini|fifa|world cup",
    re.I,
)


def _price(node) -> int | None:
    if not node:
        return None
    match = re.search(r"(\d[\d.]*)[,.](\d{2})", node.get_text(" ", strip=True).replace("\xa0", " "))
    return int(match.group(1).replace(".", "")) * 100 + int(match.group(2)) if match else None


class YellowLightning(Store):
    name = "yellowlightningcards"
    label = "Yellow Lightning Cards"
    domains = ("yellowlightningcards.nl",)
    base = "https://yellowlightningcards.nl"

    def scan(self) -> list[Snapshot]:
        snapshots: dict[str, Snapshot] = {}
        url = self.base + "/"
        seen_pages = set()
        while url and url not in seen_pages:
            seen_pages.add(url)
            soup = BeautifulSoup(self.get(url).text, "html.parser")
            cards = soup.select("#content ul.products.columns-5 > li.product")
            if not cards:
                raise ValueError("Yellow Lightning Cards page has no product cards")
            for card in cards:
                title_link = card.select_one("h2.woocommerce-loop-product__title > a")
                match = next(
                    (found for value in card.get("class", []) if (found := re.fullmatch(r"post-(\d+)", value))),
                    None,
                )
                if not title_link or not match:
                    continue
                title = title_link.get_text(" ", strip=True)
                game = detect_game(title)
                if game is None and not _OTHER_GAME.search(title):
                    game = "pokemon"
                if game in self.games and is_sealed_product(title):
                    price_node = card.select_one("span.price ins .woocommerce-Price-amount")
                    if not price_node:
                        price_node = card.select_one("span.price .woocommerce-Price-amount")
                    image = card.select_one("img.attachment-woocommerce_thumbnail")
                    snapshots[match.group(1)] = Snapshot(
                        store=self.name,
                        store_product_id=match.group(1),
                        url=title_link["href"],
                        title=title,
                        price_cents=_price(price_node),
                        in_stock="instock" in card.get("class", []),
                        game=game,
                        image=image.get("data-src") or image.get("src") if image else None,
                    )
            next_link = soup.select_one("#content nav.woocommerce-pagination a.next.page-numbers")
            url = urljoin(self.base, next_link["href"]) if next_link else None
        return list(snapshots.values())

    def fetch(self, url: str) -> Snapshot | None:
        soup = BeautifulSoup(self.get(url).text, "html.parser")
        title = soup.select_one("h1.product_title.entry-title")
        body_classes = soup.body.get("class", []) if soup.body else []
        id_match = next(
            (found for value in body_classes if (found := re.fullmatch(r"postid-(\d+)", value))),
            None,
        )
        if not title or not id_match:
            return None
        price = soup.find("meta", attrs={"property": "product:price:amount"})
        availability = soup.find("meta", attrs={"property": "product:availability"})
        canonical = soup.select_one('link[rel="canonical"]')
        image = soup.find("meta", attrs={"property": "og:image"})
        title_text = title.get_text(" ", strip=True)
        stock_value = availability.get("content", "") if availability else ""
        game = detect_game(title_text)
        if game is None and not _OTHER_GAME.search(title_text):
            game = "pokemon"
        return Snapshot(
            store=self.name,
            store_product_id=id_match.group(1),
            url=canonical.get("href") if canonical else url,
            title=title_text,
            price_cents=round(float(price["content"]) * 100) if price else None,
            in_stock=stock_value.lower() in {"instock", "in stock", "https://schema.org/instock"},
            game=game,
            image=image.get("content") if image else None,
        )
