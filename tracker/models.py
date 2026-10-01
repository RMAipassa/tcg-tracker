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
    r"sleeves?\b|portfolio|binder(?! collection)|verzamelmap|map\b|playmat|deck ?box|toploader|"
    r"album|folio|pocket pages?|sideloading pages?|sorteerbak|sort box|divider|kaartenscheider|"
    r"slab|graded|protector|beschermhoes|card holders?|kaarten?houder|opberghouder|storage box|"
    r"display frame|card frame|booster pack holder|muurdisplay|muurhouder|muurbeugel|fotolijst|kaartenstandaard|one touch standaard|"
    r"centering tool|whitening tool|scan box|telefoon houder|ringband|bewaartas|sleutelhanger|keychain|"
    r"beschermkoffer|speelkleed|kaarthoes|ultra pro|funko|pop!|lego|knuffel|pluche|plush|rugzak|"
    r"backpack|display case|card case|hard case|dispenser|horloge|\bwatch\b|\bklok\b|acryl|\bmok\b|kleurenpen|"
    r"blind box|battle figuur|battle figure|mini figuur|mini figure|figuur pack|figure pack|figure set(?! collection)",
    re.I,
)
_SEALED_MARKERS = re.compile(
    r"booster|\bbox\b|bundle|bundel|collection|collectie|\btin\b|blister|\bdecks?\b|chest|\bpack\b|display|"
    r"elite trainer|\betb\b|battle academy|checklane|build (?:and|&) battle|trainer toolkit|advent calendar|adventskalender",
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


def is_sealed_product(title: str) -> bool:
    """Conservative title check for uncurated store-wide catalogs."""
    return looks_sealed(title) and bool(_SEALED_MARKERS.search(title))


def euro(cents: int | None) -> str:
    if cents is None:
        return "?"
    return f"€{cents / 100:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
