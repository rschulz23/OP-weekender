from __future__ import annotations
"""
Base scraper class for OP Weekender event scrapers.
All scrapers return a list of Event dicts with a consistent schema.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
import logging

logging.basicConfig(level=logging.INFO, format="%(name)s | %(levelname)s | %(message)s")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}


@dataclass
class Event:
    """Normalized event schema used across all scrapers."""
    title: str
    start_date: datetime
    end_date: Optional[datetime]
    location: str
    city: str                      # e.g. "Overland Park", "Lenexa", "Multi-city"
    description: str
    url: str
    source: str                    # human-readable source name
    image_url: Optional[str] = None
    cost: Optional[str] = None     # e.g. "Free", "$10", "Varies"
    tags: list = field(default_factory=list)
    category: str = "Other"        # assigned by categorizer after scraping

    def is_weekend(self) -> bool:
        """Return True if the event falls on a Saturday or Sunday."""
        return self.start_date.weekday() in (5, 6)

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "location": self.location,
            "city": self.city,
            "description": self.description,
            "url": self.url,
            "source": self.source,
            "image_url": self.image_url,
            "cost": self.cost,
            "tags": self.tags,
            "category": self.category,
        }


class BaseScraper:
    """Base class all scrapers inherit from."""

    name: str = "BaseScraper"

    def __init__(self):
        self.logger = logging.getLogger(self.name)

    def fetch(self) -> list[Event]:
        """Override this in each subclass. Returns a list of Event objects."""
        raise NotImplementedError

    def safe_fetch(self) -> list[Event]:
        """Wraps fetch() with error handling so one broken scraper never kills the run."""
        try:
            events = self.fetch()
            self.logger.info(f"✅  {len(events)} events fetched")
            return events
        except Exception as e:
            self.logger.error(f"❌  Failed: {e}")
            return []
