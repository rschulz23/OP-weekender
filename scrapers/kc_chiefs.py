from __future__ import annotations
"""
Scraper: Kansas City Chiefs (chiefs.com/schedule/)
====================================================
Parses JSON-LD SportsEvent blocks from the static schedule page.
No API key or Playwright required.
"""

import json
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import pytz

from .base import BaseScraper, Event

CENTRAL = pytz.timezone("America/Chicago")
URL = "https://www.chiefs.com/schedule/"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    )
}


def _parse_dt(raw: str) -> datetime | None:
    """Parse ISO-8601 datetime string into timezone-aware Central datetime."""
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M"):
        try:
            dt = datetime.strptime(raw[:19], fmt)
            return pytz.utc.localize(dt).astimezone(CENTRAL)
        except ValueError:
            continue
    return None


class KCChiefsScraper(BaseScraper):
    name = "KC Chiefs"

    def fetch(self) -> list[Event]:
        try:
            resp = requests.get(URL, headers=HEADERS, timeout=20)
            resp.raise_for_status()
        except Exception as e:
            self.logger.error(f"Fetch failed: {e}")
            return []

        soup = BeautifulSoup(resp.text, "html.parser")
        events: list[Event] = []

        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or "")
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if item.get("@type") != "SportsEvent":
                        continue

                    start = _parse_dt(item.get("startDate", ""))
                    if not start:
                        continue

                    # Skip past events
                    if start < datetime.now(CENTRAL):
                        continue

                    name = item.get("name", "Kansas City Chiefs")
                    loc_raw = item.get("location", {})
                    venue = loc_raw.get("name", "Arrowhead Stadium") if isinstance(loc_raw, dict) else "Arrowhead Stadium"
                    address = loc_raw.get("address", {}) if isinstance(loc_raw, dict) else {}
                    city = address.get("addressLocality", "Kansas City") if isinstance(address, dict) else "Kansas City"

                    location = f"{venue}, {city}"

                    events.append(Event(
                        title=name,
                        start_date=start,
                        end_date=None,
                        location=location,
                        city=city,
                        description="",
                        url=item.get("url", URL),
                        source="KC Chiefs",
                        image_url=None,
                        cost=None,
                        category="Sports & Fitness",
                    ))
            except Exception as e:
                self.logger.warning(f"JSON-LD parse error: {e}")

        self.logger.info(f"Fetched {len(events)} KC Chiefs games")
        return events
