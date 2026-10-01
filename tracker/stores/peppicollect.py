"""Peppi Collect configuration for the shared JouwWeb adapter."""
from .generic import JouwWebStore


class PeppiCollect(JouwWebStore):
    name = "peppicollect"
    label = "Peppi Collect"
    domains = ("peppicollect.nl",)

    def __init__(self, games: list[str], delay: float):
        super().__init__(
            self.name,
            {
                "label": self.label,
                "base_url": "https://www.peppicollect.nl",
                "catalog_path": "/alle-producten",
            },
            games,
            delay,
        )
