from __future__ import annotations
"""
Scraper: Worlds of Fun Special Events
=======================================
Parses the special events listing page. Dates are extracted from event URLs.
"""

import re
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import pytz

from .base import BaseScraper, Event

CENTRAL = pytz.timezone("America/Chicago")
URL = "https://worldsoffun.enchantedparks.com/rides-and-experiences/events/special-events/"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    )
}

_DATE_FROM_URL = re.compile(r"/(\d{4}-\d{2}-\d{2})/?$")


class WorldsOfFunScraper(BaseScraper):
    name = "Worlds of Fun"

    def fetch(self) -> list[Event]:
        try:
            resp = requests.get(URL, headers=HEADERS, timeout=15)
            resp.raise_for_status()
        except Exception as e:
            self.logger.error(f"Fetch failed: {e}")
            return []

        soup = BeautifulSoup(resp.text, "html.parser")
        events: list[Event] = []

        for card in soup.find_all("article", class_="span4"):
            title_tag = card.find("h4", class_="tribe-events-widget-events-list__event-title")
            if not title_tag:
                title_tag = card.find("h4")
            link_tag  = card.find("a", href=True)
            desc_tag  = card.find("p")

            if not title_tag or not link_tag:
                continue

            title = title_tag.get_text(strip=True)
            href  = link_tag["href"]

            # Extract date from the URL (most reliable source)
            m = _DATE_FROM_URL.search(href)
            if not m:
                continue

            try:
                dt = datetime.strptime(m.group(1), "%Y-%m-%d").replace(hour=10, minute=0)
                start_date = CENTRAL.localize(dt)
            except ValueError:
                continue

            desc = desc_tag.get_text(strip=True)[:200] if desc_tag else ""

            events.append(Event(
                title=title,
                start_date=start_date,
                end_date=None,
                location="Worlds of Fun, Kansas City, MO",
                city="Kansas City",
                description=desc,
                url=href,
                source="Worlds of Fun",
                image_url=None,
                cost=None,
                category="Family & Kids",
            ))

        self.logger.info(f"Fetched {len(events)} events")
        return events
