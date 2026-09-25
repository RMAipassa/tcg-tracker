import re
from dataclasses import dataclass

GAMES = ("pokemon", "mtg", "naruto")

_GAME_PATTERNS = {
    "pokemon": re.compile(r"pok[eé]mon", re.I),
    "mtg": re.compile(r"magic:? the gathering|\bmtg\b|\bmagic\b", re.I),
    "naruto": re.compile(r"naruto", re.I),
}

# Accessories and merchandise that are never sealed product.
_NOT_SEALED = re.compile(
    r"sleeve|portfolio|binder(?! collection)|verzamelmap|map\b|playmat|deck ?box|toploader|"
    r"funko|pop!|lego|knuffel|pluche|plush|rugzak|backpack|display case|acryl",
    re.I,
)


@dataclass
class Snapshot:
    store: str
    store_product_id: str
    url: str
    title: str
    price_cents: int | None
    in_stock: bool
    game: str | None = None
    image: str | None = None


def detect_game(text: str) -> str | None:
    for game, pattern in _GAME_PATTERNS.items():
        if pattern.search(text):
            return game
    return None


def looks_sealed(title: str) -> bool:
    return not _NOT_SEALED.search(title)


def euro(cents: int | None) -> str:
    if cents is None:
        return "?"
    return f"€{cents / 100:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
