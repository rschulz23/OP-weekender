from __future__ import annotations
"""
Scraper: Aubrey Vineyards (aubreyvineyards.com/pages/av-events)
================================================================
Events are published as images on their Shopify page and cannot be
auto-scraped. Update MANUAL_EVENTS each week with upcoming events.
Format: ("Title", "YYYY-MM-DD", hour_24, minute, "description")
"""

from datetime import datetime
import pytz

from .base import BaseScraper, Event

CENTRAL = pytz.timezone("America/Chicago")
URL = "https://www.aubreyvineyards.com/pages/av-events"

# ---------------------------------------------------------------------------
# MANUAL EVENTS — update this list each week.
# ---------------------------------------------------------------------------
MANUAL_EVENTS: list[tuple] = [
    ("Live Music at Aubrey Vineyards", "2026-09-13", 14, 0, "Live music on the patio, 2–4 PM"),
]
# ---------------------------------------------------------------------------


class AubreyVineyardsScraper(BaseScraper):
    name = "Aubrey Vineyards"

    def fetch(self) -> list[Event]:
        events: list[Event] = []
        now = datetime.now(CENTRAL)

        for title, date_str, hour, minute, description in MANUAL_EVENTS:
            try:
                dt = datetime.strptime(date_str, "%Y-%m-%d").replace(hour=hour, minute=minute)
                start_date = CENTRAL.localize(dt)
            except ValueError:
                self.logger.warning(f"Bad date in MANUAL_EVENTS: {date_str}")
                continue

            if start_date < now:
                continue

            events.append(Event(
                title=title,
                start_date=start_date,
                end_date=None,
                location="Aubrey Vineyards, 23457 W 183rd St, Aubrey, KS",
                city="Aubrey",
                description=description,
                url=URL,
                source="Aubrey Vineyards",
                image_url=None,
                cost=None,
                category="Food & Drink",
            ))

        self.logger.info(f"Fetched {len(events)} Aubrey Vineyards events (manual)")
        return events
