from __future__ import annotations
"""
Scraper: KC Music & Arts Festival (kcmusicfestival.com)
=========================================================
Parses the festival calendar from the homepage. Each entry is a date + venue
listed as plain text. Skips postponed/cancelled events.
"""

import re
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import pytz

from .base import BaseScraper, Event

CENTRAL = pytz.timezone("America/Chicago")
URL = "https://kcmusicfestival.com/"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    )
}

# Matches "September 5, 2026 at <location>"
_DATE_RE = re.compile(
    r"^(?:(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s+)?"
    r"(\w+ \d{1,2},?\s+\d{4})\s+at\s+(.+)$",
    re.IGNORECASE,
)


class KCMusicFestivalScraper(BaseScraper):
    name = "KC Music Festival"

    def fetch(self) -> list[Event]:
        try:
            resp = requests.get(URL, headers=HEADERS, timeout=15)
            resp.raise_for_status()
        except Exception as e:
            self.logger.error(f"Fetch failed: {e}")
            return []

        soup = BeautifulSoup(resp.text, "html.parser")
        events: list[Event] = []

        for span in soup.find_all("span", class_="elementor-icon-list-text"):
            text = span.get_text(" ", strip=True).replace("\xa0", " ")

            # Skip postponed or cancelled
            if re.search(r"postponed|cancelled|canceled", text, re.IGNORECASE):
                continue

            m = _DATE_RE.match(text)
            if not m:
                continue

            date_str, location = m.group(1).strip(), m.group(2).strip()
            # Normalize date string (remove stray commas)
            date_str = re.sub(r",\s*", " ", date_str).strip()

            try:
                dt = datetime.strptime(date_str, "%B %d %Y")
                # Festival gates typically open midday; use noon as default time
                dt = dt.replace(hour=12, minute=0)
                start_date = CENTRAL.localize(dt)
            except ValueError:
                continue

            events.append(Event(
                title="KC Music & Arts Festival",
                start_date=start_date,
                end_date=None,
                location=location,
                city="Kansas City",
                description="Free general admission. Country music, arts & crafts.",
                url=URL,
                source="KC Music Festival",
                image_url=None,
                cost="Free",
                category="Music & Entertainment",
            ))

        self.logger.info(f"Fetched {len(events)} festival dates")
        return events
